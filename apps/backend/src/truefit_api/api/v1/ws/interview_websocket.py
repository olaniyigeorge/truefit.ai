from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncIterator, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends

from src.truefit_core.application.services.interview_orchestration import (
    InterviewOrchestrationService,
)
from src.truefit_core.application.ports import (
    CachePort,
    CandidateRepository,
    JobRepository,
    QueuePort,
)
from src.truefit_core.common.utils import logger
from src.truefit_infra.realtime.signaling import WebRTCSignaling
from src.truefit_infra.realtime.webrtc_client import WebRTCClient
from src.truefit_infra.cache.redis_cache import RedisCacheAdapter, redis_client
from src.truefit_infra.queue.redis_queue import RedisQueueAdapter
from src.truefit_infra.db.database import db_manager
from src.truefit_infra.db.repositories.interview_repository import (
    SQLAlchemyInterviewRepository,
)
from src.truefit_infra.db.repositories.job_repository import SQLAlchemyJobRepository
from src.truefit_infra.db.repositories.candidate_repository import (
    SQLAlchemyCandidateRepository,
)
from src.truefit_infra.agent.live_interview_agent import (
    InterviewContext,
    LiveInterviewAgent,
)
from src.truefit_infra.llm.gemini_live import GeminiLiveAdapter

# ────────────────────
# DEPENDENCY FACTORIES
# ────────────────────
# These are simple factory functions used by FastAPI's dependency injection
# system (the Depends() calls in the route signature). Each one constructs
# the infrastructure object that the websocket handler needs.
#
# I kept them as plain functions rather than a DI container because FastAPI
# resolves them per-request, which is exactly the lifecycle we want - each
# WebSocket connection gets its own fresh set of repository and adapter instances.


def get_interview_repo() -> SQLAlchemyInterviewRepository:
    """
    Returns a fresh SQLAlchemy-backed interview repository.
    This repo is responsible for persisting Interview aggregate state
    (creating, updating, completing interviews) to the database.
    """
    return SQLAlchemyInterviewRepository(db_manager)


def get_job_repo() -> SQLAlchemyJobRepository:
    """
    Returns a fresh SQLAlchemy-backed job repository.
    We use this to look up the Job aggregate (job title, description,
    required skills, interview config) during context building.
    """
    return SQLAlchemyJobRepository(db_manager)


def get_candidate_repo() -> SQLAlchemyCandidateRepository:
    """
    Returns a fresh SQLAlchemy-backed candidate repository.
    We use this to load the Candidate aggregate (name, resume) for
    personalising the interview context we inject into Gemini.
    """
    return SQLAlchemyCandidateRepository(db_manager)


def get_cache() -> RedisCacheAdapter:
    """
    Returns the Redis cache adapter (singleton redis_client).
    The cache is used here primarily for reading/writing interrupt signals
    that the agent publishes so the websocket layer can forward them to
    the frontend in real-time.
    """
    return redis_client


def get_queue() -> RedisQueueAdapter:
    """
    Returns a fresh Redis queue adapter.
    The queue is how the agent publishes domain events (interview.completed,
    interview.interrupted, etc.) to the rest of the system asynchronously.
    """
    return RedisQueueAdapter()


def get_gemini_live() -> GeminiLiveAdapter:
    """
    Returns a fresh GeminiLiveAdapter instance.
    This is the only place in this module that touches the Gemini SDK -
    through this adapter. It wraps a Gemini Live session and exposes
    a clean interface for sending/receiving audio and events.
    """
    return GeminiLiveAdapter()


def get_orchestration() -> InterviewOrchestrationService:
    """
    Assembles and returns the InterviewOrchestrationService.

    This is the core application service that coordinates the interview
    lifecycle: starting interviews, recording questions, submitting answers,
    and completing/abandoning sessions. It depends on all the other
    infrastructure pieces, so we build it last.

    Note: In a more complex setup this would use a proper DI container,
    but for now manual wiring here is clear enough.
    """
    interview_repo = get_interview_repo()
    job_repo = get_job_repo()
    candidate_repo = get_candidate_repo()
    llm_adapter = get_gemini_live()
    queue = get_queue()
    cache = get_cache()

    return InterviewOrchestrationService(
        interview_repo=interview_repo,
        job_repo=job_repo,
        candidate_repo=candidate_repo,
        llm=llm_adapter,
        queue=queue,
        cache=cache,
    )


