"""
Silero turn detection: a neural TurnDetector.

EnergyTurnDetector decides speech from loudness, so it can be fooled by loud
non-speech (it fights a fan with an adaptive floor, but loud steady machinery is
still a hard case). Silero is a small trained model that classifies the acoustics
of speech, so it rejects noise that an energy detector would hold a turn open on.

It implements the same TurnDetector protocol as EnergyTurnDetector, so it is a
drop-in: AudioBridge, the runtime and the evals treat the two the same. The design
keeps the hangover state machine (how long speech must persist to start a turn,
how long silence must persist to end one) separate from the model, so:

  - the timing logic is tested with an injected probability function, no model, no
    onnxruntime, fully deterministic;
  - the model is loaded lazily from a bundled ONNX file, so importing this module
    costs nothing and the "install soro[vad]" hint only fires when you build one.

Silero's ONNX model runs on fixed windows (512 samples at 16kHz, 256 at 8kHz), so
process() buffers arbitrary chunk sizes into whole windows before inference.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Callable, Optional

from soro.audio.turn import TurnEvent

# Shipped with the package (MIT licensed, from snakers4/silero-vad). Loaded via
# importlib.resources so it works whether installed as a wheel or run from source.
_MODEL_PACKAGE = "soro.audio.assets"
_MODEL_FILE = "silero_vad.onnx"

# Silero's supported window sizes, in samples, keyed by sample rate.
_WINDOW_SAMPLES = {16_000: 512, 8_000: 256}
# Samples of the previous window that Silero v5 reads before each new one.
_CONTEXT_SAMPLES = {16_000: 64, 8_000: 32}

SpeechProb = Callable[[bytes], float]
"""Maps one window of 16-bit mono PCM to a speech probability in [0, 1]."""


@dataclass(frozen=True)
class SileroTurnConfig:
    sample_rate: int = 16_000
    # A window above `threshold` is speech, below `threshold_off` is silence;
    # the gap is hysteresis so a probability hovering at the edge does not flap.
    threshold: float = 0.5
    threshold_off: float = 0.35
    start_ms: int = 100  # sustained speech before a turn starts
    end_ms: int = 800  # sustained silence before a turn ends (the hangover)

    def __post_init__(self) -> None:
        if self.sample_rate not in _WINDOW_SAMPLES:
            raise ValueError(
                f"Silero supports {sorted(_WINDOW_SAMPLES)} Hz, not {self.sample_rate}."
            )

    @property
    def window_samples(self) -> int:
        return _WINDOW_SAMPLES[self.sample_rate]


class SileroTurnDetector:
    def __init__(
        self,
        config: SileroTurnConfig | None = None,
        *,
        speech_prob: SpeechProb | None = None,
        model_path: str | None = None,
    ) -> None:
        """
        speech_prob: supply a probability function to bypass the model entirely
            (used in tests to drive the state machine deterministically).
        model_path: load a different ONNX model instead of the bundled one.
        With neither, the bundled model is loaded lazily, which needs soro[vad].
        """
        self.config = config or SileroTurnConfig()
        self._buf = bytearray()
        self._speaking = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._last_prob = 0.0
        self._speech_prob = speech_prob or self._load_onnx(model_path)

    # ── Protocol surface

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    @property
    def last_speech_prob(self) -> float:
        """The most recent window's probability, for debugging and the evals."""
        return self._last_prob

    def reset(self) -> None:
        # Mirror EnergyTurnDetector.reset: forget the current turn, keep what the
        # model has learned (its recurrent state is short-term acoustic context).
        self._speaking = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0

    def process(self, pcm: bytes) -> Optional[TurnEvent]:
        self._buf += pcm
        win_bytes = self.config.window_samples * 2
        frame_ms = self.config.window_samples * 1000 / self.config.sample_rate
        while len(self._buf) >= win_bytes:
            window = bytes(self._buf[:win_bytes])
            del self._buf[:win_bytes]
            self._last_prob = self._speech_prob(window)
            event = self._step(self._last_prob, frame_ms)
            if event is not None:
                # Leave any still-buffered windows for the next call so no boundary
                # is dropped and the model state stays in step with what was reported.
                return event
        return None

    def advance_silence(self, seconds: float) -> Optional[TurnEvent]:
        if not self._speaking:
            return None
        self._silence_ms += seconds * 1000
        if self._silence_ms >= self.config.end_ms:
            self.reset()
            return TurnEvent("end")
        return None

    # ── State machine (identical shape to EnergyTurnDetector._step, prob-driven)

    def _step(self, prob: float, frame_ms: float) -> Optional[TurnEvent]:
        cfg = self.config
        if not self._speaking:
            if prob >= cfg.threshold:
                self._speech_ms += frame_ms
                if self._speech_ms >= cfg.start_ms:
                    self._speaking = True
                    self._speech_ms = 0.0
                    self._silence_ms = 0.0
                    return TurnEvent("start")
            else:
                # Leak rather than reset, so a dip between syllables does not erase
                # the evidence gathered so far.
                self._speech_ms = max(0.0, self._speech_ms - frame_ms / 2)
            return None
        if prob < cfg.threshold_off:
            self._silence_ms += frame_ms
            if self._silence_ms >= cfg.end_ms:
                self.reset()
                return TurnEvent("end")
        else:
            self._silence_ms = 0.0
        return None

    # ── Model

    def _load_onnx(self, model_path: str | None) -> SpeechProb:
        try:
            import numpy as np
            import onnxruntime as ort
        except ImportError as exc:  # pragma: no cover - exercised via create_turn_detector
            raise ImportError(
                "The silero turn detector needs onnxruntime and numpy. "
                'Install them with: pip install "soro[vad]"'
            ) from exc

        session = _inference_session(model_path)

        # Silero shipped two input shapes: v5 uses a single `state` tensor, older
        # exports used separate `h`/`c`. Read the signature instead of assuming.
        input_names = [i.name for i in session.get_inputs()]
        has_sr = "sr" in input_names
        uses_state = "state" in input_names
        audio_input = next(n for n in input_names if n not in {"state", "sr", "h", "c"})
        sr = np.array(self.config.sample_rate, dtype=np.int64)

        # The recurrent state lives in a dict so the closure can update it in place,
        # without nonlocal names that only exist on one branch.
        if uses_state:
            rnn = {"state": np.zeros((2, 1, 128), dtype=np.float32)}
        else:
            rnn = {
                "h": np.zeros((2, 1, 64), dtype=np.float32),
                "c": np.zeros((2, 1, 64), dtype=np.float32),
            }

        # v5 expects each window prefixed with the tail of the previous one (64
        # samples at 16kHz, 32 at 8kHz), as silero-vad's own wrapper does. Without
        # it the model scores clear speech near zero, so no turn would ever start.
        context_len = _CONTEXT_SAMPLES[self.config.sample_rate] if uses_state else 0
        context = {"tail": np.zeros(context_len, dtype=np.float32)}

        def prob(window: bytes) -> float:
            samples = np.frombuffer(window, dtype="<i2").astype(np.float32) / 32768.0
            audio = np.concatenate([context["tail"], samples]).reshape(1, -1)
            if context_len:
                context["tail"] = samples[-context_len:]
            feeds = {audio_input: audio, **rnn}
            if has_sr:
                feeds["sr"] = sr
            out = session.run(None, feeds)
            if uses_state:
                rnn["state"] = out[1]
            else:
                rnn["h"], rnn["c"] = out[1], out[2]
            return float(np.asarray(out[0]).reshape(-1)[0])

        return prob


@lru_cache(maxsize=None)
def _inference_session(model_path: str | None):
    """
    One ONNX session per model, shared by every detector. Building a session costs
    about 150ms, which a server would otherwise pay on every call. Sharing is safe:
    InferenceSession.run is thread-safe and each detector keeps its own recurrent
    state in its prob() closure, never in the session.
    """
    import onnxruntime as ort

    if model_path is not None:
        model = model_path
    else:
        model = resources.files(_MODEL_PACKAGE).joinpath(_MODEL_FILE).read_bytes()

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    return ort.InferenceSession(model, sess_options=options, providers=["CPUExecutionProvider"])
