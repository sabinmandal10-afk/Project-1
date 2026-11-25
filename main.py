"""
GAIA test suite for the Phase 6 features (Feature 10: ecosystem balance).

Run from the project root:   python main.py

Feature 11 (emergent events) is covered by the EventDetector tests near the end.

Covers: environment multipliers, probabilistic reproduction + crowding,
prey refuge, simulation hooks, the metrics Recorder (collapse / recovery),
stress events (drought, radiation drop, plague), recolonization, and
long-run invariants + determinism.
"""

import contextlib
import io

from environment.world import World
from Simulation.simulation import Simulation
from Simulation.metrics import Recorder
from Simulation.stress import (
    Drought, RadiationDrop, Plague, StressManager, Recolonization
)
from organisms.factory import create_organism
from organisms.photosynthesis import photosynthesize
import organisms.reproduction as repro
import organisms.hunting as hunting

from Simulation.events import EventDetector
import Simulation.events as events_mod

import run_gaia
from Interface.snapshot import take_snapshot, holding_capacity

try:                                  # the viewer needs matplotlib (pip install matplotlib)
    import matplotlib
    matplotlib.use("Agg")             # draw off-screen while testing
    from Interface import viewer as viewer_mod
    HAVE_MATPLOTLIB = True
except ImportError:
    HAVE_MATPLOTLIB = False


# ---------------------------------------------------------------- helpers

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def quiet():
    """Silence the game's own prints while a test runs."""
    return contextlib.redirect_stdout(io.StringIO())


def spawn(world, species, x, y, energy=None, age=0):
    with quiet():
        o = create_organism(species)
    o.x, o.y = x, y
    o.age = age
    if energy is not None:
        o.energy = energy
    world.add_organism(o)
    return o


def section(title):
    print(f"\n--- {title} ---")


# ------------------------------------------------- environment multipliers

def test_environment_multipliers():
    section("environment multipliers")
    w = World(100, 100, seed=1)

    check("effective light starts at 1.0", w.effective_light == 1.0)
    w.light_multiplier = 0.5
    check("light multiplier halves effective light", w.effective_light == 0.5)
    check("base light level untouched", w.light_level == 1.0)

    w.radiation_multiplier = 0.2
    check("radiation multiplier applies", abs(w.effective_radiation - 0.2) < 1e-9)

    w.light_multiplier = 5
    check("effective light clamped to 1.0", w.effective_light == 1.0)

    # photosynthesis uses the effective level
    w = World(100, 100, seed=1)
    plant = spawn(w, "Verdant", 10, 10, energy=100)
    gain_full = photosynthesize(plant, w)
    w.light_multiplier = 0.5
    plant.energy = 100
    gain_half = photosynthesize(plant, w)
    check("photosynthesis full light", abs(gain_full - 5.0) < 1e-9, gain_full)
    check("photosynthesis under drought is halved", abs(gain_half - 2.5) < 1e-9, gain_half)

    # seasons and multipliers combine
    w = World(100, 100, seed=1)
    w.set_seasons(100, low=0.5, high=1.0)
    w.light_multiplier = 0.5
    w.turn = 25
    w.update_season()
    check("seasons and multiplier combine",
          abs(w.effective_light - w.light_level * 0.5) < 1e-9)


# ------------------------------------------------------------- reproduction

def test_reproduction_chance_and_crowding():
    section("reproduction: chance and crowding")
    w = World(1000, 1000, seed=3)
    plant = spawn(w, "Verdant", 500, 500, energy=100, age=20)

    base = repro.REPRO_CHANCE["Verdant"]["chance"]
    limit = repro.REPRO_CHANCE["Verdant"]["crowding_limit"]

    check("lone plant gets the base chance",
          abs(repro.reproduction_chance(plant, w) - base) < 1e-9)

    for i in range(3):
        spawn(w, "Verdant", 500 + i, 500)
    expected = base * (1 - 3 / limit)
    check("3 neighbours lower the chance",
          abs(repro.reproduction_chance(plant, w) - expected) < 1e-9)

    for i in range(limit):
        spawn(w, "Verdant", 500, 500 + i)
    check("full neighbourhood -> chance zero",
          repro.reproduction_chance(plant, w) == 0)

    # far-away plants don't count as neighbours
    w2 = World(1000, 1000, seed=3)
    p = spawn(w2, "Verdant", 100, 100, energy=100, age=20)
    for i in range(10):
        spawn(w2, "Verdant", 800 + i, 800)
    check("distant plants are not neighbours", repro.neighbours(p, w2) == 0)

    # other species never crowd a plant
    w3 = World(1000, 1000, seed=3)
    p = spawn(w3, "Verdant", 100, 100, energy=100, age=20)
    for i in range(5):
        spawn(w3, "Crystalis", 100 + i, 100)
    check("other species don't count as crowding", repro.neighbours(p, w3) == 0)

    # animals have no crowding limit
    g = spawn(w3, "Grazer", 300, 300, energy=200, age=30)
    check("animal chance is the flat base chance",
          abs(repro.reproduction_chance(g, w3) - repro.REPRO_CHANCE["Grazer"]["chance"]) < 1e-9)


def test_reproduction_is_probabilistic():
    section("reproduction: probabilistic")

    # reproduce() itself stays deterministic (rolls happen in process_reproduction)
    w = World(1000, 1000, seed=5)
    parent = spawn(w, "Verdant", 500, 500, energy=100, age=20)
    with quiet():
        child = repro.reproduce(parent, w)
    check("reproduce() still works when eligible", child is not None)
    check("parent paid the energy cost", parent.energy == 100 - repro.REPRODUCTION["Verdant"]["energy_cost"])

    # process_reproduction: not everyone eligible reproduces
    w = World(5000, 5000, seed=7)
    for _ in range(40):
        x, y = w.random_position()
        spawn(w, "Verdant", x, y, energy=100, age=20)
    before = len(w.organisms)
    with quiet():
        repro.process_reproduction(w)
    births = len(w.organisms) - before
    check("some eligible plants reproduce", births > 0, births)
    check("not every eligible plant reproduces", births < 40, births)

    # ineligible organisms never reproduce
    w = World(1000, 1000, seed=7)
    for _ in range(30):
        spawn(w, "Verdant", *w.random_position(), energy=100, age=2)   # too young
    before = len(w.organisms)
    with quiet():
        repro.process_reproduction(w)
    check("immature organisms do not reproduce", len(w.organisms) == before)

    # no explosion: plants do not jump straight to the cap
    world = run_gaia.build_world(seed=11)
    sim = Simulation(world, autonomous=True)
    with quiet():
        for _ in range(8):
            sim.advance_turn()
    plants = len(world.living_organisms("Verdant"))
    check("plants don't hit the cap within 8 turns",
          plants < repro.REPRODUCTION["Verdant"]["max_population"], plants)

    # caps still hold
    check("species cap still enforced", repro.can_reproduce(
        spawn(World(10, 10, seed=1), "Ravager", 1, 1, energy=999, age=99),
        _full_world("Ravager"))[1] == "species population limit")


def _full_world(species):
    w = World(100, 100, seed=1)
    for _ in range(repro.REPRODUCTION[species]["max_population"]):
        spawn(w, species, 10, 10)
    return w


# ------------------------------------------------------------- prey refuge

