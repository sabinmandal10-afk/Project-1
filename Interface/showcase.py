from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PredictionPrompt:
    trigger_turn: int
    question: str
    choices: List[str]
    correct_index: int
    explanation: str
    selected_index: Optional[int] = None
    revealed: bool = False


@dataclass
class ShowcaseStep:
    turn: int
    title: str
    caption: str
    speaker_note: str = ""
    focus_species: Optional[str] = None
    prediction: Optional[PredictionPrompt] = field(default=None)


class ShowcaseDirector:
    """Manages scripted story steps, presenter controls, and prediction pauses."""

    def __init__(self, steps: Optional[List[ShowcaseStep]] = None) -> None:
        self.active: bool = False
        self.pause_on_caption: bool = False
        self.show_speaker_notes: bool = False
        self.index: int = 0
        self.steps: List[ShowcaseStep] = steps or self.default_steps()
        self._last_prompted_step: Optional[int] = None

    @staticmethod
    def default_steps() -> List[ShowcaseStep]:
        try:
            from Interface.education import showcase_schedule
            sched = showcase_schedule()
            out: List[ShowcaseStep] = []
            for t_offset, item in sched:
                out.append(
                    ShowcaseStep(
                        turn=t_offset + 1,
                        title=item.get("title", ""),
                        caption=item.get("text", ""),
                        speaker_note=item.get("speaker_note", ""),
                        focus_species=(item.get("highlight") or [None])[0],
                    )
                )
            if out:
                return out
        except Exception:
            pass
        return [
            ShowcaseStep(
                turn=1,
                title="1. Founding Balance",
                caption="Producers capture energy, herbivores graze, predators regulate growth, and decomposers recycle nutrients.",
                speaker_note="Point out the starting population counts and soil fertility baseline.",
            ),
            ShowcaseStep(
                turn=18,
                title="2. Drought & Selection Pressure",
                caption="Scarce resources test trait trade-offs—watch how faster or better-sensing lineages fare.",
                speaker_note="Ask students to observe which species drops first and why.",
                prediction=PredictionPrompt(
                    trigger_turn=18,
                    question="A dry spell hits the ecosystem. What happens first to the Grazers?",
                    choices=[
                        "They surge immediately due to less competition",
                        "They dip as food tightens, then stabilize via selection",
                        "They go extinct within 2 turns",
                    ],
                    correct_index=1,
                    explanation="Tighter food supply trims excess population first, while better-adapted individuals sustain recovery.",
                ),
            ),
            ShowcaseStep(
                turn=36,
                title="3. Trophic Cascade & Recovery",
                caption="Decomposers return bound nutrients to the soil, fueling a second wave of producer growth.",
                speaker_note="Highlight the energy flow from dead matter back into the soil.",
            ),
        ]

    def start(self) -> None:
        self.active = True
        self.index = 0
        self._last_prompted_step = None
        for st in self.steps:
            if st.prediction:
                st.prediction.selected_index = None
                st.prediction.revealed = False

    def stop(self) -> None:
        self.active = False

    @property
    def current_step(self) -> Optional[ShowcaseStep]:
        if not self.active or not self.steps:
            return None
        idx = max(0, min(self.index, len(self.steps) - 1))
        return self.steps[idx]

    @property
    def active_prediction(self) -> Optional[PredictionPrompt]:
        st = self.current_step
        if not st or not st.prediction:
            return None
        pred = st.prediction
        if not pred.revealed and self._last_prompted_step == self.index:
            return pred
        return None

    def sync_turn(self, turn: int) -> Optional[PredictionPrompt]:
        """Advances step index to match simulation turn and triggers prediction pauses."""
        if not self.active or not self.steps:
            return None
        while self.index + 1 < len(self.steps) and turn >= self.steps[self.index + 1].turn:
            self.index += 1
        st = self.steps[self.index]
        if (
            st.prediction
            and not st.prediction.revealed
            and turn >= st.prediction.trigger_turn
            and self._last_prompted_step != self.index
        ):
            self._last_prompted_step = self.index
            return st.prediction
        return None

    def next_step(self) -> Optional[int]:
        if not self.steps:
            return None
        if not self.active:
            self.start()
            return self.steps[0].turn
        if self.index + 1 < len(self.steps):
            self.index += 1
            return self.steps[self.index].turn
        return None

    def prev_step(self) -> Optional[int]:
        if not self.active or not self.steps:
            return None
        if self.index > 0:
            self.index -= 1
            return self.steps[self.index].turn
        return self.steps[0].turn

    def jump_to(self, index: int) -> Optional[int]:
        """Jump directly to a step by index. Returns the target turn or None."""
        if not self.steps:
            return None
        if not self.active:
            self.start()
        self.index = max(0, min(index, len(self.steps) - 1))
        return self.steps[self.index].turn

    def select_prediction(self, choice_idx: int) -> None:
        pred = self.active_prediction
        if pred is None:
            st = self.current_step
            pred = st.prediction if st else None
        if pred and 0 <= choice_idx < len(pred.choices):
            pred.selected_index = choice_idx
            pred.revealed = True

    def summary_dict(self) -> Dict[str, object]:
        st = self.current_step
        return {
            "active": self.active,
            "step_num": self.index + 1 if st else 0,
            "total_steps": len(self.steps),
            "title": st.title if st else "",
            "caption": st.caption if st else "",
            "speaker_note": st.speaker_note if (st and self.show_speaker_notes) else "",
        }