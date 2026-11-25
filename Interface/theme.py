"""Colours and sizes shared by the Pygame viewer and its panels."""

BG = (15, 19, 24)
PANEL = (22, 28, 36)
PANEL_BORDER = (42, 50, 61)
MAP_BG = (18, 25, 22)
GRID_COLOR = (30, 39, 36)
TEXT = (220, 226, 234)
MUTED = (128, 140, 155)
ACCENT = (77, 208, 225)
BTN_BG = (32, 40, 52)
BTN_HOVER = (46, 58, 74)
BTN_ACTIVE = (55, 120, 140)
DANGER_BG = (82, 32, 38)
DANGER_HOVER = (115, 42, 50)

SPECIES_COLOR = {
    "Verdant":   (92, 214, 92),
    "Crystalis": (77, 208, 225),
    "Grazer":    (255, 202, 40),
    "Shellkin":  (179, 107, 255),
    "Ravager":   (255, 82, 82),
    "Skyrender": (255, 138, 179),
    "Mycel":     (196, 154, 108),
    "Nullborn":  (176, 190, 197),
}

# Base sprite size (pixels along the longest side) per species
SPRITE_SIZE = {
  "Verdant":   64,
  "Crystalis": 76,
  "Mycel":     68,
  "Grazer":    88,
  "Shellkin":  88,
  "Nullborn":  92,
  "Ravager":   108,
  "Skyrender": 124
}

EVENT_COLORS = {
    "population_boom": (92, 214, 92),
    "ecosystem_recovery": (77, 208, 225),
    "population_crash": (255, 82, 82),
    "ecosystem_crisis": (255, 40, 80),
    "food_shortage": (255, 167, 38),
    "predator_dominance": (255, 138, 101),
    "resource_competition": (255, 213, 79),
    "trophic_cascade": (206, 147, 216),
    "predator_starving_amid_prey": (244, 143, 177),
}

ACTION_COLORS = {
    "hunt":     (255, 82, 82),
    "graze":    (92, 214, 92),
    "flee":     (255, 167, 38),
    "scavenge": (196, 154, 108),
    "wander":   (128, 140, 155),
}

REMAINS_COLOR = (164, 124, 90)
SOIL_COLOR = (150, 205, 90)
SPEEDS = [1, 2, 4, 8, 15, 30, 60, "max"]
FPS = 60

TABS = ["Overview", "Web", "Energy", "Dynamics", "Lab"]
