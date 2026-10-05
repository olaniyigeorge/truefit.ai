"""
Silero turn detector.

Two layers, tested separately:

- The hangover state machine (start/end timing, hysteresis, leak, advance_silence)
  is driven through an injected probability function, so it runs everywhere with no
  model and no onnxruntime, and is fully deterministic.
- The real ONNX model gets a lighter check that skips unless soro[vad] is installed
  and the bundled model is present: it must load, run, and read silence as non-speech.
"""

from __future__ import annotations

from importlib import resources

import pytest

from soro.audio.silero import SileroTurnConfig, SileroTurnDetector
from soro.audio.turn import TurnDetector, TurnEvent, create_turn_detector

pytestmark = pytest.mark.unit

WIN = 512  # samples per window at 16kHz
SILENCE_WINDOW = b"\x00\x00" * WIN  # content is irrelevant when a probability is injected


class Prob:
    """A controllable speech-probability source. Set .value between calls."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value
        self.calls = 0

    def __call__(self, window: bytes) -> float:
        self.calls += 1
        return self.value


def _detector(value: float = 0.0, **cfg) -> tuple[SileroTurnDetector, Prob]:
    prob = Prob(value)
    return SileroTurnDetector(SileroTurnConfig(**cfg), speech_prob=prob), prob


def test_satisfies_the_protocol():
    det, _ = _detector()
    assert isinstance(det, TurnDetector)


def test_rejects_an_unsupported_sample_rate():
    with pytest.raises(ValueError):
        SileroTurnConfig(sample_rate=44_100)


def test_speech_starts_a_turn_after_start_ms():
    det, prob = _detector(value=0.9)  # default start_ms=100, window=32ms
    # 32, 64, 96 ms: not yet; 128 ms crosses 100.
    assert det.process(SILENCE_WINDOW) is None
    assert det.process(SILENCE_WINDOW) is None
    assert det.process(SILENCE_WINDOW) is None
    assert det.process(SILENCE_WINDOW) == TurnEvent("start")
    assert det.is_speaking


def test_silence_ends_a_turn_only_after_the_hangover():
    det, prob = _detector(value=0.9, end_ms=800)
    for _ in range(4):
        det.process(SILENCE_WINDOW)
    assert det.is_speaking
    prob.value = 0.0
    # 800ms / 32ms = 25 low windows before the turn ends.
    for _ in range(24):
        assert det.process(SILENCE_WINDOW) is None
    assert det.process(SILENCE_WINDOW) == TurnEvent("end")
    assert not det.is_speaking


def test_a_short_dip_between_syllables_does_not_end_the_turn():
    det, prob = _detector(value=0.9)
    for _ in range(4):
        det.process(SILENCE_WINDOW)
    assert det.is_speaking
    prob.value = 0.0  # a brief pause, well under end_ms
    for _ in range(5):
        det.process(SILENCE_WINDOW)
    prob.value = 0.9  # speech resumes
    det.process(SILENCE_WINDOW)
    assert det.is_speaking  # the pause was absorbed, not treated as end-of-turn


def test_a_click_shorter_than_start_ms_is_not_a_turn():
    det, prob = _detector(value=0.9)
    det.process(SILENCE_WINDOW)  # 32ms of speech, below start_ms
    det.process(SILENCE_WINDOW)  # 64ms
    prob.value = 0.0
    for _ in range(5):
        assert det.process(SILENCE_WINDOW) is None
    assert not det.is_speaking


def test_process_handles_chunks_of_any_size():
    # Five windows in a single call: the start fires inside the chunk, the rest
    # is left buffered so no boundary is dropped.
    det, _ = _detector(value=0.9)
    event = det.process(SILENCE_WINDOW * 5)
    assert event == TurnEvent("start")
    assert det.is_speaking
    assert det.process(b"") is None


def test_advance_silence_ends_a_turn_when_no_audio_arrives():
    det, _ = _detector(value=0.9, end_ms=800)
    for _ in range(4):
        det.process(SILENCE_WINDOW)
    assert det.is_speaking
    assert det.advance_silence(0.5) is None
    assert det.advance_silence(0.4) == TurnEvent("end")  # 900ms total
    assert not det.is_speaking
    assert det.advance_silence(5) is None


def test_reset_clears_the_turn():
    det, _ = _detector(value=0.9)
    for _ in range(4):
        det.process(SILENCE_WINDOW)
    assert det.is_speaking
    det.reset()
    assert not det.is_speaking


def test_last_speech_prob_tracks_the_latest_window():
    det, prob = _detector(value=0.73)
    det.process(SILENCE_WINDOW)
    assert det.last_speech_prob == pytest.approx(0.73)


# ── Real model (skips unless soro[vad] and the bundled model are present)


def _vad_available() -> bool:
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    try:
        return resources.files("soro.audio.assets").joinpath("silero_vad.onnx").is_file()
    except (ModuleNotFoundError, FileNotFoundError):
        return False


requires_vad = pytest.mark.skipif(
    not _vad_available(), reason='needs soro[vad] and the bundled silero_vad.onnx'
)


@requires_vad
def test_factory_builds_the_real_silero_detector():
    det = create_turn_detector("silero")
    assert isinstance(det, SileroTurnDetector)


@requires_vad
def test_real_model_reads_silence_as_non_speech():
    det = create_turn_detector("silero")
    frame = b"\x00\x00" * 320  # 20ms of silence
    for _ in range(50):  # 1 second
        assert det.process(frame) is None
    assert not det.is_speaking
    assert det.last_speech_prob < 0.5
