"""
Natural selection.

Animals carry two heritable genes, both multipliers around 1.0:

    speed_gene : how fast it moves     (costs extra metabolism)
    sense_gene : how far it perceives  (costs extra metabolism)

A child inherits its parent's genes plus a small random mutation. Faster
or sharper-eyed animals catch more food or escape more often, but they burn
energy faster, so there is no free lunch: selection settles on a balance
that shifts when the environment does.

Turn it off with `organisms.evolution.ENABLED = False` (everyone then keeps
gene values of exactly 1.0 and the rest of the simulation is unchanged).
"""

from data.species import SPECIES

ENABLED = True

# Which species evolve (rooted producers and decomposers do not move)
EVOLVING = {"Grazer", "Shellkin", "Ravager", "Skyrender", "Nullborn"}

# Standard deviation of the random change handed to each gene
MUTATION = 0.05

# Genes are kept inside this range
GENE_MIN, GENE_MAX = 0.6, 1.6

# Extra metabolism for each +1.0 of a gene (0.5 = +50% upkeep at double the trait)
SPEED_UPKEEP = 0.6
SENSE_UPKEEP = 0.3


def speed_gene(organism):
    return getattr(organism, "speed_gene", 1.0)


def sense_gene(organism):
    return getattr(organism, "sense_gene", 1.0)


def effective_speed(organism):
    """Movement speed including the organism's own gene."""
    return SPECIES[organism.species]["movement_speed"] * speed_gene(organism)


def effective_perception(organism, base):
    """Perception range including the organism's own gene."""
    return base * sense_gene(organism)


def apply_upkeep(organism):
    """Fast, sharp-sensed animals burn more energy."""
    base = getattr(organism, "base_metabolism", None)
    if base is None:
        base = organism.base_metabolism = organism.metabolism
    organism.metabolism = base * (
        1.0
        + SPEED_UPKEEP * (speed_gene(organism) - 1.0)
        + SENSE_UPKEEP * (sense_gene(organism) - 1.0)
    )


def inherit(parent, child, rng):
    """Hand the parent's genes to the child, with mutation."""
    if not ENABLED or parent.species not in EVOLVING:
        return

    def mutate(value):
        return max(GENE_MIN, min(GENE_MAX, value + rng.gauss(0, MUTATION)))

    child.speed_gene = mutate(speed_gene(parent))
    child.sense_gene = mutate(sense_gene(parent))
    apply_upkeep(child)


def mean_genes(organisms):
    """(mean speed gene, mean sense gene) of a group, or (1.0, 1.0) if empty."""
    organisms = list(organisms)
    if not organisms:
        return 1.0, 1.0
    n = len(organisms)
    return (sum(speed_gene(o) for o in organisms) / n,
            sum(sense_gene(o) for o in organisms) / n)
