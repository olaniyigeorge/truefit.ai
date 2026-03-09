from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Coroutine, Optional

# ← No google/genai imports here at all
from src.truefit_core.application.services.interview_orchestration import InterviewOrchestrationService
from src.truefit_core.application.ports import CachePort, DomainEvent, QueuePort
from src.truefit_core.common.utils import logger
from src.truefit_core.agents.interviewer.context import InterviewContext
from src.truefit_core.agents.interviewer.prompts import build_system_prompt
from src.truefit_core.agents.interviewer.tools import INTERVIEW_TOOLS
from src.truefit_infra.llm.gemini_live import GeminiLiveAdapter

INTERRUPT_CACHE_TTL = 30


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LiveInterviewAgent:

    def __init__(
        self,
        *,
        live_adapter: GeminiLiveAdapter,
        orchestration: InterviewOrchestrationService,
        queue: QueuePort,
        cache: CachePort,
        audio_input_stream: AsyncIterator[bytes],
        on_audio_output: Callable[[bytes], Coroutine],
        on_text_output: Optional[Callable[[str], Coroutine]] = None,
    ) -> None:
        self._adapter = live_adapter
        self._orchestration = orchestration
        self._queue = queue
        self._cache = cache
        self._audio_input = audio_input_stream
        self._on_audio_output = on_audio_output
        self._on_text_output = on_text_output
        self._current_question_id: Optional[uuid.UUID] = None
        self._interview_id: Optional[uuid.UUID] = None
        self._session_complete = asyncio.Event()

    # ── Entry point ──

    async def run(self, context: InterviewContext) -> None:
        self._interview_id = context.interview_id

        # open_session owns all LiveConnectConfig — agent has no SDK knowledge
        async with self._adapter.open_session(
            system_prompt=build_system_prompt(context),
            tools=INTERVIEW_TOOLS,
        ) as session:
            logger.info(f"[Agent] Session opened for interview {context.interview_id}")
            await self._inject_context(session, context)

            try:
                await asyncio.gather(
                    self._send_audio_loop(session),
                    self._receive_loop(session),
                )
            except InterviewCompleteSignal as sig:
                logger.info(f"[Agent] Interview {context.interview_id} completed: {sig.reason}")
            except Exception as e:
                logger.error(f"[Agent] Interview {context.interview_id} error: {e}")
                await self._orchestration.abandon_interview(
                    context.interview_id, reason="agent_error"
                )
                raise

    # ── Context injection ─────────────────────────────────────────────────────

    async def _inject_context(self, session: GeminiLiveAdapter, ctx: InterviewContext) -> None:
        await session.send_client_content(
            text=(
                f"Interview session is starting now.\n"
                f"Context: {json.dumps({
                    'interview_id': str(ctx.interview_id),
                    'job_title': ctx.job_title,
                    'required_skills': ctx.required_skills,
                    'max_questions': ctx.max_questions,
                    'topics': ctx.topics,
                }, indent=2)}\n\n"
                f"Please greet {ctx.candidate_name} warmly and begin "
                f"the interview when you hear them speak."
            )
        )

    # ── Audio sender ──────────────────────────────────────────────────────────

    async def _send_audio_loop(self, session: GeminiLiveAdapter) -> None:
        async for chunk in self._audio_input:
            if self._session_complete.is_set():
                break
            await session.send_audio(chunk)

    # ── Response receiver ─────────────────────────────────────────────────────

    async def _receive_loop(self, session: GeminiLiveAdapter) -> None:
        async for event_type, data in session.receive():
            if self._session_complete.is_set():
                break

            match event_type:
                case "audio":
                    await self._on_audio_output(data)
                case "text":
                    if self._on_text_output:
                        await self._on_text_output(data)
                case "input_text":
                    logger.debug(f"[Agent] Candidate said: {data}")
                case "tool_call":
                    result = await self._handle_tool_call(
                        name=data["name"],
                        args=data["args"],
                        call_id=data["id"],
                    )
                    await session.send_tool_response(
                        call_id=data["id"],
                        name=data["name"],
                        result=result,
                    )
                case "turn_complete":
                    logger.debug("[Agent] Turn complete")
                case "interrupted":
                    logger.debug("[Agent] Candidate interrupted")
                case "go_away":
                    logger.warning("[Agent] Server closing connection")
                    break

    # ── Tool dispatcher ───────────────────────────────────────────────────────

    async def _handle_tool_call(
        self, *, name: str, args: dict[str, Any], call_id: str
    ) -> dict[str, Any]:
        logger.info(f"[Agent] Tool: {name}({args})")
        try:
            match name:
                case "record_question":    return await self._tool_record_question(args)
                case "persist_answer":     return await self._tool_persist_answer(args)
                case "complete_interview": return await self._tool_complete_interview(args)
                case "flag_interrupt":     return await self._tool_flag_interrupt(args)
                case _:
                    logger.warning(f"[Agent] Unknown tool: {name}")
                    return {"error": f"Unknown tool: {name}", "success": False}
        except InterviewCompleteSignal:
            raise
        except Exception as e:
            logger.error(f"[Agent] Tool {name} failed: {e}")
            return {"error": str(e), "success": False}

    # ── Tool implementations ──────────────────────────────────────────────────

    async def _tool_record_question(self, args: dict) -> dict:
        result = await self._orchestration.ask_next_question(
            self._interview_id,
            topic_override=args.get("topic"),
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
        question_id_str = args.get("question_id") or (
            str(self._current_question_id) if self._current_question_id else None
        )
        if not question_id_str:
            return {"error": "No active question", "success": False}

        result = await self._orchestration.submit_answer(
            interview_id=self._interview_id,
            question_id=uuid.UUID(question_id_str),
            answer_text=args["answer_transcript"],
            duration_seconds=args.get("duration_seconds"),
        )
        if result.get("status") == "completed":
            self._session_complete.set()

        return {
            "success": True,
            "answered_count": result.get("answered_count", 0),
            "interview_complete": result.get("status") == "completed",
            "remaining_questions": result.get("remaining_questions", 0),
        }

    async def _tool_complete_interview(self, args: dict) -> dict:
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
        interrupt_id = uuid.uuid4()
        interrupt_type = args.get("interrupt_type", "answer")
        directive = {
            "clarification": "acknowledge_and_continue",
            "answer":        "stop_and_listen",
            "noise":         "resume",
            "technical":     "stop_and_listen",
        }.get(interrupt_type, "stop_and_listen")

        await self._cache.set(
            f"interrupt:{self._interview_id}",
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
        return {"success": True, "interrupt_id": str(interrupt_id), "directive": directive}


class InterviewCompleteSignal(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)