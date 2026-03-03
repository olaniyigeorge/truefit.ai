from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from truefit_core.application.ports import  EvaluationRepository, StoragePort
from truefit_core.application.query import PaginationParams
from truefit_core.domain.evaluation import Evaluation



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
    org_id: uuid.UUID
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
            org_id=e.org_id,
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