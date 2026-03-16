from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InterviewStatus(str, Enum):
    SCHEDULED = "scheduled"   # created, not yet started
    ACTIVE = "active"         # candidate is in session
    COMPLETED = "completed"   # all questions done / candidate ended session
    ABANDONED = "abandoned"   # timed-out or candidate disconnected
    EVALUATED = "evaluated"   # evaluation has been generated


@dataclass(frozen=True)
class Question:
    """
    Value object representing a single AI-generated question.
    Immutable — questions are never edited after they are sent.
    """
    id: uuid.UUID
    text: str
    topic: Optional[str] = None       # e.g. "system design", "behavioural"
    follow_up_of: Optional[uuid.UUID] = None  # links adaptive follow-ups to their parent
    asked_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Question text cannot be empty")


@dataclass(frozen=True)
class Answer:
    """
    Value object pairing an answer to its question.
    Immutable — once submitted, an answer is part of the permanent transcript.
    """
    question_id: uuid.UUID
    text: str
    answered_at: datetime = field(default_factory=_utcnow)
    duration_seconds: Optional[int] = None  # how long the candidate took

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Answer text cannot be empty")


@dataclass(frozen=True)
class Turn:
    """A paired question + optional answer — one exchange in the interview."""
    question: Question
    answer: Optional[Answer] = None

    @property
    def is_answered(self) -> bool:
        return self.answer is not None


