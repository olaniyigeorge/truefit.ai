"""
Real-time interview agent powered by Gemini Live API.

Architecture
────────────
The agent is the orchestrator. It drives the interview autonomously via the
Gemini Live session. Our application layer is NOT polling or driving turns —
instead, the agent calls back into the system via Gemini tool_calls when it
needs to persist state or enforce business rules.

Flow
────
1.  WebSocket handler calls LiveInterviewAgent.run(session_id, interview_id)
2.  Agent opens a Gemini Live connection with:
      - A system prompt built from the job + candidate context
      - Tool declarations for persist_answer, complete_interview, flag_interrupt
      - response_modalities: AUDIO (agent speaks back)
3.  Candidate audio chunks arrive via WebRTC → forwarded to Gemini via
    send_realtime_input (Gemini's built-in VAD handles turn detection)
4.  Gemini streams audio back → forwarded to candidate via WebRTC
5.  When Gemini decides an answer is complete it calls persist_answer tool
6.  When Gemini decides the interview is done it calls complete_interview tool
7.  Interrupts are handled natively by Gemini VAD — no separate detection needed

Tool call loop
──────────────
  receive() yields LiveServerMessage
    ├── server_content  → audio/text to stream back to candidate
    └── tool_call       → dispatch to _handle_tool_call()
                              ├── persist_answer      → orchestration service
                              ├── complete_interview  → orchestration service
                              ├── flag_interrupt      → cache + queue
                              └── request_clarification → no-op (agent handles it)

Key design decisions
────────────────────
- send_realtime_input is used exclusively for audio (not send_client_content)
  because it enables VAD and is optimised for low-latency streaming.
- send_client_content is used ONCE at session start to inject the full
  interview context (job, candidate, instructions) before audio begins.
- The agent never calls ask_next_question — Gemini decides the next question
  autonomously based on the system prompt + conversation history it maintains.
- InterviewOrchestrationService is still responsible for domain state;
  the agent only calls it via tool responses, never bypassing it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Optional

from google import genai
from google.genai import types as genai_types

from src.truefit_core.application.services.interview_orchestration import (
    InterviewOrchestrationService,
)
from src.truefit_core.application.ports import (
    CachePort,
    DomainEvent,
    QueuePort,
)
from src.truefit_core.common.utils import logger
from truefit_core.agents.interviewer.context import InterviewContext
from truefit_core.agents.interviewer.prompts import build_system_prompt
from truefit_core.agents.interviewer.tools import INTERVIEW_TOOLS


# ── Constants ──

LIVE_MODEL = "gemini-live-2.5-flash-preview"
AUDIO_MIME_TYPE = "audio/pcm;rate=16000"
INTERRUPT_CACHE_TTL = 30  # seconds


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



# ── Main agent class ───

class LiveInterviewAgent:
    """
    Manages a single live interview session with Gemini.

    Lifecycle:
      agent = LiveInterviewAgent(...)
      await agent.run(context)   ← blocks until interview ends or error

    Audio I/O is handled via callbacks injected at construction:
      - audio_input_stream: async generator yielding raw PCM bytes from WebRTC
      - on_audio_output: coroutine called with each audio chunk to send to candidate
    """

    def __init__(
        self,
        *,
        genai_client: genai.Client,
        orchestration: InterviewOrchestrationService,
        queue: QueuePort,
        cache: CachePort,
        # Audio I/O bridges — provided by the WebSocket/WebRTC handler
        audio_input_stream: AsyncIterator[bytes],
        on_audio_output: Callable[[bytes], asyncio.coroutine],
        on_text_output: Optional[Callable[[str], asyncio.coroutine]] = None,
    ) -> None:
        self._client = genai_client
        self._orchestration = orchestration
        self._queue = queue
        self._cache = cache
        self._audio_input = audio_input_stream
        self._on_audio_output = on_audio_output
        self._on_text_output = on_text_output

        # Mutable session state
        self._current_question_id: Optional[uuid.UUID] = None
        self._interview_id: Optional[uuid.UUID] = None
        self._session_complete = asyncio.Event()

    # ── Public entry point ──

    async def run(self, context: InterviewContext) -> None:
        """
        Start and run the full interview session.
        Blocks until the interview is complete or an unrecoverable error occurs.
        """
        self._interview_id = context.interview_id

        live_config = genai_types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=build_system_prompt(context),
            tools=INTERVIEW_TOOLS,
            # VAD is enabled by default with send_realtime_input
            # speech_config controls the agent's voice output
            speech_config=genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                        voice_name="Aoede"  # natural, professional voice
                    )
                )
            ),
        )

        async with self._client.aio.live.connect(
            model=LIVE_MODEL,
            config=live_config,
        ) as session:
            logger.info(f"Gemini Live session opened for interview {context.interview_id}")

            # Inject full context once before audio begins
            # This pre-fills the model's context window with job + candidate data
            await self._inject_context(session, context)

            # Run audio sender and response receiver concurrently
            try:
                await asyncio.gather(
                    self._send_audio_loop(session),
                    self._receive_loop(session),
                )
            except InterviewCompleteSignal:
                logger.info(f"Interview {context.interview_id} completed normally")
            except Exception as e:
                logger.error(f"Interview {context.interview_id} error: {e}")
                await self._orchestration.abandon_interview(
                    context.interview_id,
                    reason="agent_error",
                )
                raise

    # ── Context injection ───

    async def _inject_context(
        self, session: genai.live.AsyncSession, ctx: InterviewContext
    ) -> None:
        """
        Pre-fill the model context with structured job + candidate data.
        Uses send_client_content (not send_realtime_input) because this is
        a one-time structured message, not a realtime audio stream.
        After this, all candidate input will be audio via send_realtime_input.
        """
        context_payload = {
            "interview_id": str(ctx.interview_id),
            "job_title": ctx.job_title,
            "required_skills": ctx.required_skills,
            "max_questions": ctx.max_questions,
            "topics": ctx.topics,
        }

        await session.send_client_content(
            turns=genai_types.Content(
                role="user",
                parts=[
                    genai_types.Part(
                        text=(
                            f"Interview session is starting now.\n"
                            f"Context: {json.dumps(context_payload, indent=2)}\n\n"
                            f"Please greet {ctx.candidate_name} warmly and begin the interview "
                            f"when you hear them speak."
                        )
                    )
                ],
            ),
            turn_complete=True,
        )

    # ── Audio sender ───

    async def _send_audio_loop(self, session: genai.live.AsyncSession) -> None:
        """
        Forward raw PCM audio chunks from WebRTC into the Gemini session.
        Gemini's built-in VAD handles turn detection automatically —
        we do not need to signal end-of-turn manually.
        """
        async for chunk in self._audio_input:
            if self._session_complete.is_set():
                break
            await session.send_realtime_input(
                audio=genai_types.Blob(
                    data=chunk,
                    mime_type=AUDIO_MIME_TYPE,
                )
            )

    # ── Response receiver ────

    async def _receive_loop(self, session: genai.live.AsyncSession) -> None:
        """
        Process all messages from the Gemini Live server.

        LiveServerMessage variants we handle:
          - server_content.model_turn.parts  → audio/text to stream to candidate
          - tool_call                         → dispatch to _handle_tool_call
        """
        async for message in session.receive():
            if self._session_complete.is_set():
                break

            # ── Audio / text output from the agent ───
            if message.server_content:
                content = message.server_content

                if content.model_turn:
                    for part in content.model_turn.parts:
                        # Stream audio back to candidate via WebRTC
                        if part.inline_data and part.inline_data.data:
                            await self._on_audio_output(part.inline_data.data)

                        # Optional text transcript of what the agent said
                        if part.text and self._on_text_output:
                            await self._on_text_output(part.text)

            # ── Tool calls from the agent ───
            if message.tool_call:
                for fn_call in message.tool_call.function_calls:
                    result = await self._handle_tool_call(
                        name=fn_call.name,
                        args=fn_call.args or {},
                        call_id=fn_call.id,
                    )
                    # Always respond to tool calls — Gemini blocks until we do
                    await session.send_tool_response(
                        function_responses=genai_types.FunctionResponse(
                            name=fn_call.name,
                            response=result,
                            id=fn_call.id,
                        )
                    )

    # ── Tool call dispatcher ───

    async def _handle_tool_call(
        self, *, name: str, args: dict[str, Any], call_id: str
    ) -> dict[str, Any]:
        """
        Dispatch agent tool calls to the appropriate handler.
        Returns a result dict that is sent back to Gemini as the tool response.
        """
        logger.info(f"Tool call: {name}({args}) [id={call_id}]")

        try:
            if name == "record_question":
                return await self._tool_record_question(args)
            elif name == "persist_answer":
                return await self._tool_persist_answer(args)
            elif name == "complete_interview":
                return await self._tool_complete_interview(args)
            elif name == "flag_interrupt":
                return await self._tool_flag_interrupt(args)
            else:
                logger.warning(f"Unknown tool call: {name}")
                return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.error(f"Tool call {name} failed: {e}")
            return {"error": str(e), "success": False}

    # ── Tool implementations ────

    async def _tool_record_question(self, args: dict) -> dict:
        """
        Agent has just asked a question — record it and return a question_id.
        The agent must use this question_id when calling persist_answer.
        """
        result = await self._orchestration.ask_next_question(
            self._interview_id,
            topic_override=args.get("topic"),
            # The agent already spoke the question — we're recording it after the fact
            question_text_override=args.get("question_text"),
            is_follow_up=args.get("is_follow_up", False),
        )

        self._current_question_id = uuid.UUID(result["question_id"])

        return {
            "success": True,
            "question_id": result["question_id"],
            "question_number": result["question_number"],
            "questions_remaining": result["total_questions"] - result["question_number"],
        }

    async def _tool_persist_answer(self, args: dict) -> dict:
        """
        Agent has determined the candidate finished answering — persist it.
        """
        question_id_str = args.get("question_id")
        if not question_id_str:
            # Fallback: use the most recently recorded question
            if not self._current_question_id:
                return {"error": "No active question to answer", "success": False}
            question_id_str = str(self._current_question_id)

        result = await self._orchestration.submit_answer(
            interview_id=self._interview_id,
            question_id=uuid.UUID(question_id_str),
            answer_text=args["answer_transcript"],
            duration_seconds=args.get("duration_seconds"),
        )

        interview_done = result.get("status") == "completed"
        if interview_done:
            self._session_complete.set()

        return {
            "success": True,
            "answered_count": result.get("answered_count", 0),
            "interview_complete": interview_done,
            "remaining_questions": result.get("remaining_questions", 0),
        }

    async def _tool_complete_interview(self, args: dict) -> dict:
        """
        Agent has decided the interview is over — trigger completion.
        This is a safety net; normally completion fires from persist_answer
        when the last question is answered.
        """
        reason = args.get("reason", "questions_exhausted")

        await self._queue.publish(DomainEvent(
            event_type="interview.agent_ending",
            aggregate_id=str(self._interview_id),
            aggregate_type="Interview",
            occurred_at=_utcnow_iso(),
            payload={
                "interview_id": str(self._interview_id),
                "reason": reason,
                "closing_remarks": args.get("closing_remarks", ""),
            },
        ))

        self._session_complete.set()
        raise InterviewCompleteSignal(reason)

    async def _tool_flag_interrupt(self, args: dict) -> dict:
        """
        Agent detected an interrupt — cache it so the WebRTC handler can
        stop the outgoing audio stream immediately.
        """
        interrupt_id = uuid.uuid4()
        interrupt_type = args.get("interrupt_type", "answer")

        directive_map = {
            "clarification": "acknowledge_and_continue",
            "answer": "stop_and_listen",
            "noise": "resume",
            "technical": "stop_and_listen",
        }
        directive = directive_map.get(interrupt_type, "stop_and_listen")

        cache_key = f"interrupt:{self._interview_id}"
        await self._cache.set(
            cache_key,
            {
                "interrupt_id": str(interrupt_id),
                "type": interrupt_type,
                "directive": directive,
                "partial_transcript": args.get("partial_transcript"),
                "timestamp": _utcnow_iso(),
            },
            ttl_seconds=INTERRUPT_CACHE_TTL,
        )

        await self._queue.publish(DomainEvent(
            event_type="interview.interrupted",
            aggregate_id=str(self._interview_id),
            aggregate_type="Interview",
            occurred_at=_utcnow_iso(),
            payload={
                "interview_id": str(self._interview_id),
                "interrupt_id": str(interrupt_id),
                "type": interrupt_type,
                "directive": directive,
                "partial_transcript": args.get("partial_transcript"),
            },
        ))

        logger.info(
            f"Interrupt flagged on interview {self._interview_id}: "
            f"{interrupt_type} → {directive}"
        )

        return {
            "success": True,
            "interrupt_id": str(interrupt_id),
            "directive": directive,
        }


# ── Internal signal exception ───

class InterviewCompleteSignal(Exception):
    """Raised by complete_interview tool to break out of the receive loop."""
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)