"""
Updated for agent-driven flow.

Key changes from the original:
- ask_next_question now accepts question_text_override and is_follow_up.
  In agent-driven mode the agent already SPOKE the question before calling
  record_question — so we record what it said rather than generating new text.
- submit_answer is unchanged — the agent calls it with STT transcript.
- start_interview is unchanged — still called once by the WebSocket handler.
- The service is now a state guardian, not a flow controller.
  It enforces domain rules and persists state; the agent decides what to say.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from src.truefit_core.common.utils import logger
from src.truefit_core.domain.interview import Interview, InterviewStatus
from src.truefit_core.application.ports import (
    CachePort,
    CandidateRepository,
    DomainEvent,
    InterviewRepository,
    JobRepository,
    LLMPort,
    QuestionContext,
    QueuePort,
)


_EVENT_INTERVIEW_STARTED = "interview.started"
_EVENT_QUESTION_ASKED = "interview.question_asked"
_EVENT_ANSWER_SUBMITTED = "interview.answer_submitted"
_EVENT_INTERVIEW_COMPLETED = "interview.completed"
_EVENT_INTERVIEW_ABANDONED = "interview.abandoned"

_SESSION_LOCK_PREFIX = "interview_session_lock"
_SESSION_LOCK_TTL = 60


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InterviewOrchestrationService:
    def __init__(
        self,
        *,
        interview_repo: InterviewRepository,
        job_repo: JobRepository,
        candidate_repo: CandidateRepository,
        llm: LLMPort,
        queue: QueuePort,
        cache: CachePort,
    ) -> None:
        self._interviews = interview_repo
        self._jobs = job_repo
        self._candidates = candidate_repo
        self._llm = llm
        self._queue = queue
        self._cache = cache

    # ── Start session ─────

    async def start_interview(
        self,
        *,
        job_id: uuid.UUID,
        candidate_id: uuid.UUID,
    ) -> Interview:
        """
        Validate eligibility, create and persist the Interview aggregate.
        Called ONCE by the WebSocket handler before handing off to the agent.
        """
        lock_key = f"{_SESSION_LOCK_PREFIX}:{candidate_id}:{job_id}"

        if await self._cache.exists(lock_key):
            raise ValueError(
                "A session creation is already in progress for this candidate and job"
            )
        await self._cache.set(lock_key, "1", ttl_seconds=_SESSION_LOCK_TTL)

        try:
            job = await self._jobs.get_by_id(job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            job.assert_open_for_interviews()

            candidate = await self._candidates.get_by_id(candidate_id)
            if candidate is None:
                raise ValueError(f"Candidate {candidate_id} not found")
            candidate.assert_eligible_to_interview()

            candidate.register_active_interview(job_id)

            config = job.interview_config
            interview = Interview(
                job_id=job_id,
                candidate_id=candidate_id,
                org_id=job.org_id,
                max_questions=config.max_questions,
                max_duration_minutes=config.max_duration_minutes,
            )
            interview.start()

            await self._interviews.save(interview)
            await self._candidates.save(candidate)

            await self._queue.publish(DomainEvent(
                event_type=_EVENT_INTERVIEW_STARTED,
                aggregate_id=str(interview.id),
                aggregate_type="Interview",
                occurred_at=_utcnow_iso(),
                payload={
                    "interview_id": str(interview.id),
                    "job_id": str(job_id),
                    "candidate_id": str(candidate_id),
                    "org_id": str(job.org_id),
                    "max_questions": config.max_questions,
                    "max_duration_minutes": config.max_duration_minutes,
                },
            ))

            logger.info(f"Interview {interview.id} started for candidate {candidate_id}")
            return interview

        finally:
            await self._cache.delete(lock_key)

    # ── Record question (agent-driven) ──

    async def ask_next_question(
        self,
        interview_id: uuid.UUID,
        *,
        # Agent-driven: the agent already spoke the question, we just record it
        question_text_override: Optional[str] = None,
        topic_override: Optional[str] = None,
        is_follow_up: bool = False,
    ) -> dict:
        """
        Record a question on the interview transcript.

        Two modes:
        1. Agent-driven (v1):  question_text_override is provided.
           The agent already said the question aloud — we record what it said.

        2. Service-driven (fallback / future text mode): no override.
           We call the LLM port to generate the next question.
        """
        interview = await self._get_active_interview(interview_id)

        if interview.awaiting_answer:
            raise ValueError("Cannot record a new question while the previous is unanswered")
        if not interview.can_ask_more:
            raise ValueError(
                f"Interview has reached the maximum of {interview.max_questions} questions"
            )

        if question_text_override:
            question_text = question_text_override
            topic = topic_override
        else:
            # Fallback: service generates question (text mode)
            job = await self._jobs.get_by_id(interview.job_id)
            if job is None:
                raise RuntimeError(f"Job {interview.job_id} not found")

            config = job.interview_config
            context = QuestionContext(
                job_title=job.title,
                job_description=job.description,
                required_skills=[s.name for s in job.required_skills],
                experience_level=job.experience_level.value,
                custom_instructions=config.custom_instructions,
                transcript=interview.transcript,
                topics_remaining=self._remaining_topics(interview, config.topics),
                question_number=interview.question_count + 1,
                total_questions=interview.max_questions,
            )
            generated = await self._llm.generate_question(context)
            question_text = generated.text
            topic = topic_override or generated.topic

        follow_up_of = None
        if is_follow_up and interview.current_question:
            follow_up_of = interview.current_question.id

        question = interview.ask_question(
            text=question_text,
            topic=topic,
            follow_up_of=follow_up_of,
        )
        await self._interviews.save(interview)

        await self._queue.publish(DomainEvent(
            event_type=_EVENT_QUESTION_ASKED,
            aggregate_id=str(interview_id),
            aggregate_type="Interview",
            occurred_at=_utcnow_iso(),
            payload={
                "interview_id": str(interview_id),
                "question_id": str(question.id),
                "question_number": interview.question_count,
                "total_questions": interview.max_questions,
                "topic": question.topic,
            },
        ))

        return {
            "question_id": str(question.id),
            "text": question.text,
            "topic": question.topic,
            "question_number": interview.question_count,
            "total_questions": interview.max_questions,
            "is_last": interview.question_count >= interview.max_questions,
        }

    # ── Submit answer ────

    async def submit_answer(
        self,
        *,
        interview_id: uuid.UUID,
        question_id: uuid.UUID,
        answer_text: str,
        duration_seconds: Optional[int] = None,
    ) -> dict:
        interview = await self._get_active_interview(interview_id)

        interview.submit_answer(
            question_id=question_id,
            text=answer_text,
            duration_seconds=duration_seconds,
        )
        await self._interviews.save(interview)

        await self._queue.publish(DomainEvent(
            event_type=_EVENT_ANSWER_SUBMITTED,
            aggregate_id=str(interview_id),
            aggregate_type="Interview",
            occurred_at=_utcnow_iso(),
            payload={
                "interview_id": str(interview_id),
                "question_id": str(question_id),
                "answered_count": interview.answered_count,
            },
        ))

        if not interview.can_ask_more and not interview.awaiting_answer:
            return await self._complete_and_respond(interview)

        return {
            "status": "answer_recorded",
            "answered_count": interview.answered_count,
            "remaining_questions": interview.max_questions - interview.question_count,
        }

    # ── Abandon ──

    async def abandon_interview(
        self,
        interview_id: uuid.UUID,
        *,
        reason: str = "unknown",
    ) -> None:
        interview = await self._interviews.get_by_id(interview_id)
        if interview is None:
            raise ValueError(f"Interview {interview_id} not found")

        if interview.is_finished:
            logger.info(f"Interview {interview_id} already finished, ignoring abandon")
            return

        interview.abandon(reason=reason)
        await self._interviews.save(interview)
        await self._release_candidate_lock(interview)

        await self._queue.publish(DomainEvent(
            event_type=_EVENT_INTERVIEW_ABANDONED,
            aggregate_id=str(interview_id),
            aggregate_type="Interview",
            occurred_at=_utcnow_iso(),
            payload={
                "interview_id": str(interview_id),
                "candidate_id": str(interview.candidate_id),
                "job_id": str(interview.job_id),
                "reason": reason,
                "questions_answered": interview.answered_count,
            },
        ))
        logger.info(f"Interview {interview_id} abandoned: {reason}")

    # ── Internal helpers ──

    async def _complete_and_respond(self, interview: Interview) -> dict:
        interview.complete()
        await self._interviews.save(interview)
        await self._release_candidate_lock(interview)

        await self._queue.publish(DomainEvent(
            event_type=_EVENT_INTERVIEW_COMPLETED,
            aggregate_id=str(interview.id),
            aggregate_type="Interview",
            occurred_at=_utcnow_iso(),
            payload={
                "interview_id": str(interview.id),
                "candidate_id": str(interview.candidate_id),
                "job_id": str(interview.job_id),
                "org_id": str(interview.org_id),
                "questions_answered": interview.answered_count,
                "elapsed_minutes": interview.elapsed_minutes,
            },
        ))
        logger.info(f"Interview {interview.id} completed ({interview.answered_count} answers)")

        return {
            "status": "completed",
            "interview_id": str(interview.id),
            "questions_answered": interview.answered_count,
        }

    async def _release_candidate_lock(self, interview: Interview) -> None:
        candidate = await self._candidates.get_by_id(interview.candidate_id)
        if candidate:
            candidate.release_active_interview(interview.job_id)
            await self._candidates.save(candidate)

    async def _get_active_interview(self, interview_id: uuid.UUID) -> Interview:
        interview = await self._interviews.get_by_id(interview_id)
        if interview is None:
            raise ValueError(f"Interview {interview_id} not found")
        if not interview.is_active:
            raise ValueError(
                f"Interview {interview_id} is not active (status={interview.status.value})"
            )
        return interview

    @staticmethod
    def _remaining_topics(interview: Interview, all_topics: list[str]) -> list[str]:
        covered = {t.question.topic for t in interview.turns if t.question.topic}
        return [t for t in all_topics if t not in covered] or all_topics