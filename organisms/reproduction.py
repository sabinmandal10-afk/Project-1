from data.species import SPECIES
from organisms.factory import create_organism


# Per-species reproduction rules.
#   maturity_age      : minimum age before reproducing
#   energy_threshold  : parent must have at least this much energy
#   energy_cost       : energy the parent spends to reproduce
#   max_population    : cap on living members of this species
REPRODUCTION = {
    "Verdant":   {"maturity_age": 8, "energy_threshold": 45, "energy_cost": 15, "max_population": 150},
    "Crystalis": {"maturity_age": 12, "energy_threshold": 45, "energy_cost": 15, "max_population": 80},
    "Grazer":    {"maturity_age": 12, "energy_threshold": 130, "energy_cost": 50, "max_population": 60},
    "Shellkin":  {"maturity_age": 12, "energy_threshold": 130, "energy_cost": 36, "max_population": 40},
    "Ravager":   {"maturity_age": 18, "energy_threshold": 215, "energy_cost": 95, "max_population": 10},
    "Skyrender": {"maturity_age": 18, "energy_threshold": 215, "energy_cost": 95, "max_population": 8},
    "Mycel":     {"maturity_age": 15, "energy_threshold": 130, "energy_cost": 40, "max_population": 15},
    "Nullborn":  {"maturity_age": 15, "energy_threshold": 140, "energy_cost": 45, "max_population": 10},
}

# Per-turn chance that an eligible organism actually reproduces, and (for
# rooted species) how many same-species neighbours within CROWDING_RADIUS
# it takes to stop reproduction completely. Chance falls linearly as the
# neighbourhood fills up, which gives each producer a carrying capacity.
#   chance          : 0..1 probability per eligible turn
#   crowding_limit  : neighbours that bring the chance to zero (optional)
REPRO_CHANCE = {
    "Verdant":   {"chance": 0.25, "crowding_limit": 7},
    "Crystalis": {"chance": 0.15, "crowding_limit": 7},
    "Grazer":    {"chance": 0.30},
    "Shellkin":  {"chance": 0.30},
    "Ravager":   {"chance": 0.04},
    "Skyrender": {"chance": 0.04},
    "Mycel":     {"chance": 0.20},
    "Nullborn":  {"chance": 0.20},
}

CROWDING_RADIUS = 6.0

# Fraction of the parent's energy cost that reaches the offspring.
# The rest is lost to the environment as organic remains (energy is conserved).
OFFSPRING_ENERGY_SHARE = 0.6

# Hard cap on all living organisms in the world
GLOBAL_POPULATION_LIMIT = 500

# Offspring appear within this distance of their parent
SPAWN_SPREAD = 1.5


def living_count(world, species=None):
    return sum(
        1 for o in world.organisms
        if o.status == "Alive" and (species is None or o.species == species)
    )


def can_reproduce(organism, world):
    """Returns (ok, reason)."""
    if organism.status != "Alive":
        return False, "dead"

    rules = REPRODUCTION.get(organism.species)
    if rules is None:
        return False, "no reproduction rules"

    if organism.age < rules["maturity_age"]:
        return False, "too young"

    if organism.energy < rules["energy_threshold"]:
        return False, "not enough energy"

    if living_count(world, organism.species) >= rules["max_population"]:
        return False, "species population limit"

    if living_count(world) >= GLOBAL_POPULATION_LIMIT:
        return False, "world population limit"

    return True, "ok"


def neighbours(organism, world, radius=CROWDING_RADIUS):
    """Living members of the same species within `radius` (excluding itself)."""
    return sum(
        1 for o in world.organisms
        if o is not organism
        and o.status == "Alive"
        and o.species == organism.species
        and world.distance(organism, o) <= radius
    )


def reproduction_chance(organism, world):
    """Probability this organism reproduces this turn, if it is eligible."""
    rule = REPRO_CHANCE.get(organism.species, {"chance": 1.0})
    chance = rule["chance"]

    limit = rule.get("crowding_limit")
    if limit:
        chance *= max(0.0, 1 - neighbours(organism, world) / limit)

    return chance


def reproduce(organism, world):
    """Attempt reproduction. Returns the offspring, or None."""
    ok, reason = can_reproduce(organism, world)

    if not ok:
        return None

    rules = REPRODUCTION[organism.species]
    cost = rules["energy_cost"]

    # Parent pays the cost
    organism.energy -= cost

    # Offspring is created from the species template, then given its share
    offspring = create_organism(organism.species)
    offspring.energy = cost * OFFSPRING_ENERGY_SHARE

    # Energy not passed on becomes organic remains
    world.add_organic_remains(cost - offspring.energy, organism.x, organism.y)
    world.stats["births"] += 1

    dx = world.rng.uniform(-SPAWN_SPREAD, SPAWN_SPREAD)
    dy = world.rng.uniform(-SPAWN_SPREAD, SPAWN_SPREAD)
    offspring.x, offspring.y = world.clamp(organism.x + dx, organism.y + dy)

    world.add_organism(offspring)

    print(f"{organism.name} gave birth to {offspring.name}!")

    return offspring


def process_reproduction(world):
    """Run once per turn. Newborns don't reproduce on the turn they are born."""
    for organism in list(world.organisms):
        ok, _ = can_reproduce(organism, world)

        if not ok:
            continue

        if world.rng.random() < reproduction_chance(organism, world):
            reproduce(organism, world)