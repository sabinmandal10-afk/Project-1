"""Run the same setup over several seeds to see how robust a configuration is.

    python sweep.py

Each species shows: survivors at the end / seeds, then (mean population).
Edit constants first (e.g. organisms.hunting.PREY_REFUGE_COUNT) and compare runs.
"""

from run_gaia import run


def trial(label, seeds=range(1, 9), turns=800, **kw):
    alive, pops = {}, {}

    for seed in seeds:
        _, rec, _ = run(turns=turns, seed=seed, **kw)
        for s in rec.species:
            alive[s] = alive.get(s, 0) + (rec.rows[-1][s] > 0)
            pops[s] = pops.get(s, 0) + sum(r[s] for r in rec.rows) / len(rec.rows)

    n = len(list(seeds))
    print(label, " ".join(
        f"{s[:4]}:{alive[s]}/{n}({pops[s] / n:.0f})" for s in rec.species))


if __name__ == "__main__":
    trial("current settings")