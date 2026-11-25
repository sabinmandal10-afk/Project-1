from __future__ import annotations

import io
import math
import struct
import wave
from typing import Dict, Optional

import pygame


class SoundController:
    """Lightweight procedural sound effects with mute support and safe fallbacks."""

    def __init__(self, muted: bool = False, volume: float = 0.25) -> None:
        self.muted = muted
        self.volume = max(0.0, min(1.0, volume))
        self._enabled = False
        self._sounds: Dict[str, Optional[pygame.mixer.Sound]] = {}
        self._init_mixer()

    def _init_mixer(self) -> None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            self._enabled = pygame.mixer.get_init() is not None
        except Exception:
            self._enabled = False

        if not self._enabled:
            return

        presets = {
            "birth": (523.25, 659.25, 0.09),
            "hunt": (220.0, 146.83, 0.11),
            "disaster": (130.81, 87.31, 0.22),
            "click": (784.0, 880.0, 0.04),
            "prompt": (440.0, 587.33, 0.12),
        }
        for name, (f1, f2, dur) in presets.items():
            try:
                wav_bytes = self._tone_wav(f1, f2, dur)
                snd = pygame.mixer.Sound(file=io.BytesIO(wav_bytes))
                snd.set_volume(self.volume)
                self._sounds[name] = snd
            except Exception:
                self._sounds[name] = None

    @staticmethod
    def _tone_wav(freq_start: float, freq_end: float, duration: float, sample_rate: int = 22050) -> bytes:
        n_samples = max(1, int(sample_rate * duration))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            frames = bytearray()
            for i in range(n_samples):
                t = i / sample_rate
                frac = i / n_samples
                env = math.sin(math.pi * frac) * 0.35
                freq = freq_start + (freq_end - freq_start) * frac
                sample = int(32767 * env * math.sin(2.0 * math.pi * freq * t))
                frames.extend(struct.pack("<h", sample))
            wf.writeframes(bytes(frames))
        return buf.getvalue()

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    def play(self, cue: str) -> None:
        if self.muted or not self._enabled:
            return
        snd = self._sounds.get(cue)
        if snd is not None:
            try:
                snd.set_volume(self.volume)
                snd.play()
            except Exception:
                pass