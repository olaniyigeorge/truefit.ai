"""
Turn-detection eval: the noisy-room scenario.

The scorer is tested with a stub detector so its counting (false triggers, latency)
is exact and independent of any real detector. The energy detector is then run over
the fixtures to lock in its known guarantees (silence and steady fan produce no turn;
real turns are detected). Silero is included when soro[vad] is available.
"""

from __future__ import annotations

import pytest

from soro.audio import EnergyTurnDetector
from soro.audio.turn import TurnEvent, create_turn_detector
from soro.evals import (
    NOISY_ROOM_CASES,
    TurnCase,
    compare_detectors,
    format_report,
    score_case,
)
from soro.evals.audio_fixtures import FRAME_SAMPLES, quiet

pytestmark = pytest.mark.unit

FRAME = b"\x00\x00" * FRAME_SAMPLES


class StubDetector:
    """Emits scripted events at chosen frame indices, so score_case can be checked exactly."""

    def __init__(self, events: dict[int, str]) -> None:
        self._events = events
        self._i = -1
        self._speaking = False

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def process(self, pcm: bytes):
        self._i += 1
        kind = self._events.get(self._i)
        if kind is None:
            return None
        self._speaking = kind == "start"
        return TurnEvent(kind)

    def advance_silence(self, seconds: float):
        return None

    def reset(self) -> None:
        self._speaking = False


def _case(name, n_frames, **kw) -> TurnCase:
    return TurnCase(name=name, frames=[FRAME] * n_frames, **kw)


def test_scorer_counts_false_triggers_in_a_no_speech_case():
    case = _case("noise", 50, speech_present=False)
    result = score_case(lambda: StubDetector({10: "start", 20: "end"}), case)
    assert result.false_starts == 1
    assert result.false_ends == 1
    assert not result.passed


def test_scorer_passes_a_clean_turn_and_measures_end_latency():
    # start at frame 10, end at frame 60 -> t=1.2s; speech actually ended at 1.0s.
    case = _case("turn", 80, speech_present=True, speech_end_s=1.0)
    result = score_case(lambda: StubDetector({10: "start", 60: "end"}), case)
    assert result.detected_turn
    assert result.passed
    assert result.end_latency_ms == pytest.approx(200, abs=1)


def test_scorer_fails_a_missed_turn():
    case = _case("missed", 50, speech_present=True, speech_end_s=0.5)
    result = score_case(lambda: StubDetector({}), case)
    assert not result.detected_turn
    assert not result.passed


def test_noisy_room_cases_exist():
    names = {c.name for c in NOISY_ROOM_CASES}
    assert {"quiet_room", "steady_fan", "fan_switches_on", "speech_in_quiet"} <= names


def test_energy_detector_never_false_triggers_on_quiet_or_steady_fan():
    for name in ("quiet_room", "steady_fan"):
        case = next(c for c in NOISY_ROOM_CASES if c.name == name)
        result = score_case(EnergyTurnDetector, case)
        assert result.false_starts == 0
        assert result.false_ends == 0
        assert result.passed, name


def test_energy_detector_finds_the_speech_cases():
    for name in ("speech_in_quiet", "speech_over_fan"):
        case = next(c for c in NOISY_ROOM_CASES if c.name == name)
        result = score_case(EnergyTurnDetector, case)
        assert result.detected_turn, name
        assert result.end_latency_ms is not None


def test_format_report_renders_a_table():
    results = compare_detectors({"energy": EnergyTurnDetector})
    report = format_report(results)
    assert "energy" in report
    assert "case" in report
    assert "quiet_room" in report


def test_quiet_fixture_length_is_deterministic():
    import random

    assert len(quiet(1.0, random.Random(0))) == 50  # 1s of 20ms frames


# ── With the neural detector, when available


def _vad_available() -> bool:
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    from importlib import resources

    try:
        return resources.files("soro.audio.assets").joinpath("silero_vad.onnx").is_file()
    except (ModuleNotFoundError, FileNotFoundError):
        return False


@pytest.mark.skipif(not _vad_available(), reason="needs soro[vad] and the bundled model")
def test_silero_rejects_steady_fan_as_non_speech():
    case = next(c for c in NOISY_ROOM_CASES if c.name == "steady_fan")
    result = score_case(lambda: create_turn_detector("silero"), case)
    assert result.false_starts == 0
    assert result.false_ends == 0
    assert result.passed
