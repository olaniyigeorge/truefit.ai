"""Typed read endpoints for persisted interview evaluations."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.truefit_core.application.evaluation_schema import SkillScoreResult
from src.truefit_infra.auth.authorization import CANDIDATE, RECRUITER, _forbidden, is_admin
from src.truefit_infra.auth.middleware import TokenPayload, get_current_user
from src.truefit_infra.db.database import db_manager
from src.truefit_infra.db.models import (
    Application,
    Evaluation as EvaluationModel,
    InterviewSession,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evaluation_id: uuid.UUID
    interview_id: uuid.UUID
    candidate_id: uuid.UUID
    job_id: uuid.UUID
    org_id: uuid.UUID
    recommendation: str
    overall_score: float | None
    technical_score: float | None
    communication_score: float | None
    problem_solving_score: float | None
    culture_fit_score: float | None
    skill_scores: list[SkillScoreResult]
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    has_report: bool
    model_version: str | None
    is_fallback: bool = False
    created_at: str


def _canonical_recommendation(value: object) -> str:
    if hasattr(value, "value"):
        value = value.value
    return {
        "strong_yes": "strong_hire",
        "yes": "hire",
        "maybe": "maybe",
        "no": "no_hire",
        "strong_no": "strong_no_hire",
    }.get(str(value), "maybe")


async def _get_evaluation(evaluation_id: uuid.UUID | None, interview_id: uuid.UUID | None):
    stmt = (
        select(EvaluationModel)
        .join(EvaluationModel.session)
        .join(InterviewSession.application)
        .options(
            selectinload(EvaluationModel.session)
            .selectinload(InterviewSession.application)
            .selectinload(Application.job),
            selectinload(EvaluationModel.session)
            .selectinload(InterviewSession.application)
            .selectinload(Application.candidate),
        )
    )
    if evaluation_id is not None:
        stmt = stmt.where(EvaluationModel.id == evaluation_id)
    else:
        stmt = stmt.where(InterviewSession.id == interview_id)

    async with db_manager.get_session() as session:
        return (await session.execute(stmt)).scalar_one_or_none()


async def _authorize(user: TokenPayload, evaluation: EvaluationModel) -> None:
    application = evaluation.session.application
    job = application.job
    candidate = application.candidate
    if is_admin(user):
        return
    if user.role == CANDIDATE and str(candidate.user_id) == str(user.user_id):
        return
    if user.role == RECRUITER and str(job.org_id) == str(user.org_id):
        return
    raise _forbidden()


def _to_response(evaluation: EvaluationModel) -> EvaluationOut:
    application = evaluation.session.application
    job = application.job
    evidence = dict(evaluation.evidence or {})
    skill_scores: list[SkillScoreResult] = []
    for item in evidence.get("skill_scores", []):
        try:
            skill_scores.append(SkillScoreResult.model_validate(item))
        except Exception:
            continue

    return EvaluationOut(
        evaluation_id=evaluation.id,
        interview_id=evaluation.session_id,
        candidate_id=application.candidate_id,
        job_id=application.job_id,
        org_id=job.org_id,
        recommendation=_canonical_recommendation(evaluation.recommendation),
        overall_score=float(evaluation.overall_score)
        if evaluation.overall_score is not None
        else None,
        technical_score=evidence.get("technical_score"),
        communication_score=evidence.get("communication_score"),
        problem_solving_score=evidence.get("problem_solving_score"),
        culture_fit_score=evidence.get("culture_fit_score"),
        skill_scores=skill_scores,
        summary=evaluation.summary or "",
        strengths=list(evaluation.strengths or []),
        weaknesses=list(evaluation.concerns or []),
        has_report=evaluation.report_asset_id is not None,
        model_version=evidence.get("model_version"),
        is_fallback=bool(evidence.get("is_fallback", False)),
        created_at=evaluation.created_at.isoformat(),
    )


@router.get("/{evaluation_id}", response_model=EvaluationOut)
async def get_evaluation(
    evaluation_id: uuid.UUID,
    user: TokenPayload = Depends(get_current_user),
) -> EvaluationOut:
    evaluation = await _get_evaluation(evaluation_id=evaluation_id, interview_id=None)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    await _authorize(user, evaluation)
    return _to_response(evaluation)


@router.get("/by-interview/{interview_id}", response_model=EvaluationOut)
async def get_evaluation_for_interview(
    interview_id: uuid.UUID,
    user: TokenPayload = Depends(get_current_user),
) -> EvaluationOut:
    evaluation = await _get_evaluation(evaluation_id=None, interview_id=interview_id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    await _authorize(user, evaluation)
    return _to_response(evaluation)
