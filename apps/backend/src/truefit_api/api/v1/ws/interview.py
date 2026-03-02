"""
WebSocket endpoint that manages a live interview session.

Responsibilities
────────────────
1. Authenticate the connection (candidate + job)
2. Start the domain interview via InterviewOrchestrationService
3. Build InterviewContext from DB snapshot
4. Bridge WebRTC audio ↔ Gemini Live session via LiveInterviewAgent
5. Forward agent audio output back to the candidate
6. Handle interrupt signals — stop outgoing audio when cache key is set
7. Clean up on disconnect

Message protocol (client → server, JSON over WS)
──────────────────────────────────────────────────
  { "type": "audio_chunk", "data": "<base64 PCM bytes>" }
  { "type": "end_session",  "reason": "candidate_ended" }
  { "type": "ping" }

Message protocol (server → client, JSON over WS)
──────────────────────────────────────────────────
  { "type": "session_started",  "interview_id": "...", "max_questions": N }
  { "type": "audio_chunk",      "data": "<base64 PCM bytes>" }
  { "type": "transcript",       "speaker": "agent|candidate", "text": "..." }
  { "type": "question_recorded","question_id": "...", "number": N, "total": N }
  { "type": "answer_recorded",  "answered": N, "remaining": N }
  { "type": "interrupt",        "directive": "stop_and_listen|resume|..." }
  { "type": "session_ended",    "status": "completed|abandoned", "reason": "..." }
  { "type": "error",            "message": "..." }
  { "type": "pong" }
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from typing import AsyncIterator, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from google import genai

from src.truefit_core.application.services.interview_orchestration import (
    InterviewOrchestrationService,
)
from src.truefit_core.application.ports import (
    CachePort,
    CandidateRepository,
    JobRepository,
    QueuePort,
)
from src.truefit_infra.agent.live_interview_agent import (
    InterviewContext,
    LiveInterviewAgent,
)
from src.truefit_core.common.utils import logger


interview_ws_router = APIRouter(tags=["interview-ws"])

# How often to poll the interrupt cache key (ms)
_INTERRUPT_POLL_INTERVAL = 0.05  # 50ms


@interview_ws_router.websocket("/ws/interview/{job_id}/{candidate_id}")
async def interview_websocket(
    websocket: WebSocket,
    job_id: uuid.UUID,
    candidate_id: uuid.UUID,
    # Injected via FastAPI dependency injection
    orchestration: InterviewOrchestrationService = Depends(),
    job_repo: JobRepository = Depends(),
    candidate_repo: CandidateRepository = Depends(),
    queue: QueuePort = Depends(),
    cache: CachePort = Depends(),
    genai_client: genai.Client = Depends(),
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
        genai_client=genai_client,
    )
    await connection.run()


class InterviewConnection:
    """
    Manages the full lifecycle of one WebSocket interview connection.
    Encapsulated as a class so state (audio queue, interview_id, etc.)
    is scoped to the connection without globals.
    """

    def __init__(
        self,
        *,
        websocket: WebSocket,
        job_id: uuid.UUID,
        candidate_id: uuid.UUID,
        orchestration: InterviewOrchestrationService,
        job_repo: JobRepository,
        candidate_repo: CandidateRepository,
        queue: QueuePort,
        cache: CachePort,
        genai_client: genai.Client,
    ) -> None:
        self._ws = websocket
        self._job_id = job_id
        self._candidate_id = candidate_id
        self._orchestration = orchestration
        self._job_repo = job_repo
        self._candidate_repo = candidate_repo
        self._queue = queue
        self._cache = cache
        self._genai_client = genai_client

        # Audio queue: WebSocket receives chunks → agent reads them
        self._audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()

        self._interview_id: Optional[uuid.UUID] = None
        self._suppress_audio = False  # True when an interrupt is active

    # ── Entry point ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        try:
            # 1. Start the domain interview
            interview = await self._orchestration.start_interview(
                job_id=self._job_id,
                candidate_id=self._candidate_id,
            )
            self._interview_id = interview.id

            # 2. Build context snapshot from DB
            context = await self._build_context(interview.id)

            # 3. Notify client the session is ready
            await self._send({
                "type": "session_started",
                "interview_id": str(interview.id),
                "max_questions": interview.max_questions,
                "max_duration_minutes": interview.max_duration_minutes,
            })

            # 4. Create the agent
            agent = LiveInterviewAgent(
                genai_client=self._genai_client,
                orchestration=self._orchestration,
                queue=self._queue,
                cache=self._cache,
                audio_input_stream=self._audio_input_stream(),
                on_audio_output=self._on_audio_output,
                on_text_output=self._on_text_output,
            )

            # 5. Run agent + WS receiver concurrently
            await asyncio.gather(
                agent.run(context),
                self._ws_receive_loop(),
                self._interrupt_monitor_loop(),
            )

        except WebSocketDisconnect:
            logger.info(f"Candidate {self._candidate_id} disconnected")
            await self._handle_disconnect("candidate_disconnected")

        except Exception as e:
            logger.error(f"Interview connection error: {e}")
            await self._send({"type": "error", "message": str(e)})
            await self._handle_disconnect("error")

        finally:
            await self._audio_queue.put(None)  # signal audio stream to stop

    # ── WebSocket receive loop ─────────────────────────────────────────────────

    async def _ws_receive_loop(self) -> None:
        """
        Receive messages from the candidate's browser.
        Routes audio chunks into the audio queue and handles control messages.
        """
        async for raw in self._ws.iter_text():
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "audio_chunk":
                # Decode base64 PCM and enqueue for the agent
                audio_bytes = base64.b64decode(msg["data"])
                await self._audio_queue.put(audio_bytes)

            elif msg_type == "end_session":
                reason = msg.get("reason", "candidate_ended")
                await self._orchestration.abandon_interview(
                    self._interview_id, reason=reason
                )
                await self._send({
                    "type": "session_ended",
                    "status": "abandoned",
                    "reason": reason,
                })
                break

            elif msg_type == "ping":
                await self._send({"type": "pong"})

    # ── Audio stream (generator for the agent) ────────────────────────────────

    async def _audio_input_stream(self) -> AsyncIterator[bytes]:
        """
        Async generator that yields PCM audio chunks from the WebSocket queue.
        The agent's _send_audio_loop iterates this.
        None sentinel signals end of stream.
        """
        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:
                break
            yield chunk

    # ── Audio output (agent → candidate) ──────────────────────────────────────

    async def _on_audio_output(self, audio_bytes: bytes) -> None:
        """
        Forward agent audio to the candidate's browser.
        Suppressed when an interrupt is active — stops mid-speech playback.
        """
        if self._suppress_audio:
            return

        await self._send({
            "type": "audio_chunk",
            "data": base64.b64encode(audio_bytes).decode(),
        })

    async def _on_text_output(self, text: str) -> None:
        """Forward agent text transcript to the client (for captions/debug)."""
        await self._send({
            "type": "transcript",
            "speaker": "agent",
            "text": text,
        })

    # ── Interrupt monitor ──────────────────────────────────────────────────────

    async def _interrupt_monitor_loop(self) -> None:
        """
        Poll the interrupt cache key set by LiveInterviewAgent._tool_flag_interrupt.
        When detected:
          - Suppress outgoing audio immediately (no more chunks sent to client)
          - Send interrupt directive to client so it can stop local playback
          - Clear the cache key

        This loop runs concurrently with the agent so interrupt response
        latency is bounded by the poll interval (50ms), not a DB round-trip.
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

                if directive in ("stop_and_listen",):
                    self._suppress_audio = True
                elif directive == "resume":
                    self._suppress_audio = False

                await self._send({
                    "type": "interrupt",
                    "interrupt_id": interrupt.get("interrupt_id"),
                    "directive": directive,
                    "type_detail": interrupt.get("type"),
                })

                # Clear so we don't re-process
                await self._cache.delete(cache_key)

                # Resume audio suppression after a short window
                # (agent will re-enable when it resumes speaking)
                if directive == "stop_and_listen":
                    await asyncio.sleep(0.5)
                    self._suppress_audio = False

    # ── Context builder ───

    async def _build_context(self, interview_id: uuid.UUID) -> InterviewContext:
        """
        Load job + candidate data and build the InterviewContext snapshot.
        This is injected into Gemini once at session start.
        """
        job = await self._job_repo.get_by_id(self._job_id)
        candidate = await self._candidate_repo.get_by_id(self._candidate_id)

        if job is None:
            raise RuntimeError(f"Job {self._job_id} not found")
        if candidate is None:
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
            candidate_resume_text=None,  # TODO: extract text from resume PDF via StoragePort
        )

    # ── Disconnect handler ────────────────────────────────────────────────────

    async def _handle_disconnect(self, reason: str) -> None:
        if self._interview_id:
            await self._orchestration.abandon_interview(
                self._interview_id, reason=reason
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _send(self, payload: dict) -> None:
        try:
            await self._ws.send_text(json.dumps(payload))
        except Exception as e:
            logger.warning(f"Failed to send WS message: {e}")