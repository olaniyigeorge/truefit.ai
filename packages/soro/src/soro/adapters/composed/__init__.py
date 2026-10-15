"""
The composed adapter: a local STT, LLM and TTS behind LiveSessionPort.

create_composed_adapter() wires the free, local defaults:

    faster-whisper (STT) + an OpenAI-compatible server such as Ollama (LLM) + Piper (TTS)

Any piece can be swapped by building ComposedLiveAdapter directly with your own
SpeechToText / LanguageModel / TextToSpeech. Needs: pip install "soro[composed]",
a running LLM server and a downloaded Piper voice.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Optional

from soro.adapters.composed.adapter import ComposedLiveAdapter
from soro.adapters.composed.components import (
    FakeLanguageModel,
    FakeSpeechToText,
    FakeTextToSpeech,
    LanguageModel,
    LLMChunk,
    SpeechToText,
    TextDelta,
    TextToSpeech,
    ToolCallRequest,
)
from soro.audio.turn import TurnDetector, create_turn_detector

DEFAULT_LLM_URL = "http://localhost:11434/v1"  # Ollama
DEFAULT_LLM_MODEL = "llama3.2"
DEFAULT_STT_MODEL = "base.en"
# Seconds to wait for the server between streamed chunks. Generous because a
# small model on a busy CPU can take most of a minute to read a long prompt.
DEFAULT_LLM_TIMEOUT = 120.0


def create_composed_adapter(
    *,
    llm_base_url: Optional[str] = None,
    llm_model: Optional[str] = None,
    llm_api_key: Optional[str] = None,
    llm_timeout: Optional[float] = None,
    stt_model: Optional[str] = None,
    tts_voice: Optional[str] = None,
    turn_detector: str | TurnDetector = "silero",
) -> ComposedLiveAdapter:
    """
    Arguments fall back to environment variables, as the cloud adapters fall back
    to their API key variables: SORO_LLM_BASE_URL, SORO_LLM_MODEL, SORO_LLM_API_KEY,
    SORO_LLM_TIMEOUT, SORO_STT_MODEL and SORO_PIPER_VOICE (path to the voice .onnx).

    turn_detector defaults to Silero, which ignores steady noise such as a fan;
    pass "energy" for the pure-Python detector.

    Fails here, not mid-call, when a dependency or the voice is missing. The LLM
    server is not contacted until the first reply.
    """
    missing = [
        m
        for m in ("faster_whisper", "piper", "httpx", "numpy")
        if importlib.util.find_spec(m) is None
    ]
    if missing:
        raise ImportError(
            f'The composed adapter needs {", ".join(missing)}. Install them with: pip install "soro[composed]"'
        )
    voice = tts_voice or os.environ.get("SORO_PIPER_VOICE")
    if not voice:
        raise RuntimeError(
            "The composed adapter needs a Piper voice: pass tts_voice= or set SORO_PIPER_VOICE"
        )

    from soro.adapters.composed.faster_whisper_stt import FasterWhisperSTT
    from soro.adapters.composed.openai_compat_llm import OpenAICompatibleLLM
    from soro.adapters.composed.piper_tts import PiperTTS

    detector = (
        create_turn_detector(turn_detector) if isinstance(turn_detector, str) else turn_detector
    )
    return ComposedLiveAdapter(
        stt=FasterWhisperSTT(stt_model or os.environ.get("SORO_STT_MODEL") or DEFAULT_STT_MODEL),
        llm=OpenAICompatibleLLM(
            base_url=llm_base_url or os.environ.get("SORO_LLM_BASE_URL") or DEFAULT_LLM_URL,
            model=llm_model or os.environ.get("SORO_LLM_MODEL") or DEFAULT_LLM_MODEL,
            api_key=llm_api_key or os.environ.get("SORO_LLM_API_KEY"),
            timeout=llm_timeout or float(os.environ.get("SORO_LLM_TIMEOUT") or DEFAULT_LLM_TIMEOUT),
        ),
        tts=PiperTTS(voice),
        turn_detector=detector,
    )


__all__ = [
    "ComposedLiveAdapter",
    "FakeLanguageModel",
    "FakeSpeechToText",
    "FakeTextToSpeech",
    "LLMChunk",
    "LanguageModel",
    "SpeechToText",
    "TextDelta",
    "TextToSpeech",
    "ToolCallRequest",
    "create_composed_adapter",
]
