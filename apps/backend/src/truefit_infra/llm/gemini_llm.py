"""
GeminiLLMAdapter - standard (non-live) Gemini for text generation tasks.
Used for: question generation, answer evaluation, candidate scoring.
"""

from __future__ import annotations

from typing import Type, TypeVar
import json

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from src.truefit_core.application.ports import (
    LLMPort,
    ResumeEvaluationRequest,
    ResumeEvaluationResult,
)
from src.truefit_infra.config import AppConfig
from src.truefit_core.common.utils import logger

_MODEL = "gemini-2.0-flash-001"

T = TypeVar("T", bound=BaseModel)



class _ResumeEvalSchema(BaseModel):
    match_score: int = Field(ge=0, le=100)
    recommendation: str       
    summary: str               
    strengths: list[str]
    gaps: list[str]




class GeminiLLMAdapter(LLMPort):
    """
    Wraps genai async client for standard text generation.
    One instance is safe to share across the application (stateless).
    """

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or AppConfig.GOOGLE_API_KEY
        if not key:
            raise RuntimeError("GOOGLE_API_KEY is not configured.")
        self._client = genai.Client(api_key=key)

    async def generate(self, prompt: str, *, temperature: float = 0.7) -> str:
        """Plain text generation."""
        response = await self._client.aio.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=temperature),
        )
        return response.text or ""

    async def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        *,
        temperature: float = 0.2,
    ) -> T:
        """
        Generate a response conforming to a Pydantic schema.
        Uses Gemini's JSON mode with the schema injected into the prompt.
        """
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        full_prompt = (
            f"{prompt}\n\n"
            f"Respond ONLY with valid JSON matching this schema:\n{schema_json}"
        )

        response = await self._client.aio.models.generate_content(
            model=_MODEL,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
            ),
        )

        raw = response.text or "{}"
        return schema.model_validate_json(raw)

    async def is_healthy(self) -> bool:
        try:
            await self._client.aio.models.generate_content(
                model=_MODEL,
                contents="ping",
                config=types.GenerateContentConfig(max_output_tokens=1),
            )
            return True
        except Exception:
            return False


    async def evaluate_resume(
            self, request: ResumeEvaluationRequest
        ) -> ResumeEvaluationResult:
            prompt = f"""
        You are a technical recruiter evaluating a candidate resume against a job description.

        JOB TITLE: {request.job_title}
        EXPERIENCE LEVEL: {request.experience_level}
        REQUIRED SKILLS: {', '.join(request.required_skills)}
        JOB DESCRIPTION:
        {request.job_description}

        CANDIDATE RESUME:
        {request.resume_text}

        Evaluate how well this candidate fits the role.

        Rules:
        - match_score: 0–100 integer (75–100 = strong, 35–70 = partial, 0–30 = weak)
        - recommendation: exactly one of "strong", "maybe", or "no"
        - summary: 2–3 sentences the AI interviewer will use to personalise the session.
        Write it in second person as if briefing the interviewer, e.g.
        "The candidate has 5 years of Python experience..."
        - strengths: list of specific matching skills/experiences found in the resume
        - gaps: list of required skills/experience missing from the resume
        """
            result = await self.generate_structured(prompt, _ResumeEvalSchema)

            return ResumeEvaluationResult(
                match_score=result.match_score,
                recommendation=result.recommendation,
                summary=result.summary,
                strengths=result.strengths,
                gaps=result.gaps,
            )