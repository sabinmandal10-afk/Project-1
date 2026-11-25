"""
The Lab: switches and one-off actions for "what if?" experiments.

A Lab is a pre-turn hook. Register it on the simulation and flip switches
with toggle(); each switch changes how the world behaves until you turn it
off again. Everything here only acts through the normal simulation, so runs
stay reproducible when no experiment is active.
"""

from organisms import evolution
from organisms.factory import create_organism
from data.species import SPECIES

PREDATORS = [s for s, d in SPECIES.items() if d["type"] == "Predator"]
DECOMPOSERS = [s for s, d in SPECIES.items() if d["type"] in ("Decomposer", "Scavenger")]

METEOR_RADIUS = 28.0
BOOM_SIZE = 25

# When a removal switch is turned off (or Reset is pressed), any of these
# species that died out are brought back at this size, like founders.
FOUNDERS = {"Ravager": 3, "Skyrender": 2, "Mycel": 4, "Nullborn": 3}


# Shown in the Lab tab. kind "switch" stays on until toggled off; "action" is a one-off.
EXPERIMENTS = [
    {"key": "no_predators", "kind": "switch", "label": "No predators",
     "predict": "Predict: with every Ravager and Skyrender gone, do the herbivores thrive forever?",
     "lesson": "Without predators, herbivores boom, strip their food, then crash. "
               "Predators keep populations in balance."},
    {"key": "no_decomposers", "kind": "switch", "label": "No decomposers",
     "predict": "Predict: what happens to the dead when Mycel and Nullborn are gone?",
     "lesson": "Remains pile up and the soil stops being refreshed, so plants "
               "slowly grow worse. Recycling keeps the cycle running."},
    {"key": "barren_soil", "kind": "switch", "label": "Barren soil",
     "predict": "Predict: how do plants cope if nutrients never return to the ground?",
     "lesson": "Without the nutrient cycle plants lose their growth bonus, "
               "and every level above them feels it."},
    {"key": "no_evolution", "kind": "switch", "label": "Freeze evolution",
     "predict": "Predict: do animals still change if offspring can't inherit new traits?",
     "lesson": "With no inheritance, the averages stop drifting: populations can't adapt."},
    {"key": "endless_summer", "kind": "switch", "label": "Endless summer",
     "predict": "Predict: is a world with permanent full sunlight better for everyone?",
     "lesson": "More light means more plants, so herbivores and predators boom too, "
               "until something else becomes the limit."},
    {"key": "baby_boom", "kind": "action", "label": "Grazer baby boom",
     "predict": "Predict: 25 extra Grazers appear. Do they stay?",
     "lesson": "A sudden surplus overshoots what the plants can feed, so many starve. "
               "Carrying capacity decides how many can live here."},
    {"key": "meteor", "kind": "action", "label": "Meteor strike",
     "predict": "Predict: a meteor wipes out one region. How does life return?",
     "lesson": "Survivors at the edges and migrants refill the crater: "
               "ecosystems recover through recolonisation."},
]

BY_KEY = {e["key"]: e for e in EXPERIMENTS}


class Lab:

    def __init__(self, world):
        self.world = world
        self.active = set()
        self._saved_seasons = None
        self._saved_evolution = None
        self.last = None              # key of the most recently used experiment
        self.last_meteor = None       # (x, y, radius) for the viewer to animate
        self.last_restored = {}       # species brought back by the latest switch-off / reset

    # ---------- queries ----------

    def is_on(self, key):
        return key in self.active

    @property
    def any_active(self):
        return bool(self.active)

    # ---------- control ----------

    def toggle(self, key):
        spec = BY_KEY[key]
        if spec["kind"] == "action":
            self.trigger(key)
            return True

        self.last_restored = {}
        if key in self.active:
            self.active.discard(key)
            self._leave(key)
        else:
            self.active.add(key)
            self._enter(key)
        self.last = key
        return key in self.active

    def trigger(self, key):
        self.last = key
        if key == "baby_boom":
            self._baby_boom()
        elif key == "meteor":
            self._meteor()

    def clear(self):
        """Switch every experiment off and bring back anything it wiped out."""
        self.last_restored = {}
        for key in sorted(self.active):
            self.active.discard(key)
            self._leave(key)

    # ---------- switches ----------

    def _enter(self, key):
        w = self.world
        if key == "barren_soil":
            w.nutrient_cycle = False
            w.fertility.clear()
        elif key == "no_evolution":
            self._saved_evolution = evolution.ENABLED
            evolution.ENABLED = False
        elif key == "endless_summer":
            self._saved_seasons = (w.season_length, w.season_low, w.season_high)
            w.season_length = None
            w.set_environment(light=1.0)
        elif key == "no_predators":
            self._remove(PREDATORS)          # act now, even while paused
        elif key == "no_decomposers":
            self._remove(DECOMPOSERS)

    def _leave(self, key):
        w = self.world
        if key == "barren_soil":
            w.nutrient_cycle = True
        elif key == "no_evolution":
            evolution.ENABLED = True if self._saved_evolution is None else self._saved_evolution
        elif key == "endless_summer" and self._saved_seasons:
            length, low, high = self._saved_seasons
            if length:
                w.set_seasons(length, low=low, high=high)
            self._saved_seasons = None
        elif key == "no_predators":
            self._restore(PREDATORS)
        elif key == "no_decomposers":
            self._restore(DECOMPOSERS)

    # ---------- hook ----------

    def __call__(self, sim):
        """Runs at the start of every turn."""
        if "no_predators" in self.active:
            self._remove(PREDATORS)
        if "no_decomposers" in self.active:
            self._remove(DECOMPOSERS)
        if "endless_summer" in self.active:
            self.world.set_environment(light=1.0)

    def _remove(self, species_names):
        for name in species_names:
            for organism in self.world.living_organisms(name):
                organism.status = "Dead"
                organism.death_cause = "experiment"
                organism.process_death(self.world)

    def _restore(self, species_names):
        """Re-seed species that were wiped out, so Reset really restores the world."""
        w = self.world
        for name in species_names:
            if w.living_organisms(name):
                continue
            count = FOUNDERS.get(name, 2)
            for _ in range(count):
                organism = create_organism(name)
                organism.x, organism.y = w.random_position()
                w.add_organism(organism)
            self.last_restored[name] = count

    # ---------- one-off actions ----------

    def _baby_boom(self):
        w = self.world
        for _ in range(BOOM_SIZE):
            organism = create_organism("Grazer")
            organism.x, organism.y = w.random_position()
            w.add_organism(organism)

    def _meteor(self):
        w = self.world
        x, y = w.random_position()
        for organism in w.living_organisms():
            if ((organism.x - x) ** 2 + (organism.y - y) ** 2) ** 0.5 <= METEOR_RADIUS:
                organism.status = "Dead"
                organism.death_cause = "meteor"
                organism.process_death(w)
        self.last_meteor = (x, y, METEOR_RADIUS)