def test_prey_refuge():
    section("prey refuge")
    count = hunting.PREY_REFUGE_COUNT

    sparse = World(100, 100, seed=1)
    hunter = spawn(sparse, "Ravager", 50, 50)
    prey = spawn(sparse, "Grazer", 51, 50)

    dense = World(100, 100, seed=1)
    hunter_d = spawn(dense, "Ravager", 50, 50)
    prey_d = spawn(dense, "Grazer", 51, 50)
    for i in range(count + 2):
        spawn(dense, "Grazer", 52 + i * 0.5, 50)

    c_sparse = hunting.hunt_chance(hunter, prey, sparse)
    c_dense = hunting.hunt_chance(hunter_d, prey_d, dense)

    check("lone prey is harder to catch than a herd", c_sparse < c_dense, (c_sparse, c_dense))
    check("lone prey chance never below the floor", c_sparse >= hunting.MIN_HUNT_SUCCESS)
    check("dense prey gets the normal chance",
          abs(c_dense - hunting.hunt_chance(hunter_d, prey_d)) < 1e-9)
    check("hunt_chance works without a world (old signature)",
          0 < hunting.hunt_chance(hunter, prey) <= hunting.MAX_HUNT_SUCCESS)
    check("density factor is 1.0 with a full herd",
          hunting.prey_density_factor(hunter_d, prey_d, dense) == 1.0)
    check("armoured Shellkin still harder than Grazer",
          hunting.hunt_chance(hunter_d, spawn(dense, "Shellkin", 51, 51), dense)
          < c_dense)


# --------------------------------------------------------- simulation hooks

def test_hooks():
    section("simulation hooks")
    w = World(100, 100, seed=1)
    spawn(w, "Verdant", 10, 10)
    sim = Simulation(w, autonomous=False)

    calls = []
    sim.pre_turn_hooks.append(lambda s: calls.append(("pre", s.world.turn)))
    sim.post_turn_hooks.append(lambda s: calls.append(("post", s.world.turn)))

    with quiet():
        sim.advance_turn()
        sim.advance_turn()

    check("hooks run once per turn each", len(calls) == 4, calls)
    check("pre hook runs before post hook", [c[0] for c in calls] == ["pre", "post", "pre", "post"])
    check("hooks see the new turn number", [c[1] for c in calls] == [1, 1, 2, 2])
    check("works with no hooks registered", Simulation(World(10, 10, seed=1)).pre_turn_hooks == [])


# ----------------------------------------------------------------- recorder

def test_recorder():
    section("metrics recorder")
    w = World(100, 100, seed=1)
    sim = Simulation(w, autonomous=False)
    rec = Recorder()
    sim.post_turn_hooks.append(rec)
    for i in range(5):
        spawn(w, "Verdant", 10 + i, 10)
    spawn(w, "Grazer", 30, 30)

    with quiet():
        for _ in range(6):
            sim.advance_turn()

    check("one row per turn", len(rec.rows) == 6, len(rec.rows))
    row = rec.rows[-1]
    check("row has species counts", row["Verdant"] == 5 and row["Grazer"] == 1, row)
    check("row has total population", row["total_pop"] == 6)
    check("row has environment values", row["light"] == 1.0 and "remains" in row)
    check("row turn matches world turn", row["turn"] == w.turn)
    check("summary is text", "Verdant" in rec.summary())

    # births / deaths are per-turn deltas, not running totals
    w = World(100, 100, seed=1)
    rec = Recorder()
    w.turn = 1
    w.stats["births"] = 5
    rec.record(w)
    w.turn = 2
    w.stats["births"] = 7
    rec.record(w)
    check("births column is a per-turn delta", [r["births"] for r in rec.rows] == [5, 2])

    # CSV export
    import os, tempfile, csv
    path = os.path.join(tempfile.gettempdir(), "gaia_test_metrics.csv")
    rec.to_csv(path)
    with open(path) as f:
        rows = list(csv.DictReader(f))
    check("CSV has one line per turn", len(rows) == 2)
    os.remove(path)


def test_collapse_and_recovery():
    section("collapse and recovery detection")
    w = World(100, 100, seed=1)
    rec = Recorder(species=["Grazer"])
    herd = [spawn(w, "Grazer", 10 + i, 10) for i in range(10)]

    w.turn = 1
    rec.record(w)
    check("no event while healthy", rec.events == [])

    for g in herd[:5]:
        g.status = "Dead"
    w.turn = 2
    rec.record(w)
    check("no collapse at 50% of peak", rec.events == [])

    for g in herd[5:9]:
        g.status = "Dead"
    w.turn = 3
    rec.record(w)
    check("collapse flagged below 25% of peak",
          [e[1] for e in rec.events] == ["collapse"], rec.events)

    herd[9].status = "Dead"
    w.turn = 4
    rec.record(w)
    check("extinction flagged", [e[1] for e in rec.events] == ["collapse", "extinct"], rec.events)

    for i in range(8):
        spawn(w, "Grazer", 50 + i, 50)
    w.turn = 5
    rec.record(w)
    check("recovery flagged", [e[1] for e in rec.events][-1] == "recovery", rec.events)

    w.turn = 6
    rec.record(w)
    check("no duplicate events while stable", len(rec.events) == 3, rec.events)

    # tiny populations are ignored
    w = World(100, 100, seed=1)
    rec = Recorder(species=["Grazer"])
    few = [spawn(w, "Grazer", 10 + i, 10) for i in range(3)]
    w.turn = 1
    rec.record(w)
    for g in few:
        g.status = "Dead"
    w.turn = 2
    rec.record(w)
    check("peaks below MIN_PEAK never count as a collapse", rec.events == [], rec.events)


# ------------------------------------------------------------ stress events

def _stress_sim(seed=1):
    w = World(200, 200, seed=seed)
    return w, Simulation(w, autonomous=False)


def test_drought_and_radiation():
    section("stress: drought and radiation")
    w, sim = _stress_sim()
    manager = StressManager([Drought(start=3, duration=2, severity=0.3)])

    seen = []
    for turn in range(1, 7):
        w.turn = turn
        manager(sim)
        seen.append(round(w.effective_light, 3))

    check("light normal before the drought", seen[:2] == [1.0, 1.0], seen)
    check("light drops during the drought", seen[2:4] == [0.3, 0.3], seen)
    check("light restored after the drought", seen[4:] == [1.0, 1.0], seen)
    check("stress log has start and end",
          [(t, k) for t, k, _ in manager.log] == [(3, "start"), (5, "end")], manager.log)

    # overlapping events stack and unwind correctly
    w, sim = _stress_sim()
    manager = StressManager([Drought(1, 4, 0.5), Drought(2, 1, 0.5)])
    levels = []
    for turn in range(1, 7):
        w.turn = turn
        manager(sim)
        levels.append(round(w.effective_light, 3))
    check("overlapping droughts stack then unwind", levels == [0.5, 0.25, 0.5, 0.5, 1.0, 1.0], levels)

    # radiation drop starves Crystalis
    w, sim = _stress_sim()
    crystal = spawn(w, "Crystalis", 10, 10, energy=100)
    manager = StressManager([RadiationDrop(start=1, duration=10, severity=0.0)])
    w.turn = 1
    manager(sim)
    gain = photosynthesize(crystal, w)
    check("radiation drop stops Crystalis photosynthesis", gain == 0, gain)


def test_plague():
    section("stress: plague")
    w, sim = _stress_sim(seed=4)
    herd = [spawn(w, "Grazer", 10 + i, 10, energy=80) for i in range(20)]
    other = [spawn(w, "Shellkin", 100 + i, 100) for i in range(5)]

    manager = StressManager([Plague(start=1, species="Grazer", fraction=0.5)])
    w.turn = 1
    with quiet():
        manager(sim)

    dead = [g for g in herd if g.status == "Dead"]
    check("plague kills the requested fraction", len(dead) == 10, len(dead))
    check("plague deaths are labelled", all(g.death_cause == "plague" for g in dead))
    check("other species untouched", all(s.status == "Alive" for s in other))
    check("plague victims leave remains", w.organic_remains > 0)
    check("death counted in world stats", w.stats["deaths_plague"] == 10, dict(w.stats))

    # plague only fires once (the next turn arrives, nothing new happens)
    w.turn = 2
    with quiet():
        manager(sim)
    check("plague is a one-off", len([g for g in herd if g.status == "Dead"]) == 10)

    # plague on an extinct species is harmless
    w2, sim2 = _stress_sim()
    manager2 = StressManager([Plague(start=1, species="Ravager", fraction=1.0)])
    w2.turn = 1
    try:
        with quiet():
            manager2(sim2)
        ok = True
    except Exception as e:
        ok = False
    check("plague on a missing species doesn't crash", ok)


