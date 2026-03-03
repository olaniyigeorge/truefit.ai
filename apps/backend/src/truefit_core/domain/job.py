from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class ExperienceLevel(str, Enum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    PRINCIPAL = "principal"


@dataclass
class SkillRequirement:
    """
    A single skill the role requires or prefers.

    name        Canonical skill name e.g. "Python", "System Design"
    required    False = nice-to-have / preferred
    weight      Relative importance for AI scoring (0.0 - 1.0)
    min_years   Optional minimum years of experience for this specific skill.
                Stored here (not on JobRequirements) because it is skill-specific.
    """
    name: str
    required: bool = True
    weight: float = 1.0
    min_years: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Skill name cannot be empty")
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"Skill weight must be between 0 and 1, got {self.weight}")
        if self.min_years is not None and self.min_years < 0:
            raise ValueError("min_years cannot be negative")


@dataclass
class JobRequirements:
    """
    Role-level requirements that sit above individual skills.

    experience_level    The seniority band — first-class field, also indexed on DB.
    min_total_years     Total career experience (vs per-skill min_years on SkillRequirement).
    education           Free text e.g. "Bachelor's in CS or equivalent"
    certifications      e.g. ["AWS Solutions Architect", "PMP"]
    location            e.g. "Remote - US only", "London, UK"
    work_arrangement    "remote" | "hybrid" | "onsite"
    extra               Escape hatch for bespoke criteria with no schema change needed.
    """
    experience_level: ExperienceLevel
    min_total_years: Optional[int] = None
    education: Optional[str] = None
    certifications: list[str] = field(default_factory=list)
    location: Optional[str] = None
    work_arrangement: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.min_total_years is not None and self.min_total_years < 0:
            raise ValueError("min_total_years cannot be negative")


@dataclass
class InterviewConfig:
    """
    Controls how the AI agent conducts the interview for this job.
    Decoupled from Job so it can be updated without touching job identity.
    """
    max_questions: int = 10
    max_duration_minutes: int = 30
    topics: list[str] = field(default_factory=list)
    custom_instructions: Optional[str] = None

    def __post_init__(self) -> None:
        if self.max_questions < 1:
            raise ValueError("max_questions must be at least 1")
        if self.max_duration_minutes < 5:
            raise ValueError("max_duration_minutes must be at least 5")


