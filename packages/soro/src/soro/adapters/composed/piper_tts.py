"""
TextToSpeech with Piper, a fast local neural voice.

A Piper voice is an .onnx model plus a .onnx.json config beside it (download
from the rhasspy/piper-voices repository). The sample rate is read from that
config without loading the model, so the adapter can report its capabilities
before any synthesis happens; most voices are 22.05kHz.

Synthesis runs in a worker thread per sentence. Both the 1.2 API
(synthesize_stream_raw) and the 1.3+ API (synthesize yielding AudioChunks) work.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator, Optional


def _piper():
    try:
        from piper import PiperVoice
    except ImportError:
        try:
            from piper.voice import PiperVoice
        except ImportError as exc:
            raise ImportError(
                'The Piper TTS needs piper-tts. Install it with: pip install "soro[composed]"'
            ) from exc
    return PiperVoice


def voice_sample_rate(voice_path: str | Path, config_path: str | Path | None = None) -> int:
    config = Path(config_path) if config_path else Path(f"{voice_path}.json")
    if not config.exists():
        raise FileNotFoundError(f"Piper voice config not found: {config} (it ships beside the .onnx)")
    return int(json.loads(config.read_text(encoding="utf-8"))["audio"]["sample_rate"])


class PiperTTS:
    def __init__(
        self,
        voice_path: str | Path,
        *,
        config_path: str | Path | None = None,
        sample_rate: Optional[int] = None,
        chunk_ms: int = 100,
    ) -> None:
        """
        voice_path: the voice's .onnx file.
        sample_rate: override when the config cannot be read.
        chunk_ms: size of the audio chunks yielded per sentence.
        """
        self.voice_path = str(voice_path)
        self.config_path = str(config_path) if config_path else None
        self._rate = sample_rate or voice_sample_rate(voice_path, config_path)
        self._chunk_bytes = self._rate * 2 * chunk_ms // 1000
        self._voice: Any = None
        self._lock = asyncio.Lock()

    @property
    def sample_rate(self) -> int:
        return self._rate

    async def _load(self) -> Any:
        async with self._lock:
            if self._voice is None:
                PiperVoice = _piper()
                self._voice = await asyncio.to_thread(PiperVoice.load, self.voice_path, self.config_path)
        return self._voice

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        voice = await self._load()

        def run() -> bytes:
            if hasattr(voice, "synthesize_stream_raw"):  # piper-tts 1.2
                return b"".join(voice.synthesize_stream_raw(text))
            return b"".join(chunk.audio_int16_bytes for chunk in voice.synthesize(text))  # 1.3+

        pcm = await asyncio.to_thread(run)
        for i in range(0, len(pcm), self._chunk_bytes):
            yield pcm[i : i + self._chunk_bytes]
