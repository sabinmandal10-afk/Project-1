"""
GAIA 60 FPS Live Viewer (Pygame).

Features:
  - Smooth 60 FPS position interpolation, left/right facing & procedural walk/hover/sway
  - Hunting visuals: fading chase/flee trails, '!' flee alerts, and predation claw-slashes
  - Ambient weather & disaster particles (sunlight motes, radiation glow, drought wind, plague spores)
  - Click-to-Spawn brush: click any species in the sidebar, then click the map
  - Visual AI cues: birth/kill/plague rings, perception radius, and target lines
  - DPI-aware, auto-fitting, resizable window
  - Drop-in sprite loader (assets/sprites/<species>.png, assets/world/terrain.png)
  - Live Light & Radiation sliders, Auto/Manual seasons, and disaster buttons

Keys:
  Space      : Play / Pause
  Right      : Step 1 turn
  Up / Down  : Increase / Decrease speed
  R          : Toggle organic remains
  C / Esc    : Clear selection / exit Spawn Mode
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
from Interface.snapshot import take_snapshot
from organisms.factory import create_organism
from Simulation.stress import Drought, Plague, RadiationDrop


# ------------------------------------------------------------------ theme

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
SPEEDS = [1, 2, 4, 8, 15, 30, 60, "max"]
FPS = 60


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
    """Loads optional PNGs from assets/sprites/ and assets/world/."""

    def __init__(self, assets_dir="assets"):
        self.assets_dir = assets_dir
        self.raw_sprites = {}
        self.scaled_cache = {}
        self.terrain = None
        self._load()

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

        terrain_path = os.path.join(self.assets_dir, "world", "terrain.png")
        if os.path.isfile(terrain_path):
            try:
                self.terrain = pygame.image.load(terrain_path).convert()
            except pygame.error:
                pass

    def get(self, name, size_px, angle_deg=0.0):
        raw = self.raw_sprites.get(name)
        if raw is None:
            return None
        q_size = max(16, int(round(size_px / 2) * 2))
        facing_left = abs(angle_deg) > 90
        key = (name, q_size, facing_left)
        img = self.scaled_cache.get(key)
        if img is None:
            rw, rh = raw.get_size()
            scale = q_size / max(rw, rh)
            w = max(1, int(rw * scale))
            h = max(1, int(rh * scale))
            scaled = pygame.transform.smoothscale(raw, (w, h))
            img = pygame.transform.flip(scaled, True, False) if facing_left else scaled
            self.scaled_cache[key] = img
        return img


# ----------------------------------------------------------------- viewer

class PygameViewer:

    def __init__(self, sim, recorder=None, detector=None, stress=None,
                 speed_index=2, start_paused=False, width=1400, height=840):
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
        self._species_rects = {}
        self._fx_surf = None
        self._anim_time = 0.0
        self._plague_fx_timer = 0.0
        self._turn_progress = 1.0
        self._acc = 0.0
        self.history = deque(maxlen=400)

        self.map_rect = pygame.Rect(0, 0, 100, 100)
        self.side_rect = pygame.Rect(0, 0, 100, 100)

        self.snap = take_snapshot(self.world)
        self._sync_interp(self.snap, snap_only=True)
        self._remember(self.snap)

    def _update_layout(self, width, height, sprites=None):
        self.width = max(960, width)
        self.height = max(640, height)
        pad = 12
        side_w = max(360, min(430, int(self.width * 0.32)))
        map_w = self.width - side_w - pad * 3
        map_h = self.height - pad * 2
        self.map_rect = pygame.Rect(pad, pad, map_w, map_h)
        self.side_rect = pygame.Rect(self.map_rect.right + pad, pad, side_w, map_h)
        self._fx_surf = pygame.Surface(self.map_rect.size, pygame.SRCALPHA)
        self._build_ui()
        if sprites and sprites.terrain:
            return pygame.transform.smoothscale(sprites.terrain, self.map_rect.size)
        return None

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
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(turns):
                self.sim.advance_turn()
                if self.recorder is None:
                    self._remember(take_snapshot(self.world))
        self.snap = take_snapshot(self.world)
        self._sync_interp(self.snap)
        self._remember(self.snap)

    def _sync_interp(self, snap, snap_only=False):
        old_map = self._interp
        new_map = {}

        for o in snap.organisms:
            oid = id(o.ref)
            old = old_map.get(oid)
            if old is None or snap_only:
                new_map[oid] = (o.x, o.y, o.x, o.y, 0.0, o.ref)
                if old is None and not snap_only:
                    self._add_effect(o.x, o.y, (92, 214, 92), duration=0.45, max_radius=20)
            else:
                px, py = old[2], old[3]
                dx, dy = o.x - px, o.y - py
                angle = math.degrees(math.atan2(dy, dx)) if (dx * dx + dy * dy) > 1e-4 else old[4]
                new_map[oid] = (px, py, o.x, o.y, angle, o.ref)

        if not snap_only:
            for oid, (_, _, cx, cy, _, ref) in old_map.items():
                if oid not in new_map:
                    self._trails.pop(oid, None)
                    cause = getattr(ref, "death_cause", None)
                    if cause == "predation":
                        self._add_effect(cx, cy, (255, 70, 70), duration=0.65, max_radius=34)
                        self._slashes.append([cx, cy, 0.0, 0.35])
                    elif cause == "plague":
                        self._add_effect(cx, cy, (190, 90, 255), duration=0.6, max_radius=28)

        self._interp = new_map

    def _remember(self, snap):
        if self.history and self.history[-1][0] == snap.turn:
            self.history[-1] = (snap.turn, dict(snap.counts))
        else:
            self.history.append((snap.turn, dict(snap.counts)))

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

    # ------------------------------------------------------- coordinates

    def _world_to_screen(self, wx, wy):
        r = self.map_rect
        sx = r.x + (wx / max(1e-6, self.world.width)) * r.w
        sy = r.bottom - (wy / max(1e-6, self.world.height)) * r.h
        return sx, sy

    def _screen_to_world(self, sx, sy):
        r = self.map_rect
        wx = ((sx - r.x) / r.w) * self.world.width
        wy = ((r.bottom - sy) / r.h) * self.world.height
        return wx, wy

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

        reach = max(self.world.width, self.world.height) * 0.04
        best, best_d = None, reach
        for o in self.snap.organisms:
            d = math.hypot(o.x - wx, o.y - wy)
            if d < best_d:
                best, best_d = o.ref, d
        self.selected = best

    # ----------------------------------------------------------- drawing

    def _draw_map(self, surf, sprites, terrain_scaled, font_sm, font_md):
        r = self.map_rect
        pygame.draw.rect(surf, MAP_BG, r)

        if terrain_scaled is not None:
            surf.blit(terrain_scaled, r.topleft)
        else:
            step_x = r.w / 10
            step_y = r.h / 10
            for i in range(1, 10):
                gx = int(r.x + i * step_x)
                gy = int(r.y + i * step_y)
                pygame.draw.line(surf, GRID_COLOR, (gx, r.top), (gx, r.bottom), 1)
                pygame.draw.line(surf, GRID_COLOR, (r.left, gy), (r.right, gy), 1)

        prev_clip = surf.get_clip()
        surf.set_clip(r)

        # Organic remains
        if self.show_remains:
            for rx, ry, amount in self.snap.remains_patches:
                sx, sy = self._world_to_screen(rx, ry)
                rad = min(22, int(4 + 1.4 * (amount ** 0.5)))
                spr = sprites.get("remains", rad * 2)
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
            base = {"Producer": 5, "Consumer": 7, "Predator": 10,
                    "Decomposer": 6, "Scavenger": 7}.get(o.kind, 7)
            size = int(base * (0.7 + 0.6 * o.fullness))

            if o.ref is self.selected:
                selected_pos = (draw_x, draw_y)
                selected_view = o

            spr_base = SPRITE_SIZE.get(o.species, 36)
            spr_size = spr_base * (0.8 + 0.35 * o.fullness)
            spr_angle = angle if o.kind not in ("Producer", "Decomposer") else 0.0
            spr = sprites.get(o.species, spr_size, spr_angle)
            if spr:
                sw, sh = spr.get_size()
                shadow_w = max(8, int(sw * (0.7 if o.species == "Skyrender" else 0.9)))
                shadow_h = max(6, sh // 3)
                shadow = pygame.Surface((shadow_w, shadow_h), pygame.SRCALPHA)
                pygame.draw.ellipse(shadow, (0, 0, 0, 75), shadow.get_rect())
                surf.blit(shadow, shadow.get_rect(center=(int(sx), int(sy + sh * 0.35 + shadow_drop))))
                surf.blit(spr, spr.get_rect(center=(draw_x, draw_y)))
            else:
                self._draw_procedural_organism(surf, draw_x, draw_y, size, angle, o.kind, color)

            # Quick "!" alert above fleeing prey
            if act_kind == "flee":
                alert = font_md.render("!", True, (255, 195, 60))
                surf.blit(alert, (draw_x - alert.get_width() // 2, draw_y - 34))

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

            # Action rings
            for wx, wy, color, age, dur, max_r in self._effects:
                prog = min(1.0, age / dur)
                rad = max(2, int(4 + prog * max_r))
                alpha = int((1.0 - prog) * 220)
                ex, ey = self._world_to_screen(wx, wy)
                pygame.draw.circle(self._fx_surf, (*color, alpha), (int(ex - r.x), int(ey - r.y)), rad, 2)

            surf.blit(self._fx_surf, r.topleft)

        # Dynamic lighting, drought haze, plague flash & radiation atmosphere overlay
        light = self.snap.light
        rad = self.snap.radiation
        dark_alpha = int(max(0.0, min(0.68, (1.0 - light) * 0.72)) * 255)
        if dark_alpha > 4:
            shade = pygame.Surface(r.size, pygame.SRCALPHA)
            shade.fill((6, 10, 18, dark_alpha))
            surf.blit(shade, r.topleft)

        if "drought" in self._active_disasters():
            haze = pygame.Surface(r.size, pygame.SRCALPHA)
            haze.fill((160, 100, 35, 34))
            surf.blit(haze, r.topleft)

        if self._plague_fx_timer > 0:
            phaze = pygame.Surface(r.size, pygame.SRCALPHA)
            phaze.fill((120, 35, 165, int(35 * min(1.0, self._plague_fx_timer))))
            surf.blit(phaze, r.topleft)

        if rad < 0.75:
            tint = pygame.Surface(r.size, pygame.SRCALPHA)
            tint.fill((40, 20, 60, int((0.75 - rad) * 60)))
            surf.blit(tint, r.topleft)

        # Selected organism: perception radius, AI target line & Inspector HUD
        if selected_pos and selected_view:
            profile = BEHAVIOR.get(selected_view.species)
            if profile and profile.get("perception", 0) > 0:
                perc_px = int((profile["perception"] / max(1e-6, self.world.width)) * r.w)
                if perc_px > 4:
                    psurf = pygame.Surface((perc_px * 2 + 2, perc_px * 2 + 2), pygame.SRCALPHA)
                    pygame.draw.circle(psurf, (77, 208, 225, 22), (perc_px + 1, perc_px + 1), perc_px)
                    pygame.draw.circle(psurf, (77, 208, 225, 95), (perc_px + 1, perc_px + 1), perc_px, 1)
                    surf.blit(psurf, (selected_pos[0] - perc_px - 1, selected_pos[1] - perc_px - 1))

            action = getattr(selected_view.ref, "last_action", None)
            action_label = "photosynthesize" if selected_view.kind == "Producer" else "idle"
            if action is not None:
                action_label = action.kind
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
            lines = [
                f"{selected_view.name}  ({selected_view.species})",
                f"Type: {selected_view.kind}   Age: {selected_view.age}",
                f"Energy: {selected_view.energy:.1f}  ({int(selected_view.fullness * 100)}%)",
                f"Action: {action_label}",
            ]
            box = pygame.Rect(r.x + 12, r.y + 12, 248, 88)
            hud = pygame.Surface(box.size, pygame.SRCALPHA)
            hud.fill((12, 16, 22, 220))
            surf.blit(hud, box.topleft)
            pygame.draw.rect(surf, ACCENT, box, 1, border_radius=5)
            for i, line in enumerate(lines):
                surf.blit(font_sm.render(line, True, TEXT if i == 0 else MUTED),
                          (box.x + 10, box.y + 8 + i * 18))
        elif self.selected is not None:
            self.selected = None

        # Spawn Mode banner at bottom-left of map
        if self.spawn_species is not None:
            sp_col = SPECIES_COLOR.get(self.spawn_species, ACCENT)
            msg = f"SPAWN BRUSH: {self.spawn_species}  (Click map to spawn  |  Right-click / Esc to exit)"
            st = font_sm.render(msg, True, TEXT)
            srect = pygame.Rect(r.x + 12, r.bottom - 34, st.get_width() + 18, 24)
            hud = pygame.Surface(srect.size, pygame.SRCALPHA)
            hud.fill((12, 16, 22, 220))
            surf.blit(hud, srect.topleft)
            pygame.draw.rect(surf, sp_col, srect, 2, border_radius=4)
            surf.blit(st, (srect.x + 9, srect.y + 5))

        # Top-right map badge (Turn & active stress)
        badge_txt = f"Turn {self.snap.turn}   |   Alive {self.snap.total_population}/{self.snap.population_limit}"
        if self.stress and self.stress.active:
            active_names = ", ".join(e.name.upper() for e in self.stress.active)
            badge_txt += f"   |   ACTIVE: {active_names}"
        bt = font_md.render(badge_txt, True, TEXT)
        badge_rect = pygame.Rect(r.right - bt.get_width() - 22, r.y + 10, bt.get_width() + 14, 26)
        hud = pygame.Surface(badge_rect.size, pygame.SRCALPHA)
        hud.fill((12, 16, 22, 200))
        surf.blit(hud, badge_rect.topleft)
        pygame.draw.rect(surf, PANEL_BORDER, badge_rect, 1, border_radius=4)
        surf.blit(bt, (badge_rect.x + 7, badge_rect.y + 5))

        surf.set_clip(prev_clip)
        pygame.draw.rect(surf, PANEL_BORDER, r, 1)

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

    def _draw_sidebar(self, surf, font_sm, font_md, font_lg, mouse_pos):
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

        # Population bars (clickable to toggle Spawn Brush)
        y = self.panels_start_y
        surf.blit(font_md.render("Species  (click row to spawn)", True, TEXT), (sx, y))
        y += 20
        peak = max([c for c in self.snap.counts.values()] + [10])
        bar_max = max(60, sw - 125)
        self._species_rects.clear()

        for name in SPECIES:
            row_rect = pygame.Rect(sx - 4, y - 1, sw + 8, 17)
            self._species_rects[name] = row_rect
            is_armed = (self.spawn_species == name)
            if is_armed:
                pygame.draw.rect(surf, (45, 62, 82), row_rect, border_radius=3)
                pygame.draw.rect(surf, SPECIES_COLOR.get(name, ACCENT), row_rect, 1, border_radius=3)
            elif row_rect.collidepoint(mouse_pos):
                pygame.draw.rect(surf, (30, 38, 49), row_rect, border_radius=3)

            count = self.snap.counts.get(name, 0)
            col = SPECIES_COLOR.get(name, TEXT)
            surf.blit(font_sm.render(name, True, col), (sx, y))
            bar_w = int(((count ** 0.5) / (peak ** 0.5)) * bar_max)
            pygame.draw.rect(surf, (32, 39, 49), (sx + 80, y + 3, bar_max, 10), border_radius=3)
            if bar_w > 0:
                pygame.draw.rect(surf, col, (sx + 80, y + 3, bar_w, 10), border_radius=3)
            cnt_txt = font_sm.render(str(count), True, TEXT)
            surf.blit(cnt_txt, (sx + 86 + bar_max, y))
            y += 18

        # Mini population history graph
        y += 8
        surf.blit(font_md.render("Population History", True, TEXT), (sx, y))
        y += 20
        remaining = self.side_rect.bottom - y - 12
        graph_h = max(65, min(105, remaining // 2))
        graph_rect = pygame.Rect(sx, y, sw, graph_h)
        pygame.draw.rect(surf, BG, graph_rect, border_radius=4)
        pygame.draw.rect(surf, PANEL_BORDER, graph_rect, 1, border_radius=4)

        pts = [(r["turn"], r) for r in self.recorder.rows[-250:]] if (self.recorder and self.recorder.rows) else list(self.history)[-250:]
        if len(pts) >= 2:
            max_y = max(10, max(c.get(s, 0) for _, c in pts for s in SPECIES))
            for name in SPECIES:
                col = SPECIES_COLOR.get(name, TEXT)
                coords = []
                for i, (_, counts) in enumerate(pts):
                    px = graph_rect.x + 4 + (i / (len(pts) - 1)) * (graph_rect.w - 8)
                    val = counts.get(name, 0)
                    py = graph_rect.bottom - 4 - ((val ** 0.5) / (max_y ** 0.5)) * (graph_rect.h - 8)
                    coords.append((px, py))
                pygame.draw.lines(surf, col, False, coords, 2)

        # Plain-English Ecosystem Log
        y = graph_rect.bottom + 10
        surf.blit(font_md.render("Ecosystem Log", True, TEXT), (sx, y))
        y += 20
        max_lines = max(1, (self.side_rect.bottom - y - 8) // 18)
        events = list(self.detector.events)[-max_lines:] if self.detector else []
        events.reverse()

        if not events:
            surf.blit(font_sm.render("Ecosystem stable", True, MUTED), (sx, y))
        else:
            for e in events:
                col = EVENT_COLORS.get(e.kind, MUTED)
                surf.blit(font_sm.render(format_event(e), True, col), (sx, y))
                y += 18

    # --------------------------------------------------------- main loop

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

        font_sm = pygame.font.SysFont("consolas", 12)
        font_md = pygame.font.SysFont("segoeui", 14, bold=True)
        font_lg = pygame.font.SysFont("segoeui", 18, bold=True)

        sprites = SpriteBank()
        terrain_scaled = self._update_layout(win_w, win_h, sprites)

        running = True
        try:
            while running:
                dt = clock.tick(FPS) / 1000.0
                self._anim_time += dt
                mouse_pos = pygame.mouse.get_pos()

                for fx in self._effects:
                    fx[3] += dt
                self._effects = [fx for fx in self._effects if fx[3] < fx[4]]

                for sl in self._slashes:
                    sl[2] += dt
                self._slashes = [sl for sl in self._slashes if sl[2] < sl[3]]

                self._update_particles(dt)

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                        break
                    elif event.type == pygame.VIDEORESIZE:
                        screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                        terrain_scaled = self._update_layout(event.w, event.h, sprites)
                        continue

                    handled = False
                    for sl in self.sliders:
                        if sl.handle_event(event):
                            handled = True
                    for btn in self.buttons:
                        if btn.handle_event(event):
                            handled = True
                    if handled:
                        continue

                    if event.type == pygame.MOUSEBUTTONDOWN:
                        if event.button == 3:
                            self.spawn_species = None
                        elif event.button == 1:
                            picked_sp = None
                            for name, rect in self._species_rects.items():
                                if rect.collidepoint(event.pos):
                                    picked_sp = name
                                    break
                            if picked_sp is not None:
                                self.spawn_species = None if self.spawn_species == picked_sp else picked_sp
                                self.selected = None
                            else:
                                self._handle_map_click(event.pos)

                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_SPACE:
                            self._toggle_pause()
                        elif event.key == pygame.K_RIGHT:
                            self._step_one()
                        elif event.key == pygame.K_UP:
                            self.speed_index = min(len(SPEEDS) - 1, self.speed_index + 1)
                            self.sl_speed.value = self.speed_index
                        elif event.key == pygame.K_DOWN:
                            self.speed_index = max(0, self.speed_index - 1)
                            self.sl_speed.value = self.speed_index
                        elif event.key == pygame.K_r:
                            self._toggle_remains()
                        elif event.key in (pygame.K_c, pygame.K_ESCAPE):
                            self.selected = None
                            self.spawn_species = None

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

                screen.fill(BG)
                self._draw_map(screen, sprites, terrain_scaled, font_sm, font_md)
                self._draw_sidebar(screen, font_sm, font_md, font_lg, mouse_pos)
                pygame.display.flip()
        except KeyboardInterrupt:
            pass
        finally:
            pygame.quit()