"""
Teaching content for the viewer: what each species is, why events happen,
the guided Showcase story, the food-web layout, and a few helpers that turn
raw numbers into lessons. Pure Python (no pygame), so it is easy to edit and
test. Change the text here to tailor GAIA to your class.
"""

from data.species import SPECIES
from data.behavior import BEHAVIOR
from organisms.behavior import THREATS
from organisms.feeding import GRAZING_EFFICIENCY
from organisms.hunting import HUNTING_EFFICIENCY


# ------------------------------------------------------------ species cards

SPECIES_INFO = {
    "Verdant": {
        "role": "Producer (plant)",
        "blurb": "Turns sunlight into energy. Grows faster on rich soil and "
                 "slows down in winter or drought.",
        "lesson": "Producers are the base of every food chain.",
    },
    "Crystalis": {
        "role": "Producer (crystal)",
        "blurb": "Feeds on radiation instead of light, so it keeps growing "
                 "when a drought darkens the world.",
        "lesson": "Different energy sources make an ecosystem more resilient.",
    },
    "Grazer": {
        "role": "Herbivore",
        "blurb": "Fast and wary. Eats Verdant, flees from predators and "
                 "breeds quickly when food is plentiful.",
        "lesson": "Herbivores turn plants into food for predators.",
    },
    "Shellkin": {
        "role": "Armoured herbivore",
        "blurb": "Slow but hard to catch: its shell defeats many attacks. "
                 "Eats Crystalis.",
        "lesson": "Defence is an alternative to speed.",
    },
    "Ravager": {
        "role": "Ground predator",
        "blurb": "Fast and fearless. Hunts Grazers and Shellkin, but many "
                 "attacks fail and each failure costs energy.",
        "lesson": "Predators are rare because each level keeps only part of the energy.",
    },
    "Skyrender": {
        "role": "Aerial predator",
        "blurb": "The fastest animal, with the widest view of the map. "
                 "Spots prey from far away.",
        "lesson": "Senses and speed are both weapons.",
    },
    "Mycel": {
        "role": "Decomposer",
        "blurb": "Rooted fungus that reaches through the ground to digest "
                 "remains nearby and enrich the soil.",
        "lesson": "Decomposers close the loop: dead things become soil.",
    },
    "Nullborn": {
        "role": "Scavenger",
        "blurb": "Wanders the map hunting for remains, cleaning up what "
                 "others leave behind.",
        "lesson": "Scavengers recycle energy that would otherwise be wasted.",
    },
}


def diet_of(species):
    food = SPECIES[species]["food"]
    if isinstance(food, str):
        food = [food]
    return list(food)


def card_for(species):
    """Everything a species card shows, as plain data."""
    data = SPECIES[species]
    info = SPECIES_INFO.get(species, {})
    behavior = BEHAVIOR.get(species, {})
    return {
        "name": species,
        "role": info.get("role", data["type"]),
        "blurb": info.get("blurb", ""),
        "lesson": info.get("lesson", ""),
        "diet": diet_of(species),
        "eaten_by": list(THREATS.get(species, [])),
        "speed": data["movement_speed"],
        "lifespan": data["lifespan"],
        "perception": behavior.get("perception", 0),
    }


# ---------------------------------------------------------- event lessons

EVENT_LESSONS = {
    "population_boom": "Lots of food and few enemies let a population multiply "
                       "fast, until its food runs short.",
    "population_crash": "A sudden die-off: too many mouths, too little food, "
                        "or heavy hunting.",
    "food_shortage": "The average animal is close to starving: its food can't "
                     "keep up with demand.",
    "resource_competition": "Many animals share few plants, so each one "
                            "gets a smaller meal.",
    "predator_dominance": "Predators are catching prey faster than the prey "
                          "can breed.",
    "predator_starving_amid_prey": "Prey is plentiful but out of reach: it's "
                                   "fast, armoured or spread thin.",
    "trophic_cascade": "Losing a predator frees its prey to boom, a chain "
                       "reaction down the food web.",
    "ecosystem_recovery": "A crashed species is back near its old size. "
                          "Ecosystems can heal.",
    "ecosystem_crisis": "Several species collapsed together: a shock is "
                        "spreading through the food web.",
}


def lesson_for(kind):
    return EVENT_LESSONS.get(kind, "")


