from data.species import SPECIES


# Animals can't store more than this multiple of their starting energy
ENERGY_CAP_FACTOR = 4.0


def energy_cap(organism):
    return SPECIES[organism.species]["starting_energy"] * ENERGY_CAP_FACTOR


def energy_room(organism):
    """How much more energy this organism can still take in."""
    return max(0, energy_cap(organism) - organism.energy)