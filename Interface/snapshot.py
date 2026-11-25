"""
A read-only picture of the world at one moment.

The viewer (and, later, the event log) draw from a Snapshot instead of
reaching into the world directly. Nothing here changes the simulation.
"""

from dataclasses import dataclass, field

from data.species import SPECIES
from organisms.energy import energy_cap
from organisms.evolution import mean_genes, speed_gene, sense_gene
from environment.world import FERTILITY_CELL, FERTILITY_SATURATION
from organisms.photosynthesis import MAX_ENERGY_FACTOR
from organisms.reproduction import GLOBAL_POPULATION_LIMIT


@dataclass
class OrganismView:
    ref: object            # the live organism (lets the viewer follow one)
    name: str
    species: str
    kind: str              # Producer, Consumer, Predator, ...
    x: float
    y: float
    energy: float
    age: int
    fullness: float        # energy as a share of what it can hold (0..1)
    lifespan: int = 100    # age at which it dies of old age
    speed_gene: float = 1.0
    sense_gene: float = 1.0


@dataclass
class EnergyStats:
    n: int = 0
    mean: float = 0.0
    low: float = 0.0
    high: float = 0.0
    total: float = 0.0


@dataclass
class Snapshot:
    turn: int
    width: float
    height: float
    organisms: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)          # species -> living
    energy: dict = field(default_factory=dict)          # species -> EnergyStats
    total_population: int = 0
    population_limit: int = GLOBAL_POPULATION_LIMIT
    total_energy: float = 0.0
    light: float = 1.0
    radiation: float = 1.0
    seasonal: bool = False
    remains_total: float = 0.0
    remains_patches: list = field(default_factory=list)  # (x, y, amount)
    resources: list = field(default_factory=list)        # (name, quantity)
    traits: dict = field(default_factory=dict)           # species -> (speed gene, sense gene)
    fertility: list = field(default_factory=list)        # (cell_x, cell_y, richness 0..1)
    fertility_cell: float = FERTILITY_CELL
    fertility_mean: float = 0.0
    stats: dict = field(default_factory=dict)            # the world's running tallies


def holding_capacity(species):
    """The most energy a member of this species can store."""
    data = SPECIES[species]
    if data["type"] == "Producer":
        return data["starting_energy"] * MAX_ENERGY_FACTOR

    class _Probe:
        pass

    probe = _Probe()
    probe.species = species
    return energy_cap(probe)


def take_snapshot(world):
    snap = Snapshot(
        turn=world.turn,
        width=world.width,
        height=world.height,
        light=world.effective_light,
        radiation=world.effective_radiation,
        seasonal=bool(world.season_length),
        remains_total=world.organic_remains,
        remains_patches=[(p.x, p.y, p.amount) for p in world.remains_patches],
        resources=[(r.name, r.quantity) for r in world.resources],
        fertility=[
            (cx, cy, min(1.0, value / FERTILITY_SATURATION))
            for (cx, cy), value in getattr(world, "fertility", {}).items()
        ],
        stats=dict(world.stats),
    )
    if snap.fertility:
        snap.fertility_mean = sum(f for _, _, f in snap.fertility) / len(snap.fertility)

    by_species = {name: [] for name in SPECIES}

    for o in world.organisms:
        if o.status != "Alive" or o.species not in by_species:
            continue

        cap = holding_capacity(o.species)
        view = OrganismView(
            ref=o, name=o.name, species=o.species,
            kind=SPECIES[o.species]["type"],
            x=o.x, y=o.y, energy=o.energy, age=o.age,
            fullness=max(0.0, min(1.0, o.energy / cap)) if cap else 0.0,
            lifespan=o.lifespan,
            speed_gene=speed_gene(o), sense_gene=sense_gene(o),
        )
        snap.organisms.append(view)
        by_species[o.species].append(view)

    for name, members in by_species.items():
        snap.counts[name] = len(members)
        if members:
            energies = [m.energy for m in members]
            stats = EnergyStats(
                n=len(members),
                mean=sum(energies) / len(energies),
                low=min(energies), high=max(energies),
                total=sum(energies),
            )
        else:
            stats = EnergyStats()
        snap.energy[name] = stats
        snap.total_energy += stats.total
        snap.traits[name] = mean_genes(m.ref for m in members)

    snap.total_population = len(snap.organisms)
    return snap