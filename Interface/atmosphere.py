from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, List, Tuple

import pygame


@dataclass
class AmbientParticle:
    x: float
    y: float
    vx: float
    vy: float
    radius: float
    alpha: int
    kind: str  # "spore" | "rain" | "glow"


class AtmosphereController:
    """Day/night cycle, weather overlay, ambient particles, and visible trait visuals."""

    WEATHER_MODES = ("clear", "rain", "fog", "drought")

    def __init__(self, day_length_turns: int = 24, seed: int = 42) -> None:
        self.day_length_turns = max(6, int(day_length_turns))
        self.rng = random.Random(seed)
        self.weather: str = "clear"
        self.time_of_day: float = 0.25  # 0.0 = midnight, 0.25 = dawn, 0.5 = noon, 0.75 = dusk
        self.particles: List[AmbientParticle] = []
        self._init_particles(90)

    def _init_particles(self, count: int) -> None:
        self.particles = [
            AmbientParticle(
                x=self.rng.random(),
                y=self.rng.random(),
                vx=self.rng.uniform(-0.02, 0.02),
                vy=self.rng.uniform(-0.015, 0.015),
                radius=self.rng.uniform(1.5, 3.5),
                alpha=self.rng.randint(45, 130),
                kind="spore" if i % 3 else "glow",
            )
            for i in range(count)
        ]

    def update(self, dt: float, turn: int, active_events: List[str] | None = None) -> None:
        self.time_of_day = ((turn % self.day_length_turns) / self.day_length_turns) % 1.0
        events_lower = [e.lower() for e in (active_events or [])]
        if any("drought" in e for e in events_lower):
            self.weather = "drought"
        elif any("rain" in e or "storm" in e for e in events_lower):
            self.weather = "rain"
        elif any("fog" in e or "mist" in e for e in events_lower):
            self.weather = "fog"
        elif self.weather not in self.WEATHER_MODES:
            self.weather = "clear"

        for p in self.particles:
            if self.weather == "rain":
                p.kind = "rain"
                p.x += (-0.08 + p.vx * 0.5) * dt
                p.y += 0.85 * dt
            else:
                if p.kind == "rain":
                    p.kind = "spore"
                p.x += p.vx * dt
                p.y += (p.vy + math.sin(p.x * 12.0 + turn) * 0.008) * dt

            if p.x < 0.0:
                p.x += 1.0
            elif p.x > 1.0:
                p.x -= 1.0
            if p.y > 1.0:
                p.y -= 1.0
            elif p.y < 0.0:
                p.y += 1.0

    def is_night(self) -> bool:
        # Night roughly between 0.80 and 0.20 on [0, 1)
        return self.time_of_day >= 0.80 or self.time_of_day <= 0.20

    def get_lighting_tint(self) -> Tuple[int, int, int, int]:
        # Daylight curve peaking at time_of_day = 0.5
        daylight = 0.5 - 0.5 * math.cos(2.0 * math.pi * self.time_of_day)
        night_factor = max(0.0, min(1.0, 1.0 - daylight * 1.25))
        if self.weather == "drought":
            return (235, 195, 130, 38)
        if self.weather == "fog":
            return (200, 215, 220, 52)
        if self.weather == "rain":
            return (140, 165, 200, 46)
        alpha = int(night_factor * 95)
        return (24, 34, 78, alpha)

    @staticmethod
    def transform_sprite_for_genes(sprite: pygame.Surface, org: Any) -> pygame.Surface:
        """Visibly scales or tints a sprite based on speed/sense/size genes."""
        genes = getattr(org, "genes", {}) if isinstance(getattr(org, "genes", None), dict) else {}
        speed = float(genes.get("speed", getattr(org, "speed_gene", 1.0)) or 1.0)
        sense = float(genes.get("sense", getattr(org, "sense_gene", 1.0)) or 1.0)
        scale = max(0.75, min(1.35, 0.85 + 0.15 * speed))

        w, h = sprite.get_width(), sprite.get_height()
        nw, nh = max(4, int(round(w * scale))), max(4, int(round(h * scale)))
        surf = sprite if (nw == w and nh == h) else pygame.transform.smoothscale(sprite, (nw, nh))

        # Subtle warm/cool tint shift for high speed or high sense
        delta = max(-0.4, min(0.4, (speed - 1.0) * 0.35 + (sense - 1.0) * 0.2))
        if abs(delta) > 0.04:
            tinted = surf.copy()
            if delta > 0:
                amt = int(min(65, delta * 140))
                tinted.fill((amt, int(amt * 0.5), 0, 0), special_flags=pygame.BLEND_RGBA_ADD)
            else:
                amt = int(min(65, abs(delta) * 140))
                tinted.fill((0, int(amt * 0.4), amt, 0), special_flags=pygame.BLEND_RGBA_ADD)
            return tinted
        return surf

    def draw_overlay(self, target_surf: pygame.Surface, rect: pygame.Rect) -> None:
        r, g, b, alpha = self.get_lighting_tint()
        if alpha > 0:
            overlay = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            overlay.fill((r, g, b, alpha))
            target_surf.blit(overlay, rect.topleft)

        p_surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        night = self.is_night()
        for p in self.particles:
            px = rect.x + int(p.x * rect.width)
            py = rect.y + int(p.y * rect.height)
            if p.kind == "rain":
                pygame.draw.line(
                    p_surf,
                    (175, 205, 240, min(130, p.alpha + 25)),
                    (px, py),
                    (px - 3, py + 9),
                    1,
                )
            elif p.kind == "glow" and night:
                pygame.draw.circle(p_surf, (130, 245, 215, min(160, p.alpha + 40)), (px, py), int(p.radius + 1))
            else:
                pygame.draw.circle(p_surf, (235, 240, 210, p.alpha // 2), (px, py), max(1, int(p.radius)))

        target_surf.blit(p_surf, rect.topleft)