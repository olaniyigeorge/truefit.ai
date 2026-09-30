import math
import random
from array import array

import pytest

from soro.audio import (
    EnergyTurnDetector,
    TurnDetector,
    TurnEvent,
    create_turn_detector,
)

pytestmark = pytest.mark.unit

RATE = 16_000
CHUNK = 320  # 20ms


def _pcm(values) -> bytes:
    return array("h", [int(max(-32768, min(32767, v))) for v in values]).tobytes()


def noise(rms: float, rng: random.Random, n: int = CHUNK) -> bytes:
    # uniform noise has rms = peak / sqrt(3)
    peak = rms * math.sqrt(3)
    return _pcm(rng.uniform(-peak, peak) for _ in range(n))


def speech_frames(seconds: float, rng: random.Random, rms: float = 2500.0) -> list[bytes]:
    """Noise with a 4Hz syllable envelope that dips close to silence, like speech."""
    frames = []
    for i in range(int(seconds / 0.02)):
        t = i * 0.02
        envelope = 0.15 + 0.85 * max(0.0, math.sin(2 * math.pi * 4 * t)) ** 2
        frames.append(noise(rms * envelope * 1.5, rng))
    return frames


def quiet(seconds: float, rng: random.Random, rms: float = 30.0) -> list[bytes]:
    return [noise(rms, rng) for _ in range(int(seconds / 0.02))]


def fan(seconds: float, rng: random.Random, rms: float = 900.0) -> list[bytes]:
    return [noise(rms * rng.uniform(0.92, 1.08), rng) for _ in range(int(seconds / 0.02))]


def run(detector, frames) -> list[tuple[float, str]]:
    events, t = [], 0.0
    for f in frames:
        t += 0.02
        ev = detector.process(f)
        if ev:
            events.append((round(t, 2), ev.kind))
    return events


def test_detector_satisfies_the_protocol():
    assert isinstance(EnergyTurnDetector(), TurnDetector)


def test_factory_builds_energy_and_rejects_unknown():
    assert isinstance(create_turn_detector("energy", end_ms=500), EnergyTurnDetector)
    with pytest.raises(ValueError):
        create_turn_detector("nope")


def test_silence_produces_no_events():
    rng = random.Random(1)
    assert run(EnergyTurnDetector(), quiet(3, rng)) == []


def test_speech_starts_and_ends_a_turn():
    rng = random.Random(2)
    frames = quiet(1, rng) + speech_frames(2, rng) + quiet(2, rng)
    events = run(EnergyTurnDetector(), frames)
    assert [k for _, k in events] == ["start", "end"]
    start, end = events[0][0], events[1][0]
    assert 1.0 <= start <= 1.4
    assert end > 3.0 + 0.7  # only after the hangover, not at the first pause


def test_short_pauses_inside_speech_do_not_end_the_turn():
    rng = random.Random(3)
    frames = (
        quiet(0.5, rng)
        + speech_frames(1, rng)
        + quiet(0.4, rng)
        + speech_frames(1, rng)
        + quiet(1.5, rng)
    )
    assert [k for _, k in run(EnergyTurnDetector(), frames)] == ["start", "end"]


def test_a_click_shorter_than_start_ms_is_not_a_turn():
    rng = random.Random(4)
    frames = quiet(1, rng) + [noise(4000, rng)] * 2 + quiet(1, rng)
    assert run(EnergyTurnDetector(), frames) == []


def test_steady_fan_noise_from_the_start_never_triggers_a_turn():
    # The old detector treated any peak over 400 as speech and never ended a turn.
    rng = random.Random(5)
    assert run(EnergyTurnDetector(), fan(20, rng)) == []


def test_speech_over_fan_noise_is_detected_and_ends():
    rng = random.Random(6)
    speech = [
        _pcm(
            a + b
            for a, b in zip(
                array("h", s).tolist(), array("h", n).tolist()
            )
        )
        for s, n in zip(speech_frames(2, rng, rms=8000), fan(2, rng))
    ]
    frames = fan(2, rng) + speech + fan(3, rng)
    assert [k for _, k in run(EnergyTurnDetector(), frames)] == ["start", "end"]


def test_fan_switching_on_mid_call_does_not_hold_a_turn_open():
    rng = random.Random(7)
    frames = quiet(2, rng) + fan(12, rng)
    events = run(EnergyTurnDetector(), frames)
    kinds = [k for _, k in events]
    # It may briefly look like a turn, but it must end once the noise is learned.
    assert kinds in ([], ["start", "end"])
    detector = EnergyTurnDetector()
    run(detector, frames)
    assert not detector.is_speaking


def test_noise_floor_rises_with_steady_noise_and_falls_when_it_stops():
    rng = random.Random(8)
    detector = EnergyTurnDetector()
    run(detector, quiet(1, rng))
    low = detector.noise_floor
    run(detector, fan(10, rng))
    high = detector.noise_floor
    run(detector, quiet(2, rng))
    assert high > 10 * low
    assert detector.noise_floor < high / 5


def test_advance_silence_ends_a_turn_when_no_audio_arrives():
    rng = random.Random(9)
    detector = EnergyTurnDetector()
    run(detector, quiet(0.5, rng) + speech_frames(1, rng))
    assert detector.is_speaking
    assert detector.advance_silence(0.5) is None
    assert detector.advance_silence(0.5) == TurnEvent("end")
    assert not detector.is_speaking
    assert detector.advance_silence(5) is None


def test_reset_clears_the_turn_but_keeps_the_noise_floor():
    rng = random.Random(10)
    detector = EnergyTurnDetector()
    run(detector, fan(5, rng) + speech_frames(1, rng, rms=6000))
    floor = detector.noise_floor
    detector.reset()
    assert not detector.is_speaking
    assert detector.noise_floor == floor


def test_chunks_of_any_size_are_handled():
    rng = random.Random(11)
    detector = EnergyTurnDetector()
    frames = quiet(0.5, rng) + speech_frames(1, rng)
    big = [b"".join(frames[i : i + 5]) for i in range(0, len(frames), 5)]
    events = [ev for ev in (detector.process(c) for c in big) if ev]
    assert events and events[0].kind == "start"
    assert detector.process(b"") is None
