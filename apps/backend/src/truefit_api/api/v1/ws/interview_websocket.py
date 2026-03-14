# interview_websocket.py
from __future__ import annotations

import asyncio
import base64
import json
import uuid
from typing import AsyncIterator, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from google import genai

from src.truefit_core.application.services.interview_orchestration import InterviewOrchestrationService
from src.truefit_core.application.ports import CachePort, CandidateRepository, JobRepository, QueuePort
from src.truefit_core.common.utils import logger
from src.truefit_infra.realtime.signaling import WebRTCSignaling
from src.truefit_infra.realtime.webrtc_client import WebRTCClient
from src.truefit_infra.cache.redis_cache import RedisCacheAdapter, redis_client
from src.truefit_infra.queue.redis_queue import RedisQueueAdapter 
from src.truefit_infra.db.database import db_manager
from src.truefit_infra.db.repositories.interview_repository import SQLAlchemyInterviewRepository
from src.truefit_infra.db.repositories.job_repository import SQLAlchemyJobRepository
from src.truefit_infra.db.repositories.candidate_repository import SQLAlchemyCandidateRepository
from src.truefit_infra.agent.live_interview_agent import InterviewContext, LiveInterviewAgent
from src.truefit_infra.llm.gemini_live import GeminiLiveAdapter


# ── Dependencies ───

def get_interview_repo() -> SQLAlchemyInterviewRepository:
    return SQLAlchemyInterviewRepository(db_manager)

def get_job_repo() -> SQLAlchemyJobRepository:
    return SQLAlchemyJobRepository(db_manager)

def get_candidate_repo() -> SQLAlchemyCandidateRepository:
    return SQLAlchemyCandidateRepository(db_manager)

def get_cache() -> RedisCacheAdapter:
    return redis_client         

def get_queue() -> RedisQueueAdapter:
    return RedisQueueAdapter()  

def get_gemini_live() -> GeminiLiveAdapter:
    return GeminiLiveAdapter()   


def get_orchestration() -> InterviewOrchestrationService:
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



interview_ws_router = APIRouter(tags=["interview-ws"], prefix="/api/v1")

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


