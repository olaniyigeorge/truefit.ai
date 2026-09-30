"""
The Soro port: the one interface between a voice agent and any realtime model.

Adapters (Gemini Live, OpenAI Realtime, a composed STT -> LLM -> TTS pipeline,
a fake for tests) implement LiveSessionPort. Agents and the runtime only ever
see this file, never a provider SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from soro.errors import CapabilityNotSupported
from soro.tools import ToolSpec

# Event types every LiveSessionPort adapter may yield from receive().
LIVE_EVENT_TYPES = frozenset(
    {
        "audio",  # bytes: PCM at capabilities.output_sample_rate
        "text",  # str: agent output transcript
        "input_text",  # str: user speech transcript
        "tool_call",  # dict: {"id", "name", "args"}
        "turn_complete",  # None: agent finished its turn
        "interrupted",  # None: agent was cut off mid-speech
        "session_ending",  # dict | None: provider is closing, {"reason", ...}
        "session_resumed",  # dict: adapter reconnected, {"reason", "restarted"}
    }
)


@dataclass(frozen=True)
class AdapterCapabilities:
    """
    What a provider adapter can do and the audio formats it speaks. Consumers
    read this instead of assuming Gemini's numbers.

    input_sample_rate / output_sample_rate: mono s16 PCM rates for send_audio()
        and for "audio" events.
    supports_images: send_image() works. When False it raises CapabilityNotSupported.
    native_vad: True means the provider (or the adapter) finds turn boundaries
        itself and callers must not signal them. False means the caller marks
        the boundaries with send_activity_start() / send_activity_end().
    """

    input_sample_rate: int = 16_000
    output_sample_rate: int = 24_000
    supports_images: bool = False
    native_vad: bool = True


class LiveSessionPort(ABC):
    """
    Abstraction over a real-time multimodal AI session.

    Implementations wrap a live AI API (Gemini Live, OpenAI Realtime, a composed
    STT -> LLM -> TTS pipeline, ...) and expose a uniform interface for the agent
    layer. The agent never imports any AI SDK directly. All SDK types are
    confined to the adapter.

    Lifecycle
    ---------
    All methods except open_session() require an active session.
    Sessions are opened and closed via the open_session() context manager:

        async with adapter.open_session(system_prompt, tools=specs) as session:
            await session.send_client_content(text="...")
            await session.send_audio(pcm_bytes)
            async for event_type, data in session.receive():
                ...

    Audio format contract
    ---------------------
    send_audio() takes mono s16 PCM at capabilities.input_sample_rate, and
    "audio" events carry mono s16 PCM at capabilities.output_sample_rate.
    Both default to 16kHz in and 24kHz out. Adapters that differ must say so
    in `capabilities`, and callers must read it rather than hard-code rates.
    """

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Static description of this adapter. Override when it differs from the defaults."""
        return AdapterCapabilities()

    # -- Session lifecycle

    @abstractmethod
    def open_session(
        self,
        system_prompt: str,
        tools: list[ToolSpec] | None = None,
    ) -> Any:
        """
        Return an async context manager that opens and closes the session.
        Must be used as: async with adapter.open_session(...) as session.
        The yielded value is the adapter itself with an active session.

        tools: provider-neutral ToolSpec objects. Adapters translate them to
        their wire format (legacy declaration dicts are also accepted, see
        application.tools.normalize_tools).
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Tear down the active session. Called automatically by open_session()."""
        ...

    # -- Sending

    @abstractmethod
    async def send_audio(self, pcm_bytes: bytes) -> None:
        """
        Stream a raw PCM audio chunk into the session at
        capabilities.input_sample_rate (16kHz mono s16 by default, 20ms is 640 bytes).
        """
        ...

    async def send_activity_start(self) -> None:
        """
        Manual turn signalling: the user started speaking. Only meaningful when
        capabilities.native_vad is False. Optional: the default does nothing.
        """
        return None

    async def send_activity_end(self) -> None:
        """
        Manual turn signalling: the user stopped speaking, so the model should
        respond. Only meaningful when capabilities.native_vad is False.
        Optional: the default does nothing.
        """
        return None

    async def send_audio_stream_end(self) -> None:
        """
        Tell the provider the audio stream itself has ended (auto-VAD modes).
        Optional: the default does nothing.
        """
        return None

    async def send_image(self, jpeg_bytes: bytes, source: str = "camera") -> None:
        """
        Send a JPEG frame for visual context. Optional capability: check
        capabilities.supports_images first. The default raises
        CapabilityNotSupported so a missing capability is never silently dropped.
        source: "camera" | "screen", informational only.
        """
        raise CapabilityNotSupported(
            f"{type(self).__name__} does not support image input"
        )

    @abstractmethod
    async def send_client_content(self, text: str) -> None:
        """
        Inject a one-time structured text message into the session.
        Used before audio begins to pre-load context (job, candidate data).
        Not for conversational turns - use send_audio() for those.
        """
        ...

    @abstractmethod
    async def send_tool_response(
        self,
        *,
        call_id: str,
        name: str,
        result: dict,
    ) -> None:
        """
        Respond to a tool_call event from receive().
        Must be called for every tool_call received - the session blocks
        until a response is provided.
        """
        ...

    # -- Receiving

    @abstractmethod
    async def receive(self) -> AsyncGenerator[tuple[str, Any], None]:
        """
        Async generator yielding normalised (event_type, data) tuples. See
        LIVE_EVENT_TYPES for the full set:

          ("audio",          bytes)        PCM at capabilities.output_sample_rate
          ("text",           str)          agent output transcript
          ("input_text",     str)          user speech transcript
          ("tool_call",      dict)         {"id": str, "name": str, "args": dict}
          ("turn_complete",  None)         agent finished its speaking turn
          ("interrupted",    None)         agent was interrupted mid-speech
          ("session_ending", dict | None)  provider is closing the session,
                                           e.g. {"reason": "provider_go_away", ...}
          ("session_resumed", dict)        the adapter reconnected after a dropped or
                                           recycled connection: {"reason": ..., "restarted": bool}.
                                           restarted=False: the conversation continues, but
                                           the user's last turn may have been lost.
                                           restarted=True: state was lost and the opening
                                           content was replayed, so it begins again.

        The stream covers the whole session: it keeps yielding across turns and
        only ends when the session closes. (Provider SDKs that expose one turn
        per call must be re-entered by the adapter.) Implementations must not
        raise on end-of-stream - simply stop yielding.
        """
        ...

    # -- Health

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Return True if there is an active open session."""
        ...
