from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import pygame

from organisms.lineage_flow import LineageAndFlowTracker


class SidebarChartsPanel:
    """Draws population/biodiversity curves, gene histograms, energy flow, and lineage."""

    def __init__(self) -> None:
        self.history_totals: List[int] = []
        self.biodiversity_history: List[float] = []
        self.speed_samples: List[float] = []

    def push_sample(self, species_counts: Dict[str, int], speed_genes: List[float]) -> None:
        total = sum(max(0, c) for c in species_counts.values())
        self.history_totals.append(total)
        if len(self.history_totals) > 120:
            self.history_totals.pop(0)

        # Shannon diversity index H'
        shannon = 0.0
        if total > 0:
            for c in species_counts.values():
                if c > 0:
                    p = c / total
                    shannon -= p * math.log(p)
        self.biodiversity_history.append(shannon)
        if len(self.biodiversity_history) > 120:
            self.biodiversity_history.pop(0)

        self.speed_samples = list(speed_genes)

    def draw_population_and_diversity(
        self,
        surf: pygame.Surface,
        rect: pygame.Rect,
        font_md: pygame.font.Font,
        font_sm: pygame.font.Font,
    ) -> None:
        pygame.draw.rect(surf, (22, 27, 36), rect, border_radius=6)
        pygame.draw.rect(surf, (52, 62, 80), rect, width=1, border_radius=6)

        latest_h = self.biodiversity_history[-1] if self.biodiversity_history else 0.0
        surf.blit(
            font_md.render(f"Population & Diversity (H' {latest_h:.2f})", True, (235, 240, 248)),
            (rect.x + 10, rect.y + 6),
        )

        plot = pygame.Rect(rect.x + 10, rect.y + 28, rect.width - 20, max(24, rect.height - 36))
        pygame.draw.rect(surf, (14, 17, 23), plot, border_radius=4)

        if len(self.history_totals) >= 2:
            max_pop = max(1, max(self.history_totals))
            pts: List[Tuple[int, int]] = []
            n = len(self.history_totals)
            for i, v in enumerate(self.history_totals):
                x = plot.x + int((i / (n - 1)) * (plot.width - 10)) + 5
                y = plot.bottom - 5 - int((v / max_pop) * (plot.height - 12))
                pts.append((x, y))
            pygame.draw.lines(surf, (92, 214, 152), False, pts, 2)

            # Shannon index scaled onto plot (max ~2.0)
            h_pts: List[Tuple[int, int]] = []
            for i, h_val in enumerate(self.biodiversity_history):
                x = plot.x + int((i / (n - 1)) * (plot.width - 10)) + 5
                y = plot.bottom - 5 - int(min(1.0, h_val / 2.0) * (plot.height - 12))
                h_pts.append((x, y))
            pygame.draw.lines(surf, (115, 185, 255), False, h_pts, 1)

    def draw_gene_histogram(
        self,
        surf: pygame.Surface,
        rect: pygame.Rect,
        font_md: pygame.font.Font,
        font_sm: pygame.font.Font,
    ) -> None:
        pygame.draw.rect(surf, (22, 27, 36), rect, border_radius=6)
        pygame.draw.rect(surf, (52, 62, 80), rect, width=1, border_radius=6)

        mean_g = sum(self.speed_samples) / len(self.speed_samples) if self.speed_samples else 1.0
        surf.blit(
            font_md.render(f"Speed Gene Histogram (mean {mean_g:.2f})", True, (235, 240, 248)),
            (rect.x + 10, rect.y + 6),
        )

        bins = 8
        lo, hi = 0.5, 1.5
        counts = [0] * bins
        for g in self.speed_samples:
            clamped = max(lo, min(hi - 1e-6, float(g)))
            idx = int(((clamped - lo) / (hi - lo)) * bins)
            counts[idx] += 1

        max_c = max(1, max(counts))
        bar_area = pygame.Rect(rect.x + 12, rect.y + 28, rect.width - 24, max(20, rect.height - 44))
        bw = max(6, bar_area.width // bins - 4)

        for i, c in enumerate(counts):
            bh = int((c / max_c) * bar_area.height)
            bx = bar_area.x + i * (bw + 4)
            by = bar_area.bottom - bh
            pygame.draw.rect(surf, (240, 178, 72), (bx, by, bw, bh), border_radius=2)

        surf.blit(font_sm.render("0.5", True, (150, 160, 175)), (bar_area.x, bar_area.bottom + 2))
        surf.blit(font_sm.render("1.5", True, (150, 160, 175)), (bar_area.right - 22, bar_area.bottom + 2))

    def draw_energy_and_lineage(
        self,
        surf: pygame.Surface,
        rect: pygame.Rect,
        tracker: LineageAndFlowTracker,
        selected_org: Optional[Any],
        font_md: pygame.font.Font,
        font_sm: pygame.font.Font,
    ) -> None:
        pygame.draw.rect(surf, (22, 27, 36), rect, border_radius=6)
        pygame.draw.rect(surf, (52, 62, 80), rect, width=1, border_radius=6)

        surf.blit(font_md.render("Energy Flow & Lineage", True, (235, 240, 248)), (rect.x + 10, rect.y + 6))

        flows = tracker.get_flow_totals(cumulative=True)
        top_flows = sorted(flows.items(), key=lambda kv: kv[1], reverse=True)[:3]
        y = rect.y + 28
        for (src, dst), amt in top_flows:
            line = f"{src[:4]}->{dst[:4]}: {amt:.1f}"
            surf.blit(font_sm.render(line, True, (175, 225, 195)), (rect.x + 12, y))
            y += 16

        if selected_org is not None:
            info = tracker.get_lineage_summary(selected_org)
            rec = info["record"]
            lin_txt = (
                f"#{rec.org_id[:6]} gen:{rec.generation} "
                f"kids:{len(info['children'])} meals:{rec.meals}"
            )
            surf.blit(font_sm.render(lin_txt, True, (255, 215, 125)), (rect.x + 12, y + 2))