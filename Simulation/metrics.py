"""Records ecosystem history and watches for collapse / recovery."""

import csv

from data.species import SPECIES

# A species counts as collapsed when it falls below this share of its peak...
COLLAPSE_FRACTION = 0.25
# ...and as recovered once it climbs back above this share of that peak.
RECOVERY_FRACTION = 0.60
# Peaks smaller than this are too small to call a "collapse"
MIN_PEAK = 6

COUNTED_STATS = [
    "births", "deaths", "deaths_starvation", "deaths_old age",
    "deaths_predation", "deaths_plague", "kills", "failed_hunts",
    "meals_grazed", "remains_eaten",
]


class Recorder:

    def __init__(self, species=None):
        self.species = list(species or SPECIES.keys())
        self.rows = []
        self.events = []          # (turn, kind, species, detail)
        self._last_stats = {}
        self._peak = {s: 0 for s in self.species}
        self._collapsed = set()
        self._extinct = set()

    # Use as a post-turn hook: sim.post_turn_hooks.append(recorder)
    def __call__(self, sim):
        self.record(sim.world)

    def record(self, world):
        row = {"turn": world.turn}

        for name in self.species:
            row[name] = len(world.living_organisms(name))

        row["total_pop"] = sum(row[s] for s in self.species)
        row["living_energy"] = round(
            sum(o.energy for o in world.living_organisms()), 1)
        row["remains"] = round(world.organic_remains, 1)
        row["light"] = round(world.effective_light, 3)
        row["radiation"] = round(world.effective_radiation, 3)

        # Per-turn change in the world's running tallies
        for key in COUNTED_STATS:
            total = world.stats.get(key, 0)
            row[key] = round(total - self._last_stats.get(key, 0), 2)
            self._last_stats[key] = total

        self.rows.append(row)
        self._watch(world.turn, row)

    # ---------- collapse and recovery ----------

    def _watch(self, turn, row):
        for name in self.species:
            count = row[name]
            self._peak[name] = max(self._peak[name], count)
            peak = self._peak[name]

            if peak < MIN_PEAK:
                continue

            if count == 0 and name not in self._extinct:
                self._extinct.add(name)
                self._collapsed.add(name)
                self.events.append((turn, "extinct", name,
                                    f"peak was {peak}"))
            elif count > 0:
                self._extinct.discard(name)

            if name not in self._collapsed:
                if count < peak * COLLAPSE_FRACTION:
                    self._collapsed.add(name)
                    self.events.append((turn, "collapse", name,
                                        f"{count} left, peak {peak}"))
            else:
                if count >= peak * RECOVERY_FRACTION and count > 0:
                    self._collapsed.discard(name)
                    self.events.append((turn, "recovery", name,
                                        f"{count} again, peak {peak}"))
                    # Measure the next collapse against this new level
                    self._peak[name] = count

    # ---------- output ----------

    def to_csv(self, path):
        if not self.rows:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(self.rows[0].keys()))
            writer.writeheader()
            writer.writerows(self.rows)

    def summary(self):
        lines = ["species      start  min  max  mean  end"]
        for name in self.species:
            series = [r[name] for r in self.rows]
            if not series:
                continue
            lines.append(
                f"{name:<12} {series[0]:>5} {min(series):>4} {max(series):>4} "
                f"{sum(series) / len(series):>5.1f} {series[-1]:>4}"
            )
        if self.events:
            lines.append("\nevents:")
            for turn, kind, name, detail in self.events:
                lines.append(f"  turn {turn:>4}  {kind:<9} {name} ({detail})")
        return "\n".join(lines)