class InterviewConnection:

    def __init__(self, *, websocket, job_id, candidate_id, orchestration,
                 job_repo, candidate_repo, queue, cache, live_adapter) -> None:
        self._ws = websocket
        self._job_id = job_id
        self._candidate_id = candidate_id
        self._orchestration = orchestration
        self._job_repo = job_repo
        self._candidate_repo = candidate_repo
        self._queue = queue
        self._cache = cache
        self._live_adapter = live_adapter

        self._interview_id: Optional[uuid.UUID] = None
        self._session_id: Optional[str] = None
        self._suppress_audio = False

        # Set once WebRTC handshake completes
        self._webrtc: Optional[WebRTCClient] = None
        self._signaling: Optional[WebRTCSignaling] = None

        # Unblocks agent startup after WebRTC is wired
        self._webrtc_ready = asyncio.Event()

    # ── Entry point ─

    async def run(self) -> None:
        self._session_id = str(uuid.uuid4())

        try:
            # ① Domain setup
            interview = await self._orchestration.start_interview(
                job_id=self._job_id,
                candidate_id=self._candidate_id,
            )
            self._interview_id = interview.id
            context = await self._build_context(interview.id)

            print(f"\n\n\nStarted interview {interview.id} for job {self._job_id} and candidate {self._candidate_id}\n\n\n")

            # ② Tell the frontend the session exists + the session_id it needs for signaling
            await self._send({
                "type": "session_started",
                "interview_id": str(interview.id),
                "session_id": self._session_id,     # ← frontend uses this in webrtc_offer
                "max_questions": interview.max_questions,
                "max_duration_minutes": interview.max_duration_minutes,
            })

            # ③ Instantiate signaling (no HTTP, no router)
            self._signaling = WebRTCSignaling(
                session_id=self._session_id,
                job_id=self._job_id,
                candidate_id=self._candidate_id,
            )

            # ④ Start receive loop NOW so it can process the offer while we wait
            ws_task = asyncio.create_task(self._ws_receive_loop())
            interrupt_task = asyncio.create_task(self._interrupt_monitor_loop())


            # ④ Wait for WebRTC to connect before starting agent
            #    (_ws_receive_loop handles the offer/ICE messages and sets _webrtc_ready)
            try:
                await asyncio.wait_for(self._webrtc_ready.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                ws_task.cancel()
                interrupt_task.cancel()
                await self._send({"type": "error", "message": "WebRTC setup timed out"})
                return

            # ⑤ Wire up DataChannel inbound → this connection's handler
            if self._webrtc:
                self._webrtc.data_channel.on_inbound_event = self._on_datachannel_event

            # ⑥ Build agent — audio I/O now comes from WebRTC AudioBridge
            agent = LiveInterviewAgent(
                live_adapter=self._live_adapter,
                orchestration=self._orchestration,
                queue=self._queue,
                cache=self._cache,
                audio_input_stream=self._audio_input_stream(),
                on_audio_output=self._on_audio_output,
                on_text_output=self._on_text_output,
            )

            # ⑧ Run agent alongside the already-running tasks
            agent_task = asyncio.create_task(agent.run(context))

            await asyncio.gather(agent_task, ws_task, interrupt_task)


            # # ⑦ Run everything concurrently
            # await asyncio.gather(
            #     agent.run(context),
            #     self._ws_receive_loop(),
            #     self._interrupt_monitor_loop(),
            # )

        except WebSocketDisconnect:
            logger.info(f"Candidate {self._candidate_id} disconnected")
            await self._handle_disconnect("candidate_disconnected")

        except Exception as e:
            logger.error(f"Interview connection error: {e}", exc_info=True)
            await self._send({"type": "error", "message": str(e)})
            await self._handle_disconnect("error")

        finally:
            if self._signaling:
                await self._signaling.close()

    # ── WebSocket receive loop ────────────────────────────────────────────────

    async def _ws_receive_loop(self) -> None:
        """
        All WS messages flow through here.

        Before WebRTC ready:   handles webrtc_offer, ice_candidate
        After WebRTC ready:    handles control messages (end_session, ping)
        Audio never arrives here — it flows via WebRTC AudioBridge.
        """
        logger.info("WS receive loop started")
        async for raw in self._ws.iter_text():
            logger.info(f"WS message received: {raw[:100]}") 
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            match msg.get("type"):

                # ── WebRTC handshake (before agent starts) ────────────────
                case "webrtc_offer":
                    await self._handle_webrtc_offer(msg)

                case "ice_candidate":
                    await self._handle_ice_candidate(msg)

                # ── Control messages (after agent starts) ─────────────────
                case "end_session":
                    reason = msg.get("reason", "candidate_ended")
                    await self._orchestration.abandon_interview(self._interview_id, reason=reason)
                    await self._send({"type": "session_ended", "status": "abandoned", "reason": reason})
                    break

                case "ping":
                    await self._send({"type": "pong"})

    # ── WebRTC handshake handlers (called from receive loop) ─────────────────

    async def _handle_webrtc_offer(self, msg: dict) -> None:
        """
        Browser sent { type: webrtc_offer, sdp, sdp_type, ... }.
        Delegates to WebRTCSignaling, sends back the answer, fires _webrtc_ready.
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
        await self._send({
            "type": "webrtc_answer",
            "sdp": sdp_answer,
            "sdp_type": "answer",
        })

        
        # Store client reference + wire outbound audio track
        self._webrtc = self._signaling.client

        # Unblock agent startup
        self._webrtc_ready.set()

    async def _handle_ice_candidate(self, msg: dict) -> None:
        """Browser sent { type: ice_candidate, candidate, sdpMid, sdpMLineIndex }."""
        if not self._signaling:
            return
        await self._signaling.handle_ice_candidate(
            candidate=msg["candidate"],
            sdp_mid=msg.get("sdpMid"),
            sdp_mline_index=msg.get("sdpMLineIndex"),
        )

    # ── Audio I/O — WebRTC paths ──────────────────────────────────────────────

    async def _audio_input_stream(self) -> AsyncIterator[bytes]:
        """Reads PCM from AudioBridge.inbound_queue (filled by WebRTC track pump)."""
        if not self._webrtc:
            raise RuntimeError("WebRTC not ready before audio stream started")
        async for chunk in self._webrtc.audio_bridge.audio_input_stream():
            yield chunk

    async def _on_audio_output(self, audio_bytes: bytes) -> None:
        """Pushes agent PCM into AudioBridge.outbound_queue → WebRTC track → browser."""
        if self._suppress_audio:
            return
        if self._webrtc:
            await self._webrtc.audio_bridge.push_audio(audio_bytes)

    async def _on_text_output(self, text: str) -> None:
        """Transcripts go over the WebSocket control channel."""
        await self._send({"type": "transcript", "speaker": "agent", "text": text})

    # ── DataChannel inbound (candidate actions during the call) ──────────────

    async def _on_datachannel_event(self, event: dict) -> None:
        match event.get("type"):
            case "screen_share_start":
                logger.info(f"[{self._interview_id}] Screen share started")
            case "screen_share_stop":
                logger.info(f"[{self._interview_id}] Screen share stopped")
            case "clarification_request":
                # Could feed into agent context if needed
                pass

    # ── Interrupt monitor — unchanged, stays on WS ───────────────────────────

    async def _interrupt_monitor_loop(self) -> None:
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

                await self._send({
                    "type": "interrupt",
                    "interrupt_id": interrupt.get("interrupt_id"),
                    "directive": directive,
                    "type_detail": interrupt.get("type"),
                })
                await self._cache.delete(cache_key)

                if directive == "stop_and_listen":
                    await asyncio.sleep(0.5)
                    self._suppress_audio = False

    # ── Context builder — unchanged ───────────────────────────────────────────

    async def _build_context(self, interview_id: uuid.UUID) -> InterviewContext:
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
            candidate_resume_text=None,
        )

    async def _handle_disconnect(self, reason: str) -> None:
        if self._interview_id:
            await self._orchestration.abandon_interview(self._interview_id, reason=reason)

    async def _send(self, payload: dict) -> None:
        try:
            await self._ws.send_text(json.dumps(payload))
        except Exception as e:
            logger.warning(f"Failed to send WS message: {e}")