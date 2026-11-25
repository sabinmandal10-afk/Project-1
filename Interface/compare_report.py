from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pygame


@dataclass
class ComparisonSeries:
    label_a: str = "Baseline"
    label_b: str = "No Predators"
    turns: List[int] = field(default_factory=list)
    pop_a: List[int] = field(default_factory=list)
    pop_b: List[int] = field(default_factory=list)
    gene_shift_a: List[float] = field(default_factory=list)
    gene_shift_b: List[float] = field(default_factory=list)

    def record(self, turn: int, total_a: int, total_b: int, gene_a: float = 1.0, gene_b: float = 1.0) -> None:
        if self.turns and self.turns[-1] == turn:
            self.pop_a[-1] = total_a
            self.pop_b[-1] = total_b
            self.gene_shift_a[-1] = gene_a
            self.gene_shift_b[-1] = gene_b
            return
        self.turns.append(turn)
        self.pop_a.append(total_a)
        self.pop_b.append(total_b)
        self.gene_shift_a.append(gene_a)
        self.gene_shift_b.append(gene_b)


class SplitCompareView:
    """Renders side-by-side population & trait comparison curves."""

    def __init__(self) -> None:
        self.enabled: bool = False
        self.series = ComparisonSeries()

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        return self.enabled

    def draw(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        font_md: pygame.font.Font,
        font_sm: pygame.font.Font,
    ) -> None:
        pygame.draw.rect(surface, (18, 22, 30), rect, border_radius=8)
        pygame.draw.rect(surface, (65, 80, 105), rect, width=1, border_radius=8)

        title = font_md.render(
            f"SPLIT COMPARE: {self.series.label_a}  vs  {self.series.label_b}",
            True,
            (235, 240, 248),
        )
        surface.blit(title, (rect.x + 14, rect.y + 10))

        plot_rect = pygame.Rect(rect.x + 16, rect.y + 38, rect.width - 32, rect.height - 54)
        pygame.draw.rect(surface, (12, 15, 21), plot_rect, border_radius=6)

        n = len(self.series.pop_a)
        if n < 2:
            msg = font_sm.render("Collecting comparison turns...", True, (150, 160, 175))
            surface.blit(msg, (plot_rect.x + 14, plot_rect.y + 14))
            return

        max_val = max(1, max(self.series.pop_a + self.series.pop_b))

        def to_pts(vals: List[int]) -> List[Tuple[int, int]]:
            pts: List[Tuple[int, int]] = []
            for i, v in enumerate(vals):
                x = plot_rect.x + int((i / max(1, n - 1)) * (plot_rect.width - 16)) + 8
                y = plot_rect.bottom - 8 - int((v / max_val) * (plot_rect.height - 24))
                pts.append((x, y))
            return pts

        pts_a = to_pts(self.series.pop_a)
        pts_b = to_pts(self.series.pop_b)
        pygame.draw.lines(surface, (90, 215, 145), False, pts_a, 2)
        pygame.draw.lines(surface, (240, 125, 110), False, pts_b, 2)

        leg_a = font_sm.render(f"{self.series.label_a}: {self.series.pop_a[-1]}", True, (90, 215, 145))
        leg_b = font_sm.render(f"{self.series.label_b}: {self.series.pop_b[-1]}", True, (240, 125, 110))
        surface.blit(leg_a, (plot_rect.x + 10, plot_rect.y + 8))
        surface.blit(leg_b, (plot_rect.x + 170, plot_rect.y + 8))


class ReportCard:
    """Generates and exports an end-of-show summary card."""

    def __init__(self) -> None:
        self.visible: bool = False
        self.last_export_path: Optional[str] = None

    def toggle(self) -> bool:
        self.visible = not self.visible
        return self.visible

    def build_surface(
        self,
        size: Tuple[int, int],
        stats: Dict[str, object],
        font_lg: pygame.font.Font,
        font_md: pygame.font.Font,
        font_sm: pygame.font.Font,
    ) -> pygame.Surface:
        w, h = size
        surf = pygame.Surface((w, h))
        surf.fill((15, 19, 27))
        card = pygame.Rect(40, 36, max(200, w - 80), max(200, h - 72))
        pygame.draw.rect(surf, (24, 30, 42), card, border_radius=12)
        pygame.draw.rect(surf, (88, 166, 255), card, width=2, border_radius=12)

        header = font_lg.render("GAIA — End-of-Show Ecosystem Report Card", True, (245, 248, 255))
        surf.blit(header, (card.x + 24, card.y + 20))

        lines = [
            f"Turn Reached: {stats.get('turn', 0)}",
            f"Biggest Population Crash: {stats.get('biggest_crash', 'None observed')}",
            f"Extinctions / Re-seeds: {stats.get('extinctions', 'None')}",
            f"Mean Speed Gene Shift: {stats.get('gene_shift', '0.00')}",
            f"Key Events: {', '.join(stats.get('events', [])[:4]) or 'Steady state'}",
            "Press [R] to export PNG  |  Press [Esc] or [C] to close",
        ]
        y = card.y + 68
        for idx, line in enumerate(lines):
            fnt = font_sm if idx == len(lines) - 1 else font_md
            col = (150, 175, 205) if idx == len(lines) - 1 else (220, 228, 240)
            surf.blit(fnt.render(line, True, col), (card.x + 24, y))
            y += 34

        return surf

    def export_png(self, surf: pygame.Surface, out_path: str = "gaia_report_card.png") -> str:
        target = Path(out_path)
        pygame.image.save(surf, str(target))
        self.last_export_path = str(target.resolve())
        return self.last_export_path