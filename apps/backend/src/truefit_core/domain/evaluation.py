from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HiringRecommendation(str, Enum):
    STRONG_HIRE = "strong_hire"
    HIRE = "hire"
    MAYBE = "maybe"
    NO_HIRE = "no_hire"
    STRONG_NO_HIRE = "strong_no_hire"


@dataclass(frozen=True)
class SkillScore:
    """
    Score for a single skill requirement — maps directly to the
    SkillRequirement.name field on the Job.
    """
    skill_name: str
    score: float          # 0.0 – 10.0
    rationale: str        # concise LLM-generated reasoning for this score
    evidence_question_ids: list[uuid.UUID] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 10.0:
            raise ValueError(
                f"Skill score must be between 0 and 10, got {self.score} for '{self.skill_name}'"
            )
        if not self.rationale.strip():
            raise ValueError("Skill score rationale cannot be empty")


@dataclass(frozen=True)
class EvaluationScores:
    """
    Holistic scoring breakdown.
    All scores are 0.0 - 10.0 to make aggregation / weighting straightforward.
    """
    technical: float                        # domain / technical skill mastery
    communication: float                    # clarity, structure, articulation
    problem_solving: float                  # reasoning and approach quality
    culture_fit: float                      # alignment with role expectations
    overall: float                          # weighted composite (computed by LLM or service)
    skill_scores: list[SkillScore] = field(default_factory=list)

    def __post_init__(self) -> None:
        for attr in ("technical", "communication", "problem_solving", "culture_fit", "overall"):
            v = getattr(self, attr)
            if not 0.0 <= v <= 10.0:
                raise ValueError(f"Score '{attr}' must be between 0 and 10, got {v}")


class Evaluation:
    """
    Aggregate representing the AI-generated assessment of a completed interview.

    Invariants enforced:
    - An Evaluation can only be created for a COMPLETED interview (enforced by
      the application layer before construction; the entity validates it has an
      interview_id to tie to).
    - Once created, an Evaluation is effectively immutable — it is a historical
      record of the AI's judgement at a point in time.
    - A report_storage_key (set after the PDF is persisted) is the only mutable
      field after creation, and it can only be set once.
    """

    def __init__(
        self,
        *,
        interview_id: uuid.UUID,
        job_id: uuid.UUID,
        candidate_id: uuid.UUID,
        org_id: uuid.UUID,
        scores: EvaluationScores,
        recommendation: HiringRecommendation,
        summary: str,               # 2-3 paragraph LLM narrative
        strengths: list[str],       # bullet-friendly key positives
        weaknesses: list[str],      # bullet-friendly key gaps
        evaluation_id: Optional[uuid.UUID] = None,
        report_storage_key: Optional[str] = None,  # set after PDF upload
        model_version: Optional[str] = None,       # e.g. "gemini-1.5-pro"
        created_at: Optional[datetime] = None,
    ) -> None:
        if not summary.strip():
            raise ValueError("Evaluation summary cannot be empty")
        if not strengths:
            raise ValueError("At least one strength must be provided")
        if not weaknesses:
            raise ValueError("At least one weakness must be provided")

        self._id: uuid.UUID = evaluation_id or uuid.uuid4()
        self._interview_id: uuid.UUID = interview_id
        self._job_id: uuid.UUID = job_id
        self._candidate_id: uuid.UUID = candidate_id
        self._org_id: uuid.UUID = org_id
        self._scores: EvaluationScores = scores
        self._recommendation: HiringRecommendation = recommendation
        self._summary: str = summary.strip()
        self._strengths: list[str] = list(strengths)
        self._weaknesses: list[str] = list(weaknesses)
        self._report_storage_key: Optional[str] = report_storage_key
        self._model_version: Optional[str] = model_version
        self._created_at: datetime = created_at or _utcnow()

    # ── Identity ──

    @property
    def id(self) -> uuid.UUID:
        return self._id

    @property
    def interview_id(self) -> uuid.UUID:
        return self._interview_id

    @property
    def job_id(self) -> uuid.UUID:
        return self._job_id

    @property
    def candidate_id(self) -> uuid.UUID:
        return self._candidate_id

    @property
    def org_id(self) -> uuid.UUID:
        return self._org_id

    @property
    def scores(self) -> EvaluationScores:
        return self._scores

    @property
    def recommendation(self) -> HiringRecommendation:
        return self._recommendation

    @property
    def summary(self) -> str:
        return self._summary

    @property
    def strengths(self) -> list[str]:
        return list(self._strengths)

    @property
    def weaknesses(self) -> list[str]:
        return list(self._weaknesses)

    @property
    def report_storage_key(self) -> Optional[str]:
        return self._report_storage_key

    @property
    def model_version(self) -> Optional[str]:
        return self._model_version

    @property
    def created_at(self) -> datetime:
        return self._created_at

    # ── Queries ──

    @property
    def is_hire_recommended(self) -> bool:
        return self._recommendation in (
            HiringRecommendation.HIRE,
            HiringRecommendation.STRONG_HIRE,
        )

    @property
    def has_report(self) -> bool:
        return self._report_storage_key is not None

    @property
    def overall_score(self) -> float:
        return self._scores.overall

    def score_for_skill(self, skill_name: str) -> Optional[SkillScore]:
        for s in self._scores.skill_scores:
            if s.skill_name.lower() == skill_name.lower():
                return s
        return None

    # ── Commands ──

    def attach_report(self, storage_key: str) -> None:
        """
        Link the generated PDF report (stored in truefit_infra storage) to this evaluation.
        Can only be set once — reports are immutable once generated.
        """
        if self._report_storage_key is not None:
            raise ValueError(
                f"Report already attached for evaluation {self._id} "
                f"(key={self._report_storage_key!r})"
            )
        if not storage_key.strip():
            raise ValueError("storage_key cannot be empty")
        self._report_storage_key = storage_key

    # ── Serialisation (convenience for passing to queues / APIs) ──

    def to_summary_dict(self) -> dict:
        """
        Lightweight dict suitable for embedding in job dashboards
        or recommendation feeds — no full transcript.
        """
        return {
            "evaluation_id": str(self._id),
            "interview_id": str(self._interview_id),
            "candidate_id": str(self._candidate_id),
            "job_id": str(self._job_id),
            "recommendation": self._recommendation.value,
            "overall_score": self._scores.overall,
            "has_report": self.has_report,
            "created_at": self._created_at.isoformat(),
        }

    # ── Representation ───

    def __repr__(self) -> str:
        return (
            f"Evaluation(id={self._id}, interview_id={self._interview_id}, "
            f"recommendation={self._recommendation.value}, "
            f"overall={self._scores.overall:.1f})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Evaluation):
            return NotImplemented
        return self._id == other._id

    def __hash__(self) -> int:
        return hash(self._id)