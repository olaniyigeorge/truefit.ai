"""Validated LLM evaluation contracts shared by providers and the API.

The model output is deliberately stricter than the persistence/domain layer. An
LLM may return JSON, but it must be normalized here before it can influence a
candidate decision or reach the frontend.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.truefit_core.domain.evaluation import HiringRecommendation


class SkillScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=10.0)
    rationale: str = Field(min_length=1)

    @field_validator("skill_name", "rationale")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


class LLMEvaluationResult(BaseModel):
    """Canonical, parseable result returned by every evaluation provider."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    recommendation: HiringRecommendation
    overall_score: float = Field(ge=0.0, le=10.0)
    technical_score: float = Field(ge=0.0, le=10.0)
    communication_score: float = Field(ge=0.0, le=10.0)
    problem_solving_score: float = Field(ge=0.0, le=10.0)
    culture_fit_score: float = Field(ge=0.0, le=10.0)
    skill_scores: list[SkillScoreResult] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    strengths: list[str] = Field(min_length=1)
    weaknesses: list[str] = Field(min_length=1)
    model_version: str | None = None
    is_fallback: bool = False

    @field_validator("summary")
    @classmethod
    def summary_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("summary cannot be blank")
        return value

    @field_validator("strengths", "weaknesses")
    @classmethod
    def list_not_blank(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if not cleaned:
            raise ValueError("list must contain at least one non-blank item")
        return cleaned

    @classmethod
    def fallback(
        cls,
        *,
        required_skills: list[str],
        model_version: str | None = None,
    ) -> "LLMEvaluationResult":
        """Return a safe, explicit result when provider output is unusable."""

        return cls(
            recommendation=HiringRecommendation.MAYBE,
            overall_score=0.0,
            technical_score=0.0,
            communication_score=0.0,
            problem_solving_score=0.0,
            culture_fit_score=0.0,
            skill_scores=[
                SkillScoreResult(
                    skill_name=skill,
                    score=0.0,
                    rationale="No validated score was returned; manual review required.",
                )
                for skill in required_skills
                if skill.strip()
            ],
            summary="The automated evaluation was unavailable. Manual review is required.",
            strengths=["No validated strengths were returned."],
            weaknesses=["The evaluation provider returned invalid or unavailable output."],
            model_version=model_version,
            is_fallback=True,
        )


def parse_evaluation_result(payload: Any) -> LLMEvaluationResult:
    """Validate a provider payload and reject malformed output consistently."""

    return LLMEvaluationResult.model_validate(payload)
