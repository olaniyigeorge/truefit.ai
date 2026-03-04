"""
POST   /interviews                      Start an interview session
GET    /interviews/{interview_id}        Get interview + transcript
GET    /interviews                       List by candidate or job
POST   /interviews/{interview_id}/abandon  Abandon an active session
GET    /interviews/{interview_id}/transcript  Full Q&A transcript
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from src.truefit_core.domain.interview import Interview, InterviewStatus
from src.truefit_infra.db.database import db_manager
from src.truefit_infra.db.repositories.interview_repository import (
    SQLAlchemyInterviewRepository,
)
from src.truefit_infra.db.repositories.job_repository import SQLAlchemyJobRepository
from src.truefit_infra.db.repositories.candidate_repository import (
    SQLAlchemyCandidateRepository,
)

router = APIRouter(prefix="/interviews", tags=["interviews"])


# ── Dependencies ───

def get_interview_repo() -> SQLAlchemyInterviewRepository:
    return SQLAlchemyInterviewRepository(db_manager)

def get_job_repo() -> SQLAlchemyJobRepository:
    return SQLAlchemyJobRepository(db_manager)

def get_candidate_repo() -> SQLAlchemyCandidateRepository:
    return SQLAlchemyCandidateRepository(db_manager)


# ── Request schemas ──

class StartInterviewRequest(BaseModel):
    job_id: uuid.UUID
    candidate_id: uuid.UUID


class AbandonRequest(BaseModel):
    reason: str = "manual"
    initiated_by: str = "candidate"  # "candidate" | "system" | "admin"


# ── Response schemas ──

class TurnOut(BaseModel):
    question_id: uuid.UUID
    question_text: str
    topic: Optional[str]
    answer_text: Optional[str]
    duration_seconds: Optional[int]
    asked_at: str
    answered_at: Optional[str]


class InterviewOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    company_id: uuid.UUID
    status: str
    question_count: int
    answered_count: int
    max_questions: int
    max_duration_minutes: int
    elapsed_minutes: Optional[float]
    started_at: Optional[str]
    ended_at: Optional[str]
    created_at: str

    @classmethod
    def from_domain(cls, i: Interview) -> "InterviewOut":
        return cls(
            id=i.id,
            job_id=i.job_id,
            candidate_id=i.candidate_id,
            company_id=i.company_id,
            status=i.status.value,
            question_count=i.question_count,
            answered_count=i.answered_count,
            max_questions=i.max_questions,
            max_duration_minutes=i.max_duration_minutes,
            elapsed_minutes=i.elapsed_minutes,
            started_at=i.started_at.isoformat() if i.started_at else None,
            ended_at=i.ended_at.isoformat() if i.ended_at else None,
            created_at=i.created_at.isoformat(),
        )


class TranscriptOut(BaseModel):
    interview_id: uuid.UUID
    status: str
    turns: list[TurnOut]


# ── Endpoints ──

@router.post("", response_model=InterviewOut, status_code=status.HTTP_201_CREATED)
async def start_interview(
    body: StartInterviewRequest,
    interview_repo: SQLAlchemyInterviewRepository = Depends(get_interview_repo),
    job_repo: SQLAlchemyJobRepository = Depends(get_job_repo),
    candidate_repo: SQLAlchemyCandidateRepository = Depends(get_candidate_repo),
):
    job = await job_repo.get_by_id(body.job_id)
    if not job:
        raise HTTPException(404, detail=f"Job {body.job_id} not found")

    candidate = await candidate_repo.get_by_id(body.candidate_id)
    if not candidate:
        raise HTTPException(404, detail=f"Candidate {body.candidate_id} not found")

    try:
        job.assert_open_for_interviews()
        candidate.assert_eligible_to_interview()
        candidate.register_active_interview(body.job_id)
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, detail=str(e))

    interview = Interview(
        job_id=body.job_id,
        candidate_id=body.candidate_id,
        company_id=job.org_id,
        max_questions=job.interview_config.max_questions,
        max_duration_minutes=job.interview_config.max_duration_minutes,
    )
    interview.start()

    await interview_repo.save(interview)
    await candidate_repo.save(candidate)

    return InterviewOut.from_domain(interview)


@router.get("/{interview_id}", response_model=InterviewOut)
async def get_interview(
    interview_id: uuid.UUID,
    repo: SQLAlchemyInterviewRepository = Depends(get_interview_repo),
):
    interview = await repo.get_by_id(interview_id)
    if not interview:
        raise HTTPException(404, detail=f"Interview {interview_id} not found")
    return InterviewOut.from_domain(interview)


@router.get("", response_model=list[InterviewOut])
async def list_interviews(
    candidate_id: Optional[uuid.UUID] = Query(None),
    job_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: SQLAlchemyInterviewRepository = Depends(get_interview_repo),
):
    if not candidate_id and not job_id:
        raise HTTPException(400, detail="Provide candidate_id or job_id")

    if candidate_id:
        interviews = await repo.list_by_candidate(candidate_id, limit=limit, offset=offset)
    else:
        interviews = await repo.list_by_job(job_id, limit=limit, offset=offset)

    return [InterviewOut.from_domain(i) for i in interviews]


@router.post("/{interview_id}/abandon", response_model=InterviewOut)
async def abandon_interview(
    interview_id: uuid.UUID,
    body: AbandonRequest,
    interview_repo: SQLAlchemyInterviewRepository = Depends(get_interview_repo),
    candidate_repo: SQLAlchemyCandidateRepository = Depends(get_candidate_repo),
):
    interview = await interview_repo.get_by_id(interview_id)
    if not interview:
        raise HTTPException(404, detail=f"Interview {interview_id} not found")

    if interview.is_finished:
        raise HTTPException(400, detail=f"Interview is already {interview.status.value}")

    interview.abandon(reason=f"{body.reason}:{body.initiated_by}")
    await interview_repo.save(interview)

    # Release candidate's active interview lock
    candidate = await candidate_repo.get_by_id(interview.candidate_id)
    if candidate:
        candidate.release_active_interview(interview.job_id)
        await candidate_repo.save(candidate)

    return InterviewOut.from_domain(interview)


@router.get("/{interview_id}/transcript", response_model=TranscriptOut)
async def get_transcript(
    interview_id: uuid.UUID,
    repo: SQLAlchemyInterviewRepository = Depends(get_interview_repo),
):
    interview = await repo.get_by_id(interview_id)
    if not interview:
        raise HTTPException(404, detail=f"Interview {interview_id} not found")

    turns = [
        TurnOut(
            question_id=t.question.id,
            question_text=t.question.text,
            topic=t.question.topic,
            answer_text=t.answer.text if t.answer else None,
            duration_seconds=t.answer.duration_seconds if t.answer else None,
            asked_at=t.question.asked_at.isoformat(),
            answered_at=t.answer.answered_at.isoformat() if t.answer else None,
        )
        for t in interview.turns
    ]

    return TranscriptOut(
        interview_id=interview.id,
        status=interview.status.value,
        turns=turns,
    )