def test_stress_edge_cases():
    section("stress: edge cases")

    # severity 0 ends cleanly (used to divide by zero)
    w, sim = _stress_sim()
    manager = StressManager([RadiationDrop(start=1, duration=3, severity=0.0)])
    values = []
    for turn in range(1, 6):
        w.turn = turn
        manager(sim)
        values.append(w.radiation_multiplier)
    check("severity 0 works and is restored afterwards", values == [0.0, 0.0, 0.0, 1.0, 1.0], values)

    # a drought registered after its start turn still applies while it would be running
    w, sim = _stress_sim()
    manager = StressManager([Drought(start=1, duration=10, severity=0.5)])
    w.turn = 5
    manager(sim)
    check("late-registered duration event still starts", w.light_multiplier == 0.5, w.light_multiplier)
    w.turn = 11
    manager(sim)
    check("and ends on schedule", w.light_multiplier == 1.0, w.light_multiplier)

    # events that are entirely in the past are ignored
    w, sim = _stress_sim()
    manager = StressManager([Drought(start=1, duration=3, severity=0.5)])
    w.turn = 20
    manager(sim)
    check("an already-finished event is ignored", w.light_multiplier == 1.0 and manager.log == [])

    # migrants respect the global population limit
    old = repro.GLOBAL_POPULATION_LIMIT
    try:
        repro.GLOBAL_POPULATION_LIMIT = 30
        w, sim = _stress_sim(seed=2)
        for i in range(30):
            spawn(w, "Verdant", 20 + i, 20)
        hook = Recolonization({"Grazer": {"delay": 0, "count": 3, "min_food": 10, "food": ["Verdant"]}})
        w.turn = 1
        with quiet():
            hook(sim)
            w.turn = 2
            hook(sim)
        check("migrants are blocked when the world is full", len(w.living_organisms("Grazer")) == 0)
    finally:
        repro.GLOBAL_POPULATION_LIMIT = old


# ----------------------------------------------------------- recolonization

def test_recolonization():
    section("recolonization")
    rules = {"Grazer": {"delay": 5, "count": 3, "min_food": 10, "food": ["Verdant"]}}

    w, sim = _stress_sim(seed=2)
    for i in range(12):
        spawn(w, "Verdant", 20 + i, 20)
    hook = Recolonization(rules)

    for turn in range(1, 5):
        w.turn = turn
        with quiet():
            hook(sim)
    check("no migrants before the delay", len(w.living_organisms("Grazer")) == 0)

    w.turn = 6
    with quiet():
        hook(sim)
    migrants = w.living_organisms("Grazer")
    check("migrants arrive after the delay", len(migrants) == 3, len(migrants))
    check("migrants arrive at the map edge",
          all(m.x in (0, w.width) or m.y in (0, w.height) for m in migrants),
          [(m.x, m.y) for m in migrants])
    check("migration is logged", hook.log == [(6, "Grazer", 3)], hook.log)
    check("migrants counted in stats", w.stats["migrants"] == 3)

    for turn in range(7, 15):
        w.turn = turn
        with quiet():
            hook(sim)
    check("no more migrants while the species lives", len(w.living_organisms("Grazer")) == 3)

    # no food -> nobody comes
    w, sim = _stress_sim(seed=2)
    spawn(w, "Verdant", 20, 20)
    hook = Recolonization(rules)
    for turn in range(1, 30):
        w.turn = turn
        with quiet():
            hook(sim)
    check("no migrants when there is no food", len(w.living_organisms("Grazer")) == 0)

    # a species that goes extinct again waits the full delay again
    w, sim = _stress_sim(seed=2)
    for i in range(12):
        spawn(w, "Verdant", 20 + i, 20)
    hook = Recolonization(rules)
    w.turn = 1
    with quiet():
        hook(sim)
    w.turn = 6
    with quiet():
        hook(sim)
    for g in w.living_organisms("Grazer"):
        g.status = "Dead"
    w.turn = 7
    with quiet():
        hook(sim)
    check("delay restarts after a second extinction", len(w.living_organisms("Grazer")) == 0)


# ------------------------------------------------- long runs and invariants

def test_long_run_invariants():
    section("long run with stress (500 turns)")
    events = [Drought(start=150, duration=50, severity=0.3),
              Plague(start=300, species="Grazer", fraction=0.6),
              RadiationDrop(start=380, duration=40, severity=0.2)]
    w, rec, stress = run_gaia.run(turns=500, seed=21, events=events)

    limit = repro.GLOBAL_POPULATION_LIMIT
    check("500 turns without crash", w.turn == 500)
    check("recorder has a row per turn", len(rec.rows) == 500)
    check("population never exceeded the global limit",
          all(r["total_pop"] <= limit for r in rec.rows), max(r["total_pop"] for r in rec.rows))
    check("no species exceeded its cap", all(
        r[s] <= repro.REPRODUCTION[s]["max_population"] for r in rec.rows for s in rec.species))
    check("no negative energy", all(o.energy >= 0 for o in w.organisms))
    check("no negative remains", w.organic_remains >= 0)
    check("everyone inside the world", all(w.in_bounds(o.x, o.y) for o in w.organisms))
    check("no dead organisms left in the world", all(o.status == "Alive" for o in w.organisms))
    check("unique organism names", len({o.name for o in w.organisms}) == len(w.organisms))
    check("producers survive", len(w.living_organisms("Verdant")) > 0 and len(w.living_organisms("Crystalis")) > 0)
    check("environment fully restored after events",
          w.light_multiplier == 1.0 and w.radiation_multiplier == 1.0,
          (w.light_multiplier, w.radiation_multiplier))
    check("all three stress events logged",
          {name for _, _, name in stress.log} >= {"drought", "plague", "radiation_drop"}, stress.log)
    check("plague deaths recorded", sum(r["deaths_plague"] for r in rec.rows) > 0)

    drought_light = [r["light"] for r in rec.rows if 150 <= r["turn"] < 200]
    check("recorded light shows the drought", max(drought_light) <= 0.31, max(drought_light))

    print("\n      population every 100 turns:")
    for r in rec.rows[99::100]:
        short = {s[:4]: r[s] for s in rec.species}
        print(f"        turn {r['turn']:>3}: {short}")
    print("\n" + "\n".join("      " + line for line in rec.summary().splitlines()))


def test_determinism():
    section("determinism")
    _, rec_a, _ = run_gaia.run(turns=120, seed=5)
    _, rec_b, _ = run_gaia.run(turns=120, seed=5)
    _, rec_c, _ = run_gaia.run(turns=120, seed=6)

    check("same seed -> identical history", rec_a.rows == rec_b.rows)
    check("different seed -> different history", rec_a.rows != rec_c.rows)


def test_recovery_after_collapse():
    section("ecosystem collapse and recovery")
    # Wipe out all grazers mid-run; recolonization should bring them back
    events = [Plague(start=100, species="Grazer", fraction=1.0)]
    w, rec, _ = run_gaia.run(turns=400, seed=10, events=events)

    kinds = [(k, s) for _, k, s, _ in rec.events]
    check("grazer extinction detected", ("extinct", "Grazer") in kinds, rec.events)
    check("migrants arrived", w.stats["migrants"] > 0, dict(w.stats))
    check("grazers present again at the end", len(w.living_organisms("Grazer")) > 0)
    check("recovery event recorded", ("recovery", "Grazer") in kinds, rec.events)

    # same wipe-out without recolonization stays extinct
    w2, rec2, _ = run_gaia.run(turns=400, seed=10, events=events, recolonize=False)
    check("without recolonization the extinction is permanent",
          len(w2.living_organisms("Grazer")) == 0)



