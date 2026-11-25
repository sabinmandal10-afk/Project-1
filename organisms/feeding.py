from data.species import SPECIES
from organisms.energy import energy_room


# How close a consumer must be to a plant to graze on it
GRAZE_RANGE = 2.0

# Energy a consumer takes from a plant in one bite
BITE_SIZE = 20

# How far a recycler can reach to eat remains (Mycel spreads through the
# ground, Nullborn must walk right up to the pile)
REMAINS_REACH = {
    "Mycel": 8.0,
    "Nullborn": 2.0
}
DEFAULT_REMAINS_REACH = 2.0


def remains_reach(species):
    return REMAINS_REACH.get(species, DEFAULT_REMAINS_REACH)


# Share of the remains a recycler eats that it returns to the soil as
# nutrients (the nutrient cycle: dead things -> soil -> plants)
RECYCLER_SOIL_SHARE = 0.5

# Grazing never takes a plant below this much energy, so plants regrow
PLANT_RESERVE = 40

# Fraction of the bitten energy the consumer actually gains
# (the rest is lost as heat)
GRAZING_EFFICIENCY = 0.6


def graze(consumer, world, plant):
    """A consumer eats part of a living producer organism."""

    if consumer.status == "Dead":
        print(f"{consumer.name} cannot graze. It is dead!")
        return 0

    if consumer not in world.organisms or plant not in world.organisms:
        print("Both organisms must belong to this world!")
        return 0

    if consumer is plant:
        print("An organism cannot graze on itself!")
        return 0

    consumer_data = SPECIES[consumer.species]

    if consumer_data["type"] != "Consumer":
        print(f"{consumer.species} is not a consumer!")
        return 0

    if plant.status == "Dead":
        print(f"{plant.name} is already dead!")
        return 0

    allowed_food = consumer_data["food"]

    if isinstance(allowed_food, str):
        allowed_food = [allowed_food]

    if plant.species not in allowed_food:
        print(f"{consumer.species} cannot eat {plant.species}!")
        return 0

    if not world.in_range(consumer, plant, GRAZE_RANGE):
        print(f"{consumer.name} is too far from {plant.name}!")
        return 0

    # A bite is limited by the plant's reserve and by how much the
    # consumer still has room for
    room = energy_room(consumer)

    bite = min(
        BITE_SIZE,
        max(0, plant.energy - PLANT_RESERVE),
        room / GRAZING_EFFICIENCY
    )

    if bite <= 0:
        return 0

    # Plant loses energy, consumer gains a share of it
    plant.energy -= bite
    energy_gained = bite * GRAZING_EFFICIENCY
    consumer.energy += energy_gained
    world.stats["meals_grazed"] += 1
    world.stats[f"ate:{consumer.species}>{plant.species}"] += 1

    tracker = getattr(world, "lineage_tracker", None)
    if tracker is not None:
        tracker.record_meal(consumer, amount=energy_gained, source_role="producer")

    print(f"\n{consumer.name} grazed on {plant.name}!")
    print(f"Energy gained: {energy_gained}")
    print(f"Current energy: {consumer.energy}")

    # A fully eaten plant dies
    if plant.energy <= 0:
        plant.status = "Dead"
        plant.process_death(world)

    return energy_gained


def feed(organism, world, food_name, amount):
    """Feed an organism from the shared pool of organic remains."""

    # 1. Check whether organism is alive
    if organism.status == "Dead":
        print(f"{organism.name} cannot eat. It is dead!")
        return 0

    # 2. Check whether organism belongs to this world
    if organism not in world.organisms:
        print("Organism does not belong to this world!")
        return 0

    # 3. Get organism's dietary information
    species_data = SPECIES[organism.species]
    allowed_food = species_data["food"]

    if isinstance(allowed_food, str):
        allowed_food = [allowed_food]

    # 4. Check dietary restrictions
    if food_name not in allowed_food:
        print(f"{organism.species} cannot eat {food_name}!")
        return 0

    # 5. Validate requested amount
    if amount <= 0:
        print("Feeding amount must be positive!")
        return 0

    # 6. Only organic remains are fed this way
    if food_name != "Organic Remains":
        print(f"{food_name} cannot be fed directly. Use graze() or hunt()!")
        return 0

    # 7. Only eat what there is room for
    room = energy_room(organism)

    if room <= 0:
        print(f"{organism.name} is too full to eat!")
        return 0

    # 8. Take remains from piles within reach
    wanted = min(amount, room)
    consumed = world.take_organic_remains(
        wanted, organism.x, organism.y, remains_reach(organism.species)
    )

    if consumed <= 0:
        print("No organic remains within reach!")
        return 0

    # 1:1 energy conversion
    energy_gained = consumed
    organism.energy += energy_gained
    world.stats["remains_eaten"] += consumed
    world.stats[f"ate:{organism.species}>Remains"] += 1
    soil_returned = consumed * RECYCLER_SOIL_SHARE
    world.add_fertility(organism.x, organism.y, soil_returned)

    tracker = getattr(world, "lineage_tracker", None)
    if tracker is not None:
        tracker.record_meal(organism, amount=energy_gained, source_role="herbivore")
        tracker.record_energy("decomposer", "environment", soil_returned)

    print(f"\n{organism.name} has consumed organic remains!")
    print(f"Remains consumed: {consumed}")
    print(f"Energy gained: {energy_gained}")
    print(f"Current energy: {organism.energy}")

    return energy_gained
