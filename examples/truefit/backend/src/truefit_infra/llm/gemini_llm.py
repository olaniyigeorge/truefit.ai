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

from src.truefit_core.application.evaluation_schema import LLMEvaluationResult
from src.truefit_core.application.ports import (
    EvaluationRequest,
    GeneratedQuestion,
    LLMPort,
    QuestionContext,
)
from src.truefit_infra.config import AppConfig
from src.truefit_core.common.utils import logger

_MODEL = "gemini-2.0-flash-001"

T = TypeVar("T", bound=BaseModel)


class GeminiLLMAdapter(LLMPort):
    """
    Wraps genai async client for standard text generation.
    One instance is safe to share across the application (stateless).
    """

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or AppConfig.GEMINI_API_KEY
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        self._client = genai.Client(api_key=key)

    async def generate_question(self, context: QuestionContext) -> GeneratedQuestion:
        prompt = f"""
You are conducting a structured technical interview.
Job title: {context.job_title}
Job description: {context.job_description}
Required skills: {", ".join(context.required_skills)}
Experience level: {context.experience_level}
Topics remaining: {", ".join(context.topics_remaining) or "none"}
Question number: {context.question_number}
Previous transcript: {json.dumps(context.transcript)}
Additional instructions: {context.custom_instructions or "none"}

Generate one concise, answerable interview question. Prefer a follow-up when the
previous answer needs clarification. Do not reveal the rubric or scoring criteria.
"""

        class QuestionResult(BaseModel):
            text: str = Field(min_length=1)
            topic: str | None = None
            is_follow_up: bool = False

        result = await self.generate_structured(prompt, QuestionResult)
        return GeneratedQuestion(
            text=result.text.strip(), topic=result.topic, is_follow_up=result.is_follow_up
        )

    async def evaluate_interview(self, request: EvaluationRequest) -> LLMEvaluationResult:
        prompt = f"""
Evaluate this completed interview against the job requirements.

Job title: {request.job_title}
Job description: {request.job_description}
Required skills: {", ".join(request.required_skills)}
Experience level: {request.experience_level}
Custom instructions: {request.custom_instructions or "none"}
Interview transcript: {json.dumps(request.transcript)}

Score every numeric field from 0 to 10. Use one recommendation from:
strong_hire, hire, maybe, no_hire, strong_no_hire.
Give evidence-based strengths and weaknesses. Never invent evidence that is not
present in the transcript.
"""
        try:
            return await self.generate_structured(prompt, LLMEvaluationResult)
        except Exception as exc:
            logger.warning("Gemini evaluation output failed validation; using fallback: %s", exc)
            return LLMEvaluationResult.fallback(
                required_skills=request.required_skills,
                model_version=_MODEL,
            )

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
            f"{prompt}\n\nRespond ONLY with valid JSON matching this schema:\n{schema_json}"
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