# -------------------------------------------- feature 11: emergent events

def _fake_row(turn, kills=0, **counts):
    row = {"turn": turn, "kills": kills}
    for name in run_gaia.START_POPULATION:
        row[name] = counts.get(name, 0)
    return row


def _detector(series, kills=None, species=None):
    """
    Build a Recorder whose history is `series`: {species: [count per turn]}.
    Returns (world, recorder, detector) with the clock on the last turn.
    """
    w = World(200, 200, seed=1)
    rec = Recorder(species=species)
    det = EventDetector(rec)
    length = max(len(v) for v in series.values())
    for i in range(length):
        counts = {name: values[i] for name, values in series.items()}
        rec.rows.append(_fake_row(i + 1, kills=(kills[i] if kills else 0), **counts))
    w.turn = length
    return w, rec, det


def _run_through(series, **kw):
    """Feed history one turn at a time, as a real run would."""
    full = _detector(series, **kw)
    w, rec, det = full
    rows = list(rec.rows)
    rec.rows = []
    for i, row in enumerate(rows, 1):
        rec.rows.append(row)
        w.turn = i
        det.check(w)
    return w, rec, det


def _kinds(det, species=None):
    return [e.kind for e in det.events if species is None or e.species == species]


def test_event_booms_and_crashes():
    section("events: booms and crashes")

    w, rec, det = _run_through({"Grazer": [10] * 20 + [24]})
    check("boom detected when a species more than 1.5x's", "population_boom" in _kinds(det, "Grazer"), det.events)

    w, rec, det = _run_through({"Grazer": [10] * 20 + [12]})
    check("small growth is not a boom", _kinds(det) == [], det.events)

    w, rec, det = _run_through({"Grazer": [20] * 20 + [8]})
    check("crash detected when a species halves", "population_crash" in _kinds(det, "Grazer"), det.events)
    crash = [e for e in det.events if e.kind == "population_crash"][0]
    check("crash severity reflects the drop", 0.5 < crash.severity <= 1.0, crash.severity)

    w, rec, det = _run_through({"Grazer": [8] * 20 + [3]})
    check("tiny populations don't count as crashes", _kinds(det) == [], det.events)

    w, rec, det = _run_through({"Ravager": [3] * 20 + [1]})
    check("predators use a smaller threshold", "population_crash" in _kinds(det, "Ravager"), det.events)

    w, rec, det = _run_through({"Ravager": [2] * 20 + [3]})
    check("2 -> 3 predators is not a boom", _kinds(det) == [], det.events)

    # cooldown: a continuing slide is reported once, not every turn
    w, rec, det = _run_through({"Grazer": [30] * 20 + [14, 13, 12, 11, 10, 9, 8, 7]})
    check("cooldown stops repeat crash reports", _kinds(det).count("population_crash") == 1, det.events)

    # no history yet -> nothing
    w, rec, det = _run_through({"Grazer": [30, 5]})
    check("no trend events before a full window of history", _kinds(det) == [])


def test_event_recovery_and_cascade():
    section("events: recovery, cascade, crisis")

    series = {"Grazer": [20] * 20 + [8] * 10 + [17]}
    w, rec, det = _run_through(series)
    kinds = _kinds(det, "Grazer")
    check("recovery follows a crash", kinds == ["population_crash", "ecosystem_recovery"], det.events)

    series = {"Grazer": [20] * 20 + [8] * 15}
    w, rec, det = _run_through(series)
    check("no recovery while the species is still down", "ecosystem_recovery" not in _kinds(det))

    # predators crash, then prey boom shortly after -> trophic cascade
    series = {
        "Ravager": [6] * 10 + [2] * 40,
        "Grazer":  [10] * 25 + [10, 11, 12, 14, 16, 18, 20, 22, 24, 26] * 1 + [26] * 15,
    }
    w, rec, det = _run_through(series)
    check("predator crash then prey boom -> trophic cascade",
          "trophic_cascade" in _kinds(det, "Grazer"), det.events)

    # prey boom with healthy predators is NOT a cascade
    series = {"Ravager": [4] * 50, "Grazer": [10] * 25 + [26] * 25}
    w, rec, det = _run_through(series)
    check("prey boom alone is not a cascade", "trophic_cascade" not in _kinds(det), det.events)

    # three species crashing together -> crisis
    series = {
        "Grazer":   [30] * 20 + [10] * 5,
        "Shellkin": [30] * 20 + [10] * 5,
        "Verdant":  [90] * 20 + [30] * 5,
    }
    w, rec, det = _run_through(series)
    check("three simultaneous crashes -> ecosystem crisis",
          "ecosystem_crisis" in _kinds(det, "Ecosystem"), det.events)

    series = {"Grazer": [30] * 20 + [10] * 5, "Shellkin": [30] * 20 + [10] * 5}
    w, rec, det = _run_through(series)
    check("two crashes are not yet a crisis", "ecosystem_crisis" not in _kinds(det), det.events)


def test_event_predator_dominance():
    section("events: predator dominance")

    series = {"Grazer": [20] * 25, "Shellkin": [10] * 25}
    kills = [0] * 5 + [2] * 20
    w, rec, det = _run_through(series, kills=kills)
    check("heavy killing relative to prey -> predator dominance",
          "predator_dominance" in _kinds(det, "Predators"), det.events)

    w, rec, det = _run_through(series, kills=[0] * 25)
    check("no kills -> no dominance", "predator_dominance" not in _kinds(det))

    w, rec, det = _run_through({"Grazer": [3] * 25}, kills=[1] * 25)
    check("too few prey to call it dominance", "predator_dominance" not in _kinds(det))


def test_event_shortages_and_competition():
    section("events: shortage, competition, starving predators")

    def world_with(species, count, energy):
        w = World(200, 200, seed=1)
        for i in range(count):
            spawn(w, species, 10 + i, 10, energy=energy)
        return w

    def detect(w):
        rec = Recorder()
        rec.rows.append(_fake_row(1))
        det = EventDetector(rec)
        w.turn = 1
        det.check(w)
        return det

    det = detect(world_with("Grazer", 8, energy=15))
    check("starving herd -> food shortage", "food_shortage" in _kinds(det, "Grazer"), det.events)

    det = detect(world_with("Grazer", 8, energy=200))
    check("well-fed herd -> no shortage", "food_shortage" not in _kinds(det))

    det = detect(world_with("Grazer", 3, energy=15))
    check("tiny starving group is ignored", "food_shortage" not in _kinds(det))

    det = detect(world_with("Verdant", 12, energy=1))
    check("producers never have food shortages", "food_shortage" not in _kinds(det))

    # competition: many grazers, few edible plants
    w = world_with("Grazer", 10, energy=150)
    for i in range(10):
        spawn(w, "Verdant", 50 + i, 50, energy=100)
    check("many grazers per plant -> competition",
          "resource_competition" in _kinds(detect(w), "Grazer"))

    w = world_with("Grazer", 10, energy=150)
    for i in range(40):
        spawn(w, "Verdant", 50 + i, 50, energy=100)
    check("plenty of plants -> no competition",
          "resource_competition" not in _kinds(detect(w)))

    w = world_with("Grazer", 10, energy=150)
    for i in range(40):
        spawn(w, "Verdant", 50 + i, 50, energy=20)    # seedlings aren't edible
    check("seedlings don't count as food",
          "resource_competition" in _kinds(detect(w), "Grazer"))

    # recyclers competing for remains
    w = world_with("Mycel", 6, energy=100)
    check("recyclers with no remains -> competition",
          "resource_competition" in _kinds(detect(w), "Mycel"))
    w.add_organic_remains(500, 10, 10)
    check("recyclers with plenty of remains -> none",
          "resource_competition" not in _kinds(detect(w)))

    # starving predators while prey is plentiful
    w = world_with("Grazer", 16, energy=150)
    for i in range(2):
        spawn(w, "Ravager", 100 + i, 100, energy=8)
    check("starving predators amid prey flagged",
          "predator_starving_amid_prey" in _kinds(detect(w), "Predators"))

    w = world_with("Grazer", 4, energy=150)
    for i in range(2):
        spawn(w, "Ravager", 100 + i, 100, energy=8)
    check("starving predators with little prey is expected, not flagged",
          "predator_starving_amid_prey" not in _kinds(detect(w)))


