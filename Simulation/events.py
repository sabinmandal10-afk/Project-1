"""
Feature 11: emergent events.

The EventDetector watches the ecosystem and names the things that happen in
it: booms, crashes, shortages, predator dominance, competition, recoveries
and a few unexpected patterns. It adds nothing to the world; it only reads
the Recorder's history and the live world.

Use it as a post-turn hook, registered AFTER the Recorder:

    recorder = Recorder()
    detector = EventDetector(recorder)
    sim.post_turn_hooks.append(recorder)
    sim.post_turn_hooks.append(detector)
"""

import csv
from dataclasses import dataclass

from data.species import SPECIES
from organisms.behavior import hunger, THREATS, MIN_PLANT_ENERGY, REMAINS_BITE


# ---------------------------------------------------------------- settings

# Booms and crashes compare a species now with `TREND_WINDOW` turns ago
TREND_WINDOW = 20
BOOM_RATIO = 1.5          # now >= 1.5 x then
CRASH_RATIO = 0.5         # now <= 0.5 x then

# Populations smaller than this are too small for a trend to mean much
MIN_COUNT = {"Producer": 10, "Consumer": 10, "Predator": 3,
             "Decomposer": 6, "Scavenger": 6}

# A boom or crash must also change the count by at least this many animals
MIN_CHANGE = {"Producer": 10, "Consumer": 6, "Predator": 2,
              "Decomposer": 3, "Scavenger": 3}

# Food shortage: the species' average hunger (0 fed .. 1 starving)
SHORTAGE_HUNGER = 0.7
SHORTAGE_MIN_MEMBERS = 5

# Predator dominance: kills over the window / prey alive at its start
DOMINANCE_WINDOW = 20
DOMINANCE_KILL_RATIO = 0.4
DOMINANCE_MIN_PREY = 8

# Resource competition: consumers per edible plant
COMPETITION_RATIO = 0.7
COMPETITION_MIN_ANIMALS = 8

# Predators starving even though prey is plentiful (an unexpected pattern)
STARVING_PREDATOR_HUNGER = 0.6
PLENTIFUL_PREY = 15

# Several species crashing close together is a crisis
CRISIS_SPECIES = 3
CRISIS_WINDOW = 15

# A prey boom this soon after a predator crash is a trophic cascade
CASCADE_WINDOW = 30

# A crashed species has recovered when back at this share of its old level
RECOVERY_SHARE = 0.8

# Same kind of event for the same species is not repeated sooner than this
COOLDOWN = {
    "population_boom": 30, "population_crash": 40, "food_shortage": 40,
    "predator_dominance": 40, "resource_competition": 50,
    "ecosystem_recovery": 0, "ecosystem_crisis": 60,
    "trophic_cascade": 60, "predator_starving_amid_prey": 60,
}


@dataclass
class Event:
    turn: int
    kind: str
    species: str       # a species name, or "Ecosystem" / "Predators"
    severity: float    # 0..1, rough size of the event
    detail: str

    def __str__(self):
        return (f"turn {self.turn:>4}  {self.kind:<28} {self.species:<10} "
                f"[{self.severity:.2f}] {self.detail}")


def _type(species):
    return SPECIES[species]["type"]


def _min_count(species):
    return MIN_COUNT.get(_type(species), 10)


# ---------------------------------------------------------------- detector