# ──────
# ROUTER
# ──────
# This router is registered in the FastAPI app. The single WebSocket endpoint
# is the entry point for every interview session - the frontend connects here
# to kick off a live AI interview.


interview_ws_router = APIRouter(tags=["interview-ws"], prefix="/api/v1")

# How often (seconds) we poll Redis for interrupt signals during an active session.
# 50ms gives us near-real-time interrupt propagation without hammering Redis.
_INTERRUPT_POLL_INTERVAL = 0.05


@interview_ws_router.websocket("/ws/interview/{job_id}/{candidate_id}")
async def interview_websocket(
    websocket: WebSocket,
    job_id: uuid.UUID,
    candidate_id: uuid.UUID,
    orchestration: InterviewOrchestrationService = Depends(get_orchestration),
    job_repo: JobRepository = Depends(get_job_repo),
    candidate_repo: CandidateRepository = Depends(get_candidate_repo),
    queue: QueuePort = Depends(get_queue),
    cache: CachePort = Depends(get_cache),
    live_adapter: GeminiLiveAdapter = Depends(get_gemini_live),
) -> None:
    """
    THE main WebSocket endpoint for a live AI interview session.

    URL: /api/v1/ws/interview/{job_id}/{candidate_id}

    This function is intentionally thin - it accepts the connection, builds
    the InterviewConnection object that holds all the session state, and
    delegates everything to connection.run(). The route itself just wires
    FastAPI's DI into our domain objects.

    The full message protocol between frontend and server is:

    FRONTEND -> SERVER:
      { type: "webrtc_offer",     sdp, sdp_type, ... }   - WebRTC handshake step 1
      { type: "ice_candidate",    candidate, sdpMid, ... } - ICE trickle candidates
      { type: "end_session",      reason? }               - candidate ends early
      { type: "ping" }                                    - keepalive

    SERVER -> FRONTEND:
      { type: "session_started",  interview_id, session_id, max_questions, ... }
      { type: "webrtc_answer",    sdp, sdp_type }         - WebRTC handshake step 2
      { type: "ice_candidate",    candidate, sdpMid, ... } - ICE trickle candidates
      { type: "transcript",       speaker, text }         - live captions
      { type: "interrupt",        interrupt_id, directive, ... }
      { type: "session_ended",    status, reason }
      { type: "error",            message }
      { type: "pong" }
    """
    await websocket.accept()

    connection = InterviewConnection(
        websocket=websocket,
        job_id=job_id,
        candidate_id=candidate_id,
        orchestration=orchestration,
        job_repo=job_repo,
        candidate_repo=candidate_repo,
        queue=queue,
        cache=cache,
        live_adapter=live_adapter,
    )
    await connection.run()


# ────────────────────
# INTERVIEW CONNECTION
# ────────────────────
# This class owns the entire lifecycle of one WebSocket interview session.
# I separated it from the route handler so we have a clean place to hold
# per-connection state (interview_id, session_id, webrtc client, etc.)
# without leaking it into module-level globals or route closures.
#
# Concurrency model:
#   Three asyncio tasks run simultaneously once WebRTC is ready:
#     1. _ws_receive_loop      - reads control messages from the WebSocket
#     2. _interrupt_monitor_loop - polls Redis for interrupt signals
#     3. agent_task            - the LiveInterviewAgent (audio send + receive)
#
#   Audio data never flows through the WebSocket. It flows via WebRTC:
#     Browser mic -> WebRTC AudioBridge -> Gemini (via agent._send_audio_loop)
#     Gemini response -> AudioBridge -> WebRTC track -> Browser speaker


