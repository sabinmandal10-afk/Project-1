"""Headless GAIA runner: build a world, run N turns quietly, report."""

import contextlib
import io
import sys

from environment.world import World
from Simulation.simulation import Simulation
from organisms.factory import create_organism
from Simulation.metrics import Recorder
from Simulation.events import EventDetector
from Simulation.stress import StressManager, Recolonization

# Species that die out come back as migrants once their food is plentiful
RECOLONIZE = {
    "Grazer":    {"delay": 60, "count": 4, "min_food": 20, "food": ["Verdant"]},
    "Shellkin":  {"delay": 60, "count": 3, "min_food": 20, "food": ["Crystalis"]},
    "Ravager":   {"delay": 40, "count": 2, "min_food": 15, "food": ["Grazer", "Shellkin"]},
    "Skyrender": {"delay": 40, "count": 1, "min_food": 15, "food": ["Grazer", "Shellkin"]},
}

START_POPULATION = {
    "Verdant": 30, "Crystalis": 15, "Grazer": 20, "Shellkin": 12,
    "Ravager": 3, "Skyrender": 2, "Mycel": 4, "Nullborn": 3,
}


def build_world(seed=1, size=100, population=None, seasons=True):
    world = World(size, size, seed=seed)

    if seasons:
        world.set_seasons(length=120, low=0.5, high=1.0)

    for species, count in (population or START_POPULATION).items():
        for _ in range(count):
            organism = create_organism(species)
            organism.x, organism.y = world.random_position()
            world.add_organism(organism)

    return world


def build_simulation(seed=1, events=None, recolonize=True, **world_options):
    """
    Everything wired up and ready to step: world, simulation, recorder,
    stress manager and event detector. Used by run() and by the viewer.
    Returns (sim, recorder, stress).
    """
    world = build_world(seed=seed, **world_options)
    sim = Simulation(world, autonomous=True)

    recorder = Recorder()
    stress = StressManager(events)
    sim.pre_turn_hooks.append(stress)
    if recolonize:
        sim.pre_turn_hooks.append(Recolonization(RECOLONIZE))
    sim.post_turn_hooks.append(recorder)
    detector = EventDetector(recorder)
    sim.post_turn_hooks.append(detector)
    recorder.detector = detector   # keeps the 3-value return of run()

    return sim, recorder, stress


def run(turns=400, seed=1, events=None, quiet=True, recolonize=True, **world_options):
    sim, recorder, stress = build_simulation(
        seed=seed, events=events, recolonize=recolonize, **world_options)

    # The simulation prints a lot; silence it for long runs
    sink = io.StringIO() if quiet else sys.stdout
    with contextlib.redirect_stdout(sink):
        for _ in range(turns):
            sim.advance_turn()

    return sim.world, recorder, stress


if __name__ == "__main__":
    from Simulation.stress import Drought, Plague

    world, recorder, stress = run(
        turns=500,
        events=[Drought(start=200, duration=60, severity=0.3),
                Plague(start=350, species="Grazer", fraction=0.7)],
    )
    print(recorder.summary())
    print("\nstress log:", stress.log)
    print("\n--- emergent events ---")
    print(recorder.detector.summary(limit=40))
    recorder.detector.to_csv("gaia_events.csv")
    recorder.to_csv("gaia_run.csv")
    print("history saved to gaia_run.csv")