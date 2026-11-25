from organisms.feeding import feed, graze
from organisms.hunting import hunt, HUNT_RANGE
from organisms.movement import move_toward
from organisms.photosynthesis import process_photosynthesis
from organisms.reproduction import process_reproduction
from organisms.behavior import plan_actions


class Simulation:

    def __init__(self, world, autonomous=False):
        self.world = world
        self.autonomous = autonomous
        self.pending_moves = []
        self.pending_feeding = []
        self.pending_grazing = []
        self.pending_hunting = []

        # Callables taking the simulation; run at the start / end of each turn
        self.pre_turn_hooks = []
        self.post_turn_hooks = []

    def request_move(self, organism, x, y):
        self.pending_moves.append((organism, x, y))

    def request_feed(self, organism, food_name, amount):
        self.pending_feeding.append((organism, food_name, amount))

    def request_graze(self, consumer, plant):
        self.pending_grazing.append((consumer, plant))

    def request_hunt(self, predator, prey):
        self.pending_hunting.append((predator, prey))

    def advance_turn(self):

        self.world.turn += 1
        self.world.update_season()

        tracker = getattr(self.world, "lineage_tracker", None)
        if tracker is not None:
            tracker.begin_turn()

        print(f"\n========== TURN {self.world.turn} ==========")

        for hook in self.pre_turn_hooks:
            hook(self)

        # 0. Organisms decide what to do (only in autonomous mode)
        if self.autonomous:
            plan_actions(self)

        # 1. Photosynthesis
        process_photosynthesis(self.world)

        # 2. Aging and metabolism
        for organism in self.world.organisms.copy():
            if organism.status == "Alive":
                organism.advance_turn(self.world)

        # 3. Movement
        for organism, x, y in self.pending_moves:
            if organism.status == "Alive":
                move_toward(organism, self.world, x, y)

        # 4. Feeding (organic remains, then grazing)
        for organism, food_name, amount in self.pending_feeding:
            if organism.status == "Alive":
                feed(organism, self.world, food_name, amount)

        for consumer, plant in self.pending_grazing:
            if consumer.status == "Alive":
                graze(consumer, self.world, plant)

        # 5. Hunting
        for predator, prey in self.pending_hunting:
            if predator.status == "Alive":

                # Final lunge: close in on where the prey is *now*,
                # after everyone else has finished moving
                if (
                    prey.status == "Alive"
                    and prey in self.world.organisms
                    and not self.world.in_range(predator, prey, HUNT_RANGE)
                ):
                    move_toward(predator, self.world, prey.x, prey.y)

                # Another predator got there first
                if prey.status == "Dead":
                    self.world.stats["contested_hunts"] += 1

                hunt(predator, self.world, prey)

        # 6. Reproduction
        process_reproduction(self.world)

        # 7. Remains rot, and the dead are removed from the world
        self.world.decay_remains()
        removed = self.world.remove_dead()

        # 8. Clear queued actions
        self.pending_moves.clear()
        self.pending_feeding.clear()
        self.pending_grazing.clear()
        self.pending_hunting.clear()

        print(f"Turn {self.world.turn} completed! ({removed} removed)")

        for hook in self.post_turn_hooks:
            hook(self)

        return self.world.turn
