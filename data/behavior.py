# Behavior profile for every mobile or feeding species.
#
#   perception : how far the organism can sense food, prey and threats
#   eat_below  : it is hungry while energy < starting_energy * eat_below
#   aggression : 0..1  predators: how readily they attack when not hungry
#   caution    : 0..1  how strongly it reacts to nearby threats
#   curiosity  : 0..1  how likely it is to wander when it has nothing to do
#
# Producers have no behavior: they just photosynthesize.

BEHAVIOR = {

    "Grazer": {
        "perception": 12,
        "eat_below": 1.7,
        "aggression": 0.0,
        "caution": 0.8,
        "curiosity": 0.5,
    },

    "Shellkin": {
        "perception": 6,
        "eat_below": 1.5,
        "aggression": 0.0,
        "caution": 0.3,
        "curiosity": 0.3,
    },

    "Ravager": {
        "perception": 15,
        "eat_below": 1.6,
        "aggression": 0.7,
        "caution": 0.0,
        "curiosity": 0.7,
    },

    "Skyrender": {
        "perception": 25,
        "eat_below": 1.6,
        "aggression": 0.4,
        "caution": 0.0,
        "curiosity": 0.8,
    },

    "Mycel": {
        "perception": 8,
        "eat_below": 1.5,
        "aggression": 0.0,
        "caution": 0.0,
        "curiosity": 0.0,
    },

    "Nullborn": {
        "perception": 10,
        "eat_below": 1.5,
        "aggression": 0.0,
        "caution": 0.2,
        "curiosity": 0.6,
    },
}