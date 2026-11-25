from __future__ import annotations

from typing import Any, Dict, List, Optional

import pygame

from Interface.atmosphere import AtmosphereController
from Interface.charts_panel import SidebarChartsPanel
from Interface.compare_report import ComparisonSeries, ReportCard, SplitCompareView
from Interface.showcase import ShowcaseDirector
from Interface.sound import SoundController
from organisms.lineage_flow import LineageAndFlowTracker


class ViewerUpgrades:
    """Drop-in coordinator for showcase, predictions, atmosphere, sound, lineage, flow, and charts."""

    def __init__(self) -> None:
        self.atmosphere = AtmosphereController()
        self.sound = SoundController()
        self.showcase = ShowcaseDirector()
        self.lineage_flow = LineageAndFlowTracker()
        self.charts = SidebarChartsPanel()
        self.compare_view = SplitCompareView()
        self.report_card = ReportCard()
        self.selected_org: Optional[Any] = None
        self.event_log: List[str] = []

    def on_turn_advanced(self, turn: int, world: Any, active_events: Optional[List[str]] = None) -> bool:
        """Returns True if the simulation should pause for a prediction prompt."""
        self.lineage_flow.begin_turn()
        self.lineage_flow.sync_from_world(world, turn)

        species_counts: Dict[str, int] = {}
        speed_genes: List[float] = []
        orgs = getattr(world, "organisms", None)
        if isinstance(orgs, (list, tuple)):
            for o in orgs:
                if getattr(o, "alive", True):
                    sp = str(getattr(o, "species", getattr(o, "name", "Other")))
                    species_counts[sp] = species_counts.get(sp, 0) + 1
                    g = self.lineage_flow.extract_genes(o)
                    if "speed" in g:
                        speed_genes.append(g["speed"])

        self.charts.push_sample(species_counts, speed_genes)

        total_a = sum(species_counts.values())
        mean_speed = sum(speed_genes) / len(speed_genes) if speed_genes else 1.0
        # Placeholder baseline comparison series; feed real second-world count if running twin worlds
        self.compare_view.series.record(turn, total_a, int(total_a * 1.12), mean_speed, 1.0)

        pred = self.showcase.sync_turn(turn)
        if pred is not None:
            self.sound.play("prompt")
            return True
        if self.showcase.active and self.showcase.pause_on_caption:
            return True
        return False

    def handle_upgrade_key(self, key: int, viewer: Any) -> bool:
        """Handles extra keys; returns True if consumed."""
        pred = self.showcase.active_prediction
        if pred is not None:
            if key in (pygame.K_1, pygame.K_KP1):
                self.showcase.select_prediction(0)
                self.sound.play("click")
                return True
            if key in (pygame.K_2, pygame.K_KP2):
                self.showcase.select_prediction(1)
                self.sound.play("click")
                return True
            if key in (pygame.K_3, pygame.K_KP3):
                self.showcase.select_prediction(2)
                self.sound.play("click")
                return True
            if key in (pygame.K_SPACE, pygame.K_RETURN):
                viewer.paused = False
                return True

        if key == pygame.K_RIGHTBRACKET:
            t = self.showcase.next_step()
            if t is not None:
                self.sound.play("click")
            return True
        if key == pygame.K_LEFTBRACKET:
            t = self.showcase.prev_step()
            if t is not None:
                self.sound.play("click")
            return True
        if key == pygame.K_n:
            self.showcase.show_speaker_notes = not self.showcase.show_speaker_notes
            return True
        if key == pygame.K_b:
            self.compare_view.toggle()
            return True
        if key == pygame.K_c:
            self.report_card.toggle()
            return True
        if key == pygame.K_r and self.report_card.visible and viewer._screen is not None:
            stats = {
                "turn": getattr(viewer, "turn", 0),
                "biggest_crash": "Tracked in history",
                "extinctions": "Auto re-seeded in Lab",
                "gene_shift": f"{(sum(self.charts.speed_samples)/len(self.charts.speed_samples) - 1.0 if self.charts.speed_samples else 0.0):+.2f}",
                "events": self.event_log,
            }
            card_surf = self.report_card.build_surface(
                viewer._win,
                stats,
                viewer.fonts["lg"],
                viewer.fonts["md"],
                viewer.fonts["sm"],
            )
            self.report_card.export_png(card_surf)
            return True
        return False

    def draw_prediction_overlay(
        self,
        screen: pygame.Surface,
        win_w: int,
        win_h: int,
        font_lg: pygame.font.Font,
        font_md: pygame.font.Font,
        font_sm: pygame.font.Font,
    ) -> None:
        st = self.showcase.current_step
        if not self.showcase.active or not st:
            return

        # Presenter caption bar at bottom of map
        bar = pygame.Rect(20, win_h - 92, max(260, win_w - 360), 72)
        pygame.draw.rect(screen, (16, 20, 28), bar, border_radius=8)
        pygame.draw.rect(screen, (95, 175, 255), bar, width=1, border_radius=8)
        screen.blit(font_md.render(st.title, True, (255, 220, 120)), (bar.x + 12, bar.y + 8))
        screen.blit(font_sm.render(st.caption[:95], True, (235, 240, 248)), (bar.x + 12, bar.y + 30))
        if st.speaker_note and self.showcase.show_speaker_notes:
            screen.blit(font_sm.render(f"Note: {st.speaker_note[:90]}", True, (150, 220, 180)), (bar.x + 12, bar.y + 50))

        pred = st.prediction
        if pred and (self.showcase.active_prediction is not None or pred.revealed):
            box = pygame.Rect(60, 70, min(640, win_w - 120), 230)
            pygame.draw.rect(screen, (20, 25, 36), box, border_radius=10)
            pygame.draw.rect(screen, (250, 185, 70), box, width=2, border_radius=10)
            screen.blit(font_lg.render("Prediction Moment", True, (255, 210, 90)), (box.x + 18, box.y + 14))
            screen.blit(font_md.render(pred.question, True, (245, 248, 252)), (box.x + 18, box.y + 46))

            y = box.y + 78
            for i, choice in enumerate(pred.choices):
                prefix = f"[{i + 1}] "
                col = (120, 230, 150) if (pred.revealed and i == pred.correct_index) else (215, 222, 235)
                screen.blit(font_sm.render(prefix + choice, True, col), (box.x + 24, y))
                y += 24

            if pred.revealed:
                screen.blit(font_sm.render(pred.explanation[:95], True, (155, 205, 255)), (box.x + 18, box.bottom - 28))