from data.species import SPECIES
from organisms.energy import energy_room


# Percentage of prey energy converted into predator energy
HUNTING_EFFICIENCY = 0.8

# How close a predator must be to its prey to attack
HUNT_RANGE = 3.0

# --- Failed hunts ---
# Set to False to make every attack in range succeed (handy for testing)
FAILED_HUNTS = True

# Chance of success before speed and defense are considered
BASE_HUNT_SUCCESS = 0.5

# Each point of speed the predator has over its prey adds this much chance
SPEED_ADVANTAGE_WEIGHT = 0.05

# Success chance is always kept between these limits
MIN_HUNT_SUCCESS = 0.1
MAX_HUNT_SUCCESS = 0.85

# Energy a predator burns on a failed attack
FAILED_HUNT_COST = 5

# Prey refuge: when few of a prey species are near the predator, they are
# harder to find and catch. At or above this many nearby, there is no effect;
# below it, success scales down. Stops predators wiping out the last prey.
PREY_REFUGE_COUNT = 8
PREY_REFUGE_RADIUS = 20.0

# Armor or other defenses that lower a predator's chance against a species
PREY_DEFENSE = {
    "Shellkin": 0.45
}


def prey_density_factor(predator, prey, world):
    """1.0 when prey are plentiful nearby, falling toward 0 as they thin out."""

    if world is None or PREY_REFUGE_COUNT <= 0:
        return 1.0

    nearby = sum(
        1 for o in world.organisms
        if o.status == "Alive"
        and o.species == prey.species
        and world.distance(predator, o) <= PREY_REFUGE_RADIUS
    )

    return min(1.0, nearby / PREY_REFUGE_COUNT)


def hunt_chance(predator, prey, world=None):
    """Probability that an attack in range succeeds."""

    speed_gap = (
        SPECIES[predator.species]["movement_speed"]
        - SPECIES[prey.species]["movement_speed"]
    )

    chance = (
        BASE_HUNT_SUCCESS
        + speed_gap * SPEED_ADVANTAGE_WEIGHT
        - PREY_DEFENSE.get(prey.species, 0)
    )

    chance *= prey_density_factor(predator, prey, world)

    return max(MIN_HUNT_SUCCESS, min(MAX_HUNT_SUCCESS, chance))


def hunt(predator, world, prey):

    # 1. Check predator status
    if predator.status == "Dead":
        print(f"{predator.name} cannot hunt. It is dead!")
        return 0

    # 2. Check whether predator belongs to Predator species
    predator_data = SPECIES[predator.species]

    if predator_data["type"] != "Predator":
        print(f"{predator.species} is not a predator!")
        return 0

    # 3. Check whether both organisms belong to this world
    if predator not in world.organisms or prey not in world.organisms:
        print("Both organisms must belong to this world!")
        return 0

    # 4. Prevent self-hunting
    if predator is prey:
        print("An organism cannot hunt itself!")
        return 0

    # 5. Check whether prey is alive
    if prey.status == "Dead":
        print(f"{prey.name} is already dead!")
        return 0

    # 6. Check predator's dietary restrictions
    allowed_food = predator_data["food"]

    if isinstance(allowed_food, str):
        allowed_food = [allowed_food]

    if prey.species not in allowed_food:
        print(
            f"{predator.species} cannot hunt "
            f"{prey.species}!"
        )
        return 0

    # 7. Check that the prey is reachable
    if not world.in_range(predator, prey, HUNT_RANGE):
        print(f"{prey.name} is out of reach of {predator.name}!")
        return 0

    # 8. The attack can fail
    if FAILED_HUNTS and world.rng.random() >= hunt_chance(predator, prey, world):
        predator.energy = max(1, predator.energy - FAILED_HUNT_COST)
        world.stats["failed_hunts"] += 1
        print(f"{predator.name} failed to catch {prey.name}!")
        return 0

    # 9. Calculate energy distribution
    prey_energy = max(0, prey.energy)

    # A predator can't take in more than it has room for;
    # whatever it can't use stays with the body
    energy_gained = min(prey_energy * HUNTING_EFFICIENCY, energy_room(predator))
    remaining_energy = prey_energy - energy_gained

    # 10. Transfer energy to predator
    predator.energy += energy_gained

    # 11. Store remaining energy in prey
    prey.energy = remaining_energy

    # 12. Mark prey as dead
    prey.status = "Dead"
    prey.death_cause = "predation"
    world.stats["kills"] += 1

    # 13. Process prey death
    prey.process_death(world)

    return energy_gained