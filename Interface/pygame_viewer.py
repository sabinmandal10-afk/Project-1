"""
GAIA 60 FPS Live Viewer (Pygame).

Features:
  - Smooth 60 FPS position interpolation, left/right facing & procedural walk/hover/sway
  - Your sprite art and forest terrain (assets/sprites/*.png, assets/world/terrain.jpg)
  - Animals grow up (small juveniles), tiny hunger bars, death fade-outs
  - Hunting visuals: fading chase/flee trails, '!' flee alerts, and predation claw-slashes
  - Ambient weather & disaster particles, seasons with a changing tint, soil nutrient map
  - Camera: mouse-wheel zoom, drag to pan, follow one organism
  - Sidebar tabs: Overview, Web (live food web + species cards), Energy (pyramid),
    Dynamics (predator-prey cycle + evolution), Lab (what-if experiments)
  - Guided Showcase story for presentations, clean projector view, screenshots, recording
  - Event toasts that explain *why* something happened
  - Click-to-Spawn brush, live Light & Radiation sliders, disaster buttons

Mouse:
  Left click        : select an organism (or spawn, with the brush armed)
  Wheel             : zoom      Left-drag / middle-drag : pan (when zoomed)
  Right click       : leave spawn mode

Keys:
  Space      : Play / Pause           Right : Step 1 turn
  Up / Down  : Speed up / down        R     : Toggle organic remains
  S          : Start/stop Showcase    K     : Skip to next Showcase step
  PgDn/PgUp  : Next / Previous step   Left  : Previous Showcase step
  N          : Toggle speaker notes   B     : Pause at every caption
  G          : Step jump menu         M     : Soil nutrient map
  H          : Clean (projector) view
  F          : Follow selected        Z / 0 : Reset camera       + / - : Zoom
  Tab, 1-5   : Switch sidebar tab     P     : Screenshot         V : Record frames
  F1 or ?    : Help                   F11   : Fullscreen         C / Esc : Clear selection
"""

import contextlib
import ctypes
import io
import math
import os
import random
import time
from collections import deque

import pygame

from data.behavior import BEHAVIOR
from data.species import SPECIES
from Interface import education as edu
from Interface import panels
from Interface.camera import Camera
from Interface.experiments import Lab, BY_KEY
from Interface.snapshot import take_snapshot
from Interface.theme import (
    BG, PANEL, PANEL_BORDER, MAP_BG, GRID_COLOR, TEXT, MUTED, ACCENT,
    BTN_BG, BTN_HOVER, BTN_ACTIVE, DANGER_BG, DANGER_HOVER,
    SPECIES_COLOR, SPRITE_SIZE, EVENT_COLORS, ACTION_COLORS,
    REMAINS_COLOR, SOIL_COLOR, SPEEDS, FPS, TABS,
)
from organisms import evolution
from organisms.behavior import perception_of
from organisms.factory import create_organism
from organisms.reproduction import REPRODUCTION
from Interface.showcase import ShowcaseDirector, ShowcaseStep, PredictionPrompt
from Simulation.stress import Drought, Plague, RadiationDrop


# Where the season tint sits for each part of the year (spring, summer, autumn, winter)
SEASON_TINT = [(120, 200, 120, 16), (255, 220, 120, 18), (230, 140, 60, 30), (120, 160, 235, 34)]


def format_event(e):
    """Display a plain-English, self-explanatory message directly on screen."""
    sp = e.species
    nums = e.detail.split(" in ")[0] if " -> " in e.detail else ""

    if e.kind == "population_boom":
        msg = f"{sp} grew fast ({nums})"
    elif e.kind == "population_crash":
        msg = f"{sp} died off ({nums})"
    elif e.kind == "food_shortage":
        msg = f"{sp} starving (no food)"
    elif e.kind == "resource_competition":
        msg = f"{sp} running low on food"
    elif e.kind == "predator_dominance":
        msg = "Predators overhunting prey"
    elif e.kind == "predator_starving_amid_prey":
        msg = "Predators can't catch prey"
    elif e.kind == "trophic_cascade":
        msg = f"{sp} surged (predators gone)"
    elif e.kind == "ecosystem_recovery":
        msg = f"{sp} bounced back"
    elif e.kind == "ecosystem_crisis":
        msg = "MASS DIE-OFF (3+ species)"
    else:
        msg = f"{e.kind.replace('_', ' ')} ({sp})"

    return f"T{e.turn:<4} {msg}"


# --------------------------------------------------------------- UI widgets

class Button:
    def __init__(self, rect, label, on_click, danger=False):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.on_click = on_click
        self.danger = danger
        self.active = False

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.on_click()
                return True
        return False

    def draw(self, surf, font, mouse_pos):
        hovered = self.rect.collidepoint(mouse_pos)
        if self.danger:
            color = DANGER_HOVER if hovered else DANGER_BG
        elif self.active:
            color = BTN_ACTIVE
        else:
            color = BTN_HOVER if hovered else BTN_BG

        pygame.draw.rect(surf, color, self.rect, border_radius=5)
        pygame.draw.rect(surf, PANEL_BORDER, self.rect, width=1, border_radius=5)
        txt = font.render(self.label, True, TEXT)
        surf.blit(txt, txt.get_rect(center=self.rect.center))


class Slider:
    def __init__(self, rect, label, min_val, max_val, value, on_change,
                 color=ACCENT, fmt=lambda v: f"{v:.2f}"):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.min_val = min_val
        self.max_val = max_val
        self.value = value
        self.on_change = on_change
        self.color = color
        self.fmt = fmt
        self.dragging = False

    def _set_from_x(self, x):
        t = max(0.0, min(1.0, (x - self.rect.x) / max(1, self.rect.w)))
        new_val = self.min_val + t * (self.max_val - self.min_val)
        if abs(new_val - self.value) > 1e-6:
            self.value = new_val
            self.on_change(self.value)

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hit = self.rect.inflate(0, 12)
            if hit.collidepoint(event.pos):
                self.dragging = True
                self._set_from_x(event.pos[0])
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            self._set_from_x(event.pos[0])
            return True
        return False

    def draw(self, surf, font):
        lbl = font.render(self.label, True, TEXT)
        val = font.render(self.fmt(self.value), True, MUTED)
        surf.blit(lbl, (self.rect.x, self.rect.y - 16))
        surf.blit(val, (self.rect.right - val.get_width(), self.rect.y - 16))

        track = pygame.Rect(self.rect.x, self.rect.centery - 3, self.rect.w, 6)
        pygame.draw.rect(surf, (38, 46, 58), track, border_radius=3)

        t = (self.value - self.min_val) / max(1e-9, self.max_val - self.min_val)
        t = max(0.0, min(1.0, t))
        fill = pygame.Rect(track.x, track.y, int(track.w * t), track.h)
        pygame.draw.rect(surf, self.color, fill, border_radius=3)

        knob_x = track.x + int(track.w * t)
        pygame.draw.circle(surf, TEXT, (knob_x, track.centery), 7)
        pygame.draw.circle(surf, self.color, (knob_x, track.centery), 4)


# ------------------------------------------------------------ sprite loader

class SpriteBank:
    """Loads optional PNGs from assets/sprites/ and the map from assets/world/."""

    def __init__(self, assets_dir="assets"):
        self.assets_dir = self._find_assets(assets_dir)
        self.raw_sprites = {}
        self.scaled_cache = {}
        self.terrain = None
        self._terrain_key = None
        self._terrain_img = None
        self._load()

    @staticmethod
    def _find_assets(assets_dir):
        """Use ./assets if it exists, otherwise the assets folder next to the project."""
        if os.path.isdir(assets_dir):
            return assets_dir
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        beside = os.path.join(here, assets_dir)
        return beside if os.path.isdir(beside) else assets_dir

    def _load(self):
        sprite_dir = os.path.join(self.assets_dir, "sprites")
        if os.path.isdir(sprite_dir):
            for name in list(SPECIES.keys()) + ["remains"]:
                path = os.path.join(sprite_dir, f"{name.lower()}.png")
                if os.path.isfile(path):
                    try:
                        img = pygame.image.load(path).convert_alpha()
                        self.raw_sprites[name] = img
                    except pygame.error:
                        pass

        for filename in ("terrain.png", "terrain.jpg", "terrain.jpeg"):
            terrain_path = os.path.join(self.assets_dir, "world", filename)
            if os.path.isfile(terrain_path):
                try:
                    self.terrain = pygame.image.load(terrain_path).convert()
                    break
                except pygame.error:
                    pass

    def get(self, name, size_px, angle_deg=0.0):
        raw = self.raw_sprites.get(name)
        if raw is None:
            return None
        # Sizes snap to 4 px steps so growing animals don't create a new image every frame
        q_size = max(16, int(round(size_px / 4) * 4))
        facing_left = abs(angle_deg) > 90
        key = (name, q_size, facing_left)
        img = self.scaled_cache.get(key)
        if img is None:
            if len(self.scaled_cache) > 900:
                self.scaled_cache.clear()
            rw, rh = raw.get_size()
            scale = q_size / max(rw, rh)
            w = max(1, int(rw * scale))
            h = max(1, int(rh * scale))
            scaled = pygame.transform.smoothscale(raw, (w, h))
            img = pygame.transform.flip(scaled, True, False) if facing_left else scaled
            self.scaled_cache[key] = img
        return img

    def terrain_view(self, size, region=(0.0, 0.0, 1.0, 1.0)):
        """
        The map picture scaled to `size`, showing only `region`
        (left, top, right, bottom as 0..1 fractions of the world).
        The picture is cropped to the map's shape instead of being squashed.
        """
        if self.terrain is None:
            return None
        key = (tuple(size), tuple(round(v, 3) for v in region))
        if key == self._terrain_key:
            return self._terrain_img

        tw, th = self.terrain.get_size()
        aspect = size[0] / max(1, size[1])
        base_w = min(tw, th * aspect)
        base_h = base_w / aspect
        bx, by = (tw - base_w) / 2, (th - base_h) / 2

        x0 = bx + region[0] * base_w
        y0 = by + region[1] * base_h
        x1 = bx + region[2] * base_w
        y1 = by + region[3] * base_h
        rect = pygame.Rect(int(x0), int(y0), max(2, int(x1 - x0)), max(2, int(y1 - y0)))
        rect = rect.clip(self.terrain.get_rect())
        if rect.w < 2 or rect.h < 2:
            return None

        view = pygame.transform.smoothscale(self.terrain.subsurface(rect), tuple(size))
        self._terrain_key, self._terrain_img = key, view
        return view


# ----------------------------------------------------------------- viewer