# -------------------------------------------------------------- seasons

SEASONS = ["Spring", "Summer", "Autumn", "Winter"]


def season_name(world):
    """Season for the current turn, or None when seasons are switched off."""
    length = getattr(world, "season_length", None)
    if not length:
        return None
    phase = (world.turn % length) / length
    return SEASONS[int(phase * 4) % 4]


# ------------------------------------------------------ energy / mortality

LEVELS = [
    ("Producers", ("Producer",)),
    ("Herbivores", ("Consumer",)),
    ("Predators", ("Predator",)),
    ("Recyclers", ("Decomposer", "Scavenger")),
]


def trophic_levels(snapshot):
    """[(label, total energy, organisms)] bottom of the food chain first."""
    rows = []
    for label, kinds in LEVELS:
        energy = 0.0
        count = 0
        for name, data in SPECIES.items():
            if data["type"] in kinds:
                energy += snapshot.energy[name].total if name in snapshot.energy else 0.0
                count += snapshot.counts.get(name, 0)
        rows.append((label, energy, count))
    return rows


def energy_passed_up():
    """The lesson behind the pyramid: how much energy survives each step."""
    return {"grazing": GRAZING_EFFICIENCY, "hunting": HUNTING_EFFICIENCY}


DEATH_LABELS = [
    ("deaths_starvation", "Starved", (255, 167, 38)),
    ("deaths_old age", "Old age", (128, 140, 155)),
    ("deaths_predation", "Eaten", (255, 82, 82)),
    ("deaths_plague", "Plague", (195, 100, 255)),
    ("deaths_meteor", "Meteor", (255, 120, 60)),
    ("deaths_experiment", "Lab", (77, 208, 225)),
]


def mortality(rows, window=100):
    """How animals and plants died over the last `window` turns: [(label, n, colour)]."""
    recent = rows[-window:]
    out = []
    for key, label, colour in DEATH_LABELS:
        n = sum(r.get(key, 0) for r in recent)
        if n > 0 or key in ("deaths_starvation", "deaths_old age", "deaths_predation"):
            out.append((label, n, colour))
    return out


# ------------------------------------------------------------- food web

# Node positions as (x, y) fractions of the panel.
WEB_NODES = {
    "Ravager":   (0.26, 0.09),
    "Skyrender": (0.74, 0.09),
    "Grazer":    (0.26, 0.31),
    "Shellkin":  (0.74, 0.31),
    "Verdant":   (0.26, 0.53),
    "Crystalis": (0.74, 0.53),
    "Nullborn":  (0.12, 0.90),
    "Remains":   (0.36, 0.78),
    "Mycel":     (0.60, 0.90),
    "Soil":      (0.88, 0.78),
}


def web_edges():
    """
    Arrows that show where energy flows: (source, target, stat key or None, route).
    `route` is a list of extra (x, y) corner points for elbowed arrows.
    """
    edges = []
    for name, data in SPECIES.items():
        for food in diet_of(name):
            if food == "Organic Remains":
                edges.append(("Remains", name, f"ate:{name}>Remains", []))
            elif food in SPECIES:
                edges.append((food, name, f"ate:{name}>{food}", []))

    # the nutrient loop: recyclers -> soil -> plants
    edges.append(("Mycel", "Soil", None, []))
    edges.append(("Nullborn", "Soil", None, [(0.12, 1.02), (0.88, 1.02)]))
    edges.append(("Soil", "Verdant", None, [(0.88, 0.68), (0.26, 0.68)]))
    edges.append(("Soil", "Crystalis", None, [(0.88, 0.68), (0.74, 0.68)]))
    return edges


# ------------------------------------------------------------- showcase

