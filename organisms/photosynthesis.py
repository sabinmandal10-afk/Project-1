from data.species import SPECIES
from environment.world import FERTILITY_BONUS


# Which world condition powers which producer food source
ENERGY_SOURCES = {
    "Light": "effective_light",
    "Radiation": "effective_radiation"
}

# Energy gained per turn at full intensity
PHOTOSYNTHESIS_RATE = {
    "Verdant": 5.0,
    "Crystalis": 3.0
}

# Producers can't store more than this multiple of their starting energy
MAX_ENERGY_FACTOR = 2.0


def photosynthesize(organism, world):

    if organism.status != "Alive":
        return 0

    data = SPECIES[organism.species]

    if data["type"] != "Producer":
        return 0

    level_name = ENERGY_SOURCES.get(data["food"])
    rate = PHOTOSYNTHESIS_RATE.get(organism.species, 0)

    if level_name is None:
        return 0

    gain = rate * getattr(world, level_name)

    # Rich soil (from rotted remains and recyclers) boosts growth
    fertility_at = getattr(world, "fertility_at", None)
    if fertility_at is not None:
        gain *= 1 + FERTILITY_BONUS * fertility_at(organism.x, organism.y)

    cap = data["starting_energy"] * MAX_ENERGY_FACTOR
    new_energy = min(organism.energy + gain, cap)

    gained = max(0, new_energy - organism.energy)
    organism.energy = new_energy

    tracker = getattr(world, "lineage_tracker", None)
    if tracker is not None and gained > 0:
        tracker.record_meal(organism, amount=gained, source_role="environment")

    return gained


def process_photosynthesis(world):

    for organism in world.organisms:
        photosynthesize(organism, world)
