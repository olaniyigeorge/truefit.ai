"""
Turn detection on synthetic audio: a fan alone never starts a turn, speech over
it does, and the turn ends after a pause.

    python examples/turn_detection.py
"""

import math
import random
from array import array

from soro.audio import EnergyTurnDetector

rng = random.Random(0)


def chunk(rms: float) -> bytes:
    peak = rms * math.sqrt(3)
    return array("h", (int(rng.uniform(-peak, peak)) for _ in range(320))).tobytes()  # 20ms at 16kHz


detector = EnergyTurnDetector()
timeline = [("fan only", 900, 100), ("speech over fan", 5000, 50), ("fan only", 900, 100)]
t = 0.0
for label, level, frames in timeline:
    for _ in range(frames):
        t += 0.02
        event = detector.process(chunk(level * rng.uniform(0.3, 1.0) if label.startswith("speech") else level))
        if event:
            print(f"{t:5.2f}s  turn {event.kind}  ({label})")