class EventDetector:

    def __init__(self, recorder):
        self.recorder = recorder
        self.events = []
        self._last_fired = {}       # (kind, species) -> turn
        self._pending_recovery = {}  # species -> (crash turn, level before)

    # post-turn hook: sim.post_turn_hooks.append(detector)
    def __call__(self, sim):
        self.check(sim.world)

    # ---------- bookkeeping ----------

    def _emit(self, world, kind, species, severity, detail):
        last = self._last_fired.get((kind, species))
        if last is not None and world.turn - last < COOLDOWN.get(kind, 0):
            return None

        event = Event(world.turn, kind, species,
                      round(max(0.0, min(1.0, severity)), 2), detail)
        self._last_fired[(kind, species)] = world.turn
        self.events.append(event)
        return event

    def _row_ago(self, turns):
        rows = self.recorder.rows
        if len(rows) <= turns:
            return None
        return rows[-1 - turns]

    def _recent(self, kind, turns, world, species=None):
        return [e for e in self.events
                if e.kind == kind
                and world.turn - e.turn <= turns
                and (species is None or e.species == species)]

    # ---------- the checks ----------

    def check(self, world):
        if not self.recorder.rows:
            return

        self._trends(world)
        self._shortages(world)
        self._dominance(world)
        self._competition(world)
        self._starving_predators(world)
        self._recoveries(world)
        self._crisis(world)

    def _trends(self, world):
        now, then = self.recorder.rows[-1], self._row_ago(TREND_WINDOW)
        if then is None:
            return

        for name in self.recorder.species:
            before, after = then[name], now[name]
            floor = _min_count(name)

            change = abs(after - before)
            if change < MIN_CHANGE.get(_type(name), 5):
                continue

            if before >= floor and after <= before * CRASH_RATIO:
                event = self._emit(
                    world, "population_crash", name,
                    1 - after / before,
                    f"{before} -> {after} in {TREND_WINDOW} turns")
                if event:
                    self._pending_recovery.setdefault(name, (world.turn, before))

            elif after >= floor and after >= max(1, before) * BOOM_RATIO \
                    and before >= max(2, floor // 3):
                event = self._emit(
                    world, "population_boom", name,
                    min(1.0, (after / max(1, before) - 1) / 2),
                    f"{before} -> {after} in {TREND_WINDOW} turns")
                if event:
                    self._maybe_cascade(world, name, before, after)

    def _maybe_cascade(self, world, prey, before, after):
        """Prey boom shortly after its predators crashed."""
        for predator in THREATS.get(prey, []):
            crashed = self._recent("population_crash", CASCADE_WINDOW,
                                   world, predator)
            if crashed:
                self._emit(
                    world, "trophic_cascade", prey, 0.7,
                    f"{prey} boomed ({before} -> {after}) after "
                    f"{predator} crashed at turn {crashed[-1].turn}")
                return

    def _shortages(self, world):
        for name in self.recorder.species:
            if _type(name) == "Producer":
                continue

            members = world.living_organisms(name)
            if len(members) < SHORTAGE_MIN_MEMBERS:
                continue

            mean = sum(hunger(o) for o in members) / len(members)
            if mean >= SHORTAGE_HUNGER:
                self._emit(world, "food_shortage", name, mean,
                           f"average hunger {mean:.2f} across {len(members)}")

    def _dominance(self, world):
        then = self._row_ago(DOMINANCE_WINDOW)
        if then is None:
            return

        prey = [s for s in self.recorder.species if s in THREATS]
        prey_then = sum(then[s] for s in prey)
        if prey_then < DOMINANCE_MIN_PREY:
            return

        window = self.recorder.rows[-DOMINANCE_WINDOW:]
        kills = sum(r["kills"] for r in window)
        ratio = kills / prey_then

        if ratio >= DOMINANCE_KILL_RATIO:
            self._emit(world, "predator_dominance", "Predators",
                       ratio, f"{kills:.0f} kills vs {prey_then} prey "
                       f"in {DOMINANCE_WINDOW} turns")

    def _competition(self, world):
        for name in self.recorder.species:
            kind = _type(name)
            members = len(world.living_organisms(name))

            if kind == "Consumer":
                if members < COMPETITION_MIN_ANIMALS:
                    continue
                food = SPECIES[name]["food"]
                plants = sum(
                    1 for o in world.living_organisms(food)
                    if o.energy >= MIN_PLANT_ENERGY)
                ratio = members / max(1, plants)
                if ratio >= COMPETITION_RATIO:
                    self._emit(world, "resource_competition", name,
                               min(1.0, ratio),
                               f"{members} {name} for {plants} edible {food}")

            elif kind in ("Decomposer", "Scavenger"):
                if members < SHORTAGE_MIN_MEMBERS:
                    continue
                if world.organic_remains < REMAINS_BITE * members:
                    self._emit(
                        world, "resource_competition", name, 0.5,
                        f"{members} {name} sharing "
                        f"{world.organic_remains:.0f} remains")

    def _starving_predators(self, world):
        predators = [s for s in self.recorder.species if _type(s) == "Predator"]
        members = [o for s in predators for o in world.living_organisms(s)]
        prey = sum(len(world.living_organisms(s))
                   for s in self.recorder.species if s in THREATS)

        if len(members) < 2 or prey < PLENTIFUL_PREY:
            return

        mean = sum(hunger(o) for o in members) / len(members)
        if mean >= STARVING_PREDATOR_HUNGER:
            self._emit(world, "predator_starving_amid_prey", "Predators",
                       mean, f"hunger {mean:.2f} with {prey} prey around")

    def _recoveries(self, world):
        row = self.recorder.rows[-1]

        for name, (turn, level) in list(self._pending_recovery.items()):
            if row[name] >= level * RECOVERY_SHARE and row[name] > 0:
                self._emit(world, "ecosystem_recovery", name, 0.5,
                           f"{name} back to {row[name]} (was {level}) "
                           f"{world.turn - turn} turns after the crash")
                del self._pending_recovery[name]

    def _crisis(self, world):
        crashed = {e.species for e in self.events
                   if e.kind == "population_crash"
                   and world.turn - e.turn <= CRISIS_WINDOW}
        if len(crashed) >= CRISIS_SPECIES:
            self._emit(world, "ecosystem_crisis", "Ecosystem",
                       min(1.0, len(crashed) / 5),
                       f"{len(crashed)} species crashed together: "
                       f"{', '.join(sorted(crashed))}")

    # ---------- output ----------

    def by_kind(self):
        counts = {}
        for e in self.events:
            counts[e.kind] = counts.get(e.kind, 0) + 1
        return counts

    def summary(self, limit=None):
        if not self.events:
            return "no events"
        shown = self.events if limit is None else self.events[:limit]
        lines = [str(e) for e in shown]
        if limit is not None and len(self.events) > limit:
            lines.append(f"... and {len(self.events) - limit} more")
        counts = ", ".join(f"{k}: {v}" for k, v in sorted(self.by_kind().items()))
        return "\n".join(lines) + f"\n\ntotals: {counts}"

    def to_csv(self, path):
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["turn", "kind", "species", "severity", "detail"])
            for e in self.events:
                writer.writerow([e.turn, e.kind, e.species, e.severity, e.detail])