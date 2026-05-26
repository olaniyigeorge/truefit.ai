"""
OpenAIRealtimeAdapter - OpenAI Realtime API session wrapper for real-time interviews.

This adapter is the OpenAI counterpart to GeminiLiveAdapter and implements the
same LiveSessionPort interface. All other layers (agent, websocket handler,
orchestration) interact with OpenAI exclusively through this adapter's interface.


WHY THIS ADAPTER EXISTS

The OpenAI Realtime API uses a raw WebSocket with JSON events — there is no
dedicated Python SDK for it at the level of abstraction we need. By wrapping
all of that complexity here, we achieve the same isolation guarantee as the
Gemini adapter: swap models by changing one env var, not one line of agent code.


AUDIO FORMAT CONTRACT (mirrors GeminiLiveAdapter exactly)

  Inbound  (browser -> OpenAI):  16kHz mono s16 PCM
  Outbound (OpenAI -> browser):  24kHz mono s16 PCM

  The WebRTC AudioBridge resamples in both directions:
    - Browser sends 48kHz Opus -> AudioBridge resamples to 16kHz PCM -> us
    - We yield 24kHz PCM -> AudioBridge resamples to 48kHz -> browser

  We configure the OpenAI session with:
    input_audio_format  = "pcm16"  @ 16kHz  (matches inbound contract)
    output_audio_format = "pcm16"  @ 24kHz  (matches outbound contract)


EVENT TYPES YIELDED BY receive()  (identical contract to GeminiLiveAdapter)

  ("audio",         bytes)  - 24kHz PCM chunk, forward to candidate speaker
  ("text",          str)    - agent output transcript (captions), at turn end
  ("input_text",    str)    - candidate speech transcript (captions), at turn end
  ("tool_call",     dict)   - {"id", "name", "args"} - agent wants to call a tool
  ("turn_complete", None)   - agent finished speaking its turn
  ("interrupted",   None)   - agent was interrupted mid-speech by candidate
  ("go_away",       None)   - not a native OpenAI concept; never yielded
                               (included for interface parity; see note below)


EVENT MAPPING  (OpenAI server event -> our normalised event)

  response.output_audio.delta              -> ("audio", decoded_bytes)
  response.audio_transcript.done           -> buffers agent transcript
  conversation.item.input_audio_transcription.completed -> buffers input transcript
  input_audio_buffer.speech_started        -> ("interrupted", None) if response active
  response.done  [status=completed]        -> flush transcripts + ("turn_complete", None)
  response.done  [status=cancelled]        -> flush transcripts + ("interrupted", None)
  response.output_item.done [function_call] -> ("tool_call", {...})

NOTE ON go_away
  OpenAI has no equivalent of Gemini's go_away signal. The server simply closes
  the WebSocket. We handle the resulting ConnectionClosed exception in receive()
  and let it propagate so the agent can clean up normally.


TURN DETECTION / VAD

  We mirror the GeminiLiveAdapter's manual VAD approach (disabled=True).
  The agent controls turn boundaries explicitly via send_activity_start() /
  send_activity_end(). In OpenAI terms this means:
    - turn_detection = None  (server VAD disabled)
    - send_activity_start() commits the audio buffer  ->  triggers model inference
    - send_activity_end()   sets _activity_ended flag  ->  blocks further audio

  If you want to re-enable server VAD, set _TURN_DETECTION_CONFIG to the
  server_vad dict and remove the manual commit logic in send_activity_start().


TOOL FORMAT TRANSLATION

  GeminiLiveAdapter receives tools as google.genai.types.FunctionDeclaration objects.
  This adapter receives the same list but expects them in OpenAI Realtime format:
    {
      "type": "function",
      "name": "<name>",
      "description": "<description>",
      "parameters": { <JSON Schema> }
    }

  The factory (LiveAdapterFactory) passes INTERVIEW_TOOLS through unchanged, so
  the tools must already be in OpenAI format when this adapter is selected.
  See src/truefit_core/application/interview_tools.py for the tool definitions -
  ensure they export an OPENAI_INTERVIEW_TOOLS list alongside GEMINI_INTERVIEW_TOOLS,
  or define a single format-agnostic list that both adapters can consume.


USAGE PATTERN  (identical to GeminiLiveAdapter)

  adapter = OpenAIRealtimeAdapter()

  async with adapter.open_session(system_prompt, tools=INTERVIEW_TOOLS) as session:
      await session.send_client_content(text="Interview context...")
      await asyncio.gather(
          send_audio_loop(session),   # calls session.send_audio() in a loop
          receive_loop(session),       # iterates session.receive()
      )
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, AsyncGenerator, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from src.truefit_core.application.ports import LiveSessionPort
from src.truefit_infra.config import AppConfig
from src.truefit_core.common.utils import logger

# ────────────────────────────
# MODEL & CONNECTION CONSTANTS
# ────────────────────────────

_MODEL = "gpt-realtime-mini-2025-12-15"
_WS_BASE_URL = "wss://api.openai.com/v1/realtime"
_WS_URL = f"{_WS_BASE_URL}?model={_MODEL}"

# Audio format constants - must match AudioBridge contract
_INPUT_AUDIO_FORMAT = "pcm16"   # 16kHz mono s16 PCM from browser (via AudioBridge)
_OUTPUT_AUDIO_FORMAT = "pcm16"  # 24kHz mono s16 PCM to browser (via AudioBridge)
_INPUT_SAMPLE_RATE = 16_000
_OUTPUT_SAMPLE_RATE = 24_000

# Voice for the AI interviewer. Options: alloy, ash, ballad, coral, echo,
# sage, shimmer, verse. "alloy" is clear and professional
_VOICE = "alloy"

# Turn detection config. Set to None to disable server VAD (manual mode).
# To re-enable VAD: replace with the dict below and update send_activity_start().
#   {
#       "type": "server_vad",
#       "threshold": 0.5,
#       "prefix_padding_ms": 300,
#       "silence_duration_ms": 800,
#   }
_TURN_DETECTION_CONFIG: dict | None = None  # Manual VAD (disabled)


# ──────────────────
# MAIN ADAPTER CLASS
# ──────────────────


class OpenAIRealtimeAdapter(LiveSessionPort):
    """
    Wraps the OpenAI Realtime WebSocket API for the interview system.

    Implements LiveSessionPort so the agent and orchestration layers can use
    OpenAI as a drop-in replacement for GeminiLiveAdapter.

    One instance is created per WebSocket connection. It holds:
      - The API key (resolved at construction time)
      - A reference to the active websockets.WebSocketClientProtocol (None
        when no session is open)
      - A send lock to serialise outbound WebSocket messages safely

    The ONLY way to use this adapter is through the open_session() context
    manager. Calling any send/receive method outside of it raises RuntimeError.
    """

    def __init__(self, api_key: str | None = None) -> None:
        """
        Resolves the OpenAI API key. Fails fast at construction if missing.
        Key resolution order: explicit arg -> AppConfig.OPENAI_API_KEY env var.
        """
        key = api_key or getattr(AppConfig, "OPENAI_API_KEY", None)
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        self._api_key = key
        self._ws: Optional[Any] = None        # websockets connection, set in open_session
        self._send_lock = asyncio.Lock()       # serialises all ws.send() calls
        self._activity_ended = False           # blocks send_audio() after activity end
        self._active_response_id: str | None = None  # tracks if a response is in flight

    # ─────────────────────────
    # LiveSessionPort interface
    # ─────────────────────────
    # The agent only calls these. It never touches websockets or JSON directly.

    async def connect(self, system_prompt: str) -> None:
        """
        Not used in this implementation. open_session() is the correct entry point.
        Raising here makes misuse immediately obvious.
        """
        raise NotImplementedError(
            "Use OpenAIRealtimeAdapter.open_session() context manager."
        )

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """
        Forwards a PCM audio chunk from the browser to OpenAI's input buffer.

        Input format: 16kHz mono s16 PCM (resampled by AudioBridge from 48kHz Opus)
        OpenAI expects base64-encoded audio in the input_audio_buffer.append event.

        Silently skips empty chunks and chunks sent after activity_end() - the
        AudioBridge occasionally sends zero-length keepalives and we don't want
        to waste WebSocket frames or inadvertently re-open the buffer.
        """
        _require_ws(self._ws)
        if not pcm_bytes or self._activity_ended:
            return
        encoded = base64.b64encode(pcm_bytes).decode("ascii")
        await self._send({
            "type": "input_audio_buffer.append",
            "audio": encoded,
        })

    async def send_audio_stream_end(self) -> None:
        """
        Commits the audio buffer, signalling OpenAI to process it.

        In manual VAD mode (server VAD disabled), this is the trigger that tells
        OpenAI the candidate has finished speaking and inference should begin.
        Equivalent to Gemini's AudioStreamEnd.

        NOTE: Unlike Gemini, we do NOT call response.create here - OpenAI
        automatically starts inference after input_audio_buffer.commit when
        turn_detection is null. If that behaviour changes, add response.create.
        """
        _require_ws(self._ws)
        async with self._send_lock:
            await self._ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

    async def send_image(self, jpeg_bytes: bytes, source: str = "camera") -> None:
        """
        OpenAI Realtime API does not currently support image/video input in the
        same session as audio. This method is a no-op stub to satisfy the port
        interface. If OpenAI adds vision support to the Realtime API, implement
        it here by creating a conversation item with image content.
        """
        logger.debug(
            "[OpenAIRealtime] send_image() called but OpenAI Realtime does not "
            "support vision input; frame dropped."
        )

    async def send_client_content(self, text: str) -> None:
        """
        Injects a structured text message into the conversation before audio begins.

        Used once at session start by LiveInterviewAgent._inject_context() to
        pre-load job details, candidate info, and interview instructions.

        OpenAI equivalent:
          1. conversation.item.create  - adds the user message to context
          2. response.create           - triggers the model's opening greeting

        The model will respond (audio + transcript) immediately after response.create.
        """
        _require_ws(self._ws)
        # Step 1: add the user message to the conversation
        await self._send({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        })
        # Step 2: ask the model to respond (generates opening greeting)
        await self._send({"type": "response.create"})

    async def send_tool_response(
        self, *, call_id: str, name: str, result: dict
    ) -> None:
        """
        Responds to a tool call that OpenAI made.

        When receive() yields a "tool_call" event, the agent executes the tool
        and MUST call this method to unblock OpenAI - it won't continue until
        it receives the function output and a response.create trigger.

        call_id must match the call_id from the "tool_call" event exactly.
        result is whatever dict the tool handler returned.

        OpenAI flow:
          1. conversation.item.create (function_call_output) - delivers result
          2. response.create                                 - resumes inference
        """
        _require_ws(self._ws)
        # Step 1: deliver the tool result
        await self._send({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result),
            },
        })
        # Step 2: ask the model to continue from here
        await self._send({"type": "response.create"})

    async def receive(self) -> AsyncGenerator[tuple[str, Any], None]:
        """
        The main event stream from OpenAI - an async generator that yields
        (event_type, data) tuples normalised to the same contract as
        GeminiLiveAdapter.receive().

        Runs continuously for the life of the session. Terminates when the
        WebSocket closes (ConnectionClosed), which is how OpenAI signals
        end-of-session (there is no go_away equivalent).

        TRANSCRIPT BUFFERING
        OpenAI streams transcripts incrementally:
          - Agent output: response.audio_transcript.delta (per word/phrase)
            Flushed to ("text", str) on response.done or response cancelled.
          - Candidate input: conversation.item.input_audio_transcription.completed
            Arrives as a complete transcript after the candidate's turn; yielded
            immediately as ("input_text", str).

        INTERRUPTION DETECTION
        When the candidate speaks while the model is responding, OpenAI sends
        input_audio_buffer.speech_started. If a response is currently active
        (_active_response_id is set), we treat this as an interruption:
          - OpenAI automatically cancels the in-flight response
          - We yield ("interrupted", None) to signal the agent
        If no response is active (candidate spoke before model started), it's
        a false trigger - we skip it.

        FUNCTION CALLS
        Detected via response.output_item.done where item.type == "function_call".
        We use this event (not response.function_call_arguments.done) because it
        gives us the name, call_id, and complete arguments together in one place,
        avoiding a separate accumulation loop.

        EVENT MAPPING SUMMARY
          response.output_audio.delta                          -> ("audio", bytes)
          response.audio_transcript.delta                      -> buffer agent text
          response.audio_transcript.done                       -> flush agent text
          conversation.item.input_audio_transcription.completed -> ("input_text", str)
          input_audio_buffer.speech_started [if response active] -> ("interrupted", None)
          response.done [completed]                            -> ("turn_complete", None)
          response.done [cancelled/failed]                     -> ("interrupted", None)
          response.output_item.done [function_call]            -> ("tool_call", dict)
          error                                                -> logged + raised
        """
        _require_ws(self._ws)
        _text_buffer = ""    # Accumulates agent speech transcript across delta events
        _input_buffer = ""   # Accumulates candidate transcript (used if deltas arrive)

        try:
            async for raw_message in self._ws:
                event = json.loads(raw_message)
                event_type: str = event.get("type", "")

                # ── Audio output (highest priority - yield immediately) 
                # response.output_audio.delta carries base64-encoded 24kHz PCM.
                # Decode and yield immediately - audio latency is king.
                if event_type == "response.output_audio.delta":
                    audio_bytes = base64.b64decode(event["delta"])
                    logger.debug(
                        f"[OpenAIRealtime] audio chunk: {len(audio_bytes)} bytes"
                    )
                    yield ("audio", audio_bytes)

                # ── Agent transcript (incremental) 
                # Accumulate per-delta into buffer. Flush at response.done.
                elif event_type == "response.audio_transcript.delta":
                    _text_buffer += event.get("delta", "")

                # ── Agent transcript done (alternative flush point) 
                # response.audio_transcript.done carries the full text of the current
                # content part. We overwrite the buffer with the authoritative version
                # to avoid any drift from partial deltas.
                elif event_type == "response.audio_transcript.done":
                    transcript = event.get("transcript", "").strip()
                    if transcript:
                        _text_buffer = transcript  # authoritative; replaces buffer

                # ── Candidate speech transcript 
                # Arrives as a complete string after the candidate's audio turn
                # is committed and transcribed. Yield immediately.
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    transcript = event.get("transcript", "").strip()
                    if transcript:
                        logger.info(
                            f"[OpenAIRealtime] Candidate speech: '{transcript[:60]}'"
                        )
                        yield ("input_text", transcript)

                # ── Interruption detection
                # input_audio_buffer.speech_started fires when the candidate starts
                # speaking. If a model response is in flight, this is an interruption.
                # OpenAI will cancel the response automatically; we just signal it.
                elif event_type == "input_audio_buffer.speech_started":
                    if self._active_response_id is not None:
                        logger.info("[OpenAIRealtime] Interrupted (speech_started during response)")
                        # Flush any partial transcript before signalling interrupt
                        if _text_buffer.strip():
                            yield ("text", _text_buffer.strip())
                            _text_buffer = ""
                        if _input_buffer.strip():
                            yield ("input_text", _input_buffer.strip())
                            _input_buffer = ""
                        yield ("interrupted", None)
                        self._active_response_id = None

                # ── Response lifecycle tracking 
                # response.created tells us a new response has started - track its ID
                # so we can detect interruptions accurately.
                elif event_type == "response.created":
                    self._active_response_id = event.get("response", {}).get("id")
                    logger.debug(
                        f"[OpenAIRealtime] Response started: {self._active_response_id}"
                    )

                # ── Function calls 
                # response.output_item.done fires when any output item finishes.
                # When item.type == "function_call", it contains the complete call:
                #   item.name     - function name
                #   item.call_id  - ID to use in send_tool_response()
                #   item.arguments - JSON string of args
                # We yield one "tool_call" event per function call item.
                elif event_type == "response.output_item.done":
                    item = event.get("item", {})
                    if item.get("type") == "function_call":
                        fn_name = item.get("name", "")
                        call_id = item.get("call_id", "")
                        raw_args = item.get("arguments", "{}")
                        try:
                            args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            logger.warning(
                                f"[OpenAIRealtime] Failed to parse tool args for "
                                f"{fn_name}: {raw_args!r}"
                            )
                            args = {}
                        logger.info(
                            f"[OpenAIRealtime] Tool call: {fn_name}({args})"
                        )
                        yield (
                            "tool_call",
                            {"id": call_id, "name": fn_name, "args": args},
                        )

                # ── Turn complete / interrupted 
                # response.done fires at the end of every response regardless of outcome.
                # status == "completed"  -> normal end of agent turn
                # status == "cancelled"  -> response was interrupted by candidate speech
                # status == "failed"     -> model error; log and treat as interrupted
                elif event_type == "response.done":
                    response_obj = event.get("response", {})
                    status = response_obj.get("status", "completed")
                    self._active_response_id = None  # response is over

                    # Flush agent transcript buffer regardless of status
                    flushed_text = _text_buffer.strip()
                    _text_buffer = ""
                    flushed_input = _input_buffer.strip()
                    _input_buffer = ""

                    if status == "completed":
                        logger.info(
                            f"[OpenAIRealtime] turn_complete - "
                            f"buf='{flushed_text[:60]}'"
                        )
                        if flushed_text:
                            yield ("text", flushed_text)
                        if flushed_input:
                            yield ("input_text", flushed_input)
                        yield ("turn_complete", None)

                    elif status in ("cancelled", "failed"):
                        logger.info(
                            f"[OpenAIRealtime] response {status} "
                            f"(interrupted or errored)"
                        )
                        if flushed_text:
                            yield ("text", flushed_text)
                        if flushed_input:
                            yield ("input_text", flushed_input)
                        yield ("interrupted", None)

                # ── Error events
                elif event_type == "error":
                    error_info = event.get("error", {})
                    logger.error(
                        f"[OpenAIRealtime] API error: "
                        f"code={error_info.get('code')} "
                        f"message={error_info.get('message')}"
                    )
                    # Re-raise as a plain exception so the agent's error handler
                    # can clean up. Include the full error info for debugging.
                    raise RuntimeError(
                        f"OpenAI Realtime API error: {json.dumps(error_info)}"
                    )

                # ── Session / informational events
                # Log but don't yield - the agent doesn't need these.
                elif event_type in ("session.created", "session.updated"):
                    logger.info(f"[OpenAIRealtime] {event_type}")

                elif event_type == "input_audio_buffer.committed":
                    logger.debug("[OpenAIRealtime] Audio buffer committed")

                elif event_type == "rate_limits.updated":
                    limits = event.get("rate_limits", [])
                    logger.debug(f"[OpenAIRealtime] Rate limits: {limits}")

                else:
                    # Catch-all for unknown/future events - log at debug level
                    logger.debug(f"[OpenAIRealtime] Unhandled event: {event_type}")

        except ConnectionClosed as e:
            # OpenAI closes the WebSocket at session end (no go_away equivalent).
            # This is the normal termination path; let the agent's cleanup run.
            logger.info(f"[OpenAIRealtime] WebSocket closed: {e}")
            raise
        except Exception as e:
            logger.error(f"[OpenAIRealtime] receive() error: {type(e).__name__}: {e}")
            raise

    async def close(self) -> None:
        """
        Clears the WebSocket reference. Actual socket teardown happens in
        _OpenAISessionContext.__aexit__(). Satisfies LiveSessionPort interface.
        """
        self._ws = None

    async def is_healthy(self) -> bool:
        """
        Returns True if a WebSocket session is currently open.
        Used for health checks - False means no active connection.
        """
        return self._ws is not None and self._ws.open

    # ───────────────────────
    # SESSION CONTEXT MANAGER
    # ───────────────────────

    def open_session(
        self,
        system_prompt: str,
        tools: list | None = None,
    ) -> "_OpenAISessionContext":
        """
        The ONLY supported way to start an OpenAI Realtime session.

        Returns an async context manager. On __aenter__, it connects to the
        OpenAI Realtime WebSocket, sends session.update with the system prompt
        and tool definitions, then returns the adapter (so `as session` works
        identically to the Gemini adapter).

        On __aexit__, it clears self._ws and closes the WebSocket gracefully.

        system_prompt becomes the "instructions" field in session.update.
        tools is the list of OpenAI-format function declarations.

        Usage:
            async with adapter.open_session(prompt, tools=TOOLS) as session:
                await session.send_client_content("context...")
                async for event_type, data in session.receive():
                    ...
        """
        return _OpenAISessionContext(
            adapter=self,
            system_prompt=system_prompt,
            tools=tools or [],
        )

    # ─────────────────────────────────────
    # EXPLICIT ACTIVITY SIGNALS (manual VAD)
    # ─────────────────────────────────────

    async def send_activity_start(self) -> None:
        """
        Signal that the candidate has started speaking.

        In manual VAD mode (server VAD disabled), this re-opens the audio flow
        for the next candidate turn. We do NOT send anything to OpenAI here -
        audio data is just appended to the buffer via send_audio() until
        send_activity_end() commits it.

        If you switch to server_vad mode, you may remove this entirely - the
        server handles turn start detection automatically.
        """
        if self._ws:
            self._activity_ended = False
            logger.debug("[OpenAIRealtime] activity_start: audio flow re-opened")

    async def send_activity_end(self) -> None:
        """
        Signal that the candidate has stopped speaking.

        Blocks further audio appends immediately (sets _activity_ended) then
        commits the buffer, which triggers model inference in manual VAD mode.

        OpenAI will begin generating a response as soon as the commit is processed.
        """
        if self._ws:
            self._activity_ended = True
            async with self._send_lock:
                await self._ws.send(
                    json.dumps({"type": "input_audio_buffer.commit"})
                )
            logger.debug("[OpenAIRealtime] activity_end: buffer committed")

    # ────────────────
    # INTERNAL HELPERS
    # ────────────────

    async def _send(self, payload: dict) -> None:
        """
        Serialises and sends a JSON event over the WebSocket with the send lock.
        All outbound sends go through here to prevent concurrent write races.
        """
        async with self._send_lock:
            await self._ws.send(json.dumps(payload))

    async def _configure_session(
        self, system_prompt: str, tools: list
    ) -> None:
        """
        Sends the initial session.update event to configure the live session.

        Called once by _OpenAISessionContext.__aenter__() immediately after
        the WebSocket connection is established. Sets:
          - instructions (system prompt)
          - modalities (audio only, matching Gemini's AUDIO response mode)
          - audio input/output formats (pcm16 @ 16kHz in / 24kHz out)
          - voice persona
          - turn_detection (None = manual mode, matching GeminiLiveAdapter)
          - input_audio_transcription (whisper-1 for candidate speech captions)
          - tools (function declarations)

        The server responds with session.updated to confirm. We don't await that
        confirmation explicitly - subsequent events will queue behind it on the
        WebSocket and arrive in order.
        """
        # Build the tool list in OpenAI Realtime format.
        # Each tool must have: type="function", name, description, parameters.
        openai_tools = []
        for tool in tools:
            if isinstance(tool, dict):
                # Already in OpenAI format - pass through directly
                openai_tools.append(tool)
            else:
                # Attempt duck-typed conversion from Gemini FunctionDeclaration
                # (has .name, .description, .parameters attributes).
                # This is a best-effort fallback; prefer native OpenAI format.
                try:
                    openai_tools.append({
                        "type": "function",
                        "name": tool.name,
                        "description": getattr(tool, "description", ""),
                        "parameters": _convert_schema(
                            getattr(tool, "parameters", None)
                        ),
                    })
                except AttributeError:
                    logger.warning(
                        f"[OpenAIRealtime] Could not convert tool {tool!r} to "
                        f"OpenAI format; skipping."
                    )

        session_config: dict = {
            "modalities": ["audio", "text"],   # audio output + text for transcripts
            "instructions": system_prompt,
            "voice": _VOICE,
            "input_audio_format": _INPUT_AUDIO_FORMAT,
            "output_audio_format": _OUTPUT_AUDIO_FORMAT,
            "input_audio_transcription": {
                "model": "whisper-1",           # enables candidate speech transcripts
            },
            "turn_detection": _TURN_DETECTION_CONFIG,  # None = manual VAD
            "tool_choice": "auto",
        }
        if openai_tools:
            session_config["tools"] = openai_tools

        await self._send({
            "type": "session.update",
            "session": session_config,
        })
        logger.info(
            f"[OpenAIRealtime] session.update sent "
            f"(tools={len(openai_tools)}, vad={'server' if _TURN_DETECTION_CONFIG else 'manual'})"
        )


# ──────────────────────────────────────
# SESSION CONTEXT MANAGER IMPLEMENTATION
# ──────────────────────────────────────


class _OpenAISessionContext:
    """
    Internal async context manager that wraps one OpenAI Realtime WebSocket session.

    Created by OpenAIRealtimeAdapter.open_session() - not instantiated directly.

    On __aenter__:
      - Opens the WebSocket connection to the OpenAI Realtime endpoint
      - Stores the connection on adapter._ws (enables all send/receive methods)
      - Sends session.update to configure the session (system prompt, tools, audio)
      - Returns the adapter itself so `as session` gives the adapter

    On __aexit__:
      - Clears adapter._ws
      - Closes the WebSocket connection gracefully
    """

    def __init__(
        self,
        *,
        adapter: OpenAIRealtimeAdapter,
        system_prompt: str,
        tools: list,
    ) -> None:
        self._adapter = adapter
        self._system_prompt = system_prompt
        self._tools = tools
        self._ws_cm = None  # holds the websockets async context manager

    async def __aenter__(self) -> OpenAIRealtimeAdapter:
        """
        Opens the WebSocket connection and configures the session.

        WebSocket headers per OpenAI docs:
          Authorization: Bearer <api_key>
          OpenAI-Beta: realtime=v1
        """
        headers = {
            "Authorization": f"Bearer {self._adapter._api_key}",
            "OpenAI-Beta": "realtime=v1",
        }
        self._ws_cm = websockets.connect(_WS_URL, additional_headers=headers)
        ws = await self._ws_cm.__aenter__()
        self._adapter._ws = ws
        logger.info("[OpenAIRealtime] WebSocket connected")

        # Send session configuration immediately after connect.
        # The server will send session.created first, but session.update can
        # be sent without waiting for that confirmation - events are ordered.
        await self._adapter._configure_session(
            system_prompt=self._system_prompt,
            tools=self._tools,
        )

        return self._adapter  # `as session` yields the adapter itself

    async def __aexit__(self, *args) -> None:
        """
        Clears the WebSocket reference and closes the connection.
        Clears first so concurrent calls fail fast with RuntimeError.
        """
        self._adapter._ws = None
        self._adapter._active_response_id = None
        if self._ws_cm:
            try:
                await self._ws_cm.__aexit__(*args)
            except Exception as e:
                logger.warning(f"[OpenAIRealtime] Error during WS close: {e}")
        logger.info("[OpenAIRealtime] Session closed")


# ───────
# HELPERS
# ───────


def _require_ws(ws: Any) -> None:
    """
    Guard function called at the top of every method that requires an active
    WebSocket connection.

    Raises a clear RuntimeError if called outside of open_session(), rather than
    an AttributeError on None or a confusing websockets exception.
    """
    if ws is None:
        raise RuntimeError(
            "OpenAIRealtimeAdapter: no active session. "
            "All calls must be made inside an open_session() context manager."
        )


def _convert_schema(parameters: Any) -> dict:
    """
    Best-effort conversion of a Gemini Schema object to a JSON Schema dict
    compatible with the OpenAI Realtime API's function parameters format.

    This handles the common case where tools are defined with Gemini's
    types.Schema and need to be used with the OpenAI adapter.

    If parameters is already a dict, it's returned as-is.
    If it has a .model_dump() method (Pydantic), that's used.
    If it has a to_json_dict() or similar, that's tried.
    Falls back to an empty object schema to avoid crashing.

    For production use, define tools natively in OpenAI format and pass them
    directly - this conversion is a convenience bridge, not a guarantee.
    """
    if parameters is None:
        return {"type": "object", "properties": {}}
    if isinstance(parameters, dict):
        return parameters
    # Pydantic model (Gemini SDK often uses these)
    if hasattr(parameters, "model_dump"):
        return parameters.model_dump(exclude_none=True)
    # Generic object with __dict__
    if hasattr(parameters, "__dict__"):
        return {k: v for k, v in parameters.__dict__.items() if v is not None}
    logger.warning(
        f"[OpenAIRealtime] Could not convert schema {type(parameters).__name__}; "
        f"falling back to empty object schema."
    )
    return {"type": "object", "properties": {}}