class Interview:
    """
    Aggregate root for a live AI interview session.

    Lifecycle:  SCHEDULED → ACTIVE → COMPLETED → EVALUATED
                                   ↘ ABANDONED

    Invariants enforced:
    - Questions can only be asked during ACTIVE state.
    - An answer can only be submitted to the current (most recent) unanswered question.
    - An interview cannot exceed max_questions or max_duration_minutes (from job config).
    - Once COMPLETED or ABANDONED, the transcript is frozen.
    - EVALUATED requires a prior COMPLETED state.
    """

    def __init__(
        self,
        *,
        job_id: uuid.UUID,
        candidate_id: uuid.UUID,
        org_id: uuid.UUID,
        max_questions: int,
        max_duration_minutes: int,
        interview_id: Optional[uuid.UUID] = None,
        status: InterviewStatus = InterviewStatus.SCHEDULED,
        turns: Optional[list[Turn]] = None,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> None:
        if max_questions < 1:
            raise ValueError("max_questions must be at least 1")
        if max_duration_minutes < 1:
            raise ValueError("max_duration_minutes must be at least 1")

        self._id: uuid.UUID = interview_id or uuid.uuid4()
        self._job_id: uuid.UUID = job_id
        self._candidate_id: uuid.UUID = candidate_id
        self._org_id: uuid.UUID = org_id
        self._max_questions: int = max_questions
        self._max_duration_minutes: int = max_duration_minutes
        self._status: InterviewStatus = status
        self._turns: list[Turn] = list(turns or [])
        self._started_at: Optional[datetime] = started_at
        self._ended_at: Optional[datetime] = ended_at
        self._created_at: datetime = created_at or _utcnow()
        self._updated_at: datetime = updated_at or _utcnow()

    # ── Identity ──

    @property
    def id(self) -> uuid.UUID:
        return self._id

    @property
    def job_id(self) -> uuid.UUID:
        return self._job_id

    @property
    def candidate_id(self) -> uuid.UUID:
        return self._candidate_id

    @property
    def org_id(self) -> uuid.UUID:
        return self._org_id

    @property
    def status(self) -> InterviewStatus:
        return self._status

    @property
    def turns(self) -> list[Turn]:
        return list(self._turns)

    @property
    def started_at(self) -> Optional[datetime]:
        return self._started_at

    @property
    def ended_at(self) -> Optional[datetime]:
        return self._ended_at

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    @property
    def max_questions(self) -> int:
        return self._max_questions

    @property
    def max_duration_minutes(self) -> int:
        return self._max_duration_minutes

    # ── Queries ──

    @property
    def is_active(self) -> bool:
        return self._status == InterviewStatus.ACTIVE

    @property
    def is_finished(self) -> bool:
        return self._status in (
            InterviewStatus.COMPLETED,
            InterviewStatus.ABANDONED,
            InterviewStatus.EVALUATED,
        )

    @property
    def question_count(self) -> int:
        return len(self._turns)

    @property
    def answered_count(self) -> int:
        return sum(1 for t in self._turns if t.is_answered)

    @property
    def current_question(self) -> Optional[Question]:
        """The last asked question, regardless of whether it has been answered."""
        return self._turns[-1].question if self._turns else None

    @property
    def awaiting_answer(self) -> bool:
        """True when the last question has not yet been answered."""
        return bool(self._turns) and not self._turns[-1].is_answered

    @property
    def can_ask_more(self) -> bool:
        return (
            self.is_active
            and not self.awaiting_answer
            and self.question_count < self._max_questions
            and not self._is_timed_out()
        )

    @property
    def elapsed_minutes(self) -> Optional[float]:
        if not self._started_at:
            return None
        end = self._ended_at or _utcnow()
        return (end - self._started_at).total_seconds() / 60

    @property
    def transcript(self) -> list[dict]:
        """
        Serialisable view of the full conversation.
        Useful for passing to the LLM for evaluation.
        """
        return [
            {
                "question_id": str(t.question.id),
                "question": t.question.text,
                "topic": t.question.topic,
                "answer": t.answer.text if t.answer else None,
                "duration_seconds": t.answer.duration_seconds if t.answer else None,
            }
            for t in self._turns
        ]

    # ── Commands ──

    def start(self) -> None:
        """Transition SCHEDULED → ACTIVE and record start time."""
        if self._status != InterviewStatus.SCHEDULED:
            raise ValueError(
                f"Cannot start interview in status '{self._status.value}'"
            )
        self._status = InterviewStatus.ACTIVE
        self._started_at = _utcnow()
        self._touch()

    def ask_question(
        self,
        *,
        text: str,
        topic: Optional[str] = None,
        follow_up_of: Optional[uuid.UUID] = None,
    ) -> Question:
        """
        Add the next AI question to the transcript.
        Returns the Question so the application layer can persist / broadcast it.
        """
        self._assert_active()

        if self.awaiting_answer:
            raise ValueError(
                "Cannot ask a new question while the previous one is unanswered"
            )
        if self.question_count >= self._max_questions:
            raise ValueError(
                f"Interview has reached the maximum of {self._max_questions} questions"
            )
        if self._is_timed_out():
            self.abandon(reason="max_duration_exceeded")
            raise ValueError("Interview timed out and has been abandoned")

        question = Question(
            id=uuid.uuid4(),
            text=text,
            topic=topic,
            follow_up_of=follow_up_of,
        )
        self._turns.append(Turn(question=question))
        self._touch()
        return question

    def submit_answer(
        self,
        *,
        question_id: uuid.UUID,
        text: str,
        duration_seconds: Optional[int] = None,
    ) -> None:
        """
        Record the candidate's answer to the current question.
        Only the most recent unanswered question can be answered.
        """
        self._assert_active()

        if not self.awaiting_answer:
            raise ValueError("There is no pending question to answer")
        if self._turns[-1].question.id != question_id:
            raise ValueError(
                f"question_id {question_id} does not match the current question"
            )

        answer = Answer(
            question_id=question_id,
            text=text,
            duration_seconds=duration_seconds,
        )
        # Replace the last turn (frozen dataclass — rebuild it)
        current_turn = self._turns[-1]
        self._turns[-1] = Turn(question=current_turn.question, answer=answer)
        self._touch()

    def complete(self) -> None:
        """
        Transition ACTIVE → COMPLETED.
        Called by the orchestration service when the session is naturally done
        (max questions reached, candidate ends session, or time limit hit gracefully).
        """
        self._assert_active()
        self._status = InterviewStatus.COMPLETED
        self._ended_at = _utcnow()
        self._touch()

    def abandon(self, *, reason: str = "unknown") -> None:  # noqa: ARG002
        """
        Transition ACTIVE → ABANDONED.
        Called on timeout, disconnection, or explicit cancellation.
        The reason is passed for logging upstream; not stored on the entity
        to keep the domain free of infrastructure concerns.
        """
        if self._status not in (InterviewStatus.ACTIVE, InterviewStatus.SCHEDULED):
            raise ValueError(
                f"Cannot abandon interview in status '{self._status.value}'"
            )
        self._status = InterviewStatus.ABANDONED
        self._ended_at = _utcnow()
        self._touch()


    def void_open_questions(self) -> int:
        """
        Remove unanswered turns from the transcript.
        Called on session resume to clear state left by a previous disconnected session.
        Returns the count removed.
        """
        open_turns = [t for t in self._turns if not t.is_answered]
        for turn in open_turns:
            self._turns.remove(turn)
        self._touch()
        return len(open_turns)

    def mark_evaluated(self) -> None:
        """
        Transition COMPLETED → EVALUATED once an Evaluation aggregate is persisted.
        Called by the application layer, not by Evaluation itself (to keep aggregates decoupled).
        """
        if self._status != InterviewStatus.COMPLETED:
            raise ValueError(
                f"Can only evaluate a COMPLETED interview, current status: {self._status.value}"
            )
        self._status = InterviewStatus.EVALUATED
        self._touch()

    # ── Assertions ───

    def assert_completed(self) -> None:
        if self._status != InterviewStatus.COMPLETED:
            raise ValueError(
                f"Interview must be COMPLETED for evaluation, got: {self._status.value}"
            )

    # ── Internal helpers ──

    def _assert_active(self) -> None:
        if not self.is_active:
            raise ValueError(
                f"Operation requires ACTIVE interview, current status: {self._status.value}"
            )

    def _is_timed_out(self) -> bool:
        if not self._started_at:
            return False
        deadline = self._started_at + timedelta(minutes=self._max_duration_minutes)
        return _utcnow() > deadline

    def _touch(self) -> None:
        self._updated_at = _utcnow()

    # ── Representation ──

    def __repr__(self) -> str:
        return (
            f"Interview(id={self._id}, job_id={self._job_id}, "
            f"candidate_id={self._candidate_id}, status={self._status.value}, "
            f"questions={self.question_count}/{self._max_questions})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Interview):
            return NotImplemented
        return self._id == other._id

    def __hash__(self) -> int:
        return hash(self._id)