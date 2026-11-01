from pydantic import ValidationError
import pytest

from src.truefit_core.application.evaluation_schema import (
    LLMEvaluationResult,
    parse_evaluation_result,
)
from src.truefit_core.application.ports import EvaluationRequest
from src.truefit_core.domain.evaluation import HiringRecommendation
from src.truefit_infra.llm.gemini_llm import GeminiLLMAdapter


def valid_payload() -> dict:
    return {
        "recommendation": "hire",
        "overall_score": 8.2,
        "technical_score": 8.5,
        "communication_score": 7.5,
        "problem_solving_score": 8.0,
        "culture_fit_score": 8.0,
        "skill_scores": [{"skill_name": "Python", "score": 9, "rationale": "Strong evidence."}],
        "summary": "The candidate demonstrated strong backend experience.",
        "strengths": ["Python experience"],
        "weaknesses": ["Limited leadership evidence"],
    }


def test_evaluation_result_is_validated_and_normalized():
    result = parse_evaluation_result(valid_payload())

    assert result.recommendation is HiringRecommendation.HIRE
    assert result.skill_scores[0].score == 9
    assert result.is_fallback is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("overall_score", 11),
        ("recommendation", "unknown"),
        ("strengths", []),
        ("summary", "  "),
    ],
)
def test_invalid_provider_output_is_rejected(field, value):
    payload = valid_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        parse_evaluation_result(payload)


def test_fallback_is_valid_and_explicit():
    result = LLMEvaluationResult.fallback(
        required_skills=["Python", "PostgreSQL"],
        model_version="test-model",
    )

    assert result.is_fallback is True
    assert result.recommendation is HiringRecommendation.MAYBE
    assert len(result.skill_scores) == 2
    assert result.overall_score == 0


@pytest.mark.asyncio
async def test_gemini_adapter_returns_fallback_when_generation_fails(monkeypatch):
    adapter = object.__new__(GeminiLLMAdapter)

    async def fail_generation(*_args, **_kwargs):
        raise ValueError("malformed JSON")

    monkeypatch.setattr(adapter, "generate_structured", fail_generation)
    result = await adapter.evaluate_interview(
        EvaluationRequest(
            job_title="Backend Engineer",
            job_description="Build APIs",
            required_skills=["Python"],
            experience_level="senior",
            transcript=[],
        )
    )

    assert result.is_fallback is True
    assert result.model_version == "gemini-2.0-flash-001"
