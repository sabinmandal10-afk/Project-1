from data.species import SPECIES


# Energy spent per unit of distance moved
MOVE_COST_PER_UNIT = 0.1


def move_toward(organism, world, target_x, target_y):
    """
    Move up to `movement_speed` units toward a target point.
    Returns the distance actually moved.
    """

    if organism.status == "Dead":
        print(f"{organism.name} cannot move. It is dead!")
        return 0

    speed = SPECIES[organism.species]["movement_speed"]

    if speed <= 0:
        print(f"{organism.species} cannot move!")
        return 0

    # Targets outside the world are pulled back to the border
    target_x, target_y = world.clamp(target_x, target_y)

    distance = world.distance_to(organism, target_x, target_y)

    if distance == 0:
        return 0

    step = min(speed, distance)

    # Never spend the last point of energy on movement
    affordable = max(0, organism.energy - 1) / MOVE_COST_PER_UNIT
    step = min(step, affordable)

    if step <= 0:
        print(f"{organism.name} is too weak to move!")
        return 0

    ratio = step / distance

    organism.x += (target_x - organism.x) * ratio
    organism.y += (target_y - organism.y) * ratio
    organism.energy -= step * MOVE_COST_PER_UNIT

    return step