# Each step: how many turns it stays on screen, what it says, and what the
# viewer should do (highlight species, switch tab, move the camera, cause an
# event). `do` is one of: drought, plague, soil_on, soil_off.
SHOWCASE = [
    {"turns": 30, "title": "Welcome to GAIA",
     "text": "A living world with eight species. Sunlight feeds plants, plants "
             "feed herbivores, herbivores feed predators.",
     "speaker_note": "Introduce the 8 species: autonomous agents interacting via energy transfer without hard-coded population rules.",
     "tab": "Overview", "camera": "reset"},
    {"turns": 30, "title": "Producers: the base of life",
     "text": "Verdant and Crystalis turn light and radiation into energy. "
             "Everything else depends on them.",
     "speaker_note": "Highlight the two niches: Verdant uses sunlight, while Crystalis synthesizes from radiation as a drought backup.",
     "highlight": ["Verdant", "Crystalis"]},
    {"turns": 30, "title": "Herbivores",
     "text": "Grazers and Shellkin eat plants. Only about 60% of a bite "
             "becomes energy; the rest is lost as heat.",
     "speaker_note": "Explain the ecological efficiency principle: Grazers lose 40% of consumed plant energy to metabolic maintenance and movement.",
     "highlight": ["Grazer", "Shellkin"]},
    {"turns": 36, "title": "Predators",
     "text": "Ravagers and Skyrenders hunt herbivores. Many attacks fail, and "
             "each failure burns energy.",
     "speaker_note": "Note hunting failure mechanics: predators burn substantial energy per sprint, making prey density critical to their survival.",
     "highlight": ["Ravager", "Skyrender"], "camera": ("Ravager", 2.4)},
    {"turns": 34, "title": "Recyclers",
     "text": "Dead things become remains. Mycel and Nullborn eat them and "
             "enrich the soil (the glowing patches).",
     "speaker_note": "Point out the glowing soil nutrients: decomposers recycle carcasses, replenishing fertility for new plant growth.",
     "highlight": ["Mycel", "Nullborn"], "camera": "reset", "do": "soil_on"},
    {"turns": 32, "title": "Everything is connected",
     "text": "Arrows show who eats whom. Watch them pulse as meals happen.",
     "speaker_note": "Observe real-time arrow pulses indicating feeding events. Ask the audience what would happen if herbivores collapsed.",
     "tab": "Web", "do": "soil_off"},
    {"turns": 32, "title": "The energy pyramid",
     "text": "Each step up keeps only part of the energy, so there are far "
             "fewer predators than plants.",
     "speaker_note": "Contrast biomass across tiers: thousands of plant energy units are required to sustain just a few apex carnivores.",
     "tab": "Energy"},
    {"turns": 28, "title": "A drought strikes!",
     "text": "Sunlight drops to 30%. Verdant struggles; Crystalis keeps "
             "growing on radiation.",
     "speaker_note": "Stress test demonstration: dimming sunlight starves Verdant, while radiation-feeding Crystalis acts as an ecological buffer.",
     "tab": "Overview", "do": "drought"},
    {"turns": 46, "title": "Watch the ripple",
     "text": "Fewer plants means hungry herbivores, which means less food "
             "for predators. One shock spreads through the web.",
     "speaker_note": "Trophic cascade delay: note that grazer numbers drop several turns after plant biomass declines.",
     },
    {"turns": 36, "title": "Plague hits the Grazers",
     "text": "A disease kills most of the Grazers. Predators now have less "
             "to eat, and plants are suddenly safer.",
     "speaker_note": "Disease epidemic shock: grazer die-off triggers predator starvation while temporarily relieving grazing pressure on plants.",
     "do": "plague"},
    {"turns": 36, "title": "Boom and bust",
     "text": "Predators and prey rise and fall in loops, each chasing the "
             "other. This is a classic predator-prey cycle.",
     "speaker_note": "Lotka-Volterra dynamics: explain the classic phase lag where predator population peaks trail prey peaks.",
     "tab": "Dynamics"},
    {"turns": 36, "title": "Evolution in action",
     "text": "Offspring inherit speed and senses with small mutations. "
             "Faster ones survive more often, so the averages drift.",
     "speaker_note": "Natural selection in real time: faster herbivores escape predation more often, shifting the gene pool speed distribution.",
     "tab": "Dynamics"},
    {"turns": 40, "title": "Your turn!",
     "text": "Open the Lab tab: remove predators, switch off the decomposers "
             "or drop a meteor, and predict what happens first.",
     "speaker_note": "Open floor for interactive experiments: invite audience suggestions to trigger meteors, alter climate, or remove tiers.",
     "tab": "Lab", "camera": "reset"},
]


def showcase_schedule():
    """[(start_turn_offset, step)] with offsets accumulated from step lengths."""
    out, t = [], 0
    for step in SHOWCASE:
        out.append((t, step))
        t += step["turns"]
    return out


def showcase_length():
    return sum(step["turns"] for step in SHOWCASE)
