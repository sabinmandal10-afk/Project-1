"""Environmental stress: scheduled or random events that hit the ecosystem."""


class StressEvent:
    """Base: lasts `duration` turns (0 = one-off)."""

    name = "stress"
    target = None      # "light" or "radiation" for events that scale the environment
    severity = 1.0

    def __init__(self, start, duration=0):
        self.start = start
        self.duration = duration

    def begin(self, world): ...
    def end(self, world): ...


class Drought(StressEvent):
    """Sunlight is cut to `severity` of normal (0.3 = 30% of the light)."""

    name = "drought"
    target = "light"

    def __init__(self, start, duration, severity=0.3):
        super().__init__(start, duration)
        self.severity = severity


class RadiationDrop(StressEvent):
    """Radiation falls to `severity` of normal (starves Crystalis)."""

    name = "radiation_drop"
    target = "radiation"

    def __init__(self, start, duration, severity=0.2):
        super().__init__(start, duration)
        self.severity = severity


class Plague(StressEvent):
    """Kills a fraction of one species outright (one-off)."""

    name = "plague"

    def __init__(self, start, species, fraction=0.5):
        super().__init__(start, 0)
        self.species = species
        self.fraction = fraction

    def begin(self, world):
        victims = world.living_organisms(self.species)
        world.rng.shuffle(victims)

        for organism in victims[: int(len(victims) * self.fraction)]:
            organism.status = "Dead"
            organism.death_cause = "plague"
            organism.process_death(world)


class StressManager:
    """
    Runs events on schedule. Register as a pre-turn hook.

    The world's light / radiation multipliers are recomputed every turn as
    the product of the active events' severities, so overlapping events
    stack, a severity of 0 is safe, and nothing drifts. (This means the
    manager owns those two multipliers while it is registered.)
    """

    def __init__(self, events=None):
        self.events = list(events or [])
        self.active = []
        self._started = set()
        self.log = []     # (turn, "start"/"end", event name)

    def add(self, event):
        self.events.append(event)

    def __call__(self, sim):
        world = sim.world

        for event in list(self.active):
            if world.turn >= event.start + event.duration:
                event.end(world)
                self.active.remove(event)
                self.log.append((world.turn, "end", event.name))

        for event in self.events:
            if id(event) in self._started:
                continue

            # Fires on its start turn; an event with a duration that is
            # registered late still fires if it would still be running.
            on_time = event.start == world.turn
            late = (event.duration > 0
                    and event.start < world.turn < event.start + event.duration)

            if on_time or late:
                self._started.add(id(event))
                event.begin(world)
                self.log.append((world.turn, "start", event.name))
                if event.duration > 0:
                    self.active.append(event)

        self._apply_environment(world)

    def _apply_environment(self, world):
        for target in ("light", "radiation"):
            factor = 1.0
            for event in self.active:
                if event.target == target:
                    factor *= event.severity
            setattr(world, f"{target}_multiplier", factor)


class Recolonization:
    """
    Migrants arrive at the map edge when a species has been extinct a while
    and there is something for it to eat. Register as a pre-turn hook.

    species_rules: {"Ravager": {"delay": 40, "count": 2, "min_food": 15,
                                "food": ["Grazer", "Shellkin"]}}
    """

    def __init__(self, species_rules):
        self.rules = species_rules
        self._gone_since = {}
        self.log = []   # (turn, species, count)

    def __call__(self, sim):
        from organisms.factory import create_organism

        world = sim.world

        for species, rule in self.rules.items():
            if world.living_organisms(species):
                self._gone_since.pop(species, None)
                continue

            since = self._gone_since.setdefault(species, world.turn)
            if world.turn - since < rule["delay"]:
                continue

            from organisms.reproduction import GLOBAL_POPULATION_LIMIT
            if len(world.living_organisms()) + rule["count"] > GLOBAL_POPULATION_LIMIT:
                continue

            food = sum(len(world.living_organisms(f)) for f in rule["food"])
            if food < rule["min_food"]:
                continue

            for _ in range(rule["count"]):
                organism = create_organism(species)
                # arrive on a random edge
                x, y = world.random_position()
                side = world.rng.choice("NSEW")
                if side == "N": y = 0
                elif side == "S": y = world.height
                elif side == "W": x = 0
                else: x = world.width
                organism.x, organism.y = x, y
                world.add_organism(organism)

            world.stats["migrants"] += rule["count"]
            self.log.append((world.turn, species, rule["count"]))
            self._gone_since.pop(species, None)