def test_event_output():
    section("events: output")
    w, rec, det = _run_through({"Grazer": [20] * 20 + [8]})
    check("events carry turn, kind, species, severity, detail",
          all(e.turn and e.kind and e.species and 0 <= e.severity <= 1 and e.detail
              for e in det.events))
    check("summary lists events and totals", "population_crash" in det.summary() and "totals" in det.summary())
    check("empty summary is readable", EventDetector(Recorder()).summary() == "no events")
    check("by_kind counts events", det.by_kind().get("population_crash") == 1)

    import os, tempfile, csv
    path = os.path.join(tempfile.gettempdir(), "gaia_test_events.csv")
    det.to_csv(path)
    with open(path) as f:
        rows = list(csv.DictReader(f))
    check("CSV has one row per event", len(rows) == len(det.events))
    os.remove(path)

    check("empty recorder is handled", EventDetector(Recorder()).check(World(10, 10, seed=1)) is None)


def test_events_in_real_runs():
    section("events: real runs")
    w, rec, _ = run_gaia.run(turns=300, seed=10,
                             events=[Plague(start=100, species="Grazer", fraction=1.0)])
    det = rec.detector
    kinds = [(e.kind, e.species) for e in det.events]

    check("run() attaches an event detector", isinstance(det, EventDetector))
    check("plague wipe-out shows up as a Grazer crash", ("population_crash", "Grazer") in kinds, det.summary(20))
    check("recolonization shows up as a Grazer recovery", ("ecosystem_recovery", "Grazer") in kinds, det.summary(20))
    check("early growth is reported as booms", ("population_boom", "Verdant") in kinds)
    check("events are in time order", [e.turn for e in det.events] == sorted(e.turn for e in det.events))
    check("event volume stays readable", len(det.events) < 150, len(det.events))
    check("every event kind is a known one",
          all(e.kind in events_mod.COOLDOWN for e in det.events), {e.kind for e in det.events})

    _, rec2, _ = run_gaia.run(turns=300, seed=10,
                              events=[Plague(start=100, species="Grazer", fraction=1.0)])
    check("same seed -> same events", [str(e) for e in det.events] == [str(e) for e in rec2.detector.events])

    # detection never changes the simulation
    _, bare, _ = run_gaia.run(turns=120, seed=5)
    check("detector doesn't change the ecosystem",
          bare.rows == run_gaia.run(turns=120, seed=5)[1].rows)

    print("\n      events from this run:")
    for line in det.summary(12).splitlines():
        print("        " + line)



# --------------------------------------- feature 12: visualization (snapshot)

def test_snapshot():
    section("snapshot")
    w = World(100, 80, seed=1)
    spawn(w, "Verdant", 10, 20, energy=100)
    spawn(w, "Verdant", 11, 21, energy=50)
    g = spawn(w, "Grazer", 30, 40, energy=200, age=7)
    dead = spawn(w, "Grazer", 31, 41, energy=80)
    dead.status = "Dead"
    w.add_organic_remains(40, 5, 5)
    w.add_organic_remains(10, 60, 60)
    w.turn = 12

    snap = take_snapshot(w)
    check("turn and world size copied", (snap.turn, snap.width, snap.height) == (12, 100, 80))
    check("counts per species", snap.counts["Verdant"] == 2 and snap.counts["Grazer"] == 1)
    check("species with nobody alive have count 0", snap.counts["Ravager"] == 0)
    check("dead organisms are not shown", snap.total_population == 3 and all(o.name != dead.name for o in snap.organisms))
    check("every species is listed", set(snap.counts) == set(run_gaia.START_POPULATION))

    verdant = snap.energy["Verdant"]
    check("energy stats: mean/min/max/total",
          (verdant.n, verdant.mean, verdant.low, verdant.high, verdant.total) == (2, 75, 50, 100, 150))
    check("empty species has zeroed stats", snap.energy["Ravager"].n == 0 and snap.energy["Ravager"].mean == 0)
    check("total energy alive", snap.total_energy == 350)

    view = [o for o in snap.organisms if o.species == "Grazer"][0]
    check("organism view carries position, energy, age",
          (view.x, view.y, view.energy, view.age) == (30, 40, 200, 7))
    check("fullness is energy / capacity", abs(view.fullness - 200 / holding_capacity("Grazer")) < 1e-9)
    check("fullness is capped at 1", take_snapshot(_overfull()).organisms[0].fullness == 1.0)
    check("view keeps a reference to the live organism", view.ref is g)

    check("remains total and patches", snap.remains_total == 50 and len(snap.remains_patches) == 2)
    check("light and radiation come from the effective level",
          snap.light == 1.0 and snap.radiation == 1.0)

    w.light_multiplier = 0.3
    check("snapshot sees drought", abs(take_snapshot(w).light - 0.3) < 1e-9)
    check("seasonal flag", take_snapshot(w).seasonal is False)
    w.set_seasons(100)
    check("seasonal flag turns on", take_snapshot(w).seasonal is True)

    from environment.resources import Resource
    w.add_resource(Resource("Water", 250, 1))
    check("resources listed", take_snapshot(w).resources == [("Water", 250)])

    check("capacities: producers 2x, animals 4x start",
          holding_capacity("Verdant") == 200 and holding_capacity("Grazer") == 400)

    # taking a snapshot never changes the world
    before = [(o.x, o.y, o.energy, o.age, o.status) for o in w.organisms]
    take_snapshot(w)
    after = [(o.x, o.y, o.energy, o.age, o.status) for o in w.organisms]
    check("snapshot is read-only", before == after)

    check("empty world snapshot works", take_snapshot(World(10, 10, seed=1)).total_population == 0)


def _overfull():
    w = World(50, 50, seed=1)
    spawn(w, "Verdant", 1, 1, energy=9999)
    return w


# ------------------------------------------ feature 12: visualization (viewer)

def _viewer(turns=0, seed=2, events=None, **kw):
    sim, rec, _ = run_gaia.build_simulation(seed=seed, events=events)
    v = viewer_mod.SimulationViewer(sim, recorder=rec, **kw)
    if turns:
        v.step(turns)
    return sim, rec, v


def test_viewer_helpers():
    section("viewer: helpers")
    if not HAVE_MATPLOTLIB:
        print("  SKIP  matplotlib not installed (pip install matplotlib)")
        return

    check("every species has a colour and a marker",
          all(s in viewer_mod.SPECIES_STYLE for s in run_gaia.START_POPULATION))
    check("species colours are all different",
          len({v["color"] for v in viewer_mod.SPECIES_STYLE.values()}) == len(viewer_mod.SPECIES_STYLE))
    check("unknown species falls back", viewer_mod.style_for("Nobody") == viewer_mod.FALLBACK_STYLE)
    check("well-fed organisms draw bigger",
          viewer_mod.marker_size("Grazer", 1.0) > viewer_mod.marker_size("Grazer", 0.1))
    check("predators draw bigger than plants",
          viewer_mod.marker_size("Predator", 0.5) > viewer_mod.marker_size("Producer", 0.5))
    check("remains markers grow with the pile but are capped",
          viewer_mod.remains_size(10) < viewer_mod.remains_size(400) <= viewer_mod.remains_size(10 ** 6)
          == viewer_mod.remains_size(10 ** 9))
    check("speed list ends with max", viewer_mod.SPEEDS[-1] == "max" and viewer_mod.SPEEDS[0] == 1)


