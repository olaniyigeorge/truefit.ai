"""
ResumeEvaluationService

Responsibilities:
- Downloading the candidate's resume PDF from storage
- Extracting plain text from the PDF
- Calling the LLM to evaluate fit against a job
- Returning a structured ResumeEvaluationResult

This result is consumed by the interview start flow to populate
InterviewContext.candidate_resume_text so the agent can interview
the candidate personally.
"""
from __future__ import annotations

import io
import uuid

import pypdf

from src.truefit_core.application.ports import (
    CandidateRepository,
    JobRepository,
    LLMPort,
    ResumeEvaluationRequest,
    ResumeEvaluationResult,
    StoragePort,
)
from src.truefit_core.common.utils import logger


class ResumeEvaluationService:
    def __init__(
        self,
        *,
        candidate_repo: CandidateRepository,
        job_repo: JobRepository,
        llm: LLMPort,
        storage: StoragePort,
    ) -> None:
        self._candidates = candidate_repo
        self._jobs = job_repo
        self._llm = llm
        self._storage = storage

    async def evaluate(
        self,
        *,
        candidate_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> ResumeEvaluationResult:
        """
        Download the candidate's resume, extract text, evaluate against job.
        Raises ValueError if candidate has no resume attached.
        """
        candidate = await self._candidates.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        if candidate.resume is None:
            raise ValueError(
                f"Candidate {candidate.full_name} has not uploaded a resume. "
                "A resume is required before starting an interview."
            )

        job = await self._jobs.get_by_id(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        # Download PDF and extract text
        pdf_bytes = await self._storage.download(candidate.resume.storage_key)
        resume_text = self._extract_text(pdf_bytes)

        if not resume_text.strip():
            raise ValueError(
                "Could not extract text from resume PDF. "
                "Please ensure the PDF contains selectable text, not a scanned image."
            )

        logger.info(
            f"Evaluating resume for candidate {candidate_id} "
            f"against job {job_id} ({len(resume_text)} chars extracted)"
        )

        request = ResumeEvaluationRequest(
            resume_text=resume_text,
            job_title=job.title,
            job_description=job.description,
            required_skills=[s.name for s in job.required_skills],
            experience_level=job.experience_level.value,
        )

        return await self._llm.evaluate_resume(request)

    @staticmethod
    def _extract_text(pdf_bytes: bytes) -> str:
        """Extract plain text from a PDF using pypdf."""
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)