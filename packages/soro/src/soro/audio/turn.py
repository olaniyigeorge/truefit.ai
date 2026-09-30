"""
Pluggable turn detection.

A TurnDetector looks at 16-bit mono PCM and says when the speaker starts and
stops a turn. Anything that moves audio (a WebRTC bridge, a websocket, a file)
can drive one, and a provider with its own voice activity detection does not
need one at all (see AdapterCapabilities.native_vad).

    detector = EnergyTurnDetector()
    for chunk in mic_chunks:
        event = detector.process(chunk)
        if event is not None:
            ...  # event.kind is "start" or "end"

EnergyTurnDetector is pure Python and adapts to the room. It keeps a noise
floor estimate, so steady noise such as a fan raises the floor instead of
holding a turn open, and it uses two thresholds (hysteresis) so a level that
hovers near the edge does not flap. Time is measured in audio, not wall clock,
so behaviour is deterministic and testable. A neural detector (for example
Silero) can implement the same protocol.
"""

from __future__ import annotations

import math
import sys
from array import array
from collections import deque
from dataclasses import dataclass
from typing import Deque, Literal, Optional, Protocol, runtime_checkable

TurnEventKind = Literal["start", "end"]


@dataclass(frozen=True)
class TurnEvent:
    kind: TurnEventKind


@runtime_checkable
class TurnDetector(Protocol):
    @property
    def is_speaking(self) -> bool: ...

    def process(self, pcm: bytes) -> Optional[TurnEvent]:
        """Feed a chunk of 16-bit mono little-endian PCM. Returns an event on a boundary."""
        ...

    def advance_silence(self, seconds: float) -> Optional[TurnEvent]:
        """Account for time with no audio at all (for example a quiet network track)."""
        ...

    def reset(self) -> None:
        """Forget the current turn but keep anything learned about the room."""
        ...


@dataclass(frozen=True)
class EnergyTurnConfig:
    sample_rate: int = 16_000
    # A frame counts as speech above floor * on_ratio, and as silence below
    # floor * off_ratio. on_ratio > off_ratio gives the hysteresis band.
    on_ratio: float = 3.0
    off_ratio: float = 1.8
    # Absolute RMS (16-bit scale) minimums, so a dead-quiet room does not make
    # the thresholds vanishingly small.
    min_on_rms: float = 150.0
    min_off_rms: float = 80.0
    initial_floor: float = 40.0
    start_ms: int = 100  # sustained speech needed before a turn starts
    end_ms: int = 800  # sustained silence needed before a turn ends
    calibration_ms: int = 300  # initial audio used to learn the floor, no events
    floor_fall: float = 0.2  # per-frame smoothing when the level drops below the floor
    floor_rise: float = 0.002  # per-frame smoothing when speech-like audio is above it
    # Steady audio that stays above the floor is noise. Real speech moves
    # (syllables, pauses), so a flat stretch is learned into the floor quickly.
    steady_window_ms: int = 1500
    steady_ratio: float = 1.5  # max/min RMS across the window counts as steady
    floor_rise_steady: float = 0.1


def _rms(pcm: bytes) -> float:
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class EnergyTurnDetector:
    def __init__(self, config: EnergyTurnConfig | None = None) -> None:
        self.config = config or EnergyTurnConfig()
        self._floor = self.config.initial_floor
        self._calibrated_ms = 0.0
        self._calibration_min: Optional[float] = None
        self._recent: Deque[float] = deque()
        self._recent_ms = 0.0
        self._speaking = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    @property
    def noise_floor(self) -> float:
        return self._floor

    def reset(self) -> None:
        self._speaking = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0

    def process(self, pcm: bytes) -> Optional[TurnEvent]:
        frame_ms = len(pcm) // 2 * 1000 / self.config.sample_rate
        if frame_ms <= 0:
            return None
        level = _rms(pcm)
        if self._calibrate(level, frame_ms):
            return None
        self._adapt_floor(level, frame_ms)
        return self._step(level, frame_ms)

    def advance_silence(self, seconds: float) -> Optional[TurnEvent]:
        if not self._speaking:
            return None
        self._silence_ms += seconds * 1000
        if self._silence_ms >= self.config.end_ms:
            self.reset()
            return TurnEvent("end")
        return None

    def _calibrate(self, level: float, frame_ms: float) -> bool:
        if self._calibrated_ms >= self.config.calibration_ms:
            return False
        # The quietest frame seen is the best guess at the room, even if the
        # speaker starts talking straight away.
        if self._calibration_min is None or level < self._calibration_min:
            self._calibration_min = level
        self._floor = max(self._calibration_min, 1.0)
        self._calibrated_ms += frame_ms
        return True

    def _adapt_floor(self, level: float, frame_ms: float) -> None:
        cfg = self.config
        self._recent.append(level)
        self._recent_ms += frame_ms
        while self._recent_ms - frame_ms >= cfg.steady_window_ms and len(self._recent) > 1:
            self._recent.popleft()
            self._recent_ms -= frame_ms
        if level <= self._floor:
            alpha = cfg.floor_fall
        elif self._is_steady():
            alpha = cfg.floor_rise_steady
        else:
            alpha = cfg.floor_rise
        self._floor = max(self._floor + alpha * (level - self._floor), 1.0)

    def _is_steady(self) -> bool:
        cfg = self.config
        if self._recent_ms < cfg.steady_window_ms:
            return False
        lo = max(min(self._recent), 1.0)
        return max(self._recent) / lo <= cfg.steady_ratio

    def _step(self, level: float, frame_ms: float) -> Optional[TurnEvent]:
        cfg = self.config
        on = max(cfg.min_on_rms, self._floor * cfg.on_ratio)
        off = max(cfg.min_off_rms, self._floor * cfg.off_ratio)
        if not self._speaking:
            if level > on:
                self._speech_ms += frame_ms
                if self._speech_ms >= cfg.start_ms:
                    self._speaking = True
                    self._speech_ms = 0.0
                    self._silence_ms = 0.0
                    return TurnEvent("start")
            else:
                # Leak instead of reset, so the gaps between syllables do not
                # cancel the evidence gathered so far.
                self._speech_ms = max(0.0, self._speech_ms - frame_ms / 2)
            return None
        if level < off:
            self._silence_ms += frame_ms
            if self._silence_ms >= cfg.end_ms:
                self.reset()
                return TurnEvent("end")
        else:
            self._silence_ms = 0.0
        return None


def create_turn_detector(kind: str = "energy", **options) -> TurnDetector:
    """Build a detector by name. Only "energy" ships today."""
    if kind == "energy":
        return EnergyTurnDetector(EnergyTurnConfig(**options))
    raise ValueError(f"Unknown turn detector {kind!r}. Available: 'energy'.")