class InterviewConnection:
    """
    Holds all state for one live interview WebSocket session and orchestrates
    the three concurrent async tasks that drive it.

    Lifecycle:
      run() -> start_interview -> webrtc handshake -> agent starts -> gather tasks -> cleanup
    """

    def __init__(
        self,
        *,
        websocket,
        job_id,
        candidate_id,
        orchestration,
        job_repo,
        candidate_repo,
        queue,
        cache,
        live_adapter,
    ) -> None:
        # Infrastructure references
        self._ws: WebSocket = websocket  # The raw FastAPI WebSocket connection
        self._job_id = job_id  # UUID of the job being interviewed for
        self._candidate_id = candidate_id  # UUID of the candidate being interviewed
        self._orchestration: InterviewOrchestrationService = orchestration  # App service: interview lifecycle ops
        self._job_repo = job_repo  # Fetch job details for context building
        self._candidate_repo = candidate_repo  # Fetch candidate details for context
        self._queue = queue  # Publish domain events (interview.completed etc.)
        self._cache = cache  # Read/write interrupt signals
        self._live_adapter = live_adapter  # Gemini Live API wrapper

        # Per-session state
        self._interview_id: Optional[uuid.UUID] = None  # Set after start_interview()
        self._session_id: Optional[str] = None  # Random UUID, sent to frontend
        # When True, audio output from Gemini is silently dropped instead of
        # being forwarded to the browser - used during interrupt handling
        self._suppress_audio = False

        # WebRTC references (set after handshake completes)
        # These are None until the frontend sends a webrtc_offer message.
        self._webrtc: Optional[WebRTCClient] = None  # Owns tracks + data channel
        self._signaling: Optional[WebRTCSignaling] = None  # Handles SDP/ICE exchange

        # This Event is the synchronisation point between the WebSocket receive
        # loop (which processes the offer) and the main run() coroutine (which
        # waits before starting the agent). Once the offer is processed and the
        # WebRTC peer connection is up, _handle_webrtc_offer() sets this.
        self._webrtc_ready = asyncio.Event()

    # ───────────
    # ENTRY POINT
    # ───────────

    async def run(self) -> None:
        """
        Orchestrates the full session lifecycle in order:

        ① Create the Interview aggregate in the DB via orchestration service.
        ② Build the InterviewContext (job + candidate data) for the agent.
        ③ Send session_started to the frontend so it knows the interview ID
           and the session_id it must include in its webrtc_offer message.
        ④ Instantiate WebRTCSignaling (manages the peer connection).
        ⑤ Start the WS receive loop and interrupt monitor in background tasks
           so the frontend's webrtc_offer message can be handled immediately.
        ⑥ Wait (with 30s timeout) for _webrtc_ready to be set by the receive loop.
        ⑦ Wire the DataChannel inbound handler and close the mic until the
           agent's first turn completes (prevents candidate audio leaking in
           before Gemini is ready).
        ⑧ Build the LiveInterviewAgent and start its task.
        ⑨ gather() all three tasks - they run until the interview ends or
           the candidate disconnects.
        """
        self._session_id = str(uuid.uuid4())

        try:
            # ① Domain setup - creates the Interview record, returns the aggregate
            interview = await self._orchestration.start_interview(
                job_id=self._job_id,
                candidate_id=self._candidate_id,
            )
            self._interview_id = interview.id
            context = await self._build_context(interview.id)

            # ② Notify the frontend - it needs interview_id for tracking and
            #    session_id to include in its upcoming webrtc_offer message
            await self._send(
                {
                    "type": "session_started",
                    "interview_id": str(interview.id),
                    "session_id": self._session_id,  # ← frontend uses this in webrtc_offer
                    "max_questions": interview.max_questions,
                    "max_duration_minutes": interview.max_duration_minutes,
                }
            )

            # ③ Create the signaling handler - it will process the SDP offer/answer
            #    exchange and ICE candidates when they arrive over the WebSocket
            self._signaling = WebRTCSignaling(
                session_id=self._session_id,
                job_id=self._job_id,
                candidate_id=self._candidate_id,
            )

            # ④ Start the WS receive loop NOW (before waiting for WebRTC ready)
            #    so it can immediately process the webrtc_offer the frontend sends.
            #    The interrupt monitor also starts here.
            ws_task = asyncio.create_task(self._ws_receive_loop())
            interrupt_task = asyncio.create_task(self._interrupt_monitor_loop())

            # ⑤ Block until the WebRTC peer connection is established.
            #    _handle_webrtc_offer() sets _webrtc_ready once the answer is sent.
            #    30 second timeout - if the frontend never sends an offer, we abort.
            try:
                await asyncio.wait_for(self._webrtc_ready.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                ws_task.cancel()
                interrupt_task.cancel()
                await self._send({"type": "error", "message": "WebRTC setup timed out"})
                return

            # ⑥ Wire the data channel handler so we receive in-call events
            #    (screen share start/stop, clarification requests, etc.)
            #    Also close the mic immediately - it stays closed until the
            #    agent's opening turn finishes (see _on_turn_complete).
            if self._webrtc:
                self._webrtc.audio_bridge.close_mic()  # explicitly start closed
                self._webrtc.data_channel.on_inbound_event = self._on_datachannel_event

            # ⑦ Build the agent - it receives audio from the WebRTC AudioBridge
            #    and sends audio output back through it. All I/O callbacks are
            #    methods on this connection object so they can forward to the WS.
            agent = LiveInterviewAgent(
                live_adapter=self._live_adapter,
                orchestration=self._orchestration,
                queue=self._queue,
                cache=self._cache,
                audio_input_stream=self._audio_input_stream(),
                on_audio_output=self._on_audio_output,
                on_text_output=self._on_text_output,
                on_input_text_output=self._on_input_text_output,
                on_interrupt=self._on_interrupt,
                on_turn_complete=self._on_turn_complete,
            )

            # ⑧ Run all three concurrent tasks. They will run until:
            #    - The agent raises InterviewCompleteSignal (interview done)
            #    - The candidate sends end_session (early exit)
            #    - The candidate disconnects (WebSocketDisconnect)
            #    - An unhandled exception occurs
            agent_task = asyncio.create_task(agent.run(context))

            await asyncio.gather(agent_task, ws_task, interrupt_task)

        except WebSocketDisconnect:
            logger.info(f"Candidate {self._candidate_id} disconnected")
            await self._handle_disconnect("candidate_disconnected")

        except Exception as e:
            logger.error(f"Interview connection error: {e}", exc_info=True)
            await self._send({"type": "error", "message": str(e)})
            await self._handle_disconnect("error")

        finally:
            # Always clean up the WebRTC signaling resources regardless of
            # how the session ended (normal completion, disconnect, or error)
            if self._signaling:
                await self._signaling.close()

    # ──────────────────
    # INTERRUPT HANDLING
    # ──────────────────

    async def _on_interrupt(self) -> None:
        """
        Called by the LiveInterviewAgent when Gemini signals it has been
        interrupted (the candidate started speaking while the agent was talking).

        What we do here:
        1. Tell the AudioBridge to discard everything in its outbound queue
           (so the agent's buffered speech stops playing immediately).
        2. Mark the agent as no longer speaking.
        3. Set _suppress_audio = True for 300ms - a brief window to absorb
           any in-flight audio chunks that are still arriving from Gemini
           before it processes the interrupt. Without this, stale audio
           can "leak" through after the interrupt.

        The 300ms is a tuning parameter - long enough to absorb Gemini's
        in-flight response buffer, short enough not to delay the candidate.
        """
        if self._webrtc:
            await self._webrtc.audio_bridge.clear_outbound_queue()
            # clear_buf is called inside clear_outbound_queue on the track,
            # so the flag clear must come AFTER the queue is empty
            self._webrtc.audio_bridge.set_agent_speaking(False)
        self._suppress_audio = True
        await asyncio.sleep(0.3)
        self._suppress_audio = False

    async def _on_turn_complete(self) -> None:
        """
        Called by the LiveInterviewAgent when Gemini signals a turn_complete -
        meaning the agent has finished speaking its current response.

        This is the handoff point from agent speaking -> candidate speaking.
        The sequence is carefully ordered to avoid audio glitches:

        1. Close the mic immediately - we don't want any candidate audio reaching
           Gemini during the transition (it could confuse the model into thinking
           the candidate is interrupting).
        2. Wait for the outbound queue AND the track's internal buffer to fully
           drain. The track's recv() loop is still consuming frames, so we just
           poll until both are empty - we do NOT forcefully clear here.
        3. Sleep 300ms - gives the WebRTC stack time to clock the last frames
           out to the browser before we reset the resampler.
        4. Clear the queue + reset the resampler/pts - NOW it's safe because
           all legitimate audio has already been played.
        5. Open the mic and mark agent as not speaking - candidate can now talk.

        This ordering prevents the resampler reset from happening mid-playback
        and causing audible pops or truncated speech.
        """
        if not self._webrtc:
            return

        bridge = self._webrtc.audio_bridge
        track = bridge._outbound_track

        # Close mic immediately - no candidate audio to Gemini while we transition
        bridge.close_mic()

        # Wait for the queue and track buffer to fully drain naturally
        # (recv() is still running and consuming frames - let it finish)
        while not bridge.outbound_queue.empty() or (track and track.has_buffered_audio):
            await asyncio.sleep(0.02)

        # Give the WebRTC stack time to clock out the last frames to the browser
        await asyncio.sleep(0.3)

        # NOW clear - all legitimate audio has played, resampler + pts reset cleanly
        await bridge.clear_outbound_queue()  # clears buf, resets resampler, resets pts/_start

        # Open mic for candidate response
        bridge.open_mic()
        bridge.set_agent_speaking(False)

    # ──────────────────────
    # WEBSOCKET RECEIVE LOOP
    # ──────────────────────

    async def _ws_receive_loop(self) -> None:
        """
        Continuously reads text messages from the WebSocket and dispatches
        them to the appropriate handler based on the 'type' field.

        This runs as a background asyncio task for the entire duration of the
        session. It handles two phases:

        PRE-WEBRTC (before _webrtc_ready is set):
          - webrtc_offer   -> _handle_webrtc_offer()   - full SDP/ICE handshake
          - ice_candidate  -> _handle_ice_candidate()  - trickle ICE

        POST-WEBRTC (agent is running):
          - end_session    -> abandon the interview and break
          - ping           -> respond with pong (frontend keepalive)

        Note: Audio data NEVER flows through this path. The WebSocket is purely
        a control channel. All media goes through the WebRTC peer connection.
        """
        logger.info("WS receive loop started")
        async for raw in self._ws.iter_text():
            logger.info(f"\nWS message received: {raw}\n")
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON message: {raw}")
                continue

            match msg.get("type"):

                # WebRTC handshake (before agent starts) 
                case "webrtc_offer":
                    await self._handle_webrtc_offer(msg)

                case "ice_candidate":
                    await self._handle_ice_candidate(msg)

                # Control messages (after agent starts)
                case "end_session":
                    reason = msg.get("reason", "candidate_ended")
                    await self._orchestration.abandon_interview(
                        self._interview_id, reason=reason
                    )
                    await self._send(
                        {
                            "type": "session_ended",
                            "status": "abandoned",
                            "reason": reason,
                        }
                    )
                    break

                case "ping":
                    await self._send({"type": "pong"})

    # ────────────────────────
    # WEBRTC HANDSHAKE HANDLERS
    # ─────────────────────────

    async def _handle_webrtc_offer(self, msg: dict) -> None:
        """
        Processes the WebRTC offer from the frontend and completes the
        SDP negotiation (offer/answer exchange).

        Flow:
        1. Pass the SDP offer to WebRTCSignaling, which creates the peer
           connection and generates an SDP answer.
        2. Send that answer back over the same WebSocket - the frontend uses
           it to complete its side of the handshake.
        3. Store the WebRTCClient reference (gives us access to AudioBridge,
           DataChannel, etc.).
        4. Wire up the ICE candidate forwarding callback so that as the
           server-side ICE agent discovers candidates, they get sent to
           the frontend over the WebSocket.
        5. Set _webrtc_ready to unblock run() which is waiting on it.

        Expected message shape:
          { type: "webrtc_offer", sdp: "...", sdp_type: "offer",
            frame_interval_camera: 5.0, frame_interval_screen: 2.0 }
        """
        if not self._signaling:
            return

        sdp_answer = await self._signaling.handle_offer(
            sdp=msg["sdp"],
            sdp_type=msg.get("sdp_type", "offer"),
            frame_interval_camera=msg.get("frame_interval_camera", 5.0),
            frame_interval_screen=msg.get("frame_interval_screen", 2.0),
        )

        # Send answer back over the same WebSocket
        await self._send(
            {
                "type": "webrtc_answer",
                "sdp": sdp_answer,
                "sdp_type": "answer",
            }
        )

        # Store client reference + wire outbound audio track
        self._webrtc = self._signaling.client

        # Wire ICE candidate forwarding 
        # As the server's ICE agent discovers network candidates, forward
        # each one to the frontend over the WebSocket (trickle ICE pattern).
        async def _forward_ice(candidate) -> None:
            await self._send(
                {
                    "type": "ice_candidate",
                    "candidate": candidate.candidate,
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex,
                }
            )

        if self._webrtc:
            self._webrtc.on_ice_candidate = _forward_ice

        # Unblock agent startup - run() is waiting on this event
        self._webrtc_ready.set()

    async def _handle_ice_candidate(self, msg: dict) -> None:
        """
        Processes a trickle ICE candidate received from the frontend.

        The frontend discovers its network candidates asynchronously and sends
        them one by one as they're found. We forward each to WebRTCSignaling
        which adds them to the peer connection to help establish connectivity.

        Expected message shape:
          { type: "ice_candidate", candidate: "...", sdpMid: "0", sdpMLineIndex: 0 }
        """
        if not self._signaling:
            return
        await self._signaling.handle_ice_candidate(
            candidate=msg["candidate"],
            sdp_mid=msg.get("sdpMid"),
            sdp_mline_index=msg.get("sdpMLineIndex"),
        )

    # ───────────────────────
    # AUDIO I/O - WEBRTC PATHS
    # ────────────────────────
    # Audio never touches the WebSocket. Instead it flows through the WebRTC
    # AudioBridge which sits between the WebRTC peer connection and the agent.
    #
    # Inbound path:  Browser mic -> WebRTC track -> AudioBridge.inbound_queue
    #                             -> _audio_input_stream() -> Gemini Live API
    #
    # Outbound path: Gemini Live API -> _on_audio_output() ->
    #                AudioBridge.outbound_queue -> _AgentAudioTrack -> Browser speaker

    async def _audio_input_stream(self) -> AsyncIterator[bytes]:
        """
        Async generator that yields raw PCM chunks from the browser's microphone.

        These chunks come from the WebRTC AudioBridge's inbound queue, which is
        fed by the aiortc audio track. The agent's _send_audio_loop() iterates
        over this generator and forwards each chunk to Gemini.

        Raises RuntimeError if called before WebRTC is set up (which shouldn't
        happen given the _webrtc_ready gate in run(), but worth protecting).
        """
        if not self._webrtc:
            raise RuntimeError("WebRTC not ready before audio stream started")
        async for chunk_tuple in self._webrtc.audio_bridge.audio_input_stream():
            yield chunk_tuple

    async def _on_audio_output(self, audio_bytes: bytes) -> None:
        """
        Called by the LiveInterviewAgent each time Gemini sends a chunk of
        audio response (24kHz mono s16 PCM).

        We push it into the AudioBridge's outbound queue, which feeds the
        _AgentAudioTrack that streams audio to the browser via WebRTC.

        The _suppress_audio flag is checked first - if we're in an interrupt
        window, we drop the chunk silently rather than playing stale speech.
        """
        if self._suppress_audio:
            return
        if self._webrtc:
            await self._webrtc.audio_bridge.push_audio(audio_bytes)

    async def _on_text_output(self, text: str) -> None:
        """
        Called by the agent when Gemini emits an output transcript chunk
        (the agent's own speech transcribed to text).

        We forward it to the frontend as a 'transcript' message so the UI
        can display live captions of what the AI interviewer is saying.
        """
        await self._send({"type": "transcript", "speaker": "agent", "text": text})

    async def _on_input_text_output(self, text: str) -> None:
        """
        Called by the agent when Gemini emits an input transcript chunk
        (the candidate's speech transcribed to text).

        We forward it to the frontend as a 'transcript' message so the UI
        can display live captions of what the candidate is saying.

        Note: This method is defined twice in the original - once here and once
        as a top-level method. The one passed to the agent constructor is this one.
        """
        await self._send({"type": "transcript", "speaker": "candidate", "text": text})

    # ────────────────────
    # DATA CHANNEL INBOUND
    # ────────────────────

    async def _on_datachannel_event(self, event: dict) -> None:
        """
        Handles events that arrive over the WebRTC DataChannel (not audio,
        not the WebSocket - the third communication channel).

        The DataChannel is used for structured in-call events that aren't
        audio: screen share lifecycle, clarification requests, etc.

        Currently mostly logging - in the future we'd feed these into the
        agent's context or trigger specific orchestration actions.

        Event types:
          screen_share_start    - candidate started sharing their screen
          screen_share_stop     - candidate stopped sharing their screen
          clarification_request - candidate asked for clarification (could
                                  be injected into agent context)
        """
        match event.get("type"):
            case "screen_share_start":
                logger.info(f"[{self._interview_id}] Screen share started")
            case "screen_share_stop":
                logger.info(f"[{self._interview_id}] Screen share stopped")
            case "clarification_request":
                # Could feed into agent context if needed
                pass

    # ─────────────────
    # INTERRUPT MONITOR
    # ─────────────────

    async def _interrupt_monitor_loop(self) -> None:
        """
        Polls Redis every 50ms for interrupt signals published by the agent.

        The agent (LiveInterviewAgent._tool_flag_interrupt) writes interrupt
        data to Redis under the key "interrupt:{interview_id}". This loop
        reads that key and, when it finds something:

        1. Reads the directive (stop_and_listen, acknowledge_and_continue, resume)
        2. Sets _suppress_audio if the directive requires it
        3. Forwards the interrupt event to the frontend over the WebSocket
        4. Deletes the key from Redis so it doesn't fire again
        5. If stop_and_listen: waits 500ms then clears suppress_audio

        Why poll instead of pub/sub?
        Polling at 50ms is simple, predictable, and good enough for interrupt
        latency. If we needed sub-50ms we'd switch to Redis pub/sub.

        The loop runs for the entire session duration alongside the agent task.
        """
        if not self._interview_id:
            return

        cache_key = f"interrupt:{self._interview_id}"
        while True:
            await asyncio.sleep(_INTERRUPT_POLL_INTERVAL)
            try:
                interrupt = await self._cache.get(cache_key)
            except Exception:
                continue

            if interrupt:
                directive = interrupt.get("directive", "stop_and_listen")
                self._suppress_audio = directive == "stop_and_listen"

                await self._send(
                    {
                        "type": "interrupt",
                        "interrupt_id": interrupt.get("interrupt_id"),
                        "directive": directive,
                        "type_detail": interrupt.get("type"),
                    }
                )
                await self._cache.delete(cache_key)

                if directive == "stop_and_listen":
                    await asyncio.sleep(0.5)
                    self._suppress_audio = False

    # ───────────────
    # CONTEXT BUILDER
    # ───────────────

    async def _build_context(self, interview_id: uuid.UUID) -> InterviewContext:
        """
        Loads the Job and Candidate aggregates from the DB and packages
        them into an InterviewContext dataclass that the agent uses to:
          - Build the Gemini system prompt (job title, skills, instructions)
          - Inject interview metadata (max questions, topics, duration limit)
          - Personalise the greeting (candidate name)

        Raises RuntimeError if either the job or candidate can't be found -
        we can't run an interview without both.

        Note: candidate_resume_text is intentionally None for now. Resume
        parsing/injection is a planned feature.
        """
        job = await self._job_repo.get_by_id(self._job_id)
        candidate = await self._candidate_repo.get_by_id(self._candidate_id)

        if not job:
            raise RuntimeError(f"Job {self._job_id} not found")
        if not candidate:
            raise RuntimeError(f"Candidate {self._candidate_id} not found")

        return InterviewContext(
            interview_id=interview_id,
            job_title=job.title,
            job_description=job.description,
            required_skills=[s.name for s in job.required_skills],
            experience_level=job.experience_level.value,
            max_questions=job.interview_config.max_questions,
            max_duration_minutes=job.interview_config.max_duration_minutes,
            topics=job.interview_config.topics,
            custom_instructions=job.interview_config.custom_instructions,
            candidate_name=candidate.full_name,
            candidate_resume_text=None,  # TODO: wire up resume parsing
        )

    async def _handle_disconnect(self, reason: str) -> None:
        """
        Called when the candidate disconnects or an error forces session end.
        Marks the interview as abandoned in the DB so it doesn't sit in a
        'in_progress' state forever.

        Called from the except blocks in run() - always safe to call even
        if the interview was already completed (orchestration handles idempotency).
        """
        if self._interview_id:
            await self._orchestration.abandon_interview(
                self._interview_id, reason=reason
            )

    async def _send(self, payload: dict) -> None:
        """
        Safely sends a JSON message over the WebSocket.

        Wraps the send in a try/except because the WebSocket may have already
        closed by the time we try to send (e.g., during disconnect cleanup).
        We log a warning rather than raising so cleanup code can continue.
        """
        try:
            await self._ws.send_text(json.dumps(payload))
        except Exception as e:
            logger.warning(f"Failed to send WS message: {e}")
