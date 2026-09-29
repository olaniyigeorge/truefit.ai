"""
Interview tool handlers - the interview-domain half of the tool contract.

INTERVIEW_TOOLS (tools.py) declares what the model may call; this class holds
the handlers that persist state through the orchestration service, cache and
queue. LiveInterviewAgent registers them with the generic VoiceAgentRuntime.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from src.truefit_core.agents.runtime import SessionComplete
from src.truefit_core.application.ports import CachePort, DomainEvent, QueuePort
from src.truefit_core.application.services.interview_orchestration import (
    InterviewOrchestrationService,
)
from src.truefit_core.common.utils import logger

# Safety-net TTL for interrupt signals in Redis. The interrupt monitor normally
# reads and deletes the key within ~50ms.
INTERRUPT_CACHE_TTL = 30

_INTERRUPT_DIRECTIVES = {
    "clarification": "acknowledge_and_continue",
    "answer": "stop_and_listen",
    "noise": "resume",
    "technical": "stop_and_listen",
}


class InterviewCompleteSignal(SessionComplete):
    """Raised by complete_interview to end the interview normally (not an error)."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InterviewToolHandlers:
    def __init__(
        self,
        *,
        interview_id: uuid.UUID,
        orchestration: InterviewOrchestrationService,
        queue: QueuePort,
        cache: CachePort,
        stop_session: Callable[[str], None],
    ) -> None:
        """stop_session: ends the runtime's loops after the current tool response."""
        self._interview_id = interview_id
        self._orchestration = orchestration
        self._queue = queue
        self._cache = cache
        self._stop_session = stop_session
        # Set by record_question so persist_answer needn't have the model echo the id.
        self.current_question_id: Optional[uuid.UUID] = None

    def as_map(self) -> dict[str, Callable[[dict], Any]]:
        return {
            "record_question": self.record_question,
            "persist_answer": self.persist_answer,
            "complete_interview": self.complete_interview,
            "flag_interrupt": self.flag_interrupt,
        }

    async def record_question(self, args: dict) -> dict:
        """Register the question the model is about to ask. On rejection, tell it to wait."""
        try:
            result = await self._orchestration.ask_next_question(
                self._interview_id,
                topic_override=args.get("topic"),
                question_text_override=args.get("question_text"),
                is_follow_up=args.get("is_follow_up", False),
            )
            self.current_question_id = uuid.UUID(result["question_id"])
            return {
                "success": True,
                "question_id": result["question_id"],
                "question_number": result["question_number"],
                "questions_remaining": result["total_questions"]
                - result["question_number"],
            }
        except Exception as e:
            logger.warning(f"[InterviewTools] record_question rejected: {e}")
            return {
                "success": False,
                "directive": "wait_for_candidate_answer",
                "message": "A question is already active. Please wait for the candidate to respond before recording a new question.",
            }

    async def persist_answer(self, args: dict) -> dict:
        """
        Save the answer. Question id resolution: explicit arg, else the one
        stored by record_question. Stops the session once the interview is
        complete, after the model has had its tool response.
        """
        question_id_str = args.get("question_id") or (
            str(self.current_question_id) if self.current_question_id else None
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
            self._stop_session("questions_exhausted")

        return {
            "success": True,
            "answered_count": result.get("answered_count", 0),
            "interview_complete": result.get("status") == "completed",
            "remaining_questions": result.get("remaining_questions", 0),
        }

    async def complete_interview(self, args: dict) -> dict:
        """
        Publish interview.agent_ending for downstream consumers, then raise
        InterviewCompleteSignal. It raises rather than returns: the session is
        ending, so the model gets no tool response.
        """
        reason = args.get("reason", "questions_exhausted")
        await self._queue.publish(
            DomainEvent(
                event_type="interview.agent_ending",
                aggregate_id=str(self._interview_id),
                aggregate_type="Interview",
                occurred_at=_utcnow_iso(),
                payload={
                    "interview_id": str(self._interview_id),
                    "reason": reason,
                    "closing_remarks": args.get("closing_remarks", ""),
                },
            )
        )
        raise InterviewCompleteSignal(reason)

    async def flag_interrupt(self, args: dict) -> dict:
        """
        Two-part signal. Cache: "interrupt:{interview_id}" for the WebSocket
        layer's ~50ms interrupt monitor. Queue: interview.interrupted for
        downstream consumers.

        Directives: clarification -> acknowledge_and_continue, noise -> resume,
        answer/technical/unknown -> stop_and_listen.
        """
        interrupt_id = uuid.uuid4()
        interrupt_type = args.get("interrupt_type", "answer")
        directive = _INTERRUPT_DIRECTIVES.get(interrupt_type, "stop_and_listen")

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
        await self._queue.publish(
            DomainEvent(
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
            )
        )
        return {
            "success": True,
            "interrupt_id": str(interrupt_id),
            "directive": directive,
        }
