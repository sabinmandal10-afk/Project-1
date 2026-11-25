class Organism:

    organism_type = "Organism"

    def __init__(self, name, species, energy, age=0,
                 metabolism=1, lifespan=100, x=0.0, y=0.0):

        self.name = name
        self.species = species
        self.energy = energy
        self.age = age

        self.metabolism = metabolism
        self.lifespan = lifespan
        self.health = 100
        self.status = "Alive"
        self.death_processed = False
        self.death_cause = None

        # Position in the world
        self.x = x
        self.y = y

        # Where the organism is currently searching toward (set by its AI)
        self.wander_target = None

        # Heritable traits (multipliers); see organisms/evolution.py
        self.speed_gene = 1.0
        self.sense_gene = 1.0
        self.base_metabolism = metabolism

    def advance_turn(self, world):

        if self.status == "Dead":
            return

        # Increase age
        self.age += 1

        # Decrease energy through metabolism
        self.energy -= self.metabolism

        # Check whether organism has died
        if self.energy <= 0 or self.age >= self.lifespan:

            self.status = "Dead"
            self.death_cause = "starvation" if self.energy <= 0 else "old age"

            print(f"{self.species} has died!")

            # Process natural death
            self.process_death(world)

    def display_info(self):

        print("\n==== ORGANISM INFORMATION ====")
        print(f"Name: {self.name}")
        print(f"Species: {self.species}")
        print(f"Energy: {self.energy}")
        print(f"Age: {self.age}")
        print(f"Metabolism: {self.metabolism}")
        print(f"Health: {self.health}")
        print(f"Status: {self.status}")
        print(f"Position: ({self.x:.1f}, {self.y:.1f})")

    def process_death(self, world):

        if self.status != "Dead":
            return

        if self.death_processed:
            return

        remains = max(0, self.energy)

        world.add_organic_remains(remains, self.x, self.y)
        world.stats["deaths"] += 1
        world.stats[f"deaths_{self.death_cause or 'unknown'}"] += 1

        tracker = getattr(world, "lineage_tracker", None)
        if tracker is not None:
            tracker.record_death(
                self,
                turn=getattr(world, "turn", 0),
                cause=self.death_cause or "unknown",
            )

        self.energy = 0
        self.health = 0
        self.death_processed = True

        print(f"{self.name} contributed {remains} energy to organic remains!")


class Producer(Organism):
    organism_type = "Producer"


class Consumer(Organism):
    organism_type = "Consumer"


class Predator(Organism):
    organism_type = "Predator"


class Recycler(Organism):
    organism_type = "Recycler"
