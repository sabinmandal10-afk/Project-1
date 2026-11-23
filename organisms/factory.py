#Instead of manually creating eight different objects, 
# we'll use one function that creates the correct object based on its database entry.

from organisms.organism import (
    Producer,
    Consumer,
    Predator,
    Recycler
)

from data.species import SPECIES


ORGANISM_CLASSES = {
    "Producer": Producer,
    "Consumer": Consumer,
    "Predator": Predator,
    "Decomposer": Recycler,
    "Scavenger": Recycler
}

_counters = {}


def create_organism(name, label=None):

    data = SPECIES[name]

    if label is None:
        _counters[name] = _counters.get(name, 0) + 1
        label = f"{name}_{_counters[name]}"

    organism_class = ORGANISM_CLASSES[data["type"]]

    organism = organism_class(
        name=label or name,
        species=name,
        energy=data["starting_energy"],
        metabolism=data["metabolism"],
        lifespan=data["lifespan"]
    )

    return organism