def test_viewer_controls():
    section("viewer: controls")
    if not HAVE_MATPLOTLIB:
        print("  SKIP  matplotlib not installed")
        return

    sim, rec, v = _viewer(start_paused=True)
    check("starts paused when asked", v.paused is True)
    check("play button says Play when paused", v.btn_play.label.get_text() == "Play")

    v.toggle_pause()
    check("toggle_pause starts it", v.paused is False and v.btn_play.label.get_text() == "Pause")
    v.toggle_pause()
    check("and pauses again", v.paused is True)

    turn = sim.world.turn
    v.step(3)
    check("step advances the simulation", sim.world.turn == turn + 3)
    check("recorder saw every stepped turn", len(rec.rows) == 3)

    # stepping must not print the simulation's chatter
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        v.step(2)
    check("stepping is silent", buf.getvalue() == "", buf.getvalue()[:60])

    v.set_speed_index(0)
    check("slider sets the speed", v.speed == 1)
    v.set_speed_index(99)
    check("speed index is clamped", v.speed == "max")
    v.set_speed_index(3)
    check("speed label shows turns per second", "turns/s" in v.speed_value.get_text())
    v.set_speed_index(len(viewer_mod.SPEEDS) - 1)
    check("max speed label", v.speed_value.get_text() == "max")

    check("remains shown by default", v.show_remains is True)
    v.toggle_remains()
    check("remains toggle", v.show_remains is False and "off" in v.btn_remains.label.get_text())
    v.toggle_remains()

    class Key:
        def __init__(self, key):
            self.key = key

    v.paused = True
    v._on_key(Key(" "))
    check("space key toggles pause", v.paused is False)
    turn = sim.world.turn
    v._on_key(Key("right"))
    check("right arrow steps one turn", sim.world.turn == turn + 1)
    v.set_speed_index(3)
    v._on_key(Key("up"))
    check("up arrow speeds up", v.speed_index == 4)
    v._on_key(Key("down"))
    v._on_key(Key("down"))
    check("down arrow slows down", v.speed_index == 2)
    v._on_key(Key("r"))
    check("r key toggles remains", v.show_remains is False)
    v.close()


def test_viewer_drawing():
    section("viewer: what is drawn")
    if not HAVE_MATPLOTLIB:
        print("  SKIP  matplotlib not installed")
        return

    sim, rec, v = _viewer(turns=60)
    snap = take_snapshot(sim.world)

    drawn = {s: len(sc.get_offsets()) for s, sc in v.scatters.items()}
    check("one marker per living organism, per species",
          drawn == snap.counts, (drawn, snap.counts))
    check("markers sit at the organisms' positions",
          all(abs(float(sc.get_offsets()[0][0]) - [o for o in snap.organisms if o.species == s][0].x) < 1e-9
              for s, sc in v.scatters.items() if len(sc.get_offsets())))
    check("remains drawn as patches",
          len(v.remains_scatter.get_offsets()) == len(snap.remains_patches) > 0)
    check("title shows the turn", f"Turn {snap.turn}" in v.map_title.get_text())

    counts = {s: int(t.get_text()) for s, t in zip(run_gaia.START_POPULATION, v.pop_counts)}
    check("population counters match the world", counts == snap.counts, counts)
    check("total population label", f"{snap.total_population} /" in v.pop_total.get_text())

    check("energy table has a row per species", len(v.energy_rows) == len(snap.counts))
    grazer_row = v.energy_rows[list(run_gaia.START_POPULATION).index("Grazer")].get_text()
    check("energy row shows the mean", f"{snap.energy['Grazer'].mean:.0f}" in grazer_row, grazer_row)
    check("total energy line", f"{snap.total_energy:,.0f}" in v.energy_total.get_text())

    check("remains text shows the total", f"{snap.remains_total:,.0f}" in v.remains_text.get_text())
    check("light bar reflects light", abs(v.env_bars["Light"].get_width() - 0.55 * snap.light) < 1e-9)

    line = v.hist_lines["Verdant"]
    check("history graph has one point per turn", len(line.get_xdata()) == 60)

    # the remains toggle hides the remains markers
    v.toggle_remains()
    check("remains hidden when toggled off", len(v.remains_scatter.get_offsets()) == 0)
    v.toggle_remains()

    # events list
    check("events list has a line per slot", len(v.event_texts) == viewer_mod.EVENT_LINES)
    sim2, rec2, v2 = _viewer(turns=0)
    check("quiet start says nothing notable", "nothing notable" in v2.event_texts[0].get_text())
    v2.close()
    sim3, rec3, v3 = _viewer(turns=300, seed=5)
    shown = [t.get_text() for t in v3.event_texts if t.get_text()]
    check("detected events appear in the list", len(shown) > 0 and len(shown) <= viewer_mod.EVENT_LINES, shown[:3])
    v3.close()

    # viewer without a recorder / detector still works
    sim4 = run_gaia.build_simulation(seed=1)[0]
    bare = viewer_mod.SimulationViewer(sim4)
    bare.step(30)
    check("works without a recorder (history kept by the viewer)",
          len(bare.hist_lines["Verdant"].get_xdata()) >= 30)
    check("says so when no detector is attached", "no event detector" in bare.event_texts[0].get_text())
    bare.close()
    v.close()


def test_viewer_selection_and_save():
    section("viewer: selection and saving")
    if not HAVE_MATPLOTLIB:
        print("  SKIP  matplotlib not installed")
        return

    sim, rec, v = _viewer(turns=20)
    snap = take_snapshot(sim.world)
    target = [o for o in snap.organisms if o.kind != "Producer"][0]

    class Click:
        inaxes = v.ax_map
        xdata, ydata = target.x, target.y

    v._on_click(Click)
    check("clicking an organism selects it", v.selected is target.ref)
    check("selection ring appears on it", len(v.selection_ring.get_offsets()) == 1)
    check("info box shows its details", v.info_text.get_visible() and target.name in v.info_text.get_text())

    class Away:
        inaxes = v.ax_map
        xdata, ydata = -50.0, -50.0

    v._on_click(Away)
    check("clicking empty space clears the selection", v.selected is None and not v.info_text.get_visible())

    class Outside:
        inaxes = v.ax_pop
        xdata, ydata = 0.5, 0.5

    v.selected = target.ref
    v._on_click(Outside)
    check("clicks outside the map are ignored", v.selected is target.ref)

    # a selected organism that dies is dropped
    target.ref.status = "Dead"
    v.refresh()
    check("selection clears when the organism dies", v.selected is None)

    class Key:
        key = "c"

    v.selected = [o for o in take_snapshot(sim.world).organisms][0].ref
    v._on_key(Key)
    check("c key clears the selection", v.selected is None)

    import os, tempfile
    path = os.path.join(tempfile.gettempdir(), "gaia_test_frame.png")
    v.save_png(path)
    check("save_png writes an image", os.path.exists(path) and os.path.getsize(path) > 20000)
    os.remove(path)

    # blitting path (used by the live window) works and doesn't break saving
    v._enable_blit()
    v.fig.canvas.draw()
    check("blit background captured after a draw", v._bg is not None)
    turn = sim.world.turn
    v.step(1)
    v.refresh_map()
    check("map-only refresh runs", sim.world.turn == turn + 1)
    path = os.path.join(tempfile.gettempdir(), "gaia_test_frame2.png")
    v.save_png(path)
    check("save_png works while blitting and restores it", v._blit is True and os.path.getsize(path) > 20000)
    os.remove(path)
    v._disable_blit()
    check("blitting can be turned off", v._blit is False)
    v.close()

    # the viewer never changes how the ecosystem plays out
    sim_a = run_gaia.build_simulation(seed=9)[0]
    sim_b, rec_b, va = _viewer(seed=9)
    va.step(80)
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(80):
            sim_a.advance_turn()
    state = lambda s: sorted((o.species, round(o.x, 6), round(o.y, 6), round(o.energy, 6)) for o in s.world.organisms)
    check("watching doesn't change the simulation", state(sim_a) == state(sim_b))
    va.close()


