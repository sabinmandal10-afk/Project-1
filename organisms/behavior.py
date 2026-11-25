import math
from dataclasses import dataclass, field

from data.species import SPECIES
from data.behavior import BEHAVIOR
from organisms.feeding import GRAZE_RANGE, BITE_SIZE, remains_reach
from organisms.hunting import HUNT_RANGE
from organisms.evolution import effective_speed, effective_perception


# Grazers ignore plants with less energy than this (lets seedlings grow)
MIN_PLANT_ENERGY = 50

# Predators ignore prey with less energy than this (too small to be worth
# the chase), which gives the young time to grow
MIN_PREY_ENERGY = 90

# How much organic remains a recycler tries to eat per turn
REMAINS_BITE = 15

# Fear must exceed this before an organism bothers to run
FLEE_THRESHOLD = 0.15

# Random wobble on the "am I hungry enough?" decision
HUNGER_NOISE = 0.1

# Above this hunger, an organism takes risks (appetite doubles)
DESPERATE_HUNGER = 0.7


# Who is afraid of whom, derived from the species data:
# THREATS["Grazer"] == ["Ravager", "Skyrender"]
THREATS = {}

for _species, _data in SPECIES.items():
    if _data["type"] == "Predator":
        _foods = _data["food"]
        if isinstance(_foods, str):
            _foods = [_foods]
        for _prey in _foods:
            THREATS.setdefault(_prey, []).append(_species)


@dataclass
class Perception:
    food: list = field(default_factory=list)      # nearest first
    threats: list = field(default_factory=list)   # nearest first
    remains: list = field(default_factory=list)   # patches, nearest first


@dataclass
class Action:
    kind: str            # rest, wander, flee, graze, hunt, scavenge
    target: object = None
    x: float = None
    y: float = None


def _foods_of(species):
    food = SPECIES[species]["food"]
    return [food] if isinstance(food, str) else food


def speed_of(organism):
    return effective_speed(organism)


def perception_of(organism):
    """How far this organism can sense (species value times its own gene)."""
    profile = BEHAVIOR.get(organism.species)
    if profile is None:
        return 0
    return effective_perception(organism, profile["perception"])


def hunger(organism):
    """0.0 = comfortably fed, 1.0 = about to starve."""
    profile = BEHAVIOR.get(organism.species)

    if profile is None:
        return 0.0

    full_energy = SPECIES[organism.species]["starting_energy"] * profile["eat_below"]
    level = 1 - organism.energy / full_energy

    return max(0.0, min(1.0, level))


def perceive(organism, world, claims=None):
    """
    What this organism can sense around it right now.

    `claims` maps a plant's id to the energy other grazers have already
    planned to take from it this turn, so crowding is noticed.
    """
    claims = claims or {}
    profile = BEHAVIOR[organism.species]
    reach = perception_of(organism)
    kind = SPECIES[organism.species]["type"]

    perception = Perception()

    def nearby(species_names, minimum_energy=0, use_claims=False):
        found = [
            o for o in world.organisms
            if o.status == "Alive"
            and o is not organism
            and o.species in species_names
            and o.energy - (claims.get(id(o), 0) if use_claims else 0) >= minimum_energy
            and world.distance(organism, o) <= reach
        ]
        return sorted(found, key=lambda o: world.distance(organism, o))

    if kind == "Consumer":
        perception.food = nearby(_foods_of(organism.species), MIN_PLANT_ENERGY, use_claims=True)

    elif kind == "Predator":
        perception.food = nearby(_foods_of(organism.species), MIN_PREY_ENERGY)

    elif kind in ("Decomposer", "Scavenger", "Recycler"):
        perception.remains = world.remains_near(
            organism.x, organism.y, reach
        )

    perception.threats = nearby(THREATS.get(organism.species, []))

    return perception


def _wander_target(organism, world):
    """Pick (or keep) a point to search toward."""
    speed = speed_of(organism)
    target = getattr(organism, "wander_target", None)

    arrived = target is not None and world.distance_to(organism, *target) <= 1

    if target is None or arrived or world.rng.random() < 0.05:
        angle = world.rng.uniform(0, 2 * math.pi)
        distance = world.rng.uniform(speed * 2, speed * 6)
        target = world.clamp(
            organism.x + math.cos(angle) * distance,
            organism.y + math.sin(angle) * distance
        )
        organism.wander_target = target

    return target


