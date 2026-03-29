from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from truefit_core.application.ports import InterviewRepository, StoragePort
from truefit_core.application.query import PaginationParams
from truefit_core.domain.interview import Interview


@dataclass(frozen=True)
class GetInterviewResponse:
    interview_id: uuid.UUID
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    org_id: uuid.UUID
    status: str
    question_count: int
    answered_count: int
    max_questions: int
    elapsed_minutes: Optional[float]
    started_at: Optional[str]
    ended_at: Optional[str]
    transcript: list[dict]  # full Q&A pairs

    @classmethod
    def from_domain(cls, i: Interview) -> "GetInterviewResponse":
        return cls(
            interview_id=i.id,
            job_id=i.job_id,
            candidate_id=i.candidate_id,
            org_id=i.org_id,
            status=i.status.value,
            question_count=i.question_count,
            answered_count=i.answered_count,
            max_questions=i.max_questions,
            elapsed_minutes=i.elapsed_minutes,
            started_at=i.started_at.isoformat() if i.started_at else None,
            ended_at=i.ended_at.isoformat() if i.ended_at else None,
            transcript=i.transcript,
        )


async def get_interview(
    interview_id: uuid.UUID,
    *,
    interview_repo: InterviewRepository,
) -> GetInterviewResponse:
    interview = await interview_repo.get_by_id(interview_id)
    if interview is None:
        raise ValueError(f"Interview {interview_id} not found")
    return GetInterviewResponse.from_domain(interview)


async def list_candidate_interviews(
    candidate_id: uuid.UUID,
    *,
    interview_repo: InterviewRepository,
    pagination: PaginationParams = PaginationParams(),
) -> list[GetInterviewResponse]:
    interviews = await interview_repo.list_by_candidate(
        candidate_id, limit=pagination.limit, offset=pagination.offset
    )
    return [GetInterviewResponse.from_domain(i) for i in interviews]


async def list_job_interviews(
    job_id: uuid.UUID,
    *,
    interview_repo: InterviewRepository,
    pagination: PaginationParams = PaginationParams(),
) -> list[GetInterviewResponse]:
    interviews = await interview_repo.list_by_job(
        job_id, limit=pagination.limit, offset=pagination.offset
    )
    return [GetInterviewResponse.from_domain(i) for i in interviews]
