"""
Command handlers for the interview session lifecycle.

Each handler is a plain async function that:
  1. Validates / loads its inputs
  2. Delegates to the appropriate service
  3. Returns a typed response dataclass — never a raw dict

These are called from:
  - WebSocket message handlers  (StartSession, Interrupt, AbandonSession)
  - WebRTC signalling handlers  (AskQuestion, SubmitAnswer)
  - Background task runners     (AbandonSession on timeout)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from src.truefit_core.application.services import InterviewOrchestrationService
from src.truefit_core.application.ports import (
    CachePort,
    DomainEvent,
    InterviewRepository,
    QueuePort,
)
from src.truefit_core.common.utils import logger


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────
# Input dataclasses  (what the handler receives)
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class StartSessionCommand:
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    # WebRTC / transport metadata captured at connection time
    agent_version: Optional[str] = None
    connection_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AskQuestionCommand:
    interview_id: uuid.UUID
    # Optional: caller can force a topic (e.g. agent decides to probe a skill gap)
    topic_override: Optional[str] = None


@dataclass(frozen=True)
class SubmitAnswerCommand:
    interview_id: uuid.UUID
    question_id: uuid.UUID
    # In v1 this arrives as an STT transcript from the audio pipeline.
    # In future text support this is the raw typed input.
    answer_text: str
    duration_seconds: Optional[int] = None
    # Storage keys of audio/video chunks captured for this answer turn
    media_asset_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class InterruptCommand:
    """
    Fired when VAD detects the candidate speaking while the agent is talking.
    The interrupt carries whatever partial transcript was captured before
    the agent stopped, and a reason so the agent can decide how to respond.
    """
    interview_id: uuid.UUID
    turn_id: Optional[uuid.UUID]         # the turn that was interrupted
    partial_transcript: Optional[str]    # STT of what the candidate said so far
    interrupt_at_ms: int                 # ms into the agent's audio playback


class InterruptReason(str, Enum):
    CANDIDATE_SPOKE = "candidate_spoke"   # normal interrupt — candidate has something to say
    CLARIFICATION = "clarification"       # agent detects this is a question, not an answer
    NOISE = "noise"                       # VAD false positive — agent should resume
    TECHNICAL = "technical"              # connectivity / audio issue


@dataclass(frozen=True)
class AbandonSessionCommand:
    interview_id: uuid.UUID
    reason: str = "unknown"
    initiated_by: str = "system"   # "candidate" | "system" | "timeout"


# ────────────────────────────────────────────────
# Response dataclasses  (what the handler returns)
# ────────────────────────────────────────────────

@dataclass(frozen=True)
class StartSessionResponse:
    interview_id: uuid.UUID
    session_status: str
    max_questions: int
    max_duration_minutes: int
    started_at: str


@dataclass(frozen=True)
class AskQuestionResponse:
    question_id: uuid.UUID
    text: str
    topic: Optional[str]
    question_number: int
    total_questions: int
    is_last: bool


@dataclass(frozen=True)
class SubmitAnswerResponse:
    status: str                          # "answer_recorded" | "completed"
    interview_id: uuid.UUID
    answered_count: int
    remaining_questions: int
    interview_completed: bool


@dataclass(frozen=True)
class InterruptResponse:
    interview_id: uuid.UUID
    interrupt_id: uuid.UUID              # unique ID so the agent can ack it
    reason: InterruptReason
    agent_should: str                    # "stop_and_listen" | "resume" | "acknowledge_and_continue"
    partial_transcript: Optional[str]


@dataclass(frozen=True)
class AbandonSessionResponse:
    interview_id: uuid.UUID
    status: str
    reason: str


# ────────
# Handlers
# ─────────

async def handle_start_session(
    cmd: StartSessionCommand,
    *,
    orchestration: InterviewOrchestrationService,
) -> StartSessionResponse:
    """
    Create and start an interview session.
    Called once per candidate when they enter the interview room.
    The agent should call ask_next_question immediately after this succeeds.
    """
    interview = await orchestration.start_interview(
        job_id=cmd.job_id,
        candidate_id=cmd.candidate_id,
    )

    return StartSessionResponse(
        interview_id=interview.id,
        session_status=interview.status.value,
        max_questions=interview.max_questions,
        max_duration_minutes=interview.max_duration_minutes,
        started_at=interview.started_at.isoformat() if interview.started_at else _utcnow_iso(),
    )


async def handle_ask_question(
    cmd: AskQuestionCommand,
    *,
    orchestration: InterviewOrchestrationService,
) -> AskQuestionResponse:
    """
    Generate and record the next AI question.

    In the audio-first flow the agent calls this after:
      - Session start (first question)
      - A complete answer has been received and processed
      - An interrupt has been resolved (clarification answered, noise dismissed)

    The returned text is what the TTS pipeline converts to agent speech.
    """
    result = await orchestration.ask_next_question(
        cmd.interview_id,
        topic_override=cmd.topic_override,
    )

    return AskQuestionResponse(
        question_id=uuid.UUID(result["question_id"]),
        text=result["text"],
        topic=result.get("topic"),
        question_number=result["question_number"],
        total_questions=result["total_questions"],
        is_last=result["is_last"],
    )


async def handle_submit_answer(
    cmd: SubmitAnswerCommand,
    *,
    orchestration: InterviewOrchestrationService,
) -> SubmitAnswerResponse:
    """
    Record the candidate's answer (STT transcript) for the current question.

    media_asset_keys are stored for audit / replay but do not affect
    domain state — they're linked at the infra layer via InterviewTurn.
    """
    result = await orchestration.submit_answer(
        interview_id=cmd.interview_id,
        question_id=cmd.question_id,
        answer_text=cmd.answer_text,
        duration_seconds=cmd.duration_seconds,
    )

    completed = result.get("status") == "completed"

    return SubmitAnswerResponse(
        status=result["status"],
        interview_id=cmd.interview_id,
        answered_count=result.get("answered_count", 0),
        remaining_questions=result.get("remaining_questions", 0),
        interview_completed=completed,
    )


async def handle_interrupt(
    cmd: InterruptCommand,
    *,
    interview_repo: InterviewRepository,
    queue: QueuePort,
    cache: CachePort,
) -> InterruptResponse:
    """
    Handle a mid-speech interrupt from the candidate.

    This handler does NOT touch the Interview domain aggregate directly —
    interrupts are session-level events, not transcript-level events.
    The agent decides how to respond based on the returned `agent_should` directive.

    Interrupt classification logic:
    - Short utterance + question pattern  → CLARIFICATION  → agent acknowledges and re-asks
    - Substantive speech                  → CANDIDATE_SPOKE → agent stops and listens
    - Very short / low confidence STT     → NOISE           → agent resumes
    """
    interrupt_id = uuid.uuid4()

    # Load interview to make sure it's still active before doing anything
    interview = await interview_repo.get_by_id(cmd.interview_id)
    if interview is None:
        raise ValueError(f"Interview {cmd.interview_id} not found")
    if not interview.is_active:
        raise ValueError(
            f"Cannot interrupt a non-active interview (status={interview.status.value})"
        )

    reason, directive = _classify_interrupt(cmd)

    # Cache the interrupt briefly so the agent's audio pipeline can check it
    # without a DB call (the agent polls this key before emitting the next chunk)
    interrupt_cache_key = f"interrupt:{cmd.interview_id}"
    await cache.set(
        interrupt_cache_key,
        {
            "interrupt_id": str(interrupt_id),
            "reason": reason.value,
            "directive": directive,
            "partial_transcript": cmd.partial_transcript,
            "interrupt_at_ms": cmd.interrupt_at_ms,
        },
        ttl_seconds=30,
    )

    await queue.publish(DomainEvent(
        event_type="interview.interrupted",
        aggregate_id=str(cmd.interview_id),
        aggregate_type="Interview",
        occurred_at=_utcnow_iso(),
        payload={
            "interview_id": str(cmd.interview_id),
            "interrupt_id": str(interrupt_id),
            "turn_id": str(cmd.turn_id) if cmd.turn_id else None,
            "reason": reason.value,
            "directive": directive,
            "partial_transcript": cmd.partial_transcript,
            "interrupt_at_ms": cmd.interrupt_at_ms,
        },
    ))

    logger.info(
        f"Interrupt {interrupt_id} on interview {cmd.interview_id}: "
        f"{reason.value} → {directive}"
    )

    return InterruptResponse(
        interview_id=cmd.interview_id,
        interrupt_id=interrupt_id,
        reason=reason,
        agent_should=directive,
        partial_transcript=cmd.partial_transcript,
    )


async def handle_abandon_session(
    cmd: AbandonSessionCommand,
    *,
    orchestration: InterviewOrchestrationService,
) -> AbandonSessionResponse:
    """
    Abandon an in-progress interview.
    Safe to call on timeout, disconnect, or explicit cancellation.
    Idempotent — calling on an already-finished interview is a no-op.
    """
    await orchestration.abandon_interview(
        cmd.interview_id,
        reason=f"{cmd.reason}:{cmd.initiated_by}",
    )

    return AbandonSessionResponse(
        interview_id=cmd.interview_id,
        status="abandoned",
        reason=cmd.reason,
    )


# ───────────────────
# Internal helpers
# ───────────────────

def _classify_interrupt(cmd: InterruptCommand) -> tuple[InterruptReason, str]:
    """
    Heuristic classification of an interrupt based on the partial transcript.

    Returns (reason, agent_directive).

    This is intentionally kept simple — in production you'd call a fast
    classification model or use a rules engine. Swap out this function
    without touching the handler.
    """
    transcript = (cmd.partial_transcript or "").strip().lower()
    word_count = len(transcript.split()) if transcript else 0

    # Very short utterance — likely noise or filler word
    if word_count == 0 or (word_count <= 2 and not _is_question(transcript)):
        return InterruptReason.NOISE, "resume"

    # Ends with a question mark or starts with a question word → clarification
    if _is_question(transcript):
        return InterruptReason.CLARIFICATION, "acknowledge_and_continue"

    # Substantive speech — candidate wants to answer or redirect
    return InterruptReason.CANDIDATE_SPOKE, "stop_and_listen"


_QUESTION_STARTERS = frozenset({
    "what", "when", "where", "who", "why", "how", "could", "can",
    "would", "should", "is", "are", "do", "does", "did", "will",
})


def _is_question(text: str) -> bool:
    if text.endswith("?"):
        return True
    first_word = text.split()[0] if text else ""
    return first_word in _QUESTION_STARTERS