# -------------------------------------------------------------------- main

# ------------------------------------------------------------ Phase 7 tests
# Nutrient cycle, evolution, camera, teaching content and the Lab.

def test_nutrient_cycle():
    section("nutrient cycle")
    from environment.world import FERTILITY_BONUS, FERTILITY_SATURATION
    w = World(100, 100, seed=1)
    check("soil starts bare", w.fertility_at(5, 5) == 0.0)
    w.add_fertility(5, 5, FERTILITY_SATURATION)
    check("nutrients enrich the soil", w.fertility_at(5, 5) == 1.0)
    check("far away soil stays bare", w.fertility_at(95, 95) == 0.0)

    # rich soil grows plants faster
    a, b = create_organism("Verdant"), create_organism("Verdant")
    a.x, a.y, b.x, b.y = 5, 5, 95, 95
    a.energy = b.energy = 50
    w.add_organism(a); w.add_organism(b)
    gain_rich = photosynthesize(a, w)
    gain_bare = photosynthesize(b, w)
    check("rich soil boosts photosynthesis",
          abs(gain_rich / gain_bare - (1 + FERTILITY_BONUS)) < 1e-9, f"{gain_rich} vs {gain_bare}")

    # rotting remains feed the soil
    w2 = World(100, 100, seed=1)
    w2.add_organic_remains(100, 50, 50)
    before = w2.fertility_at(50, 50)
    w2.decay_remains()
    check("rotting remains enrich soil", w2.fertility_at(50, 50) > before)

    # switching it off restores the old behaviour exactly
    w3 = World(100, 100, seed=1)
    w3.nutrient_cycle = False
    w3.add_fertility(5, 5, 999)
    check("nutrient cycle can be disabled", w3.fertility_at(5, 5) == 0.0 and not w3.fertility)

    # soil leaches away slowly
    w4 = World(100, 100, seed=1)
    w4.add_fertility(5, 5, 100)
    for _ in range(50):
        w4.decay_fertility()
    check("soil nutrients decay", 0 < w4.fertility[(0, 0)] < 100)


def test_evolution():
    section("evolution")
    import random
    import organisms.evolution as evo
    from organisms.hunting import hunt_chance
    parent = create_organism("Grazer")
    child = create_organism("Grazer")
    check("genes start neutral", parent.speed_gene == 1.0 and parent.sense_gene == 1.0)

    parent.speed_gene, parent.sense_gene = 1.4, 1.2
    rng = random.Random(1)
    evo.inherit(parent, child, rng)
    check("child inherits close to parent", abs(child.speed_gene - 1.4) < 0.3)
    check("genes stay in range", all(evo.GENE_MIN <= g <= evo.GENE_MAX
                                     for g in (child.speed_gene, child.sense_gene)))
    check("fast animals burn more energy", child.metabolism > child.base_metabolism)

    # producers never evolve
    plant, seed = create_organism("Verdant"), create_organism("Verdant")
    evo.inherit(plant, seed, rng)
    check("producers do not evolve", seed.speed_gene == 1.0)

    # speed gene matters in a hunt
    pred, prey = create_organism("Ravager"), create_organism("Grazer")
    base = hunt_chance(pred, prey)
    prey.speed_gene = 1.5
    check("faster prey is harder to catch", hunt_chance(pred, prey) < base)

    # switch off: nothing changes
    evo.ENABLED = False
    try:
        kid = create_organism("Grazer")
        evo.inherit(parent, kid, rng)
        check("evolution can be frozen", kid.speed_gene == 1.0)
    finally:
        evo.ENABLED = True

    # genes really drift over a run
    world, rec, _ = run_gaia.run(turns=300, seed=2)
    spread = {o.speed_gene for o in world.living_organisms("Grazer")}
    check("a real run produces varied genes", len(spread) > 3, f"{len(spread)} distinct")


def test_camera():
    section("camera")
    from types import SimpleNamespace as NS
    from Interface.camera import Camera
    rect = NS(x=12, y=12, w=900, h=800, centerx=12 + 450, centery=12 + 400)
    cam = Camera(100, 100)
    ok = True
    for wx, wy in [(0, 0), (50, 50), (100, 100), (20, 80)]:
        sx, sy = cam.world_to_screen(wx, wy, rect)
        ok &= abs(sx - (rect.x + wx / 100 * rect.w)) < 1e-6
        ok &= abs(sy - (rect.y + rect.h - wy / 100 * rect.h)) < 1e-6
    check("zoom 1 matches the original mapping", ok)

    cam.zoom_at(2.0, 25, 75)
    for _ in range(300):
        cam.update(0.016)
    sx, sy = cam.world_to_screen(25, 75, rect)
    wx, wy = cam.screen_to_world(sx, sy, rect)
    check("screen <-> world round trip", abs(wx - 25) < 1e-6 and abs(wy - 75) < 1e-6)
    left, bottom, right, top = cam.visible_world()
    check("view stays inside the world",
          left >= -1e-6 and bottom >= -1e-6 and right <= 100 + 1e-6 and top <= 100 + 1e-6)
    cam.reset()
    for _ in range(300):
        cam.update(0.016)
    check("reset returns to the full map", cam.zoom == 1.0 and cam.is_default)


def test_education_content():
    section("teaching content")
    from Interface import education as edu
    from data.species import SPECIES
    check("every species has a card", all(edu.card_for(s)["blurb"] for s in SPECIES))
    check("food web has an arrow per diet entry", len(edu.web_edges()) >= 10)
    check("every web node is placed", all(s in edu.WEB_NODES for s in SPECIES))
    edge_names = {n for e in edu.web_edges() for n in e[:2]}
    check("web edges only use placed nodes", edge_names <= set(edu.WEB_NODES))
    check("showcase has steps and a length", edu.showcase_length() > 200)
    starts = [t for t, _ in edu.showcase_schedule()]
    check("showcase steps are in order", starts == sorted(starts))
    check("every detector event has a lesson",
          all(edu.lesson_for(k) for k in events_mod.COOLDOWN))

    world, rec, _ = run_gaia.run(turns=120, seed=3)
    snap = take_snapshot(world)
    levels = dict((n, e) for n, e, _ in edu.trophic_levels(snap))
    check("producers hold the most energy", levels["Producers"] > levels["Predators"])
    check("seasons are named", edu.season_name(world) in edu.SEASONS)
    check("mortality adds up", sum(n for _, n, _ in edu.mortality(rec.rows, 100)) > 0)


def test_lab():
    section("lab experiments")
    from Interface.experiments import Lab, PREDATORS
    sim, rec, stress = run_gaia.build_simulation(seed=3)
    lab = Lab(sim.world)
    sim.pre_turn_hooks.append(lab)
    with quiet():
        for _ in range(40):
            sim.advance_turn()
    with quiet():
        lab.toggle("no_predators")
        for _ in range(3):
            sim.advance_turn()
    check("no_predators removes every predator",
          sum(len(sim.world.living_organisms(p)) for p in PREDATORS) == 0)
    lab.toggle("no_predators")

    before = len(sim.world.living_organisms())
    with quiet():
        lab.toggle("meteor")
    check("meteor kills things and remembers where", lab.last_meteor is not None
          and len(sim.world.living_organisms()) < before)

    n = len(sim.world.living_organisms("Grazer"))
    with quiet():
        lab.toggle("baby_boom")
    check("baby boom adds grazers", len(sim.world.living_organisms("Grazer")) == n + 25)

    seasons = sim.world.season_length
    lab.toggle("endless_summer")
    check("endless summer stops the seasons", sim.world.season_length is None)
    lab.toggle("barren_soil")
    check("barren soil switches the nutrient cycle off", not sim.world.nutrient_cycle)
    lab.clear()
    check("clearing restores everything",
          sim.world.season_length == seasons and sim.world.nutrient_cycle and not lab.active)


