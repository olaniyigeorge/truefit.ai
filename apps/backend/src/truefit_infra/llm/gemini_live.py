"""
GeminiLiveAdapter - Gemini Live API session wrapper for real-time interviews.

This adapter is the ONLY place in the codebase that imports or references the
Google GenAI SDK. All other layers (agent, websocket handler, orchestration)
interact with Gemini exclusively through this adapter's interface.


WHY THIS ADAPTER EXISTS

The Gemini Live API is a streaming, session-based API with a specific SDK.
By wrapping it entirely here, we achieve two things:

1. ISOLATION - If Google changes the SDK, or we swap to a different model
   provider entirely, we only change this file. The agent, orchestration,
   and WebSocket layers are completely unaware of Gemini internals.

2. NORMALISATION - The raw Gemini SDK responses are complex objects with
   optional fields. This adapter normalises them into simple (event_type, data)
   tuples that the agent can switch on cleanly.


AUDIO FORMAT CONTRACT (IMPORTANT - the WebRTC layer depends on this)

  Inbound  (browser -> Gemini):  16kHz mono s16 PCM
  Outbound (Gemini -> browser):  24kHz mono s16 PCM

  The WebRTC AudioBridge resamples in both directions:
    - Browser sends 48kHz Opus -> AudioBridge resamples to 16kHz PCM -> us
    - We yield 24kHz PCM -> AudioBridge resamples to 48kHz -> browser


EVENT TYPES YIELDED BY receive()

  ("audio",         bytes)  - 24kHz PCM chunk, forward to candidate speaker
  ("text",          str)    - agent output transcript (captions)
  ("input_text",    str)    - candidate speech transcript (captions)
  ("tool_call",     dict)   - {"id", "name", "args"} - agent wants to call a tool
  ("turn_complete", None)   - agent finished speaking its turn
  ("interrupted",   None)   - agent was interrupted mid-speech by candidate
  ("session_ending", dict)  - server is about to close the connection ({"reason", "time_left"})


USAGE PATTERN (how LiveInterviewAgent uses this)

  adapter = GeminiLiveAdapter()

  async with adapter.open_session(system_prompt, tools=INTERVIEW_TOOLS) as session:
      await session.send_client_content(text="Interview context...")
      await asyncio.gather(
          send_audio_loop(session),   # calls session.send_audio() in a loop
          receive_loop(session),       # iterates session.receive()
      )
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from websockets.exceptions import ConnectionClosed

from src.truefit_core.application.ports import AdapterCapabilities, LiveSessionPort
from src.truefit_core.application.tools import ToolSpec, normalize_tools
from src.truefit_infra.config import AppConfig
from src.truefit_core.common.utils import logger

# ───────────────────────
# MODEL & AUDIO CONSTANTS
# ───────────────────────
# Using the native audio preview model - this gives us native audio I/O
# (both input and output are raw audio, no text intermediate step).
# The previous models (gemini-2.0-flash-live-001) required text-to-speech
# separately; this model does it natively and sounds more natural.


# Override with GEMINI_LIVE_MODEL. This is a preview model; opaque 1011 "Internal
# error" closes are common on preview Live models, which is why sessions resume.
_DEFAULT_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

# Close codes that mean "the connection or server hiccuped, try again", as
# opposed to a bad request that would fail the same way on every retry.
_TRANSIENT_CLOSE_CODES = {1001, 1006, 1011, 1012, 1013}
# Reconnects allowed in a row without a single message arriving in between.
_MAX_CONSECUTIVE_RECONNECTS = 3

_INPUT_SAMPLE_RATE = 16_000  # Gemini expects 16kHz inbound
_OUTPUT_SAMPLE_RATE = 24_000  # Gemini outputs at 24kHz
_INPUT_MIME = f"audio/pcm;rate={_INPUT_SAMPLE_RATE}"  # MIME type for sending audio


class GeminiLiveAdapter(LiveSessionPort):
    """
    Wraps the Google GenAI Live API for the interview system.

    This class is instantiated once per WebSocket connection (via get_gemini_live()
    dependency factory). It holds:
      - The genai.Client (authenticated, shared across session opens)
      - A reference to the currently active session (None when no session is open)

    The ONLY way to use this adapter is through the open_session() context manager.
    Calling send_audio(), receive(), etc. outside of it will raise RuntimeError.

    Implements LiveSessionPort (the abstract port from the core layer) so that
    higher layers can type-hint against the port, not this concrete adapter.
    """

    def __init__(self, api_key: str | None = None) -> None:
        """
        Initialises the Gemini client with the API key.
        Key resolution order: explicit arg -> AppConfig.GEMINI_API_KEY env var.
        Raises RuntimeError at construction time if no key is found - fail fast.
        """
        key = api_key or AppConfig.GEMINI_API_KEY
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        self._client = genai.Client(api_key=key)
        self._session: Optional[Any] = (
            None  # Set to the live session inside open_session()
        )
        self._send_lock = asyncio.Lock()  # Lock to prevent concurrent audio sends
        self._activity_ended = False
        self._model: str = getattr(AppConfig, "GEMINI_LIVE_MODEL", None) or _DEFAULT_MODEL
        # Reconnect state (see _try_reconnect). The handle is Gemini's server-side
        # session-resumption token; with it a new connection continues the same
        # conversation. Without one we can only start over and replay.
        self._ctx: Optional["_LiveSessionContext"] = None
        self._resume_handle: Optional[str] = None
        self._sent_content: list[str] = []
        self._consecutive_reconnects = 0
        self._session_ready = asyncio.Event()  # cleared while a reconnect is in flight
        self._session_ready.set()

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            input_sample_rate=_INPUT_SAMPLE_RATE,
            output_sample_rate=_OUTPUT_SAMPLE_RATE,
            supports_images=True,
            native_vad=False,  # we run with automatic_activity_detection disabled and signal activity explicitly
        )
 
    # ─────────────────────────
    # LiveSessionPort interface
    # ─────────────────────────
    # These methods implement the abstract port. The agent only calls these -
    # it never touches the genai SDK directly.

    async def connect(self, system_prompt: str) -> None:
        """
        Not used in this implementation - open_session() is the correct way
        to start a session. Raising here makes the misuse obvious immediately.
        """
        raise NotImplementedError(
            "Use GeminiLiveAdapter.open_session() context manager."
        )

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """
        Forwards a chunk of microphone audio from the browser to Gemini.

        Input format: 16kHz mono s16 PCM (resampled by AudioBridge from 48kHz Opus)
        This is called in a tight loop by VoiceAgentRuntime._send_audio_loop().

        We silently skip empty chunks - the AudioBridge occasionally sends
        zero-length bytes as a keepalive and we don't want to waste API calls.
        """
        session = await self._live()
        if not pcm_bytes or self._activity_ended:
            return
        await session.send_realtime_input(
            media=types.Blob(data=pcm_bytes, mime_type=_INPUT_MIME)
        )

    async def send_audio_stream_end(self) -> None:
        """
        NOTE: Do NOT call this when automatic_activity_detection is disabled.
        Per the Vertex AI Live API reference: "An AudioStreamEnd isn't sent in
        this configuration. Instead, any interruption of the stream is marked
        by an ActivityEnd message."
        This method is retained for potential future use with auto-VAD mode only.
        """
        session = await self._live()
        async with self._send_lock:
            await session.send_realtime_input(audio_stream_end=True)

    async def send_image(self, jpeg_bytes: bytes, source: str = "camera") -> None:
        """
        Forwards a JPEG frame from the candidate's camera or screen share to Gemini.

        The source parameter ('camera' or 'screen') is informational - Gemini
        receives both as image/jpeg. The FrameSampler in WebRTCClient samples
        frames at configurable intervals (frame_interval_camera, frame_interval_screen)
        and calls this to inject visual context into the interview session.

        This enables the interviewer to see what the candidate is doing -
        useful for coding interviews where the candidate shares their screen.
        """
        session = await self._live()
        await session.send_realtime_input(
            video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
        )

    async def send_client_content(self, text: str) -> None:
        """
        Injects a structured text message into the session before audio begins.

        Used once at session start by VoiceAgentRuntime (opening message) to
        pre-load the job details, candidate info, and interview instructions
        into Gemini's context window. This is separate from the system prompt -
        it's a user-turn message that gives Gemini the specific data it needs
        for this particular interview.

        turn_complete=True tells Gemini to process this as a complete turn and
        respond - it will generate the opening greeting immediately after.
        """
        session = await self._live()
        self._sent_content.append(text)  # replayed if the session must restart from scratch
        await session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=text)],
            ),
            turn_complete=True,
        )

    async def send_tool_response(
        self, *, call_id: str, name: str, result: dict
    ) -> None:
        """
        Responds to a tool call that Gemini made.

        When Gemini decides to call a function (record_question, persist_answer,
        complete_interview, flag_interrupt), it yields a "tool_call" event from
        receive(). The agent handles the tool call and then MUST call this method
        to unblock Gemini - it won't continue until it gets a response.

        call_id must match the id from the tool_call event exactly.
        result is whatever dict the tool handler returned.
        """
        session = await self._live()
        await session.send_tool_response(
            function_responses=types.FunctionResponse(
                name=name,
                response=result,
                id=call_id,
            )
        )

    async def _live(self) -> Any:
        """The live SDK session, waiting first if a reconnect is in flight."""
        await self._session_ready.wait()
        _require_session(self._session)
        return self._session

    async def _try_reconnect(self, reason: str) -> bool:
        """
        Replace a dead or expiring SDK session and report whether it worked.

        With a resumption handle the new connection continues the same
        conversation server-side. With no handle yet (the failure came very early)
        we start over and replay the client content, which restores the opening
        message. Senders wait on _session_ready meanwhile. Gives up after a few
        reconnects in a row with nothing received in between, so a request that
        can never work fails instead of looping.
        """
        ctx = self._ctx
        if ctx is None or self._consecutive_reconnects >= _MAX_CONSECUTIVE_RECONNECTS:
            return False
        self._consecutive_reconnects += 1
        self._session_ready.clear()
        try:
            await asyncio.sleep(0.25 * (self._consecutive_reconnects - 1))  # brief backoff
            handle = self._resume_handle
            await ctx.reopen(handle)
            self._activity_ended = True  # audio waits for the next activity_start
            if handle is None:
                for text in list(self._sent_content):
                    await self._session.send_client_content(
                        turns=types.Content(role="user", parts=[types.Part(text=text)]),
                        turn_complete=True,
                    )
            logger.warning(
                f"[GeminiLive] reconnected after {reason} "
                f"({'resumed' if handle else 'restarted, opening message replayed'})"
            )
            return True
        except Exception as exc:
            logger.error(f"[GeminiLive] reconnect after {reason} failed: {exc!r}")
            return False
        finally:
            self._session_ready.set()

    @staticmethod
    def _is_transient(exc: BaseException) -> bool:
        if isinstance(exc, ConnectionClosed):
            return True
        if isinstance(exc, genai_errors.APIError):
            return exc.code in _TRANSIENT_CLOSE_CODES
        return False

    async def _messages(self) -> AsyncGenerator[Any, None]:
        """
        Every message from the Gemini session, across turns and reconnects.

        The SDK's session.receive() covers ONE model turn: it stops right after
        turn_complete. Reading it once (as this adapter used to) meant the agent
        answered the greeting and then never again, while the mic stayed open.
        So keep re-entering it until the session closes.

        Two kinds of trouble are absorbed here rather than ending the interview:
        a transient close (1011 "Internal error" and friends) and Gemini's go_away
        notice that the connection is about to be recycled. Either way we
        reconnect and yield a _Resumed marker so the agent can re-orient.
        """
        empty_passes = 0
        while self._session is not None:
            got_any = False
            try:
                async for response in self._session.receive():
                    got_any = True
                    self._consecutive_reconnects = 0  # the connection is delivering
                    update = getattr(response, "session_resumption_update", None)
                    if update is not None and update.new_handle and update.resumable:
                        self._resume_handle = update.new_handle
                    if response.go_away and self._resume_handle:
                        logger.info(
                            f"[GeminiLive] go_away (time_left={response.go_away.time_left}), resuming"
                        )
                        if await self._try_reconnect("go_away"):
                            yield _Resumed("go_away")
                            break  # continue on the new session
                    yield response
            except Exception as exc:
                if not self._is_transient(exc):
                    raise
                logger.warning(f"[GeminiLive] transient session failure: {exc!r}")
                if await self._try_reconnect(f"{type(exc).__name__} {getattr(exc, 'code', '')}".strip()):
                    yield _Resumed("connection_error")
                    continue
                raise
            empty_passes = 0 if got_any else empty_passes + 1
            if empty_passes >= 3:
                logger.warning("[GeminiLive] receive() returned nothing 3 times, stopping")
                return
            if not got_any:
                await asyncio.sleep(0.05)

    async def receive(self) -> AsyncGenerator[tuple[str, Any], None]:
        """
        The main event stream from Gemini - an async generator that yields
        (event_type, data) tuples for every significant event in the session.

        This runs continuously for the life of the session (called from
        VoiceAgentRuntime._receive_loop()). It never returns normally -
        it runs until the session closes or an exception occurs.

        TEXT BUFFERING 
        Gemini streams output transcript (what it's saying) and input transcript
        (what it hears the candidate saying) incrementally - one word or phrase
        at a time. We buffer these in _text_buf and _input_buf and only yield
        them as a complete string on turn_complete or interrupted.
        This gives the agent a complete, usable transcript per turn.

        EVENT PRECEDENCE
        Audio (response.data) is yielded immediately, before processing
        server_content. This is intentional - audio latency is more critical
        than transcript latency, so we forward audio chunks as fast as possible.

        EVENTS YIELDED 
        ("audio",         bytes)  - PCM chunk, yield immediately on every frame
        ("text",          str)    - agent transcript, yielded at turn_complete/interrupted
        ("input_text",    str)    - candidate transcript, yielded at turn_complete/interrupted
        ("tool_call",     dict)   - {"id", "name", "args"}, one per function call
        ("turn_complete", None)   - agent finished its response turn
        ("interrupted",   None)   - candidate interrupted the agent mid-speech
        ("session_ending", dict)  - Gemini server is closing the connection
        """
        _require_session(self._session)
        _text_buffer = ""  # Accumulates agent speech transcript across streaming chunks
        _input_buffer = (
            ""  # Accumulates candidate speech transcript across streaming chunks
        )

        try:
            async for response in self._messages():
                if isinstance(response, _Resumed):
                    yield ("session_resumed", {"reason": response.reason})
                    continue

                # Audio (highest priority - forward immediately) 
                # response.data contains the raw 24kHz PCM audio bytes.
                # Yield this immediately without any buffering.
                if response.data:
                    logger.debug(f"[GeminiLive] Received audio chunk: {len(response.data)} bytes")
                    yield ("audio", response.data)

                sc = response.server_content
                if sc:
                    # Transcript accumulation 
                    # output_transcription = what the agent is saying (its speech -> text)
                    # input_transcription  = what the candidate is saying (their speech -> text)
                    if sc.output_transcription:
                        _text_buffer += sc.output_transcription.text
                    if sc.input_transcription:
                        _input_buffer += sc.input_transcription.text
                        logger.info(
                            f"[GeminiLive] Candidate speech: '{sc.input_transcription.text[:60]}'"
                        )

                    # Interrupted: candidate started talking, flush and signal 
                    # Flush both buffers (partial transcripts are still useful)
                    # then signal the agent so it can stop playing audio.
                    if sc.interrupted:
                        logger.info("[GeminiLive] Interrupted")
                        if _text_buffer.strip():
                            yield ("text", _text_buffer.strip())
                            _text_buffer = ""
                        if _input_buffer.strip():
                            yield ("input_text", _input_buffer.strip())
                            _input_buffer = ""
                        yield ("interrupted", None)

                    # Turn complete: agent finished speaking, flush and signal ─
                    # This is the normal end of an agent turn. Flush transcripts
                    # then signal the agent to open the mic for the candidate.
                    if sc.turn_complete:
                        logger.info(
                            f"[GeminiLive] turn_complete - buf='{_text_buffer[:60]}'"
                        )
                        if _text_buffer.strip():
                            yield ("text", _text_buffer.strip())
                            _text_buffer = ""
                        if _input_buffer.strip():
                            yield ("input_text", _input_buffer.strip())
                            _input_buffer = ""
                        yield ("turn_complete", None)

                # Tool calls: Gemini wants to call one of our functions
                # Each function call in the response gets its own yield.
                # The agent MUST respond to each one via send_tool_response()
                # or Gemini will block waiting for a response.
                if response.tool_call:
                    for fn_call in response.tool_call.function_calls:
                        yield (
                            "tool_call",
                            {
                                "id": fn_call.id,
                                "name": fn_call.name,
                                "args": dict(fn_call.args),
                            },
                        )

                # Go away: server is shutting down the session 
                # We log the time remaining and yield the signal so the agent
                # can clean up gracefully (save progress, send closing remarks).
                if response.go_away:
                    logger.warning(
                        f"[GeminiLive] go_away: time_left={response.go_away.time_left}"
                    )
                    yield (
                        "session_ending",
                        {
                            "reason": "provider_go_away",
                            "time_left": str(response.go_away.time_left),
                        },
                    )

        except Exception as e:
            logger.error(f"[GeminiLive] receive() error: {type(e).__name__}: {e}")
            raise

    async def close(self) -> None:
        """
        Clears the session reference. The actual SDK session cleanup
        happens in _LiveSessionContext.__aexit__(). This method exists
        to satisfy the LiveSessionPort interface.
        """
        self._session = None

    async def is_healthy(self) -> bool:
        """
        Returns True if a session is currently open.
        Used for health checks - a False here means no active session.
        """
        return self._session is not None

    # ───────────────────────
    # SESSION CONTEXT MANAGER
    # ───────────────────────

    def open_session(
        self,
        system_prompt: str,
        tools: list[ToolSpec] | None = None,
    ) -> "_LiveSessionContext":
        """
        The ONLY supported way to start a Gemini Live session.

        Returns an async context manager. On __aenter__, it opens the SDK
        session and sets self._session. On __aexit__, it clears self._session
        and closes the SDK session.

        The system_prompt becomes Gemini's system instruction - it sets the
        model's persona, behaviour rules, and interview format for the session.
        Built by build_system_prompt(context) in the agent's prompts module.

        tools are provider-neutral ToolSpec objects (legacy declaration dicts
        are also accepted) that tell Gemini what functions it can call.

        Usage:
            async with adapter.open_session(prompt, tools=TOOLS) as session:
                # 'session' is the adapter itself (self), now with _session set
                await session.send_client_content("context...")
                async for event_type, data in session.receive():
                    ...
        """
        return _LiveSessionContext(
            adapter=self,
            system_prompt=system_prompt,
            tools=normalize_tools(tools),
        )
    
    # ----------------------
    # EXPLICIT ACTIVITY SIGNALS FOR TURN MANAGEMENT (optional - we rely on Gemini's VAD by default)
    # ----------------------

    async def send_activity_start(self) -> None:
        """Tell Gemini the candidate has started speaking."""
        await self._session_ready.wait()
        if self._session:
            self._activity_ended = False  # Re-open audio flow for new turn
            async with self._send_lock:
                await self._session.send_realtime_input(
                    activity_start=types.ActivityStart()
                )


    async def send_activity_end(self) -> None:
        """Tell Gemini the candidate has finished speaking. Triggers model response."""
        await self._session_ready.wait()
        if self._session:
            self._activity_ended = True  # Block further audio immediately
            async with self._send_lock:
                await self._session.send_realtime_input(
                    activity_end=types.ActivityEnd()
                )


# ──────────────────────────────────────
# SESSION CONTEXT MANAGER IMPLEMENTATION
# ──────────────────────────────────────
# Separated from GeminiLiveAdapter to keep the class clean.
# This class owns the SDK-level async context manager lifecycle.


class _LiveSessionContext:
    """
    Internal async context manager that wraps one Gemini Live SDK session.

    Created by GeminiLiveAdapter.open_session() - not instantiated directly.

    On __aenter__:
      - Builds the LiveConnectConfig with all our interview-specific settings
      - Opens the SDK session via client.aio.live.connect()
      - Stores the live session on adapter._session (enables all the send/receive methods)
      - Returns the adapter itself as the context value

    On __aexit__:
      - Clears adapter._session (disables send/receive methods)
      - Exits the SDK context manager (closes the connection gracefully)
    """

    def __init__(
        self,
        *,
        adapter: GeminiLiveAdapter,
        system_prompt: str,
        tools: list[ToolSpec],
    ) -> None:
        self._adapter = adapter
        self._system_prompt = system_prompt
        self._tools = tools
        self._cm = None  # Will hold the SDK async context manager

    async def __aenter__(self) -> GeminiLiveAdapter:
        """
        Opens the Gemini Live session with interview-specific configuration.

        Key config decisions:
          response_modalities=["AUDIO"]
            We want audio output, not text. The model speaks directly.

          output_audio_transcription / input_audio_transcription
            Both enabled - gives us captions for both the agent and candidate.

          voice_config voice_name="Kore"
            The specific voice persona for the AI interviewer. Kore sounds
            professional and clear. Change this to adjust the interviewer's voice.

          automatic_activity_detection
            Enabled with 4000ms silence threshold - Gemini will detect when
            the candidate stops talking and process their answer automatically.
            prefix_padding_ms=20 gives a tiny buffer before VAD kicks in.

          tools
            The INTERVIEW_TOOLS function declarations. Gemini uses these to
            record questions, persist answers, flag interrupts, etc.
        """
        self._adapter._ctx = self
        self._adapter._resume_handle = None
        self._adapter._sent_content = []
        self._adapter._consecutive_reconnects = 0
        await self._connect(None)
        logger.info("[LiveSessionContext] Session opened")
        return self._adapter  # Return adapter so `as session` gives the adapter

    def _build_config(self, handle: Optional[str]) -> "types.LiveConnectConfig":
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self._system_prompt,
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
                )
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=True,
                    # silence_duration_ms=800,  # Wait 4s of silence before processing
                    # prefix_padding_ms=20,  # 20ms buffer before VAD triggers
                )
            ),
            thinking_config=types.ThinkingConfig(
                    thinking_budget=0,
                    include_thoughts=False,
            ),
            # TODO: thinking_budget, no enable_affective_dialog - these need v1alpha
            tools=_to_gemini_tools(self._tools),
            # Lets a dropped or recycled connection continue the same conversation.
            session_resumption=types.SessionResumptionConfig(handle=handle),
            # Audio sessions are otherwise capped at about 15 minutes; interviews run longer.
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
            ),
        )

        return config

    async def _connect(self, handle: Optional[str]) -> None:
        """Open the SDK session (resuming from `handle` when given)."""
        cm = self._adapter._client.aio.live.connect(
            model=self._adapter._model, config=self._build_config(handle)
        )
        session = await cm.__aenter__()
        self._cm = cm
        self._adapter._session = session  # Now all send/receive methods will work

    async def reopen(self, handle: Optional[str]) -> None:
        """Close the current SDK session (best effort) and open a fresh one."""
        old, self._cm = self._cm, None
        self._adapter._session = None
        if old is not None:
            try:
                await old.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug(f"[LiveSessionContext] closing old session: {exc!r}")
        await self._connect(handle)

    async def __aexit__(self, *args) -> None:
        """
        Closes the Gemini Live session cleanly.
        Clears _session first so any concurrent calls fail fast with RuntimeError
        rather than operating on a half-closed session.
        """
        self._adapter._session = None
        self._adapter._ctx = None
        if self._cm:
            await self._cm.__aexit__(*args)
        logger.info("[GeminiLive] Session closed")


class _Resumed:
    """Internal marker: the adapter reconnected; becomes a "session_resumed" event."""

    def __init__(self, reason: str) -> None:
        self.reason = reason


# ───────
# HELPERS
# ───────


def _to_gemini_tools(specs: list[ToolSpec]) -> Optional[list[dict]]:
    """ToolSpec -> Gemini's [{"function_declarations": [...]}] shape (None when empty)."""
    if not specs:
        return None
    return [
        {
            "function_declarations": [
                {"name": s.name, "description": s.description, "parameters": s.parameters}
                for s in specs
            ]
        }
    ]


def _require_session(session: Any) -> None:
    """
    Guard function called at the top of every method that requires an active session.

    If called outside of an open_session() context, raises a clear RuntimeError
    rather than an AttributeError on None or a confusing SDK error.
    This makes debugging misuse of the adapter much faster.
    """
    if session is None:
        raise RuntimeError(
            "GeminiLiveAdapter: no active session. "
            "All calls must be made inside an open_session() context manager."
        )
