"""
Read-only handlers. No state mutation. No domain aggregates loaded —
queries work with whatever the repo returns (can be DTOs or ORM models
mapped to response dataclasses).

Because queries are read-only they can bypass the domain layer entirely
and talk to read-optimised repo methods or even raw SQL projections.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from src.truefit_core.application.ports import (
    CandidateRepository,
    EvaluationRepository,
    InterviewRepository,
    JobRepository,
    StoragePort,
)
from src.truefit_core.domain.candidate import Candidate
from src.truefit_core.domain.evaluation import Evaluation
from src.truefit_core.domain.interview import Interview
from src.truefit_core.domain.job import Job


# ───────────────────────
# Shared pagination input
# ───────────────────────

@dataclass(frozen=True)
class PaginationParams:
    limit: int = 20
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if self.offset < 0:
            raise ValueError("offset cannot be negative")


# ───────────
# Job queries
# ───────────

@dataclass(frozen=True)
class GetJobResponse:
    job_id: uuid.UUID
    company_id: uuid.UUID
    title: str
    description: str
    status: str
    experience_level: str
    skills: list[dict]
    interview_config: dict
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, job: Job) -> "GetJobResponse":
        return cls(
            job_id=job.id,
            company_id=job.company_id,
            title=job.title,
            description=job.description,
            status=job.status.value,
            experience_level=job.experience_level.value,
            skills=[
                {"name": s.name, "required": s.required, "weight": s.weight}
                for s in job.skills
            ],
            interview_config={
                "max_questions": job.interview_config.max_questions,
                "max_duration_minutes": job.interview_config.max_duration_minutes,
                "topics": job.interview_config.topics,
                "custom_instructions": job.interview_config.custom_instructions,
            },
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
        )


async def get_job(
    job_id: uuid.UUID,
    *,
    job_repo: JobRepository,
) -> GetJobResponse:
    job = await job_repo.get_by_id(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    return GetJobResponse.from_domain(job)


async def list_company_jobs(
    company_id: uuid.UUID,
    *,
    job_repo: JobRepository,
    pagination: PaginationParams = PaginationParams(),
) -> list[GetJobResponse]:
    jobs = await job_repo.get_by_company(
        company_id, limit=pagination.limit, offset=pagination.offset
    )
    return [GetJobResponse.from_domain(j) for j in jobs]


# ─────────────────
# Candidate queries
# ──────────────────

@dataclass(frozen=True)
class GetCandidateResponse:
    candidate_id: uuid.UUID
    full_name: str
    email: str
    phone: Optional[str]
    linkedin_url: Optional[str]
    status: str
    has_resume: bool
    resume_filename: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, c: Candidate) -> "GetCandidateResponse":
        return cls(
            candidate_id=c.id,
            full_name=c.full_name,
            email=c.contact.email,
            phone=c.contact.phone,
            linkedin_url=c.contact.linkedin_url,
            status=c.status.value,
            has_resume=c.resume is not None,
            resume_filename=c.resume.filename if c.resume else None,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
        )


async def get_candidate(
    candidate_id: uuid.UUID,
    *,
    candidate_repo: CandidateRepository,
) -> GetCandidateResponse:
    candidate = await candidate_repo.get_by_id(candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    return GetCandidateResponse.from_domain(candidate)


async def get_resume_download_url(
    candidate_id: uuid.UUID,
    *,
    candidate_repo: CandidateRepository,
    storage: StoragePort,
    expires_in_seconds: int = 3600,
) -> str:
    candidate = await candidate_repo.get_by_id(candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    if candidate.resume is None:
        raise ValueError(f"Candidate {candidate_id} has no resume")
    return await storage.get_presigned_url(
        candidate.resume.storage_key,
        expires_in_seconds=expires_in_seconds,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Interview queries
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GetInterviewResponse:
    interview_id: uuid.UUID
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    company_id: uuid.UUID
    status: str
    question_count: int
    answered_count: int
    max_questions: int
    elapsed_minutes: Optional[float]
    started_at: Optional[str]
    ended_at: Optional[str]
    transcript: list[dict]             # full Q&A pairs

    @classmethod
    def from_domain(cls, i: Interview) -> "GetInterviewResponse":
        return cls(
            interview_id=i.id,
            job_id=i.job_id,
            candidate_id=i.candidate_id,
            company_id=i.company_id,
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


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation queries
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SkillScoreView:
    skill_name: str
    score: float
    rationale: str


@dataclass(frozen=True)
class GetEvaluationResponse:
    evaluation_id: uuid.UUID
    interview_id: uuid.UUID
    candidate_id: uuid.UUID
    job_id: uuid.UUID
    company_id: uuid.UUID
    recommendation: str
    overall_score: float
    technical_score: float
    communication_score: float
    problem_solving_score: float
    culture_fit_score: float
    skill_scores: list[SkillScoreView]
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    has_report: bool
    model_version: Optional[str]
    created_at: str

    @classmethod
    def from_domain(cls, e: Evaluation) -> "GetEvaluationResponse":
        return cls(
            evaluation_id=e.id,
            interview_id=e.interview_id,
            candidate_id=e.candidate_id,
            job_id=e.job_id,
            company_id=e.company_id,
            recommendation=e.recommendation.value,
            overall_score=e.scores.overall,
            technical_score=e.scores.technical,
            communication_score=e.scores.communication,
            problem_solving_score=e.scores.problem_solving,
            culture_fit_score=e.scores.culture_fit,
            skill_scores=[
                SkillScoreView(
                    skill_name=s.skill_name,
                    score=s.score,
                    rationale=s.rationale,
                )
                for s in e.scores.skill_scores
            ],
            summary=e.summary,
            strengths=e.strengths,
            weaknesses=e.weaknesses,
            has_report=e.has_report,
            model_version=e.model_version,
            created_at=e.created_at.isoformat(),
        )


async def get_evaluation_by_interview(
    interview_id: uuid.UUID,
    *,
    evaluation_repo: EvaluationRepository,
) -> GetEvaluationResponse:
    evaluation = await evaluation_repo.get_by_interview(interview_id)
    if evaluation is None:
        raise ValueError(f"No evaluation found for interview {interview_id}")
    return GetEvaluationResponse.from_domain(evaluation)


async def get_evaluation(
    evaluation_id: uuid.UUID,
    *,
    evaluation_repo: EvaluationRepository,
) -> GetEvaluationResponse:
    evaluation = await evaluation_repo.get_by_id(evaluation_id)
    if evaluation is None:
        raise ValueError(f"Evaluation {evaluation_id} not found")
    return GetEvaluationResponse.from_domain(evaluation)


async def list_job_evaluations(
    job_id: uuid.UUID,
    *,
    evaluation_repo: EvaluationRepository,
    pagination: PaginationParams = PaginationParams(),
) -> list[GetEvaluationResponse]:
    evaluations = await evaluation_repo.list_by_job(
        job_id, limit=pagination.limit, offset=pagination.offset
    )
    return [GetEvaluationResponse.from_domain(e) for e in evaluations]


async def get_report_download_url(
    evaluation_id: uuid.UUID,
    *,
    evaluation_repo: EvaluationRepository,
    storage: StoragePort,
    expires_in_seconds: int = 3600,
) -> str:
    evaluation = await evaluation_repo.get_by_id(evaluation_id)
    if evaluation is None:
        raise ValueError(f"Evaluation {evaluation_id} not found")
    if not evaluation.has_report:
        raise ValueError(f"Report not yet generated for evaluation {evaluation_id}")
    return await storage.get_presigned_url(
        evaluation.report_storage_key,
        expires_in_seconds=expires_in_seconds,
    )