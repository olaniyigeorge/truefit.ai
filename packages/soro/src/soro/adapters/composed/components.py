"""
The three pieces of a composed voice pipeline, as Protocols, with in-memory fakes.

ComposedLiveAdapter depends only on these, so any STT, LLM or TTS can be dropped
in: the local defaults (faster-whisper, an OpenAI-compatible server such as
Ollama or llama.cpp, Piper) or a hosted one. The fakes make the whole adapter
testable with no models, no network and no audio.

Conversation history uses the OpenAI chat format (role / content / tool_calls /
tool_call_id). It is what local LLM servers speak, so the default LLM passes it
through untouched; other backends translate it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Protocol, Sequence, Union, runtime_checkable

from soro.tools import ToolSpec


@dataclass(frozen=True)
class TextDelta:
    """A fragment of the assistant's reply."""

    text: str


@dataclass(frozen=True)
class ToolCallRequest:
    """The model wants a tool run. Yielded complete, never as fragments."""

    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)


LLMChunk = Union[TextDelta, ToolCallRequest]


@runtime_checkable
class SpeechToText(Protocol):
    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        """One whole utterance of mono s16 PCM in, its transcript out ("" for no speech)."""
        ...


@runtime_checkable
class LanguageModel(Protocol):
    def stream(self, messages: list[dict[str, Any]], tools: list[ToolSpec]) -> AsyncIterator[LLMChunk]:
        """Stream the next assistant message: text fragments and/or complete tool calls."""
        ...


@runtime_checkable
class TextToSpeech(Protocol):
    @property
    def sample_rate(self) -> int:
        """Rate of the PCM synthesize() yields. It becomes the adapter's output_sample_rate."""
        ...

    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Speak one sentence as a stream of mono s16 PCM chunks."""
        ...


# ── Fakes


class FakeSpeechToText:
    """Returns scripted transcripts in order (or computes one from the audio)."""

    def __init__(self, transcripts: Sequence[str] | Callable[[bytes], str] = ()) -> None:
        self._script = transcripts if callable(transcripts) else list(transcripts)
        self.heard: list[int] = []  # byte length of each utterance

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        self.heard.append(len(pcm))
        if callable(self._script):
            return self._script(pcm)
        return self._script.pop(0) if self._script else ""


class FakeLanguageModel:
    """
    Each stream() call plays the next scripted reply. A reply is a list of chunks;
    plain strings are shorthand for TextDelta. `delay_s` paces the chunks so tests
    can interrupt mid-reply.
    """

    def __init__(self, replies: Sequence[Sequence[LLMChunk | str]] = (), delay_s: float = 0.0) -> None:
        self._replies = [list(r) for r in replies]
        self.delay_s = delay_s
        self.seen: list[list[dict[str, Any]]] = []  # the history each call was given
        self.tools_seen: list[list[str]] = []

    async def stream(self, messages: list[dict[str, Any]], tools: list[ToolSpec]) -> AsyncIterator[LLMChunk]:
        self.seen.append([dict(m) for m in messages])
        self.tools_seen.append([t.name for t in tools])
        reply = self._replies.pop(0) if self._replies else []
        for chunk in reply:
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            yield TextDelta(chunk) if isinstance(chunk, str) else chunk


class FakeTextToSpeech:
    """
    One 20ms chunk of silence per `chars_per_chunk` characters (at least one), so
    longer sentences produce more audio. `delay_s` paces chunks like real playback.
    """

    def __init__(self, sample_rate: int = 24_000, chars_per_chunk: int = 10, delay_s: float = 0.0) -> None:
        self._rate = sample_rate
        self.chars_per_chunk = chars_per_chunk
        self.delay_s = delay_s
        self.spoken: list[str] = []

    @property
    def sample_rate(self) -> int:
        return self._rate

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        self.spoken.append(text)
        chunk = b"\x00\x00" * (self._rate // 50)
        for _ in range(max(1, len(text) // self.chars_per_chunk)):
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            yield chunk
