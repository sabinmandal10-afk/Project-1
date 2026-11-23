SPECIES = {

    "Verdant": {
        "type": "Producer",
        "starting_energy": 100,
        "metabolism": 1,
        "lifespan": 100,
        "movement_speed": 0,
        "food": "Light"
    },

    "Crystalis": {
        "type": "Producer",
        "starting_energy": 150,
        "metabolism": 0.5,
        "lifespan": 200,
        "movement_speed": 0,
        "food": "Radiation"
    },

    "Grazer": {
        "type": "Consumer",
        "starting_energy": 100,
        "metabolism": 2,
        "lifespan": 80,
        "movement_speed": 5,
        "food": "Verdant"
    },

    "Shellkin": {
        "type": "Consumer",
        "starting_energy": 120,
        "metabolism": 1,
        "lifespan": 120,
        "movement_speed": 2,
        "food": "Crystalis"
    },

    "Ravager": {
        "type": "Predator",
        "starting_energy": 130,
        "metabolism": 3,
        "lifespan": 90,
        "movement_speed": 8,
        "food": ["Grazer", "Shellkin"]
    },

    "Skyrender": {
        "type": "Predator",
        "starting_energy": 140,
        "metabolism": 2.5,
        "lifespan": 100,
        "movement_speed": 10,
        "food": ["Grazer", "Shellkin"]
    },

    "Mycel": {
        "type": "Decomposer",
        "starting_energy": 100,
        "metabolism": 0.5,
        "lifespan": 150,
        "movement_speed": 0,
        "food": "Organic Remains"
    },

    "Nullborn": {
        "type": "Scavenger",
        "starting_energy": 110,
        "metabolism": 1,
        "lifespan": 100,
        "movement_speed": 3,
        "food": "Organic Remains"
    }

}