def _flee_target(organism, threat, world):
    dx = organism.x - threat.x
    dy = organism.y - threat.y
    length = math.hypot(dx, dy)

    if length == 0:
        angle = world.rng.uniform(0, 2 * math.pi)
    else:
        # Base away-angle plus a random evasive juke (±35 degrees)
        angle = math.atan2(dy, dx) + world.rng.uniform(-0.6, 0.6)

    run = speed_of(organism) * 2

    return world.clamp(
        organism.x + math.cos(angle) * run,
        organism.y + math.sin(angle) * run
    )


def decide(organism, world, claims=None):
    """Choose one action for this organism this turn."""

    profile = BEHAVIOR.get(organism.species)

    if organism.status != "Alive" or profile is None:
        return Action("rest")

    kind = SPECIES[organism.species]["type"]
    speed = speed_of(organism)
    perception = perceive(organism, world, claims)
    need = hunger(organism)
    noise = world.rng.uniform(0, HUNGER_NOISE)

    # --- Safety: how scared am I? ---
    fear = 0.0

    if perception.threats and speed > 0 and profile["perception"] > 0:
        distance = world.distance(organism, perception.threats[0])
        fear = profile["caution"] * (1 - distance / perception_of(organism))

    # --- Appetite: how much do I want to eat? ---
    appetite = need

    # Aggressive predators attack at a lower level of hunger,
    # but a fully fed predator never hunts.
    if kind == "Predator":
        appetite = need * (1 + profile["aggression"])

    if need > DESPERATE_HUNGER:
        appetite *= 2

    # --- Priorities: safety first, then food, then idle ---
    if fear > FLEE_THRESHOLD and fear > appetite:
        x, y = _flee_target(organism, perception.threats[0], world)
        return Action("flee", x=x, y=y)

    if appetite > noise:

        if kind == "Consumer" and perception.food:
            return Action("graze", target=perception.food[0])

        if kind == "Predator" and perception.food:
            return Action("hunt", target=perception.food[0])

        if kind in ("Decomposer", "Scavenger", "Recycler"):
            if perception.remains:
                return Action("scavenge", target=perception.remains[0])
            # Nothing in sight: a mobile recycler searches, a rooted one waits
            if speed > 0:
                x, y = _wander_target(organism, world)
                return Action("wander", x=x, y=y)
            return Action("rest")

        # Hungry but nothing in sight: search
        if speed > 0:
            x, y = _wander_target(organism, world)
            return Action("wander", x=x, y=y)

        return Action("rest")

    # --- Nothing pressing: explore a little, or rest ---
    if speed > 0 and world.rng.random() < profile["curiosity"] * 0.5:
        x, y = _wander_target(organism, world)
        return Action("wander", x=x, y=y)

    return Action("rest")


def plan_actions(sim):
    """Let every living organism decide and queue its action."""
    world = sim.world

    # Energy already earmarked from each plant this turn
    claims = {}

    # Random order, so nobody always gets first pick
    organisms = list(world.living_organisms())
    world.rng.shuffle(organisms)

    for organism in organisms:

        action = decide(organism, world, claims)
        organism.last_action = action
        speed = speed_of(organism)

        if action.kind in ("wander", "flee"):
            sim.request_move(organism, action.x, action.y)

        elif action.kind in ("graze", "hunt"):
            reach = GRAZE_RANGE if action.kind == "graze" else HUNT_RANGE
            distance = world.distance(organism, action.target)

            within_strike = distance <= speed + reach

            if action.kind == "graze":
                # Plants don't move: walk over, then eat
                if distance > reach:
                    sim.request_move(organism, action.target.x, action.target.y)

                if within_strike:
                    sim.request_graze(organism, action.target)
                    claims[id(action.target)] = claims.get(id(action.target), 0) + BITE_SIZE

            else:
                # Prey moves, so a predator that can reach it this turn
                # just attacks (the lunge is resolved at attack time);
                # one that can't reach it yet closes the distance.
                if within_strike:
                    sim.request_hunt(organism, action.target)
                else:
                    sim.request_move(organism, action.target.x, action.target.y)

        elif action.kind == "scavenge":
            pile = action.target
            reach = remains_reach(organism.species)
            distance = math.hypot(organism.x - pile.x, organism.y - pile.y)

            # Walk up to the pile, then eat
            if distance > reach and speed > 0:
                sim.request_move(organism, pile.x, pile.y)

            if distance <= speed + reach:
                sim.request_feed(organism, "Organic Remains", REMAINS_BITE)