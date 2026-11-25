import math
import random
from collections import Counter
from organisms.lineage_flow import LineageAndFlowTracker


# Remains that fall within this distance of existing remains join that patch
REMAINS_MERGE_RADIUS = 2.0

# Fraction of every remains patch that rots away each turn
REMAINS_DECAY = 0.005

# --- Nutrient cycle: rotting remains enrich the soil, and rich soil grows
# plants faster. The soil is a coarse grid of cells.
NUTRIENT_CYCLE = True
FERTILITY_CELL = 10.0         # world units per soil cell
FERTILITY_SATURATION = 300.0  # soil this rich gives the full growth bonus
FERTILITY_BONUS = 0.5         # +50% photosynthesis on fully rich soil
FERTILITY_DECAY = 0.01        # soil nutrients wash away slowly
FERTILITY_FROM_ROT = 0.6      # share of rotting remains that enriches the soil


class RemainsPatch:
    """A pile of organic remains at a place on the map."""

    def __init__(self, x, y, amount):
        self.x = x
        self.y = y
        self.amount = amount


class World:

    def __init__(self, width, height, seed=None):

        self.width = width
        self.height = height

        self.resources = []
        self.organisms = []
        self.remains_patches = []
        self.remains_decay = REMAINS_DECAY
        self.turn = 0
        self.birth_counter = 0
        self.lineage_tracker = LineageAndFlowTracker()

        # Seeded generator: varied runs, but any run can be replayed exactly
        self.rng = random.Random(seed)

        # Environmental conditions (0.0 = none, 1.0 = full)
        self.light_level = 1.0
        self.radiation_level = 1.0

        # Temporary multipliers used by stress events (drought, radiation storms)
        self.light_multiplier = 1.0
        self.radiation_multiplier = 1.0

        # Optional seasons: light rises and falls over `season_length` turns
        self.season_length = None
        self.season_low = 0.5
        self.season_high = 1.0

        # Running tally of what happens in the world (births, kills, meals...)
        self.stats = Counter()

        # Soil fertility: {(cell_x, cell_y): nutrients}
        self.nutrient_cycle = NUTRIENT_CYCLE
        self.fertility = {}

    # ---------- environment ----------

    @property
    def effective_light(self):
        return max(0.0, min(1.0, self.light_level * self.light_multiplier))

    @property
    def effective_radiation(self):
        return max(0.0, min(1.0, self.radiation_level * self.radiation_multiplier))

    def set_environment(self, light=None, radiation=None):

        if light is not None:
            self.light_level = max(0.0, min(1.0, light))

        if radiation is not None:
            self.radiation_level = max(0.0, min(1.0, radiation))

    def set_seasons(self, length, low=0.5, high=1.0):
        """Make light cycle between `low` and `high` every `length` turns."""

        self.season_length = length
        self.season_low = max(0.0, min(1.0, low))
        self.season_high = max(0.0, min(1.0, high))
        self.update_season()

    def update_season(self):

        if not self.season_length:
            return

        middle = (self.season_low + self.season_high) / 2
        swing = (self.season_high - self.season_low) / 2

        self.light_level = middle + swing * math.sin(
            2 * math.pi * self.turn / self.season_length
        )

    # ---------- space ----------

    def in_bounds(self, x, y):

        return 0 <= x <= self.width and 0 <= y <= self.height

    def clamp(self, x, y):

        return (
            max(0, min(self.width, x)),
            max(0, min(self.height, y))
        )

    def random_position(self):

        return (
            self.rng.uniform(0, self.width),
            self.rng.uniform(0, self.height)
        )

    def distance(self, a, b):

        return math.hypot(a.x - b.x, a.y - b.y)

    def distance_to(self, organism, x, y):

        return math.hypot(organism.x - x, organism.y - y)

    def in_range(self, a, b, max_distance):

        return self.distance(a, b) <= max_distance

    # ---------- organisms & resources ----------

    def add_resource(self, resource):

        self.resources.append(resource)

    def add_organism(self, organism, x=None, y=None):

        if x is not None or y is not None:

            if x is None or y is None:
                raise ValueError("Give both x and y, or neither.")

            if not self.in_bounds(x, y):
                raise ValueError(
                    f"Position ({x}, {y}) is outside the world "
                    f"({self.width} x {self.height})."
                )

            organism.x = x
            organism.y = y

        self.organisms.append(organism)

    def living_organisms(self, species=None):

        return [
            o for o in self.organisms
            if o.status == "Alive"
            and (species is None or o.species == species)
        ]

    def nearest_living(self, organism, species_names):

        if isinstance(species_names, str):
            species_names = [species_names]

        candidates = [
            o for o in self.organisms
            if o.status == "Alive"
            and o is not organism
            and o.species in species_names
        ]

        if not candidates:
            return None

        return min(candidates, key=lambda o: self.distance(organism, o))

    def remove_dead(self):

        before = len(self.organisms)
        self.organisms = [o for o in self.organisms if o.status == "Alive"]

        return before - len(self.organisms)

    # ---------- organic remains ----------

    @property
    def organic_remains(self):
        """Total remains lying anywhere in the world."""

        return sum(patch.amount for patch in self.remains_patches)

    def add_organic_remains(self, amount, x=None, y=None):
        """Drop remains at (x, y); defaults to the middle of the world."""

        if amount <= 0:
            return

        if x is None or y is None:
            x, y = self.width / 2, self.height / 2

        for patch in self.remains_patches:
            if math.hypot(patch.x - x, patch.y - y) <= REMAINS_MERGE_RADIUS:
                patch.amount += amount
                return

        self.remains_patches.append(RemainsPatch(x, y, amount))

    def remains_near(self, x, y, reach):
        """Remains patches within `reach` of a point, nearest first."""

        found = [
            p for p in self.remains_patches
            if math.hypot(p.x - x, p.y - y) <= reach
        ]

        return sorted(found, key=lambda p: math.hypot(p.x - x, p.y - y))

    def take_organic_remains(self, amount, x, y, reach):
        """Take up to `amount` from patches within reach; returns the amount taken."""

        taken = 0

        for patch in self.remains_near(x, y, reach):

            if taken >= amount:
                break

            piece = min(patch.amount, amount - taken)
            patch.amount -= piece
            taken += piece

        self.remains_patches = [
            p for p in self.remains_patches if p.amount > 1e-9
        ]

        return taken

    def decay_remains(self):
        """Remains rot away a little every turn, feeding the soil as they go."""

        for patch in self.remains_patches:
            lost = patch.amount * self.remains_decay
            patch.amount -= lost
            self.add_fertility(patch.x, patch.y, lost * FERTILITY_FROM_ROT)

        survivors = []
        for p in self.remains_patches:
            if p.amount >= 0.5:
                survivors.append(p)
            else:
                # a pile that has all but vanished sinks into the ground
                self.add_fertility(p.x, p.y, p.amount * FERTILITY_FROM_ROT)
        self.remains_patches = survivors

        self.decay_fertility()

    # ---------- soil fertility (nutrient cycle) ----------

    def _cell(self, x, y):
        return (int(x // FERTILITY_CELL), int(y // FERTILITY_CELL))

    def add_fertility(self, x, y, amount):
        """Return nutrients to the soil at (x, y)."""

        if not self.nutrient_cycle or amount <= 0:
            return

        cell = self._cell(x, y)
        self.fertility[cell] = self.fertility.get(cell, 0.0) + amount
        self.stats["nutrients_returned"] += amount

    def fertility_at(self, x, y):
        """How rich the soil is at a point: 0.0 (bare) .. 1.0 (saturated)."""

        if not self.nutrient_cycle:
            return 0.0

        value = self.fertility.get(self._cell(x, y), 0.0)
        return min(1.0, value / FERTILITY_SATURATION)

    def decay_fertility(self):
        """Nutrients slowly leach away; empty cells are forgotten."""

        if not self.fertility:
            return

        keep = 1 - FERTILITY_DECAY
        self.fertility = {
            cell: value * keep
            for cell, value in self.fertility.items()
            if value * keep > 0.05
        }

    # ---------- display ----------

    def display_resources(self):

        print("\n--- WORLD RESOURCES ---")

        for resource in self.resources:
            resource.display_info()

    def display_organisms(self):

        print("\n--- WORLD ORGANISMS ---")

        for organism in self.organisms:
            print(
                f"{organism.name} | "
                f"{organism.species} | "
                f"{organism.status} | "
                f"({organism.x:.1f}, {organism.y:.1f})"
            )

    def display_organic_remains(self):

        print(f"Organic Remains: {self.organic_remains:.1f} "
              f"in {len(self.remains_patches)} patches")