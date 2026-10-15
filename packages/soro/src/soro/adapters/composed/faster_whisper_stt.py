"""
SpeechToText with faster-whisper, running locally on CPU or GPU.

The model is loaded on first use, in a worker thread, and transcription runs in
one too, so neither blocks the audio loops. The default "base.en" with int8 on
CPU is the latency/quality middle ground for conversation; "small.en" is more
accurate, "tiny.en" faster. Models download from Hugging Face on first load.

Whisper is not streaming: it transcribes a whole utterance after the turn ends,
so its time adds directly to turn latency. That is why it pairs with a turn
detector that ends turns promptly.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional


def _deps():
    try:
        import numpy as np
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ImportError(
            'The faster-whisper STT needs faster-whisper and numpy. Install them with: pip install "soro[composed]"'
        ) from exc
    return np, WhisperModel


class FasterWhisperSTT:
    SAMPLE_RATE = 16_000  # what Whisper expects

    def __init__(
        self,
        model: str = "base.en",
        *,
        device: str = "cpu",
        compute_type: str = "int8",
        language: Optional[str] = "en",
        beam_size: int = 1,
        no_speech_threshold: float = 0.6,
    ) -> None:
        """
        no_speech_threshold: drop segments Whisper itself rates as probably not
        speech. Whisper hallucinates words such as "You" on silence or noise; when
        the turn detector lets a noise blip through, this keeps it from becoming a
        phantom user turn. Real speech scores near 0, silence and noise above 0.7.
        """
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.beam_size = beam_size
        self.no_speech_threshold = no_speech_threshold
        self._model: Any = None
        self._lock = asyncio.Lock()

    async def _load(self) -> Any:
        async with self._lock:
            if self._model is None:
                _, WhisperModel = _deps()
                self._model = await asyncio.to_thread(
                    WhisperModel,
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                )
        return self._model

    async def warm_up(self) -> None:
        """Load the model now rather than on the first utterance."""
        await self._load()

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        if sample_rate != self.SAMPLE_RATE:
            raise ValueError(
                f"faster-whisper needs {self.SAMPLE_RATE}Hz audio, got {sample_rate}Hz"
            )
        if not pcm:
            return ""
        np, _ = _deps()
        model = await self._load()
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0

        def run() -> str:
            # segments is lazy: consume it here, in the worker thread.
            segments, _info = model.transcribe(
                audio,
                language=self.language,
                beam_size=self.beam_size,
                condition_on_previous_text=False,
                vad_filter=False,
            )
            return "".join(
                seg.text for seg in segments if seg.no_speech_prob < self.no_speech_threshold
            ).strip()

        return await asyncio.to_thread(run)
