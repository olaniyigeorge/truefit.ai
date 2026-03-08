# src/truefit_infra/llm/gemini_live.py
"""
GeminiLiveAdapter — Gemini Live API session wrapper for real-time interviews.

This adapter is the ONLY place in the codebase that imports or references the
Google GenAI SDK. All other layers (agent, websocket handler, orchestration)
interact with Gemini exclusively through this adapter's interface.

Responsibilities
────────────────
- Own the genai.Client and the Live session lifecycle
- Accept raw PCM audio from the WebRTC AudioBridge and forward to Gemini
- Accept JPEG frames from the FrameSampler and forward to Gemini
- Normalise raw LiveServerMessage responses into typed (event_type, data) tuples
- Expose send_client_content() for one-time context injection at session start
- Expose send_tool_response() so the agent can respond to Gemini tool calls

Audio format contract
─────────────────────
  Inbound  (browser → Gemini):  16kHz mono s16 PCM
  Outbound (Gemini → browser):  24kHz mono s16 PCM

  The WebRTC AudioBridge handles resampling on both ends.

Event types yielded by receive()
─────────────────────────────────
  ("audio",         bytes)  — 24kHz PCM chunk, forward to candidate speaker
  ("text",          str)    — agent output transcript (captions)
  ("input_text",    str)    — candidate speech transcript (captions)
  ("tool_call",     dict)   — {"id", "name", "args"} — agent wants to call a tool
  ("turn_complete", None)   — agent finished speaking its turn
  ("interrupted",   None)   — agent was interrupted mid-speech by candidate
  ("go_away",       None)   — server is about to close the connection

Usage
─────
  adapter = GeminiLiveAdapter()

  async with adapter.open_session(system_prompt, tools=INTERVIEW_TOOLS) as session:
      await session.send_client_content(text="Interview context...")
      await asyncio.gather(
          send_audio_loop(session),
          receive_loop(session),
      )
"""
from __future__ import annotations

from typing import Any, AsyncGenerator, Optional

from google import genai
from google.genai import types

from src.truefit_core.application.ports import LiveSessionPort
from src.truefit_infra.config import AppConfig
from src.truefit_core.common.utils import logger

_MODEL = "gemini-live-2.5-flash-preview" # "gemini-2.0-flash-live-001"  # "gemini-live-2.5-flash-native-audio" or "gemini-live-2.5-flash-native-audio"
_INPUT_SAMPLE_RATE = 16_000
_OUTPUT_SAMPLE_RATE = 24_000
_INPUT_MIME = f"audio/pcm;rate={_INPUT_SAMPLE_RATE}"


class GeminiLiveAdapter(LiveSessionPort):

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or AppConfig.GEMINI_API_KEY
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        self._client = genai.Client(api_key=key)
        self._session: Optional[Any] = None

    # ── LiveSessionPort interface ──

    async def connect(self, system_prompt: str) -> None:
        raise NotImplementedError("Use GeminiLiveAdapter.open_session() context manager.")

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Forward a 16kHz mono s16 PCM chunk from WebRTC into the live session."""
        _require_session(self._session)
        await self._session.send_realtime_input(
            audio=types.Blob(data=pcm_bytes, mime_type=_INPUT_MIME)
        )

    async def send_image(self, jpeg_bytes: bytes, source: str = "camera") -> None:
        """Forward a JPEG frame (camera or screen share) into the live session."""
        _require_session(self._session)
        await self._session.send_realtime_input(
            video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
        )

    async def send_client_content(self, text: str) -> None:
        """
        Inject a one-time structured text message before audio begins.
        Used by LiveInterviewAgent to pre-load job + candidate context
        into the model's context window at session start.
        """
        _require_session(self._session)
        await self._session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=text)],
            ),
            turn_complete=True,
        )

    async def send_tool_response(self, *, call_id: str, name: str, result: dict) -> None:
        """
        Respond to a tool_call event. Must be called for every tool_call
        received — Gemini blocks the session until a response is provided.
        """
        _require_session(self._session)
        await self._session.send_tool_response(
            function_responses=types.FunctionResponse(
                name=name,
                response=result,
                id=call_id,
            )
        )

    async def receive(self) -> AsyncGenerator[tuple[str, Any], None]:
        """
        Async generator that normalises raw LiveServerMessages into typed tuples.
        See module docstring for the full list of event types.
        """
        _require_session(self._session)

        async for response in self._session.receive():

            if response.data:
                yield ("audio", response.data)

            sc = response.server_content
            if sc:
                if sc.interrupted:
                    yield ("interrupted", None)
                if sc.turn_complete:
                    yield ("turn_complete", None)
                if sc.output_transcription:
                    yield ("text", sc.output_transcription.text)
                if sc.input_transcription:
                    yield ("input_text", sc.input_transcription.text)
                if sc.model_turn and sc.model_turn.parts:
                    for part in sc.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            yield ("audio", part.inline_data.data)

            if response.tool_call:
                for fn_call in response.tool_call.function_calls:
                    yield ("tool_call", {
                        "id":   fn_call.id,
                        "name": fn_call.name,
                        "args": dict(fn_call.args),
                    })

            if response.go_away:
                logger.warning(f"[GeminiLive] go_away: time_left={response.go_away.time_left}")
                yield ("go_away", None)

    async def close(self) -> None:
        self._session = None

    async def is_healthy(self) -> bool:
        return self._session is not None

    # ── Session context manager ───────────────────────────────────────────────

    def open_session(
        self,
        system_prompt: str,
        tools: list | None = None,
    ) -> "_LiveSessionContext":
        """
        Returns an async context manager that opens and closes the Gemini
        Live session. This is the only supported way to use the adapter.

        Example:
            async with adapter.open_session(prompt, tools=TOOLS) as session:
                await session.send_client_content(...)
                async for event, data in session.receive():
                    ...
        """
        return _LiveSessionContext(
            adapter=self,
            system_prompt=system_prompt,
            tools=tools or [],
        )


# ── Session context manager impl ─────────────────────────────────────────────

class _LiveSessionContext:
    """
    Owns the SDK-level async context manager for one Gemini Live session.
    Entered via GeminiLiveAdapter.open_session().
    Sets adapter._session on enter, clears it on exit.
    """

    def __init__(
        self,
        *,
        adapter: GeminiLiveAdapter,
        system_prompt: str,
        tools: list,
    ) -> None:
        self._adapter = adapter
        self._system_prompt = system_prompt
        self._tools = tools
        self._cm = None

    async def __aenter__(self) -> GeminiLiveAdapter:
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self._system_prompt,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
                )
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                )
            ),
            tools=self._tools or None,
        )

        self._cm = self._adapter._client.aio.live.connect(model=_MODEL, config=config)
        session = await self._cm.__aenter__()
        self._adapter._session = session
        logger.info("[GeminiLive] Session opened")
        return self._adapter

    async def __aexit__(self, *args) -> None:
        self._adapter._session = None
        if self._cm:
            await self._cm.__aexit__(*args)
        logger.info("[GeminiLive] Session closed")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_session(session: Any) -> None:
    """Raise clearly if a method is called outside an open_session() context."""
    if session is None:
        raise RuntimeError(
            "GeminiLiveAdapter: no active session. "
            "All calls must be made inside an open_session() context manager."
        )