def test_snapshot_additions():
    section("snapshot: genes, soil and stats")
    world, rec, _ = run_gaia.run(turns=150, seed=4)
    snap = take_snapshot(world)
    check("traits per species", set(snap.traits) == set(snap.counts))
    check("soil cells are reported", len(snap.fertility) > 0 and 0 <= snap.fertility_mean <= 1)
    check("meal counters per food-web arrow",
          any(k.startswith("ate:") for k in snap.stats))
    animals = [o for o in snap.organisms if o.kind != "Producer"]
    check("organisms carry genes and lifespan",
          all(o.lifespan > 0 and o.speed_gene > 0 for o in animals))


def test_lab_buttons_and_reset():
    section("lab: instant effect and a Reset that restores")
    from Interface.experiments import Lab, PREDATORS, DECOMPOSERS
    sim, rec, stress = run_gaia.build_simulation(seed=3)
    lab = Lab(sim.world)
    sim.pre_turn_hooks.append(lab)
    w = sim.world
    with quiet():
        for _ in range(40):
            sim.advance_turn()

    # switches act immediately (the viewer may be paused)
    lab.toggle("no_predators")
    check("no_predators works with no turn running",
          sum(len(w.living_organisms(p)) for p in PREDATORS) == 0)
    lab.toggle("no_decomposers")
    check("no_decomposers works with no turn running",
          sum(len(w.living_organisms(d)) for d in DECOMPOSERS) == 0)

    # turning a switch off brings the species back
    lab.toggle("no_predators")
    check("switching no_predators off restores predators",
          all(len(w.living_organisms(p)) > 0 for p in PREDATORS), str(lab.last_restored))

    # Reset undoes every switch and restores what was wiped out
    for key in ("barren_soil", "no_evolution", "endless_summer"):
        lab.toggle(key)
    seasons = 120
    lab.clear()
    import organisms.evolution as evo
    check("reset switches everything off", not lab.active)
    check("reset restores seasons, soil and evolution",
          w.season_length == seasons and w.nutrient_cycle and evo.ENABLED)
    check("reset brings the decomposers back",
          all(len(w.living_organisms(d)) > 0 for d in DECOMPOSERS))

    # a species that is alive is never duplicated by a reset
    before = len(w.living_organisms("Mycel"))
    lab.toggle("no_decomposers")
    lab.toggle("no_decomposers")
    check("restoring uses founder numbers", len(w.living_organisms("Mycel")) <= 4)
    lab.clear()
    check("reset with nothing active is harmless", not lab.active)


def test_presenter_controls():
    section("presenter controls: story, keys, pause on caption, step menu, notes")
    import os
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    import pygame
    pygame.init()
    from Interface import education as edu
    from Interface.showcase import ShowcaseDirector

    # 1. Story steps and speaker notes integrity
    schedule = edu.showcase_schedule()
    check("showcase has complete multi-chapter story", len(schedule) == 13)
    check("all showcase steps have speaker notes", all(s.get("speaker_note") for _, s in schedule))

    # 2. ShowcaseDirector presenter features
    director = ShowcaseDirector()
    check("director loads all showcase steps", len(director.steps) == len(schedule))
    check("speaker notes hidden by default", director.show_speaker_notes is False)
    check("pause on caption off by default", director.pause_on_caption is False)

    director.start()
    check("director starts at step 0", director.index == 0)
    check("current step matches first story step", director.current_step.title == schedule[0][1]["title"])

    # Next / Back stepping
    director.next_step()
    check("next_step advances index to 1", director.index == 1)
    director.prev_step()
    check("prev_step returns index to 0", director.index == 0)

    # Jump to any part via step index
    director.jump_to(7)
    check("jump_to jumps to chosen step", director.index == 7)

    # Toggles
    director.show_speaker_notes = True
    check("speaker notes toggle on", director.show_speaker_notes is True)
    summary = director.summary_dict()
    check("summary dict includes note when shown", bool(summary["speaker_note"]))
    director.show_speaker_notes = False
    check("summary dict hides note when hidden", director.summary_dict()["speaker_note"] == "")

    # 3. PygameViewer presenter integration
    from Interface.pygame_viewer import PygameViewer
    sim, rec, stress = run_gaia.build_simulation(seed=2)
    viewer = PygameViewer(sim, recorder=rec, stress=stress, showcase=True, pause_on_caption=True, speaker_notes=False)
    viewer._screen = pygame.Surface((1400, 840))
    viewer._start_showcase()

    check("showcase started", viewer.showcase_on is True)
    check("pause on caption preserved in viewer", viewer.director.pause_on_caption is True)
    check("simulation automatically pauses at first caption", viewer.paused is True)

    # Next step (PageDown / K / Right)
    viewer.skip_showcase_step()
    check("Next key advances showcase step", viewer._showcase_idx == 1 and viewer.director.index == 1)
    check("stays paused at next caption", viewer.paused is True)

    # Space/Return unpauses to let simulation run until next caption
    viewer._on_key(pygame.K_SPACE)
    check("Space unpauses at caption", viewer.paused is False)

    # Previous step (PageUp / Left)
    viewer.prev_showcase_step()
    check("Back key goes to previous step", viewer._showcase_idx == 0 and viewer.director.index == 0)

    # Step Menu
    viewer.toggle_step_menu()
    check("step menu opens", viewer.show_step_menu is True)
    viewer._on_key(pygame.K_3)  # press '3' in step menu -> jump to step index 2
    check("number key jumps directly to step", viewer._showcase_idx == 2 and viewer.show_step_menu is False)

    # Speaker notes toggle
    viewer.toggle_speaker_notes()
    check("toggle_speaker_notes shows notes", viewer.director.show_speaker_notes is True)
    viewer.toggle_speaker_notes()
    check("toggle_speaker_notes hides notes", viewer.director.show_speaker_notes is False)

    # Pause on caption toggle
    viewer.toggle_pause_on_caption()
    check("toggle_pause_on_caption turns mode off", viewer.director.pause_on_caption is False)


if __name__ == "__main__":
    for t in [
        test_environment_multipliers,
        test_reproduction_chance_and_crowding,
        test_reproduction_is_probabilistic,
        test_prey_refuge,
        test_hooks,
        test_recorder,
        test_collapse_and_recovery,
        test_drought_and_radiation,
        test_plague,
        test_stress_edge_cases,
        test_recolonization,
        test_long_run_invariants,
        test_determinism,
        test_recovery_after_collapse,
        test_event_booms_and_crashes,
        test_event_recovery_and_cascade,
        test_event_predator_dominance,
        test_event_shortages_and_competition,
        test_event_output,
        test_events_in_real_runs,
        test_snapshot,
        test_viewer_helpers,
        test_viewer_controls,
        test_viewer_drawing,
        test_viewer_selection_and_save,
        test_nutrient_cycle,
        test_evolution,
        test_camera,
        test_education_content,
        test_lab,
        test_snapshot_additions,
        test_lab_buttons_and_reset,
        test_presenter_controls,
    ]:
        try:
            t()
        except Exception as e:
            import traceback
            failed += 1
            print(f"  FAIL  {t.__name__} crashed: {e!r}")
            traceback.print_exc()

    print(f"\n==== {passed} passed, {failed} failed ====")