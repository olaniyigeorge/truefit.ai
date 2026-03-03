"""
Handles generation, persistence, and report delivery of interview evaluations.

Responsibilities:
- Validating the interview is in a completable state
- Building the LLM evaluation request from the interview + job context
- Mapping the raw LLM output onto the Evaluation domain object
- Persisting the evaluation and updating the interview status
- Uploading the structured report via StoragePort
- Publishing the evaluation.completed event downstream
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from src.truefit_core.common.utils import logger
from src.truefit_core.domain.evaluation import (
    Evaluation,
    EvaluationScores,
    HiringRecommendation,
    SkillScore,
)
from src.truefit_core.application.ports import (
    DomainEvent,
    EvaluationRepository,
    EvaluationRequest,
    InterviewRepository,
    JobRepository,
    LLMPort,
    QueuePort,
    StoragePort,
)


_EVENT_EVALUATION_COMPLETED = "evaluation.completed"
_EVENT_REPORT_READY = "evaluation.report_ready"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvaluationService:
    def __init__(
        self,
        *,
        evaluation_repo: EvaluationRepository,
        interview_repo: InterviewRepository,
        job_repo: JobRepository,
        llm: LLMPort,
        storage: StoragePort,
        queue: QueuePort,
    ) -> None:
        self._evaluations = evaluation_repo
        self._interviews = interview_repo
        self._jobs = job_repo
        self._llm = llm
        self._storage = storage
        self._queue = queue

    # ── Primary entry point ───

    async def generate_evaluation(self, interview_id: uuid.UUID) -> Evaluation:
        """
        Generate and persist an Evaluation for a completed interview.

        Flow:
        1. Load + validate interview (must be COMPLETED)
        2. Load job for context
        3. Call LLM with full transcript
        4. Map result → Evaluation domain object
        5. Persist evaluation, update interview → EVALUATED
        6. Generate and upload the report
        7. Publish events

        Idempotent: if an evaluation already exists for this interview,
        return the existing one without re-running.
        """
        # Idempotency guard
        existing = await self._evaluations.get_by_interview(interview_id)
        if existing is not None:
            logger.info(f"Evaluation already exists for interview {interview_id}, returning cached")
            return existing

        interview = await self._interviews.get_by_id(interview_id)
        if interview is None:
            raise ValueError(f"Interview {interview_id} not found")
        interview.assert_completed()

        job = await self._jobs.get_by_id(interview.job_id)
        if job is None:
            raise RuntimeError(f"Job {interview.job_id} not found during evaluation")

        # ── Call LLM ───
        request = EvaluationRequest(
            job_title=job.title,
            job_description=job.description,
            required_skills=[s.name for s in job.required_skills],
            experience_level=job.experience_level.value,
            transcript=interview.transcript,
            custom_instructions=job.interview_config.custom_instructions,
        )
        llm_result = await self._llm.evaluate_interview(request)

        # ── Map onto domain object ───
        evaluation = self._build_evaluation(
            interview_id=interview_id,
            job_id=interview.job_id,
            candidate_id=interview.candidate_id,
            org_id=interview.org_id,
            llm_result_raw=llm_result,
        )

        # ── Persist ───
        await self._evaluations.save(evaluation)

        # Mark interview as evaluated (domain state transition)
        interview.mark_evaluated()
        await self._interviews.save(interview)

        await self._queue.publish(DomainEvent(
            event_type=_EVENT_EVALUATION_COMPLETED,
            aggregate_id=str(evaluation.id),
            aggregate_type="Evaluation",
            occurred_at=_utcnow_iso(),
            payload={
                **evaluation.to_summary_dict(),
                "model_version": evaluation.model_version,
            },
        ))

        # ── Generate and store report ────
        try:
            storage_key = await self._upload_report(evaluation)
            evaluation.attach_report(storage_key)
            await self._evaluations.save(evaluation)

            await self._queue.publish(DomainEvent(
                event_type=_EVENT_REPORT_READY,
                aggregate_id=str(evaluation.id),
                aggregate_type="Evaluation",
                occurred_at=_utcnow_iso(),
                payload={
                    "evaluation_id": str(evaluation.id),
                    "interview_id": str(interview_id),
                    "candidate_id": str(interview.candidate_id),
                    "org_id": str(interview.org_id),
                    "storage_key": storage_key,
                },
            ))
            logger.info(f"Report uploaded for evaluation {evaluation.id} → {storage_key}")

        except Exception as e:
            # Report generation failure is non-fatal — evaluation is already persisted.
            # The report can be regenerated on demand.
            logger.error(f"Report upload failed for evaluation {evaluation.id}: {e}")

        return evaluation

    # ── Report re-generation (on-demand) ────

    async def regenerate_report(self, evaluation_id: uuid.UUID) -> str:
        """
        Re-upload the report for an existing evaluation and return the storage key.
        Useful if the original upload failed or the template changed.
        """
        evaluation = await self._evaluations.get_by_id(evaluation_id)
        if evaluation is None:
            raise ValueError(f"Evaluation {evaluation_id} not found")

        storage_key = await self._upload_report(evaluation)

        # Reset by creating a new evaluation instance with the new key is not
        # possible (immutable). We update via repo directly.
        # If your infra repo supports partial updates, call that here.
        # Otherwise, attach_report() will raise if already set — handle appropriately
        # by updating the storage key column in the DB directly via the repo.
        logger.info(f"Report regenerated for evaluation {evaluation_id} → {storage_key}")
        return storage_key

    # ── Internal helpers ─────

    def _build_evaluation(
        self,
        *,
        interview_id: uuid.UUID,
        job_id: uuid.UUID,
        candidate_id: uuid.UUID,
        org_id: uuid.UUID,
        llm_result_raw,  # LLMEvaluationResult
    ) -> Evaluation:
        skill_scores = [
            SkillScore(
                skill_name=s["skill_name"],
                score=float(s["score"]),
                rationale=s.get("rationale", ""),
            )
            for s in (llm_result_raw.skill_scores or [])
        ]

        scores = EvaluationScores(
            technical=llm_result_raw.technical_score,
            communication=llm_result_raw.communication_score,
            problem_solving=llm_result_raw.problem_solving_score,
            culture_fit=llm_result_raw.culture_fit_score,
            overall=llm_result_raw.overall_score,
            skill_scores=skill_scores,
        )

        try:
            recommendation = HiringRecommendation(llm_result_raw.recommendation)
        except ValueError:
            logger.warning(
                f"Unknown recommendation value '{llm_result_raw.recommendation}', defaulting to MAYBE"
            )
            recommendation = HiringRecommendation.MAYBE

        return Evaluation(
            interview_id=interview_id,
            job_id=job_id,
            candidate_id=candidate_id,
            org_id=org_id,
            scores=scores,
            recommendation=recommendation,
            summary=llm_result_raw.summary,
            strengths=llm_result_raw.strengths,
            weaknesses=llm_result_raw.weaknesses,
            model_version=llm_result_raw.model_version,
        )

    async def _upload_report(self, evaluation: Evaluation) -> str:
        """
        Serialise evaluation to JSON and upload to storage.
        Replace this with a PDF renderer (e.g. WeasyPrint, Puppeteer) when ready.
        """
        report_data = {
            "evaluation_id": str(evaluation.id),
            "interview_id": str(evaluation.interview_id),
            "candidate_id": str(evaluation.candidate_id),
            "job_id": str(evaluation.job_id),
            "recommendation": evaluation.recommendation.value,
            "scores": {
                "overall": evaluation.scores.overall,
                "technical": evaluation.scores.technical,
                "communication": evaluation.scores.communication,
                "problem_solving": evaluation.scores.problem_solving,
                "culture_fit": evaluation.scores.culture_fit,
                "skills": [
                    {
                        "name": s.skill_name,
                        "score": s.score,
                        "rationale": s.rationale,
                    }
                    for s in evaluation.scores.skill_scores
                ],
            },
            "summary": evaluation.summary,
            "strengths": evaluation.strengths,
            "weaknesses": evaluation.weaknesses,
            "generated_at": _utcnow_iso(),
        }

        key = f"reports/{evaluation.org_id}/{evaluation.job_id}/{evaluation.id}.json"
        await self._storage.upload(
            key=key,
            data=json.dumps(report_data, indent=2).encode(),
            content_type="application/json",
        )
        return key