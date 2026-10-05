"""
Synthetic audio fixtures for turn-detection evals.

These generators build 16-bit mono PCM at a 20ms frame size, deterministically
from a seed, so a run is repeatable and needs no recorded audio. They model the
cases that break naive detectors: a steady fan that keeps the mic "speaking", a
fan that switches on mid-call, and speech laid over fan noise.

A note on what synthetic audio can and cannot show. Modulated noise has a
speech-like *energy* envelope, so an energy detector treats it as speech, which
is exactly what makes the fan cases meaningful for the energy detector. A neural
detector such as Silero classifies the *acoustics* of speech, so it correctly
rejects modulated noise; its true-positive accuracy is best measured on real
recordings dropped into a fixtures directory (see load_wav_frames). The synthetic
set is therefore the right tool for false-trigger robustness, and real clips are
the right tool for true-positive latency.
"""

from __future__ import annotations

import math
import random
import wave
from array import array
from pathlib import Path

RATE = 16_000
FRAME_MS = 20
FRAME_SAMPLES = RATE * FRAME_MS // 1000  # 320


def _pcm(values) -> bytes:
    return array("h", [int(max(-32768, min(32767, v))) for v in values]).tobytes()


def _frame_count(seconds: float) -> int:
    # Multiply before dividing, and round: seconds / 0.02 truncates to one frame
    # short because 0.02 has no exact float representation.
    return round(seconds * 1000 / FRAME_MS)


def noise(rms: float, rng: random.Random, n: int = FRAME_SAMPLES) -> bytes:
    """One frame of uniform noise at the given RMS (uniform rms = peak / sqrt(3))."""
    peak = rms * math.sqrt(3)
    return _pcm(rng.uniform(-peak, peak) for _ in range(n))


def quiet(seconds: float, rng: random.Random, rms: float = 30.0) -> list[bytes]:
    return [noise(rms, rng) for _ in range(_frame_count(seconds))]


def fan(seconds: float, rng: random.Random, rms: float = 900.0) -> list[bytes]:
    """Steady broadband noise, the sound that keeps a naive detector's turn open."""
    return [noise(rms * rng.uniform(0.92, 1.08), rng) for _ in range(_frame_count(seconds))]


def speech_frames(seconds: float, rng: random.Random, rms: float = 2500.0) -> list[bytes]:
    """Noise with a 4Hz syllable envelope that dips close to silence, like speech."""
    frames = []
    for i in range(_frame_count(seconds)):
        t = i * (FRAME_MS / 1000)
        envelope = 0.15 + 0.85 * max(0.0, math.sin(2 * math.pi * 4 * t)) ** 2
        frames.append(noise(rms * envelope * 1.5, rng))
    return frames


def mix(a: list[bytes], b: list[bytes]) -> list[bytes]:
    """Sum two equal-length frame lists sample by sample (speech over fan)."""
    out = []
    for fa, fb in zip(a, b):
        sa, sb = array("h"), array("h")
        sa.frombytes(fa)
        sb.frombytes(fb)
        out.append(_pcm(x + y for x, y in zip(sa.tolist(), sb.tolist())))
    return out


def load_wav_frames(path: str | Path, frame_ms: int = FRAME_MS) -> list[bytes]:
    """
    Load a real recording as 16kHz mono s16 frames. Used for optional true-positive
    cases: drop a speech WAV next to the evals and the neural detector can be scored
    on acoustics, not just energy. Raises if the file is not 16kHz mono s16.
    """
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != RATE:
            raise ValueError(
                f"{path}: need 16kHz mono s16 PCM, got "
                f"{w.getframerate()}Hz {w.getnchannels()}ch {w.getsampwidth() * 8}bit"
            )
        raw = w.readframes(w.getnframes())
    step = RATE * frame_ms // 1000 * 2
    return [raw[i : i + step] for i in range(0, len(raw) - step + 1, step)]