class PygameViewer:

    def __init__(self, sim, recorder=None, detector=None, stress=None,
                 speed_index=2, start_paused=False, width=1400, height=840,
                 showcase=False, pause_on_caption=False, speaker_notes=False):
        self.sim = sim
        self.world = sim.world
        self.recorder = recorder
        self.detector = detector or getattr(recorder, "detector", None)
        self.stress = stress

        self.width = width
        self.height = height
        self.paused = start_paused
        self.speed_index = max(0, min(len(SPEEDS) - 1, speed_index))
        self.show_remains = True
        self.selected = None
        self.spawn_species = None
        self.saved_season_length = self.world.season_length or 120

        # Interpolation state: id(organism) -> (prev_x, prev_y, curr_x, curr_y, angle, ref)
        self._interp = {}
        self._effects = []               # [wx, wy, color, age, duration, max_radius]
        self._trails = {}                # id(org) -> deque of (wx, wy, color)
        self._slashes = []               # [wx, wy, age, duration]
        self._particles = []             # [nx, ny, vx, vy, size, age, life, kind]
        self._ghosts = []                # fading bodies: [wx, wy, species, angle, age, duration]
        self._species_rects = {}
        self._fx_surf = None
        self._soil_surf = None
        self._anim_time = 0.0
        self._plague_fx_timer = 0.0
        self._turn_progress = 1.0
        self._acc = 0.0
        self.history = deque(maxlen=400)
        self.gene_history = deque(maxlen=400)

        # Camera, lab and teaching tools
        self.camera = Camera(self.world.width, self.world.height)
        self.lab = Lab(self.world)
        self.sim.pre_turn_hooks.append(self.lab)
        self.lab_reveal = False
        self.evolving = set(evolution.EVOLVING)

        self.tab = "Overview"
        self._targets = []               # clickable regions registered while drawing
        self.mouse_pos = (0, 0)
        self.tooltip = None              # (text, colour) shown next to the mouse
        self.fonts = {}
        self.sprites = None
        self._card_species = None
        self.edge_pulse = {}             # stat key -> 0..1 glow on the food web arrows
        self._last_stats = {}
        self._seen_events = len(self.detector.events) if self.detector else 0

        self.show_soil = False
        self.show_help = False
        self.clean = False
        self.highlight = set()
        self.caption = None              # {"title", "text", "age", "dur"}
        self._toasts = []                # [title, body, colour, age, duration]
        self._drag = None

        self.showcase_on = False
        self._showcase_t0 = 0
        self._showcase_idx = -1
        self._want_showcase = showcase
        self.btn_play = None
        self.sl_speed = None
        self.show_step_menu = False        # step-jump overlay
        self.director = ShowcaseDirector() # presenter controls
        self.director.pause_on_caption = pause_on_caption
        self.director.show_speaker_notes = speaker_notes

        self.recording = False
        self._record_dir = None
        self._record_frame = 0
        self._record_clock = 0.0
        self._screen = None
        self._win = (width, height)

        self.map_rect = pygame.Rect(0, 0, 100, 100)
        self.side_rect = pygame.Rect(0, 0, 100, 100)

        self.snap = take_snapshot(self.world)
        self._last_migrants = self.world.stats.get("migrants", 0)
        self._sync_interp(self.snap, snap_only=True)
        self._remember(self.snap)

    # ------------------------------------------------------- small helpers

    @property
    def anim_time(self):
        return self._anim_time

    def add_target(self, rect, fn):
        self._targets.append((pygame.Rect(rect), fn))

    def _hit_target(self, pos):
        for rect, fn in reversed(self._targets):
            if rect.collidepoint(pos):
                fn()
                return True
        return False

    def pick_spawn(self, name):
        self.spawn_species = None if self.spawn_species == name else name
        self.selected = None

    def card_species(self):
        if self.selected is not None and getattr(self.selected, "status", "") == "Alive":
            return self.selected.species
        return self._card_species or "Grazer"

    def set_card_species(self, name):
        self._card_species = name
        self.selected = None

    def _update_layout(self, width, height, sprites=None):
        self.width = max(960, width)
        self.height = max(640, height)
        pad = 12
        if self.clean:
            map_w = self.width - pad * 2
            map_h = self.height - pad * 2
            self.map_rect = pygame.Rect(pad, pad, map_w, map_h)
            self.side_rect = pygame.Rect(self.width + 10, pad, 10, map_h)   # off screen
        else:
            side_w = max(360, min(430, int(self.width * 0.32)))
            map_w = self.width - side_w - pad * 3
            map_h = self.height - pad * 2
            self.map_rect = pygame.Rect(pad, pad, map_w, map_h)
            self.side_rect = pygame.Rect(self.map_rect.right + pad, pad, side_w, map_h)
        self._fx_surf = pygame.Surface(self.map_rect.size, pygame.SRCALPHA)
        self._soil_surf = pygame.Surface(self.map_rect.size, pygame.SRCALPHA)
        self._build_ui()
        return None   # the terrain is drawn (and zoomed) per frame by the SpriteBank

    # -------------------------------------------------------- simulation

    @property
    def speed(self):
        return SPEEDS[self.speed_index]

    def _add_effect(self, wx, wy, color, duration=0.55, max_radius=26):
        if len(self._effects) < 80:
            self._effects.append([wx, wy, color, 0.0, duration, max_radius])

    def _active_disasters(self):
        if not self.stress or not self.stress.active:
            return set()
        return {e.name.lower() for e in self.stress.active}

    def _update_particles(self, dt):
        if self._plague_fx_timer > 0:
            self._plague_fx_timer = max(0.0, self._plague_fx_timer - dt)

        disasters = self._active_disasters()
        drought = "drought" in disasters
        plague = ("plague" in disasters) or (self._plague_fx_timer > 0)

        if len(self._particles) < 65:
            if drought and random.random() < dt * 18:
                self._particles.append([
                    -0.05, random.random(),
                    random.uniform(0.28, 0.45), random.uniform(-0.02, 0.04),
                    random.randint(18, 36), 0.0, random.uniform(2.0, 3.2), "wind"
                ])
            if plague and random.random() < dt * 16:
                self._particles.append([
                    random.random(), random.random(),
                    random.uniform(-0.02, 0.02), random.uniform(-0.05, -0.02),
                    random.randint(2, 4), 0.0, random.uniform(2.5, 4.0), "plague"
                ])
            if not drought and self.snap.light > 0.55 and random.random() < dt * 9 * self.snap.light:
                self._particles.append([
                    random.random(), random.random(),
                    random.uniform(0.01, 0.03), random.uniform(-0.015, 0.015),
                    random.randint(2, 3), 0.0, random.uniform(3.0, 5.5), "sun"
                ])
            if self.snap.radiation > 0.55 and random.random() < dt * 7 * self.snap.radiation:
                self._particles.append([
                    random.random(), random.random(),
                    random.uniform(-0.015, 0.015), random.uniform(-0.03, -0.01),
                    random.randint(2, 3), 0.0, random.uniform(2.5, 4.5), "rad"
                ])

        alive = []
        for p in self._particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[5] += dt
            if p[5] < p[6] and -0.1 <= p[0] <= 1.1 and -0.1 <= p[1] <= 1.1:
                alive.append(p)
        self._particles = alive

    def _advance(self, turns=1):
        migrated = False
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(turns):
                self.sim.advance_turn()
                if self.recorder is None:
                    self._remember(take_snapshot(self.world))
        migrants_now = self.world.stats.get("migrants", 0)
        if migrants_now > self._last_migrants:
            migrated = True
            self._last_migrants = migrants_now
        self.snap = take_snapshot(self.world)
        self._sync_interp(self.snap, migrants=migrated)
        self._remember(self.snap)
        self._track_flows(self.snap)
        self._watch_events()
        if migrated:
            self._toast("Migrants arrive",
                        "A species had died out. New animals wander in from "
                        "outside the map (recolonisation).", ACCENT, 8.0)
        if self.showcase_on:
            self._tick_showcase()

    def _sync_interp(self, snap, snap_only=False, migrants=False):
        old_map = self._interp
        new_map = {}
        w, h = self.world.width, self.world.height

        for o in snap.organisms:
            oid = id(o.ref)
            old = old_map.get(oid)
            if old is None or snap_only:
                new_map[oid] = (o.x, o.y, o.x, o.y, 0.0, o.ref)
                if old is None and not snap_only:
                    at_edge = o.x <= 0.01 or o.y <= 0.01 or o.x >= w - 0.01 or o.y >= h - 0.01
                    if migrants and at_edge:
                        self._add_effect(o.x, o.y, ACCENT, duration=0.9, max_radius=46)
                    else:
                        self._add_effect(o.x, o.y, (92, 214, 92), duration=0.45, max_radius=20)
            else:
                px, py = old[2], old[3]
                dx, dy = o.x - px, o.y - py
                angle = math.degrees(math.atan2(dy, dx)) if (dx * dx + dy * dy) > 1e-4 else old[4]
                new_map[oid] = (px, py, o.x, o.y, angle, o.ref)

        if not snap_only:
            for oid, (_, _, cx, cy, ang, ref) in old_map.items():
                if oid not in new_map:
                    self._trails.pop(oid, None)
                    cause = getattr(ref, "death_cause", None)
                    if cause == "predation":
                        self._add_effect(cx, cy, (255, 70, 70), duration=0.65, max_radius=34)
                        self._slashes.append([cx, cy, 0.0, 0.35])
                    elif cause == "plague":
                        self._add_effect(cx, cy, (190, 90, 255), duration=0.6, max_radius=28)
                    if len(self._ghosts) < 70:
                        quick = cause in ("predation", "plague", "meteor", "experiment")
                        self._ghosts.append([cx, cy, ref.species, ang, 0.0, 0.3 if quick else 0.9])
                    if self.camera.follow is ref:
                        self.camera.follow = None

        self._interp = new_map

    def _remember(self, snap):
        if self.history and self.history[-1][0] == snap.turn:
            self.history[-1] = (snap.turn, dict(snap.counts))
            self.gene_history[-1] = (snap.turn, dict(snap.traits))
        else:
            self.history.append((snap.turn, dict(snap.counts)))
            self.gene_history.append((snap.turn, dict(snap.traits)))

    def _track_flows(self, snap):
        """Glow the food-web arrows for meals that happened this turn."""
        for key, value in snap.stats.items():
            if not key.startswith("ate:"):
                continue
            delta = value - self._last_stats.get(key, 0)
            if delta > 0:
                self.edge_pulse[key] = min(1.0, self.edge_pulse.get(key, 0.0) + 0.2 * delta)
            self._last_stats[key] = value

    def _watch_events(self):
        """Turn new ecosystem events into short on-screen explanations."""
        if not self.detector:
            return
        events = self.detector.events
        fresh = events[self._seen_events:]
        self._seen_events = len(events)
        for e in fresh[-2:]:
            lesson = edu.lesson_for(e.kind)
            self._toast(format_event(e), lesson, EVENT_COLORS.get(e.kind, MUTED), 9.0)

    def _toast(self, title, body, colour, duration=8.0):
        self._toasts.append([title, body, colour, 0.0, duration])
        del self._toasts[:-3]

    # --------------------------------------------------------- UI setup

    def _build_ui(self):
        sx = self.side_rect.x + 14
        sw = self.side_rect.w - 28
        y = self.side_rect.y + 38

        bw = (sw - 16) // 3
        self.btn_play = Button((sx, y, bw, 28), "Play" if self.paused else "Pause", self._toggle_pause)
        self.btn_step = Button((sx + bw + 8, y, bw, 28), "Step +1", self._step_one)
        self.btn_remains = Button(
            (sx + (bw + 8) * 2, y, bw, 28),
            "Remains: ON" if self.show_remains else "Remains: OFF",
            self._toggle_remains
        )
        self.btn_remains.active = self.show_remains

        y += 50
        self.sl_speed = Slider(
            (sx, y, sw, 14), "Simulation Speed", 0, len(SPEEDS) - 1, self.speed_index,
            self._on_speed, color=ACCENT,
            fmt=lambda v: "MAX" if SPEEDS[int(round(v))] == "max" else f"{SPEEDS[int(round(v))]} turns/s"
        )

        y += 42
        self.btn_seasons = Button(
            (sx, y, sw, 26),
            "Seasons: AUTO (click for Manual)" if self.world.season_length else "Seasons: MANUAL (click for Auto)",
            self._toggle_seasons
        )
        self.btn_seasons.active = bool(self.world.season_length)

        y += 48
        self.sl_light = Slider(
            (sx, y, sw, 14), "Sunlight", 0.0, 1.0, self.world.light_level,
            self._on_light, color=(255, 213, 79), fmt=lambda v: f"{int(v * 100)}%"
        )

        y += 40
        self.sl_rad = Slider(
            (sx, y, sw, 14), "Radiation", 0.0, 1.0, self.world.radiation_level,
            self._on_rad, color=(77, 208, 225), fmt=lambda v: f"{int(v * 100)}%"
        )

        y += 28
        self.btn_drought = Button((sx, y, bw, 26), "Drought", self._trigger_drought, danger=True)
        self.btn_raddrop = Button((sx + bw + 8, y, bw, 26), "Rad Drop", self._trigger_raddrop, danger=True)
        self.btn_plague = Button((sx + (bw + 8) * 2, y, bw, 26), "Plague", self._trigger_plague, danger=True)

        self.buttons = [
            self.btn_play, self.btn_step, self.btn_remains,
            self.btn_seasons, self.btn_drought, self.btn_raddrop, self.btn_plague
        ]
        self.sliders = [self.sl_speed, self.sl_light, self.sl_rad]
        self.panels_start_y = y + 36

    def _toggle_pause(self):
        self.paused = not self.paused
        if self.btn_play is not None:
            self.btn_play.label = "Play" if self.paused else "Pause"

    def _step_one(self):
        self._advance(1)
        self._turn_progress = 1.0

    def _toggle_remains(self):
        self.show_remains = not self.show_remains
        self.btn_remains.label = "Remains: ON" if self.show_remains else "Remains: OFF"
        self.btn_remains.active = self.show_remains

    def _on_speed(self, val):
        self.speed_index = int(round(val))

    def _toggle_seasons(self):
        if self.world.season_length:
            self.saved_season_length = self.world.season_length
            self.world.season_length = None
            self.btn_seasons.label = "Seasons: MANUAL (click for Auto)"
            self.btn_seasons.active = False
        else:
            self.world.set_seasons(self.saved_season_length, low=0.5, high=1.0)
            self.btn_seasons.label = "Seasons: AUTO (click for Manual)"
            self.btn_seasons.active = True

    def _on_light(self, val):
        if self.world.season_length:
            self._toggle_seasons()
        self.world.set_environment(light=val)
        self.snap = take_snapshot(self.world)

    def _on_rad(self, val):
        self.world.set_environment(radiation=val)
        self.snap = take_snapshot(self.world)

    def _trigger_drought(self):
        if self.stress is not None:
            self.stress.add(Drought(start=self.world.turn + 1, duration=40, severity=0.25))

    def _trigger_raddrop(self):
        if self.stress is not None:
            self.stress.add(RadiationDrop(start=self.world.turn + 1, duration=40, severity=0.2))

    def _trigger_plague(self):
        if self.stress is None:
            return
        # Target the selected spawn species if set, otherwise the most populous animal
        target = self.spawn_species
        if target is None:
            animals = [
                (count, name) for name, count in self.snap.counts.items()
                if count > 0 and SPECIES[name]["type"] != "Producer"
            ]
            target = max(animals)[1] if animals else "Grazer"

        self.stress.add(Plague(start=self.world.turn + 1, species=target, fraction=0.6))
        self._plague_fx_timer = 4.0

        # Immediate burst of purple rings on living members of that species
        for o in self.snap.organisms:
            if o.species == target:
                self._add_effect(o.x, o.y, (195, 90, 255), duration=0.8, max_radius=34)

    # ------------------------------------------------------------ the Lab

    def _refresh_after_change(self):
        """Pick up changes made outside a normal turn (lab actions)."""
        self.snap = take_snapshot(self.world)
        self._sync_interp(self.snap)

    def lab_toggle(self, key):
        spec = BY_KEY[key]
        self.lab_reveal = False
        with contextlib.redirect_stdout(io.StringIO()):
            self.lab.toggle(key)
        if key == "meteor" and self.lab.last_meteor:
            mx, my, mr = self.lab.last_meteor
            for k in range(3):
                self._add_effect(mx, my, (255, 140, 60), duration=0.9 + 0.2 * k,
                                 max_radius=mr * (3.0 + k * 1.5))
            self.camera.focus(mx, my, 1.6)
        self._refresh_after_change()
        state = "ON" if self.lab.is_on(key) else "OFF"
        title = spec["label"] if spec["kind"] == "action" else f"{spec['label']}: {state}"
        text = spec["predict"]
        if self.lab.last_restored:
            text = self._restored_text()
        self.caption = {"title": title, "text": text, "age": 0.0, "dur": 14.0}

    def _restored_text(self):
        names = ", ".join(f"{n} x{c}" for n, c in self.lab.last_restored.items())
        return f"Experiment off. Founders returned: {names}."

    def lab_reset(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.lab.clear()
        self.lab.last = None
        self.lab_reveal = False
        self.camera.reset()
        self._refresh_after_change()
        # keep the seasons button honest: clear() may have switched seasons back on
        self.btn_seasons.active = bool(self.world.season_length)
        self.btn_seasons.label = ("Seasons: AUTO (click for Manual)" if self.world.season_length
                                  else "Seasons: MANUAL (click for Auto)")
        if self.lab.last_restored:
            self.caption = {"title": "Experiments reset", "text": self._restored_text(),
                            "age": 0.0, "dur": 8.0}
        else:
            self.caption = {"title": "Experiments reset",
                            "text": "Everything is switched off and the world is back to normal.",
                            "age": 0.0, "dur": 5.0}

    def reveal_lesson(self):
        self.lab_reveal = True
        spec = BY_KEY.get(self.lab.last)
        if spec:
            self.caption = {"title": spec["label"], "text": spec["lesson"], "age": 0.0, "dur": 16.0}

    # ----------------------------------------------------------- showcase

    def toggle_showcase(self):
        if self.showcase_on:
            self._stop_showcase()
        else:
            self._start_showcase()

    def _start_showcase(self):
        self.showcase_on = True
        self._showcase_t0 = self.world.turn
        self._showcase_idx = -1
        self.director.start()
        self.paused = False
        if self.btn_play is not None:
            self.btn_play.label = "Pause"
        if self.speed == "max" or self.speed > 8 or self.speed < 4:
            self.speed_index = SPEEDS.index(4)
            if self.sl_speed is not None:
                self.sl_speed.value = self.speed_index
        self._tick_showcase()

    def _stop_showcase(self):
        self.showcase_on = False
        self.director.stop()
        self.highlight = set()
        self.caption = None
        self.show_step_menu = False

    def skip_showcase_step(self):
        """Advance to the next showcase step (K, PageDown, Right, ])."""
        if not self.showcase_on:
            self._start_showcase()
            return
        schedule = edu.showcase_schedule()
        nxt = self._showcase_idx + 1
        if nxt >= len(schedule):
            self._toast("Showcase Finished", "Reached the end of the GAIA story.", ACCENT, 4.0)
            self._stop_showcase()
            return
        self.director.index = nxt
        self._showcase_t0 = self.world.turn - schedule[nxt][0]
        self._showcase_idx = nxt - 1
        self._tick_showcase()
        if self.director.pause_on_caption:
            self.paused = True
            if self.btn_play is not None:
                self.btn_play.label = "Play"

    def prev_showcase_step(self):
        """Go back to the previous showcase step (PageUp, Left, [)."""
        if not self.showcase_on:
            self._start_showcase()
            return
        schedule = edu.showcase_schedule()
        prev_idx = max(0, self._showcase_idx - 1)
        self.director.index = prev_idx
        self._showcase_t0 = self.world.turn - schedule[prev_idx][0]
        self._showcase_idx = prev_idx - 1
        self._tick_showcase()
        if self.director.pause_on_caption:
            self.paused = True
            if self.btn_play is not None:
                self.btn_play.label = "Play"

    def jump_showcase_step(self, step_index):
        """Jump directly to any showcase step by index (from the step menu)."""
        if not self.showcase_on:
            self._start_showcase()
        schedule = edu.showcase_schedule()
        if step_index < 0 or step_index >= len(schedule):
            return
        self.director.index = step_index
        self._showcase_t0 = self.world.turn - schedule[step_index][0]
        self._showcase_idx = step_index - 1
        self._tick_showcase()
        self.show_step_menu = False
        if self.director.pause_on_caption:
            self.paused = True
            if self.btn_play is not None:
                self.btn_play.label = "Play"

    def toggle_pause_on_caption(self):
        """Toggle 'pause at every caption until I press a key' mode."""
        self.director.pause_on_caption = not self.director.pause_on_caption
        state = "ON" if self.director.pause_on_caption else "OFF"
        self._toast("Pause on caption", f"Now {state}. Story will pause at each caption.", ACCENT, 4.0)

    def toggle_speaker_notes(self):
        """Toggle hidden speaker notes overlay."""
        self.director.show_speaker_notes = not self.director.show_speaker_notes
        state = "SHOWN" if self.director.show_speaker_notes else "HIDDEN"
        self._toast("Speaker notes", f"Speaker notes are now {state}.", ACCENT, 3.0)

    def toggle_step_menu(self):
        """Show or hide the step-jump menu overlay."""
        self.show_step_menu = not self.show_step_menu

    def _tick_showcase(self):
        schedule = edu.showcase_schedule()
        elapsed = self.world.turn - self._showcase_t0
        if elapsed >= edu.showcase_length():
            self._stop_showcase()
            return
        idx = max(i for i, (start, _) in enumerate(schedule) if start <= elapsed)
        while self._showcase_idx < idx:
            self._showcase_idx += 1
            self._apply_step(schedule[self._showcase_idx][1])
            # Sync the director to the same step index
            self.director.index = self._showcase_idx
            # Pause-on-caption: pause the simulation every time a new caption appears
            if self.director.pause_on_caption and not self.paused:
                self.paused = True
                if self.btn_play is not None:
                    self.btn_play.label = "Play"

    def _apply_step(self, step):
        self.caption = {"title": step["title"], "text": step["text"],
                        "age": 0.0, "dur": None, "step": True,
                        "speaker_note": step.get("speaker_note", "")}
        self.highlight = set(step.get("highlight", []))
        if "tab" in step:
            self.tab = step["tab"]
        cam = step.get("camera")
        if cam == "reset":
            self.camera.reset()
        elif isinstance(cam, tuple):
            self._focus_species(*cam)

        action = step.get("do")
        if action == "drought" and self.stress is not None:
            self.stress.add(Drought(start=self.world.turn + 1, duration=40, severity=0.3))
        elif action == "plague" and self.stress is not None:
            self.stress.add(Plague(start=self.world.turn + 1, species="Grazer", fraction=0.6))
            self._plague_fx_timer = 4.0
            for o in self.snap.organisms:
                if o.species == "Grazer":
                    self._add_effect(o.x, o.y, (195, 90, 255), duration=0.8, max_radius=34)
        elif action == "soil_on":
            self.show_soil = True
        elif action == "soil_off":
            self.show_soil = False

    def _focus_species(self, species, zoom):
        members = [o for o in self.snap.organisms if o.species == species]
        if not members:
            return
        mx = sum(o.x for o in members) / len(members)
        my = sum(o.y for o in members) / len(members)
        best = min(members, key=lambda o: (o.x - mx) ** 2 + (o.y - my) ** 2)
        self.camera.focus(best.x, best.y, zoom)
        self.camera.follow = best.ref

    # -------------------------------------------------------- view toggles

    def toggle_soil(self):
        self.show_soil = not self.show_soil

    def toggle_help(self):
        self.show_help = not self.show_help

    def toggle_clean(self):
        self.clean = not self.clean
        self._update_layout(*self._win)

    def follow_selected(self):
        if self.selected is not None:
            self.camera.follow = self.selected
            self.camera.zoom_at(1.0)
        else:
            self._toast("Follow", "Click an animal first, then press F to follow it.", MUTED, 4.0)

    def cycle_tab(self, step=1):
        i = TABS.index(self.tab) if self.tab in TABS else 0
        self.tab = TABS[(i + step) % len(TABS)]

    def screenshot(self):
        if self._screen is None:
            return
        os.makedirs("screenshots", exist_ok=True)
        path = os.path.join("screenshots", f"gaia_turn{self.world.turn:05d}_{int(time.time()) % 100000}.png")
        try:
            pygame.image.save(self._screen, path)
            self._toast("Screenshot saved", path, ACCENT, 4.0)
        except pygame.error:
            self._toast("Screenshot failed", "Could not write the file.", (255, 82, 82), 4.0)

    def toggle_record(self):
        if not self.recording:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            self._record_dir = os.path.join("recordings", f"rec_{stamp}")
            os.makedirs(self._record_dir, exist_ok=True)
            self._record_frame = 0
            self._record_clock = 0.0
            self.recording = True
        else:
            self.recording = False
            if self._record_dir:
                cmd = (f'ffmpeg -framerate 30 -i "{self._record_dir}/f%05d.jpg" '
                       f'-pix_fmt yuv420p gaia.mp4')
                try:
                    with open(os.path.join(self._record_dir, "make_video.txt"), "w") as fh:
                        fh.write(cmd + "\n")
                except OSError:
                    pass
                self._toast("Recording saved",
                            f"{self._record_frame} frames in {self._record_dir}. "
                            f"Make a video with: {cmd}", ACCENT, 12.0)

    def _record_tick(self, dt, screen):
        if not self.recording:
            return
        self._record_clock += dt
        if self._record_clock < 1 / 30:
            return
        self._record_clock = 0.0
        w, h = screen.get_size()
        frame = screen if w <= 1280 else pygame.transform.scale(screen, (1280, int(h * 1280 / w)))
        try:
            pygame.image.save(frame, os.path.join(self._record_dir, f"f{self._record_frame:05d}.jpg"))
            self._record_frame += 1
        except pygame.error:
            self.recording = False

    # ------------------------------------------------------- coordinates

    def _world_to_screen(self, wx, wy):
        return self.camera.world_to_screen(wx, wy, self.map_rect)

    def _screen_to_world(self, sx, sy):
        return self.camera.screen_to_world(sx, sy, self.map_rect)

    def _on_wheel(self, dy):
        if not self.map_rect.collidepoint(self.mouse_pos):
            return
        wx, wy = self._screen_to_world(*self.mouse_pos)
        self.camera.zoom_at(1.18 ** dy, wx, wy)

    def _handle_map_click(self, pos):
        if not self.map_rect.collidepoint(pos):
            return
        wx, wy = self._screen_to_world(*pos)

        if self.spawn_species is not None:
            wx, wy = self.world.clamp(wx, wy)
            org = create_organism(self.spawn_species)
            self.world.add_organism(org, wx, wy)
            self.snap = take_snapshot(self.world)
            self._interp[id(org)] = (wx, wy, wx, wy, 0.0, org)
            self._add_effect(wx, wy, ACCENT, duration=0.5, max_radius=28)
            return

        reach = max(self.world.width, self.world.height) * 0.04 / max(1.0, self.camera.zoom)
        best, best_key = None, None
        for o in self.snap.organisms:
            d = math.hypot(o.x - wx, o.y - wy)
            if d >= reach:
                continue
            # an animal standing on a plant should win the click
            key = (round(d, 3), 1 if o.kind == "Producer" else 0)
            if best_key is None or key < best_key:
                best, best_key = o.ref, key
        self.selected = best
        if best is not None:
            self._card_species = best.species

    def _nearest_view(self, pos, radius_px=18):
        """The organism under a screen point (animals beat plants), or None."""
        best, best_key = None, None
        for o in self.snap.organisms:
            sx, sy = self._world_to_screen(o.x, o.y)
            d = math.hypot(sx - pos[0], sy - pos[1])
            if d > radius_px:
                continue
            key = (round(d / 4), 1 if o.kind == "Producer" else 0, d)
            if best_key is None or key < best_key:
                best, best_key = o, key
        return best

    # ----------------------------------------------------------- drawing

    def _season_tint(self):
        """Colour wash for the time of year, blended smoothly between seasons."""
        length = self.world.season_length
        if not length:
            return None
        phase = (self.world.turn % length) / length
        pos = (phase - 0.125) % 1.0 * 4          # 0 at mid-spring ... 3.x at mid-winter
        i = int(pos) % 4
        u = pos - int(pos)
        a, b = SEASON_TINT[i], SEASON_TINT[(i + 1) % 4]
        return tuple(int(a[k] + (b[k] - a[k]) * u) for k in range(4))

    def _growth(self, o):
        """Young organisms are drawn smaller and grow toward maturity."""
        maturity = REPRODUCTION.get(o.species, {}).get("maturity_age", 10) * 1.5
        return 0.6 + 0.4 * min(1.0, o.age / max(1.0, maturity))

    def _draw_map(self, surf, sprites, terrain_scaled, font_sm, font_md):
        r = self.map_rect
        cam = self.camera
        W, H = self.world.width, self.world.height
        pygame.draw.rect(surf, MAP_BG, r)

        prev_clip = surf.get_clip()
        surf.set_clip(r)

        # Terrain picture (zooms and pans with the camera) or a plain grid
        drew_terrain = False
        if sprites is not None and sprites.terrain is not None:
            left, bottom, right, top = cam.visible_world()
            region = (max(0.0, left / W), max(0.0, 1 - top / H),
                      min(1.0, right / W), min(1.0, 1 - bottom / H))
            view = sprites.terrain_view(r.size, region)
            if view is not None:
                surf.blit(view, r.topleft)
                drew_terrain = True
        if not drew_terrain:
            for i in range(1, 10):
                gx = int(self._world_to_screen(W * i / 10, 0)[0])
                gy = int(self._world_to_screen(0, H * i / 10)[1])
                pygame.draw.line(surf, GRID_COLOR, (gx, r.top), (gx, r.bottom), 1)
                pygame.draw.line(surf, GRID_COLOR, (r.left, gy), (r.right, gy), 1)

        px_scale = cam.zoom ** 0.65      # sprites grow a little when you zoom in

        # Soil nutrient map (press M)
        if self.show_soil and self.snap.fertility:
            soil = self._soil_surf
            soil.fill((0, 0, 0, 0))
            cell = self.snap.fertility_cell
            for cx_, cy_, rich in self.snap.fertility:
                x0, y0 = self._world_to_screen(cx_ * cell, (cy_ + 1) * cell)
                x1, y1 = self._world_to_screen((cx_ + 1) * cell, cy_ * cell)
                pygame.draw.rect(
                    soil, (*SOIL_COLOR, int(22 + 120 * rich)),
                    pygame.Rect(int(x0 - r.x), int(y0 - r.y), int(x1 - x0) + 1, int(y1 - y0) + 1))
            surf.blit(soil, r.topleft)

        # Organic remains
        if self.show_remains:
            for rx, ry, amount in self.snap.remains_patches:
                sx, sy = self._world_to_screen(rx, ry)
                rad = int(min(22, 4 + 1.4 * (amount ** 0.5)) * px_scale)
                if not r.inflate(60, 60).collidepoint(sx, sy):
                    continue
                spr = sprites.get("remains", rad * 2) if sprites else None
                if spr:
                    surf.blit(spr, spr.get_rect(center=(int(sx), int(sy))))
                else:
                    s = pygame.Surface((rad * 2, rad * 2), pygame.SRCALPHA)
                    pygame.draw.circle(s, (*REMAINS_COLOR, 75), (rad, rad), rad)
                    pygame.draw.circle(s, (*REMAINS_COLOR, 140), (rad, rad), rad, 1)
                    surf.blit(s, (int(sx - rad), int(sy - rad)))

        # Organisms (producers first, Skyrenders on top)
        t = self._turn_progress
        ordered = sorted(
            self.snap.organisms,
            key=lambda o: 0 if o.kind == "Producer" else (2 if o.species == "Skyrender" else 1)
        )
        selected_pos = None
        selected_view = None
        highlight_points = []
        hover = None
        if self.map_rect.collidepoint(self.mouse_pos) and self._drag is None and self.spawn_species is None:
            hover = self._nearest_view(self.mouse_pos)

        # the selected organism is looked up directly so it survives being off screen
        if self.selected is not None:
            for o in self.snap.organisms:
                if o.ref is self.selected:
                    selected_view = o
                    break

        view_rect = r.inflate(140, 140)

        for o in ordered:
            oid = id(o.ref)
            info = self._interp.get(oid)
            if info:
                px, py, cx, cy, angle, _ = info
                wx = px + (cx - px) * t
                wy = py + (cy - py) * t
                moved = ((cx - px) ** 2 + (cy - py) ** 2) > 0.0025
            else:
                wx, wy, angle, moved = o.x, o.y, 0.0, False

            sx, sy = self._world_to_screen(wx, wy)
            is_selected = o.ref is self.selected
            if is_selected:
                selected_pos = (int(sx), int(sy))
            if not is_selected and not view_rect.collidepoint(sx, sy):
                continue

            # Procedural walk hop, flying hover, and plant sway
            phase = (oid % 997) * 0.1
            x_off = 0.0
            y_off = 0.0
            shadow_drop = 0.0
            if o.species == "Skyrender":
                y_off = -10.0 + math.sin(self._anim_time * 5.0 + phase) * 4.0
                shadow_drop = -y_off + 6.0
            elif o.kind in ("Producer", "Decomposer"):
                x_off = math.sin(self._anim_time * 1.8 + phase) * 1.2
            elif moved and not self.paused:
                y_off = -abs(math.sin(self._anim_time * 11.0 + phase)) * 5.0
            else:
                y_off = math.sin(self._anim_time * 2.4 + phase) * 1.0

            draw_x = int(sx + x_off)
            draw_y = int(sy + y_off)

            # Record motion trails for active chases & fleeing
            act = getattr(o.ref, "last_action", None)
            act_kind = act.kind if act is not None else None
            if act_kind in ("hunt", "flee") and moved and not self.paused:
                trail = self._trails.setdefault(oid, deque(maxlen=8))
                tcol = (255, 80, 80) if act_kind == "hunt" else (255, 195, 60)
                if not trail or math.hypot(wx - trail[-1][0], wy - trail[-1][1]) > 0.25:
                    trail.append((wx, wy, tcol))
            elif oid in self._trails:
                self._trails[oid].popleft()
                if not self._trails[oid]:
                    del self._trails[oid]

            color = SPECIES_COLOR.get(o.species, (255, 255, 255))
            growth = self._growth(o)
            base = {"Producer": 5, "Consumer": 7, "Predator": 10,
                    "Decomposer": 6, "Scavenger": 7}.get(o.kind, 7)
            size = int(base * (0.7 + 0.6 * o.fullness) * growth * px_scale)

            spr_base = SPRITE_SIZE.get(o.species, 36)
            spr_size = spr_base * (0.8 + 0.35 * o.fullness) * growth * px_scale
            spr_angle = angle if o.kind not in ("Producer", "Decomposer") else 0.0
            spr = sprites.get(o.species, spr_size, spr_angle) if sprites else None
            half_h = size
            if spr:
                sw, sh = spr.get_size()
                half_h = sh // 2
                shadow_w = max(8, int(sw * (0.7 if o.species == "Skyrender" else 0.9)))
                shadow_h = max(6, sh // 3)
                shadow = pygame.Surface((shadow_w, shadow_h), pygame.SRCALPHA)
                pygame.draw.ellipse(shadow, (0, 0, 0, 75), shadow.get_rect())
                surf.blit(shadow, shadow.get_rect(center=(int(sx), int(sy + sh * 0.35 + shadow_drop))))
                surf.blit(spr, spr.get_rect(center=(draw_x, draw_y)))
            else:
                self._draw_procedural_organism(surf, draw_x, draw_y, size, angle, o.kind, color)

            if o.species in self.highlight:
                highlight_points.append((draw_x, draw_y, max(14, int((spr.get_width() if spr else size * 2) * 0.55)), color))

            # Tiny hunger bar: shown for hungry animals, the selected one, and the hovered one
            if o.kind != "Producer" and (o.fullness < 0.45 or is_selected or o is hover):
                bar_w = max(20, int((spr.get_width() if spr else size * 2) * 0.45))
                bx = draw_x - bar_w // 2
                by = draw_y - half_h - 8
                bar_col = (255, 82, 82) if o.fullness < 0.25 else ((255, 167, 38) if o.fullness < 0.45 else (92, 214, 92))
                pygame.draw.rect(surf, (10, 14, 18), (bx - 1, by - 1, bar_w + 2, 6), border_radius=2)
                pygame.draw.rect(surf, bar_col, (bx, by, max(1, int(bar_w * o.fullness)), 4), border_radius=2)

            # Quick "!" alert above fleeing prey
            if act_kind == "flee":
                alert = font_md.render("!", True, (255, 195, 60))
                surf.blit(alert, (draw_x - alert.get_width() // 2, draw_y - half_h - 22))

        # Bodies fading away after a death
        if sprites:
            for gx, gy, species, gangle, gage, gdur in self._ghosts:
                prog = min(1.0, gage / gdur)
                sx, sy = self._world_to_screen(gx, gy)
                if not view_rect.collidepoint(sx, sy):
                    continue
                size_g = SPRITE_SIZE.get(species, 36) * (1.0 - 0.2 * prog) * px_scale
                body = sprites.get(species, size_g, gangle if species not in ("Verdant", "Crystalis", "Mycel") else 0.0)
                if body:
                    ghost = body.copy()
                    ghost.set_alpha(int(255 * (1.0 - prog) * 0.8))
                    surf.blit(ghost, ghost.get_rect(center=(int(sx), int(sy + prog * 8))))

        # Trails, slashes, ambient weather particles & action rings
        if self._fx_surf is not None:
            self._fx_surf.fill((0, 0, 0, 0))

            # Chase / flee motion trails
            for trail in self._trails.values():
                n = len(trail)
                if n >= 2:
                    for i in range(1, n):
                        x1, y1, col = trail[i - 1]
                        x2, y2, _ = trail[i]
                        p1 = self._world_to_screen(x1, y1)
                        p2 = self._world_to_screen(x2, y2)
                        alpha = int((i / n) * 150)
                        pygame.draw.line(
                            self._fx_surf, (*col, alpha),
                            (int(p1[0] - r.x), int(p1[1] - r.y)),
                            (int(p2[0] - r.x), int(p2[1] - r.y)),
                            max(1, i // 2)
                        )

            # Predation claw-slash X-flash
            for wx, wy, age, dur in self._slashes:
                prog = min(1.0, age / dur)
                alpha = int((1.0 - prog) * 240)
                ex, ey = self._world_to_screen(wx, wy)
                cx, cy = int(ex - r.x), int(ey - r.y)
                s = int(10 + prog * 14)
                pygame.draw.line(self._fx_surf, (255, 90, 90, alpha), (cx - s, cy - s), (cx + s, cy + s), 3)
                pygame.draw.line(self._fx_surf, (255, 220, 220, alpha), (cx + s, cy - s), (cx - s, cy + s), 2)

            # Ambient particles
            for nx, ny, _, _, psize, age, life, kind in self._particles:
                fade = math.sin((age / life) * math.pi)
                px = int(nx * r.w)
                py = int(ny * r.h)
                if kind == "sun":
                    pygame.draw.circle(self._fx_surf, (255, 232, 130, int(130 * fade)), (px, py), psize)
                elif kind == "rad":
                    pygame.draw.circle(self._fx_surf, (90, 235, 255, int(140 * fade)), (px, py), psize)
                elif kind == "plague":
                    pygame.draw.circle(self._fx_surf, (195, 100, 255, int(150 * fade)), (px, py), psize)
                elif kind == "wind":
                    pygame.draw.line(
                        self._fx_surf, (230, 195, 130, int(120 * fade)),
                        (px, py), (px + psize, py + 3), 2
                    )

            # Showcase / lab highlight: pulsing rings around a species
            if highlight_points:
                pulse = 0.5 + 0.5 * math.sin(self._anim_time * 4.0)
                for hx, hy, hr, hcol in highlight_points:
                    rr = int(hr + 3 + 5 * pulse)
                    pygame.draw.circle(self._fx_surf, (*hcol, int(120 + 100 * pulse)),
                                       (hx - r.x, hy - r.y), rr, 3)

            # Action rings
            for wx, wy, color, age, dur, max_r in self._effects:
                prog = min(1.0, age / dur)
                rad = max(2, int(4 + prog * max_r * px_scale ** 0.5))
                alpha = int((1.0 - prog) * 220)
                ex, ey = self._world_to_screen(wx, wy)
                pygame.draw.circle(self._fx_surf, (*color, alpha), (int(ex - r.x), int(ey - r.y)), rad, 2)

            surf.blit(self._fx_surf, r.topleft)

        # Dynamic lighting, season tint, drought haze, plague flash & radiation atmosphere overlay
        light = self.snap.light
        rad = self.snap.radiation
        dark_alpha = int(max(0.0, min(0.68, (1.0 - light) * 0.72)) * 255)
        if dark_alpha > 4:
            shade = pygame.Surface(r.size, pygame.SRCALPHA)
            shade.fill((6, 10, 18, dark_alpha))
            surf.blit(shade, r.topleft)

        tint = self._season_tint()
        if tint is not None and tint[3] > 2:
            wash = pygame.Surface(r.size, pygame.SRCALPHA)
            wash.fill(tint)
            surf.blit(wash, r.topleft)

        if "drought" in self._active_disasters():
            haze = pygame.Surface(r.size, pygame.SRCALPHA)
            haze.fill((160, 100, 35, 34))
            surf.blit(haze, r.topleft)

        if self._plague_fx_timer > 0:
            phaze = pygame.Surface(r.size, pygame.SRCALPHA)
            phaze.fill((120, 35, 165, int(35 * min(1.0, self._plague_fx_timer))))
            surf.blit(phaze, r.topleft)

        if rad < 0.75:
            tint_r = pygame.Surface(r.size, pygame.SRCALPHA)
            tint_r.fill((40, 20, 60, int((0.75 - rad) * 60)))
            surf.blit(tint_r, r.topleft)

        # Selected organism: perception radius, AI target line & Inspector HUD
        if selected_view is not None:
            if selected_pos is not None:
                profile = BEHAVIOR.get(selected_view.species)
                if profile and profile.get("perception", 0) > 0:
                    perc_px = int(perception_of(selected_view.ref) * cam.pixels_per_unit(r))
                    if 4 < perc_px < 3000:
                        side = min(perc_px, 1500)
                        psurf = pygame.Surface((side * 2 + 2, side * 2 + 2), pygame.SRCALPHA)
                        pygame.draw.circle(psurf, (77, 208, 225, 22), (side + 1, side + 1), side)
                        pygame.draw.circle(psurf, (77, 208, 225, 95), (side + 1, side + 1), side, 1)
                        surf.blit(psurf, (selected_pos[0] - side - 1, selected_pos[1] - side - 1))

                action = getattr(selected_view.ref, "last_action", None)
                if action is not None:
                    tx = ty = None
                    if action.target is not None and hasattr(action.target, "x"):
                        tx, ty = action.target.x, action.target.y
                    elif action.x is not None and action.y is not None:
                        tx, ty = action.x, action.y
                    if tx is not None and ty is not None:
                        tsx, tsy = self._world_to_screen(tx, ty)
                        lcol = ACTION_COLORS.get(action.kind, ACCENT)
                        pygame.draw.line(surf, lcol, selected_pos, (int(tsx), int(tsy)), 2)
                        pygame.draw.circle(surf, lcol, (int(tsx), int(tsy)), 5, 2)

                pygame.draw.circle(surf, (255, 255, 255), selected_pos, 22, 2)

            action = getattr(selected_view.ref, "last_action", None)
            action_label = "photosynthesize" if selected_view.kind == "Producer" else "idle"
            if action is not None:
                action_label = action.kind
            lines = [
                f"{selected_view.name}  ({selected_view.species})",
                f"Type: {selected_view.kind}   Age: {selected_view.age}/{selected_view.lifespan}",
                f"Energy: {selected_view.energy:.1f}  ({int(selected_view.fullness * 100)}%)",
                f"Action: {action_label}",
            ]
            if selected_view.species in self.evolving:
                lines.append(f"Genes: speed x{selected_view.speed_gene:.2f}  senses x{selected_view.sense_gene:.2f}")
            box = pygame.Rect(r.x + 12, r.y + 12, 290, 12 + 18 * len(lines))
            hud = pygame.Surface(box.size, pygame.SRCALPHA)
            hud.fill((12, 16, 22, 220))
            surf.blit(hud, box.topleft)
            pygame.draw.rect(surf, ACCENT, box, 1, border_radius=5)
            for i, line in enumerate(lines):
                surf.blit(font_sm.render(line, True, TEXT if i == 0 else MUTED),
                          (box.x + 10, box.y + 8 + i * 18))
        elif self.selected is not None:
            self.selected = None

        # Hover tooltip for any organism under the mouse
        if hover is not None and (selected_view is None or hover.ref is not selected_view.ref):
            self.tooltip = (
                f"{hover.name}  ({hover.kind})\n"
                f"energy {int(hover.fullness * 100)}%   age {hover.age}/{hover.lifespan}",
                SPECIES_COLOR.get(hover.species, TEXT))

        # Spawn Mode banner at bottom-left of map
        if self.spawn_species is not None:
            sp_col = SPECIES_COLOR.get(self.spawn_species, ACCENT)
            msg = f"SPAWN BRUSH: {self.spawn_species}  (Click map to spawn  |  Right-click / Esc to exit)"
            st = font_sm.render(msg, True, TEXT)
            lift = 34 if self.clean else 0
            srect = pygame.Rect(r.x + 12, r.bottom - 34 - lift, st.get_width() + 18, 24)
            hud = pygame.Surface(srect.size, pygame.SRCALPHA)
            hud.fill((12, 16, 22, 220))
            surf.blit(hud, srect.topleft)
            pygame.draw.rect(surf, sp_col, srect, 2, border_radius=4)
            surf.blit(st, (srect.x + 9, srect.y + 5))

        # Top-right map badge (Turn, season, zoom, active stress and experiments)
        badge_txt = f"Turn {self.snap.turn}   |   Alive {self.snap.total_population}/{self.snap.population_limit}"
        season = edu.season_name(self.world)
        if season:
            badge_txt += f"   |   {season}"
        if cam.zoom > 1.05:
            badge_txt += f"   |   x{cam.zoom:.1f}"
        if self.stress and self.stress.active:
            active_names = ", ".join(e.name.upper() for e in self.stress.active)
            badge_txt += f"   |   ACTIVE: {active_names}"
        if self.lab.any_active:
            badge_txt += "   |   LAB: " + ", ".join(sorted(self.lab.active)).replace("_", " ")
        bt = font_md.render(badge_txt, True, TEXT)
        badge_rect = pygame.Rect(r.right - bt.get_width() - 22, r.y + 10, bt.get_width() + 14, 26)
        hud = pygame.Surface(badge_rect.size, pygame.SRCALPHA)
        hud.fill((12, 16, 22, 200))
        surf.blit(hud, badge_rect.topleft)
        pygame.draw.rect(surf, PANEL_BORDER, badge_rect, 1, border_radius=4)
        surf.blit(bt, (badge_rect.x + 7, badge_rect.y + 5))

        self._draw_toasts(surf, r, badge_rect)
        self._draw_caption(surf, r)
        if self.clean:
            self._draw_clean_counts(surf, r)
        if self.recording:
            pygame.draw.circle(surf, (255, 60, 60), (r.right - 24, r.bottom - 22), 7)
            surf.blit(font_sm.render("REC", True, TEXT), (r.right - 80, r.bottom - 30))

        surf.set_clip(prev_clip)
        pygame.draw.rect(surf, PANEL_BORDER, r, 1)

    # ---------------------------------------------- map overlays (text boxes)

    def _draw_toasts(self, surf, r, badge_rect):
        f = self.fonts
        y = badge_rect.bottom + 8
        width = 300
        for title, body, colour, age, dur in self._toasts:
            fade = 1.0 if age < dur - 1.0 else max(0.0, dur - age)
            lines = panels.wrap_text(f["sm"], body, width - 20)[:4]
            h = 30 + 14 * len(lines)
            box = pygame.Rect(r.right - width - 12, y, width, h)
            bg = pygame.Surface(box.size, pygame.SRCALPHA)
            bg.fill((12, 16, 22, int(225 * fade)))
            surf.blit(bg, box.topleft)
            pygame.draw.rect(surf, colour, box, 1, border_radius=5)
            pygame.draw.rect(surf, colour, (box.x, box.y, 4, box.h), border_radius=2)
            surf.blit(f["sm"].render(title, True, colour), (box.x + 12, box.y + 6))
            for i, line in enumerate(lines):
                surf.blit(f["sm"].render(line, True, TEXT), (box.x + 12, box.y + 24 + i * 14))
            y += h + 6

    def _draw_caption(self, surf, r):
        cap = self.caption
        if not cap:
            return
        f = self.fonts
        width = min(r.w - 60, 720)
        lines = panels.wrap_text(f["body"], cap["text"], width - 40)[:4]

        # Speaker notes: rendered below the caption text when toggled visible
        note_lines = []
        is_step = bool(cap.get("step") and self.showcase_on)
        note_text = cap.get("speaker_note") or ""
        if not note_text and is_step and self.director.current_step:
            note_text = self.director.current_step.speaker_note or ""

        if self.director.show_speaker_notes and is_step and note_text:
            note_lines = panels.wrap_text(f["sm"], f"SPEAKER NOTE: {note_text}", width - 50)[:3]

        h = 44 + 20 * len(lines)
        if note_lines:
            h += 12 + 16 * len(note_lines)
        if is_step:
            h += 38  # space for presenter control bar and progress line

        box = pygame.Rect(r.centerx - width // 2, r.bottom - h - 14, width, h)
        age, dur = cap["age"], cap["dur"]
        fade = min(1.0, age / 0.35)
        if dur is not None and age > dur - 1.0:
            fade = max(0.0, dur - age)

        bg = pygame.Surface(box.size, pygame.SRCALPHA)
        bg.fill((10, 14, 20, int(230 * fade)))
        surf.blit(bg, box.topleft)
        pygame.draw.rect(surf, ACCENT, box, 1, border_radius=8)

        # Step counter badge (e.g. "Step 3 / 13")
        if is_step:
            schedule = edu.showcase_schedule()
            step_label = f"Step {self.director.index + 1} of {len(schedule)}"
            sl = f["sm"].render(step_label, True, (255, 215, 100))
            surf.blit(sl, (box.right - sl.get_width() - 16, box.y + 12))

        title = f["lg"].render(cap["title"], True, ACCENT)
        title.set_alpha(int(255 * fade))
        surf.blit(title, (box.x + 18, box.y + 10))

        for i, line in enumerate(lines):
            img = f["body"].render(line, True, TEXT)
            img.set_alpha(int(255 * fade))
            surf.blit(img, (box.x + 18, box.y + 36 + i * 20))

        content_y = box.y + 36 + len(lines) * 20

        # Speaker notes box
        if note_lines:
            note_box = pygame.Rect(box.x + 14, content_y + 4, box.w - 28, 8 + len(note_lines) * 16)
            note_bg = pygame.Surface(note_box.size, pygame.SRCALPHA)
            note_bg.fill((18, 34, 28, int(220 * fade)))
            surf.blit(note_bg, note_box.topleft)
            pygame.draw.rect(surf, (80, 190, 140), note_box, 1, border_radius=4)
            for i, line in enumerate(note_lines):
                col = (130, 240, 180) if i == 0 else (200, 235, 215)
                note_img = f["sm"].render(line, True, col)
                note_img.set_alpha(int(240 * fade))
                surf.blit(note_img, (note_box.x + 8, note_box.y + 4 + i * 16))
            content_y = note_box.bottom

        # Presenter control bar
        if is_step:
            btn_y = box.bottom - 32
            bx = box.x + 14

            def draw_p_btn(label, target_fn, active=False, width=70):
                nonlocal bx
                b_rect = pygame.Rect(bx, btn_y, width, 22)
                hovered = b_rect.collidepoint(self.mouse_pos)
                if active:
                    b_color = (45, 80, 110) if not hovered else (55, 95, 130)
                    border_c = ACCENT
                    t_col = (255, 255, 255)
                else:
                    b_color = (25, 32, 42) if not hovered else (38, 48, 62)
                    border_c = PANEL_BORDER
                    t_col = TEXT if hovered else MUTED

                pygame.draw.rect(surf, b_color, b_rect, border_radius=4)
                pygame.draw.rect(surf, border_c, b_rect, 1, border_radius=4)
                t_surf = f["sm"].render(label, True, t_col)
                surf.blit(t_surf, t_surf.get_rect(center=b_rect.center))
                self.add_target(b_rect, target_fn)
                bx += width + 6

            draw_p_btn("< Prev", self.prev_showcase_step, width=54)
            draw_p_btn("Next >", self.skip_showcase_step, width=54)

            pause_lbl = "Pause: ON" if self.director.pause_on_caption else "Pause: OFF"
            draw_p_btn(pause_lbl, self.toggle_pause_on_caption, active=self.director.pause_on_caption, width=82)

            notes_lbl = "Notes: ON" if self.director.show_speaker_notes else "Notes: OFF"
            draw_p_btn(notes_lbl, self.toggle_speaker_notes, active=self.director.show_speaker_notes, width=82)

            draw_p_btn("Steps Menu", self.toggle_step_menu, active=self.show_step_menu, width=82)

            # Paused at caption indicator
            if self.director.pause_on_caption and self.paused:
                pulse = 0.5 + 0.5 * math.sin(self._anim_time * 6.0)
                p_col = (int(255 * (0.8 + 0.2 * pulse)), int(210 * (0.8 + 0.2 * pulse)), 70)
                pi = f["sm"].render("PAUSED (Space to play, PgDn for next)", True, p_col)
                surf.blit(pi, (box.right - pi.get_width() - 14, btn_y + 4))

            # Progress bar at bottom
            total = edu.showcase_length()
            done = min(1.0, (self.world.turn - self._showcase_t0) / max(1, total))
            bar = pygame.Rect(box.x + 14, box.bottom - 5, box.w - 28, 3)
            pygame.draw.rect(surf, (35, 42, 54), bar, border_radius=2)
            pygame.draw.rect(surf, ACCENT, (bar.x, bar.y, int(bar.w * done), bar.h), border_radius=2)

    def _draw_step_menu(self, surf):
        """Overlay listing all showcase steps, click one to jump."""
        if not self.show_step_menu or not self.showcase_on:
            return
        f = self.fonts
        schedule = edu.showcase_schedule()
        num_steps = len(schedule)
        line_h = 28
        pad = 20
        w = min(560, self.width - 60)
        h = 56 + num_steps * line_h + pad
        box = pygame.Rect(0, 0, w, h)
        box.center = self.map_rect.center

        bg = pygame.Surface(box.size, pygame.SRCALPHA)
        bg.fill((10, 14, 20, 245))
        surf.blit(bg, box.topleft)
        pygame.draw.rect(surf, ACCENT, box, 2, border_radius=8)

        # Header
        surf.blit(f["lg"].render("Story Steps — Jump to Chapter", True, ACCENT),
                  (box.x + 18, box.y + 10))
        surf.blit(f["sm"].render("Click a step or press [1-9]. Press G or Esc to close.", True, MUTED),
                  (box.x + 18, box.y + 32))

        # Close button [X]
        close_rect = pygame.Rect(box.right - 34, box.y + 10, 24, 24)
        c_hover = close_rect.collidepoint(self.mouse_pos)
        pygame.draw.rect(surf, (45, 55, 68) if c_hover else (25, 32, 42), close_rect, border_radius=4)
        pygame.draw.rect(surf, PANEL_BORDER, close_rect, 1, border_radius=4)
        x_lbl = f["sm"].render("X", True, TEXT)
        surf.blit(x_lbl, x_lbl.get_rect(center=close_rect.center))
        self.add_target(close_rect, self.toggle_step_menu)

        for i, (t_offset, step) in enumerate(schedule):
            y = box.y + 54 + i * line_h
            is_current = (i == self.director.index)
            row_rect = pygame.Rect(box.x + 10, y, w - 20, line_h - 2)

            hovered = row_rect.collidepoint(self.mouse_pos)
            if is_current:
                row_bg = (35, 60, 85) if not hovered else (45, 75, 105)
                row_border = ACCENT
                marker = "> "
            elif hovered:
                row_bg = (30, 40, 52)
                row_border = PANEL_BORDER
                marker = "  "
            else:
                row_bg = (18, 24, 32)
                row_border = (28, 36, 48)
                marker = "  "

            pygame.draw.rect(surf, row_bg, row_rect, border_radius=4)
            pygame.draw.rect(surf, row_border, row_rect, 1, border_radius=4)

            label_color = ACCENT if is_current else TEXT
            key_hint = f"[{i + 1}] " if i < 9 else "    "
            idx_text = f["sm"].render(f"{marker}{key_hint}{i + 1:>2}.", True, MUTED)
            title_text = f["md"].render(step["title"], True, label_color)
            turn_text = f["sm"].render(f"Turn ~{t_offset + 1}", True, MUTED)

            surf.blit(idx_text, (row_rect.x + 8, row_rect.y + 6))
            surf.blit(title_text, (row_rect.x + 72, row_rect.y + 5))
            surf.blit(turn_text, (row_rect.right - turn_text.get_width() - 12, row_rect.y + 6))

            if is_current:
                badge = f["sm"].render("ACTIVE", True, (255, 220, 100))
                surf.blit(badge, (row_rect.right - turn_text.get_width() - badge.get_width() - 20, row_rect.y + 6))

            # Register click target to jump
            self.add_target(row_rect, lambda idx=i: self.jump_showcase_step(idx))

    def _draw_clean_counts(self, surf, r):
        """Compact species counters for the sidebar-free projector view."""
        f = self.fonts
        x = r.x + 12
        y = r.bottom - 34
        items = [(n, self.snap.counts.get(n, 0)) for n in SPECIES]
        widths = [f["sm"].size(f"{n} {c}")[0] + 26 for n, c in items]
        pill = pygame.Rect(x, y, sum(widths) + 12, 26)
        bg = pygame.Surface(pill.size, pygame.SRCALPHA)
        bg.fill((12, 16, 22, 200))
        surf.blit(bg, pill.topleft)
        pygame.draw.rect(surf, PANEL_BORDER, pill, 1, border_radius=5)
        cx = pill.x + 10
        for (name, count), w in zip(items, widths):
            col = SPECIES_COLOR.get(name, TEXT)
            pygame.draw.circle(surf, col, (cx + 5, pill.centery), 5)
            surf.blit(f["sm"].render(f"{name} {count}", True, TEXT), (cx + 14, pill.y + 6))
            cx += w

    @staticmethod
    def _draw_procedural_organism(surf, x, y, size, angle_deg, kind, color):
        if kind == "Producer":
            glow = pygame.Surface((size * 4, size * 4), pygame.SRCALPHA)
            pygame.draw.circle(glow, (*color, 45), (size * 2, size * 2), size * 2)
            pygame.draw.circle(glow, (*color, 210), (size * 2, size * 2), size)
            surf.blit(glow, (x - size * 2, y - size * 2))
        elif kind == "Predator":
            rad = math.radians(angle_deg)
            tip = (x + math.cos(rad) * size * 1.4, y - math.sin(rad) * size * 1.4)
            left = (x + math.cos(rad + 2.4) * size, y - math.sin(rad + 2.4) * size)
            right = (x + math.cos(rad - 2.4) * size, y - math.sin(rad - 2.4) * size)
            pygame.draw.polygon(surf, color, [tip, left, right])
            pygame.draw.polygon(surf, (255, 255, 255), [tip, left, right], 1)
        elif kind == "Decomposer":
            pts = [(x, y - size), (x + size, y), (x, y + size), (x - size, y)]
            pygame.draw.polygon(surf, color, pts)
        else:
            pygame.draw.circle(surf, color, (x, y), size)
            pygame.draw.circle(surf, (20, 24, 30), (x, y), size, 1)

    # ----------------------------------------------------------- sidebar

    def _draw_sidebar(self, surf, font_sm, font_md, font_lg, mouse_pos):
        if self.clean:
            return
        pygame.draw.rect(surf, PANEL, self.side_rect, border_radius=6)
        pygame.draw.rect(surf, PANEL_BORDER, self.side_rect, 1, border_radius=6)

        sx = self.side_rect.x + 14
        sw = self.side_rect.w - 28

        title = font_lg.render("GAIA  //  Live Ecosystem", True, TEXT)
        surf.blit(title, (sx, self.side_rect.y + 8))

        if not self.sl_light.dragging:
            self.sl_light.value = self.snap.light
        if not self.sl_rad.dragging:
            self.sl_rad.value = self.snap.radiation

        for btn in self.buttons:
            btn.draw(surf, font_sm, mouse_pos)
        for sl in self.sliders:
            sl.draw(surf, font_sm)

        # Tab bar
        y = self.panels_start_y
        tab_w = sw // len(TABS)
        for i, name in enumerate(TABS):
            rect = pygame.Rect(sx + i * tab_w, y, tab_w - 4, 24)
            active = (name == self.tab)
            hovered = rect.collidepoint(mouse_pos)
            color = BTN_ACTIVE if active else (BTN_HOVER if hovered else BTN_BG)
            pygame.draw.rect(surf, color, rect, border_radius=5)
            pygame.draw.rect(surf, ACCENT if active else PANEL_BORDER, rect, 1, border_radius=5)
            label = font_sm.render(name, True, TEXT if active else MUTED)
            surf.blit(label, label.get_rect(center=rect.center))
            self.add_target(rect, lambda n=name: setattr(self, "tab", n))

        content = pygame.Rect(sx, y + 32, sw, self.side_rect.bottom - (y + 32) - 10)
        self.panel_bottom = content.bottom
        prev_clip = surf.get_clip()
        surf.set_clip(content.inflate(8, 0).clip(self.side_rect))

        if self.tab == "Web":
            panels.draw_web(self, surf, content)
        elif self.tab == "Energy":
            panels.draw_energy(self, surf, content)
        elif self.tab == "Dynamics":
            panels.draw_dynamics(self, surf, content)
        elif self.tab == "Lab":
            panels.draw_lab(self, surf, content)
        else:
            panels.draw_overview(self, surf, content)

        surf.set_clip(prev_clip)

    def _draw_tooltip(self, surf):
        if not self.tooltip:
            return
        text, colour = self.tooltip
        if not text:
            return
        f = self.fonts
        lines = []
        for part in text.split("\n"):
            lines.extend(panels.wrap_text(f["sm"], part, 250))
        w = max(f["sm"].size(line)[0] for line in lines) + 16
        h = 10 + 15 * len(lines)
        mx, my = self.mouse_pos
        x = min(mx + 16, surf.get_width() - w - 6)
        y = min(my + 14, surf.get_height() - h - 6)
        box = pygame.Rect(max(4, x), max(4, y), w, h)
        bg = pygame.Surface(box.size, pygame.SRCALPHA)
        bg.fill((10, 14, 20, 235))
        surf.blit(bg, box.topleft)
        pygame.draw.rect(surf, colour, box, 1, border_radius=4)
        for i, line in enumerate(lines):
            surf.blit(f["sm"].render(line, True, TEXT if i else colour), (box.x + 8, box.y + 6 + i * 15))

    def _draw_help(self, surf):
        if not self.show_help:
            return
        f = self.fonts
        rows = [
            ("Mouse", ""),
            ("Left click", "select an animal / plant (or spawn with the brush)"),
            ("Wheel, drag", "zoom the map, pan when zoomed"),
            ("Right click", "leave spawn mode"),
            ("Keys", ""),
            ("Space / Right", "play-pause / step one turn"),
            ("Up / Down", "change speed"),
            ("S", "start / stop Showcase story"),
            ("PgDn / PgUp / [ ]", "next / previous showcase step"),
            ("B", "pause at every caption until you press a key"),
            ("N", "toggle hidden speaker notes"),
            ("G / J", "open / close step jump menu (jump to any part)"),
            ("1-9", "jump to step 1-9 (in step menu)"),
            ("Tab, 1-5", "switch sidebar tab"),
            ("M", "soil nutrient map"),
            ("F / Z / + -", "follow selected / reset camera / zoom"),
            ("H", "clean projector view"),
            ("P / V", "screenshot / record frames"),
            ("F11", "fullscreen"),
            ("C, Esc", "clear selection"),
        ]
        w, h = 560, 52 + 21 * len(rows)
        box = pygame.Rect(0, 0, w, h)
        box.center = self.map_rect.center
        bg = pygame.Surface(box.size, pygame.SRCALPHA)
        bg.fill((10, 14, 20, 238))
        surf.blit(bg, box.topleft)
        pygame.draw.rect(surf, ACCENT, box, 1, border_radius=8)
        surf.blit(f["lg"].render("GAIA controls  (F1 to close)", True, ACCENT), (box.x + 18, box.y + 12))
        y = box.y + 46
        for key, text in rows:
            if not text:
                surf.blit(f["md"].render(key, True, TEXT), (box.x + 18, y))
            else:
                surf.blit(f["sm"].render(key, True, ACCENT), (box.x + 30, y + 1))
                surf.blit(f["sm"].render(text, True, MUTED), (box.x + 190, y + 1))
            y += 21

    # -------------------------------------------------------------- loop

    def _tick_visuals(self, dt):
        """Advance every purely visual timer by `dt` real seconds."""
        self._anim_time += dt
        for fx in self._effects:
            fx[3] += dt
        self._effects = [fx for fx in self._effects if fx[3] < fx[4]]
        for sl in self._slashes:
            sl[2] += dt
        self._slashes = [sl for sl in self._slashes if sl[2] < sl[3]]
        for g in self._ghosts:
            g[4] += dt
        self._ghosts = [g for g in self._ghosts if g[4] < g[5]]
        for toast in self._toasts:
            toast[3] += dt
        self._toasts = [t for t in self._toasts if t[3] < t[4]]
        if self.caption is not None:
            self.caption["age"] += dt
            if self.caption["dur"] is not None and self.caption["age"] > self.caption["dur"]:
                self.caption = None
        for key in list(self.edge_pulse):
            self.edge_pulse[key] *= pow(0.12, dt)
            if self.edge_pulse[key] < 0.02:
                del self.edge_pulse[key]
        self._update_particles(dt)

    def _follow_position(self):
        ref = self.camera.follow
        if ref is None:
            return None
        info = self._interp.get(id(ref))
        if info is None or getattr(ref, "status", "Alive") != "Alive":
            self.camera.follow = None
            return None
        px, py, cx, cy, _, _ = info
        t = self._turn_progress
        return (px + (cx - px) * t, py + (cy - py) * t)

    def _on_key(self, key):
        # Step menu key navigation: 1-9 to jump directly, 0 for step 10, Esc/G/J to close
        if self.show_step_menu:
            if pygame.K_1 <= key <= pygame.K_9:
                self.jump_showcase_step(key - pygame.K_1)
                return
            elif key == pygame.K_0:
                self.jump_showcase_step(9)
                return
            elif key in (pygame.K_ESCAPE, pygame.K_g, pygame.K_j):
                self.show_step_menu = False
                return

        if key in (pygame.K_SPACE, pygame.K_RETURN):
            self._toggle_pause()
        elif key == pygame.K_RIGHT:
            if self.showcase_on:
                self.skip_showcase_step()
            else:
                self._step_one()
        elif key in (pygame.K_PAGEDOWN, pygame.K_k, pygame.K_RIGHTBRACKET):
            self.skip_showcase_step()
        elif key in (pygame.K_PAGEUP, pygame.K_LEFTBRACKET):
            self.prev_showcase_step()
        elif key == pygame.K_LEFT:
            if self.showcase_on:
                self.prev_showcase_step()
        elif key == pygame.K_UP:
            self.speed_index = min(len(SPEEDS) - 1, self.speed_index + 1)
            self.sl_speed.value = self.speed_index
        elif key == pygame.K_DOWN:
            self.speed_index = max(0, self.speed_index - 1)
            self.sl_speed.value = self.speed_index
        elif key == pygame.K_r:
            self._toggle_remains()
        elif key in (pygame.K_c, pygame.K_ESCAPE):
            self.selected = None
            self.spawn_species = None
            self.camera.follow = None
            if self.show_help:
                self.show_help = False
            if self.show_step_menu:
                self.show_step_menu = False
        elif key == pygame.K_s:
            self.toggle_showcase()
        elif key == pygame.K_n:
            self.toggle_speaker_notes()
        elif key == pygame.K_b:
            self.toggle_pause_on_caption()
        elif key in (pygame.K_g, pygame.K_j):
            self.toggle_step_menu()
        elif key == pygame.K_m:
            self.toggle_soil()
        elif key == pygame.K_h:
            self.toggle_clean()
        elif key == pygame.K_p:
            self.screenshot()
        elif key == pygame.K_v:
            self.toggle_record()
        elif key == pygame.K_f:
            self.follow_selected()
        elif key in (pygame.K_z, pygame.K_0):
            self.camera.reset()
        elif key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            self.camera.zoom_at(1.3)
        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.camera.zoom_at(1 / 1.3)
        elif key == pygame.K_TAB:
            self.cycle_tab()
        elif key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5):
            self.tab = TABS[key - pygame.K_1]
        elif key in (pygame.K_F1, pygame.K_SLASH):
            self.toggle_help()
        elif key == pygame.K_F11:
            try:
                pygame.display.toggle_fullscreen()
            except pygame.error:
                pass

    def show(self):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

        pygame.init()
        pygame.display.set_caption("GAIA - Live Ecosystem Simulation")

        info = pygame.display.Info()
        win_w = min(self.width, int(info.current_w * 0.88))
        win_h = min(self.height, int(info.current_h * 0.85))
        screen = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)
        clock = pygame.time.Clock()
        self._screen = screen
        self._win = (win_w, win_h)

        font_sm = pygame.font.SysFont("consolas", 12)
        font_md = pygame.font.SysFont("segoeui", 14, bold=True)
        font_lg = pygame.font.SysFont("segoeui", 18, bold=True)
        font_body = pygame.font.SysFont("segoeui", 15)
        self.fonts = {"sm": font_sm, "md": font_md, "lg": font_lg, "body": font_body}

        sprites = SpriteBank()
        self.sprites = sprites
        terrain_scaled = self._update_layout(win_w, win_h, sprites)

        if self._want_showcase:
            self._want_showcase = False
            self._start_showcase()

        use_wheel_event = hasattr(pygame, "MOUSEWHEEL")
        running = True
        try:
            while running:
                dt = clock.tick(FPS) / 1000.0
                self.mouse_pos = pygame.mouse.get_pos()
                mouse_pos = self.mouse_pos
                self.tooltip = None
                self._tick_visuals(dt)

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                        break
                    elif event.type == pygame.VIDEORESIZE:
                        screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                        self._screen = screen
                        self._win = (event.w, event.h)
                        terrain_scaled = self._update_layout(event.w, event.h, sprites)
                        continue

                    handled = False
                    if not self.clean:
                        for sl in self.sliders:
                            if sl.handle_event(event):
                                handled = True
                        for btn in self.buttons:
                            if btn.handle_event(event):
                                handled = True
                    if handled:
                        continue

                    if use_wheel_event and event.type == pygame.MOUSEWHEEL:
                        self._on_wheel(event.y)

                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        if event.button == 3:
                            self.spawn_species = None
                        elif event.button in (4, 5) and not use_wheel_event:
                            self._on_wheel(1 if event.button == 4 else -1)
                        elif event.button == 1:
                            if self._hit_target(event.pos):
                                pass
                            elif self.map_rect.collidepoint(event.pos):
                                if self.spawn_species is not None:
                                    self._handle_map_click(event.pos)
                                else:
                                    self._drag = {"start": event.pos, "moved": False, "button": 1}
                        elif event.button == 2 and self.map_rect.collidepoint(event.pos):
                            self._drag = {"start": event.pos, "moved": True, "button": 2}

                    elif event.type == pygame.MOUSEBUTTONUP:
                        if self._drag is not None and event.button == self._drag["button"]:
                            if event.button == 1 and not self._drag["moved"]:
                                self._handle_map_click(self._drag["start"])
                            self._drag = None

                    elif event.type == pygame.MOUSEMOTION:
                        if self._drag is not None:
                            if not self._drag["moved"]:
                                sx0, sy0 = self._drag["start"]
                                if math.hypot(event.pos[0] - sx0, event.pos[1] - sy0) > 6:
                                    self._drag["moved"] = True
                            elif self.camera.zoom > 1.01 or self.camera._zoom_goal > 1.01:
                                self.camera.pan_pixels(event.rel[0], event.rel[1], self.map_rect)

                    elif event.type == pygame.KEYDOWN:
                        self._on_key(event.key)

                if not self.paused:
                    if self.speed == "max":
                        deadline = time.perf_counter() + 0.012
                        while time.perf_counter() < deadline:
                            self._advance(1)
                        self._turn_progress = 1.0
                    else:
                        self._acc += dt * self.speed
                        turns = int(self._acc)
                        if turns > 0:
                            self._acc -= turns
                            self._advance(min(turns, 5))
                        self._turn_progress = min(1.0, self._acc)

                self.camera.update(dt, self._follow_position())
                if self._plague_fx_timer > 0:
                    self._plague_fx_timer = max(0.0, self._plague_fx_timer - dt)

                self._targets.clear()
                screen.fill(BG)
                self._draw_map(screen, sprites, terrain_scaled, font_sm, font_md)
                self._draw_sidebar(screen, font_sm, font_md, font_lg, mouse_pos)
                self._draw_help(screen)
                self._draw_step_menu(screen)
                self._draw_tooltip(screen)
                pygame.display.flip()
                self._record_tick(dt, screen)
        except KeyboardInterrupt:
            pass
        finally:
            pygame.quit()