class Job:
    """
    Aggregate root representing an organisation's job listing.

    Invariants
    ──────────
    - Interviews can only be started against an ACTIVE job.
    - Status transitions follow a strict directed graph.
    - org_id, created_by, and title are immutable after creation.
    - At least one skill requirement must always exist.
    """

    _VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
        JobStatus.DRAFT:  {JobStatus.ACTIVE},
        JobStatus.ACTIVE: {JobStatus.PAUSED, JobStatus.CLOSED},
        JobStatus.PAUSED: {JobStatus.ACTIVE, JobStatus.CLOSED},
        JobStatus.CLOSED: set(),
    }

    def __init__(
        self,
        *,
        org_id: uuid.UUID,
        created_by: uuid.UUID,
        title: str,
        description: str,
        requirements: JobRequirements,
        skills: list[SkillRequirement],
        interview_config: Optional[InterviewConfig] = None,
        job_id: Optional[uuid.UUID] = None,
        status: JobStatus = JobStatus.DRAFT,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> None:
        if not title.strip():
            raise ValueError("Job title cannot be empty")
        if not description.strip():
            raise ValueError("Job description cannot be empty")
        if not skills:
            raise ValueError("At least one skill requirement must be specified")

        self._id: uuid.UUID = job_id or uuid.uuid4()
        self._org_id: uuid.UUID = org_id
        self._created_by: uuid.UUID = created_by
        self._title: str = title.strip()
        self._description: str = description.strip()
        self._requirements: JobRequirements = requirements
        self._skills: list[SkillRequirement] = list(skills)
        self._interview_config: InterviewConfig = interview_config or InterviewConfig()
        self._status: JobStatus = status
        self._created_at: datetime = created_at or _utcnow()
        self._updated_at: datetime = updated_at or _utcnow()

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def id(self) -> uuid.UUID:
        return self._id

    @property
    def org_id(self) -> uuid.UUID:
        return self._org_id

    @property
    def created_by(self) -> uuid.UUID:
        return self._created_by

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

    @property
    def requirements(self) -> JobRequirements:
        return self._requirements

    @property
    def experience_level(self) -> ExperienceLevel:
        """Convenience shortcut — experience_level lives on requirements."""
        return self._requirements.experience_level

    @property
    def skills(self) -> list[SkillRequirement]:
        return list(self._skills)

    @property
    def interview_config(self) -> InterviewConfig:
        return self._interview_config

    @property
    def status(self) -> JobStatus:
        return self._status

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    # ── Derived queries ─────

    @property
    def is_open_for_interviews(self) -> bool:
        return self._status == JobStatus.ACTIVE

    @property
    def required_skills(self) -> list[SkillRequirement]:
        return [s for s in self._skills if s.required]

    @property
    def preferred_skills(self) -> list[SkillRequirement]:
        return [s for s in self._skills if not s.required]

    # ── Commands ─────

    def activate(self) -> None:
        self._transition_to(JobStatus.ACTIVE)

    def pause(self) -> None:
        self._transition_to(JobStatus.PAUSED)

    def close(self) -> None:
        self._transition_to(JobStatus.CLOSED)

    def update_description(self, description: str) -> None:
        self._assert_not_closed()
        if not description.strip():
            raise ValueError("Description cannot be empty")
        self._description = description.strip()
        self._touch()

    def update_requirements(self, requirements: JobRequirements) -> None:
        self._assert_not_closed()
        self._requirements = requirements
        self._touch()

    def update_interview_config(self, config: InterviewConfig) -> None:
        self._assert_not_closed()
        self._interview_config = config
        self._touch()

    def add_skill(self, skill: SkillRequirement) -> None:
        self._assert_not_closed()
        if any(s.name.lower() == skill.name.lower() for s in self._skills):
            raise ValueError(f"Skill '{skill.name}' already exists")
        self._skills.append(skill)
        self._touch()

    def remove_skill(self, skill_name: str) -> None:
        self._assert_not_closed()
        before = len(self._skills)
        self._skills = [s for s in self._skills if s.name.lower() != skill_name.lower()]
        if len(self._skills) == before:
            raise ValueError(f"Skill '{skill_name}' not found")
        if not self._skills:
            raise ValueError("Job must retain at least one skill requirement")
        self._touch()

    def update_skill(
        self,
        skill_name: str,
        *,
        weight: Optional[float] = None,
        required: Optional[bool] = None,
        min_years: Optional[int] = None,
    ) -> None:
        """Mutate an existing skill in-place without remove + add."""
        self._assert_not_closed()
        for skill in self._skills:
            if skill.name.lower() == skill_name.lower():
                if weight is not None:
                    skill.weight = weight
                if required is not None:
                    skill.required = required
                if min_years is not None:
                    skill.min_years = min_years
                self._touch()
                return
        raise ValueError(f"Skill '{skill_name}' not found")

    # ── Assertions ────────────────────────────────────────────────────────────

    def assert_open_for_interviews(self) -> None:
        if not self.is_open_for_interviews:
            raise ValueError(
                f"Job '{self._title}' is not accepting interviews "
                f"(status={self._status.value})"
            )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _assert_not_closed(self) -> None:
        if self._status == JobStatus.CLOSED:
            raise PermissionError(f"Cannot modify a closed job (id={self._id})")

    def _transition_to(self, new_status: JobStatus) -> None:
        allowed = self._VALID_TRANSITIONS[self._status]
        if new_status not in allowed:
            raise ValueError(
                f"Invalid status transition: {self._status.value} → {new_status.value}"
            )
        self._status = new_status
        self._touch()

    def _touch(self) -> None:
        self._updated_at = _utcnow()

    # ── Representation ────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"Job(id={self._id}, title={self._title!r}, "
            f"status={self._status.value}, org_id={self._org_id})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Job):
            return NotImplemented
        return self._id == other._id

    def __hash__(self) -> int:
        return hash(self._id)