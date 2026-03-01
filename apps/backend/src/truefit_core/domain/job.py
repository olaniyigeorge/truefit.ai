from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


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
    """A required or preferred skill with optional proficiency weight."""

    name: str
    required: bool = True
    weight: float = 1.0  # relative importance for scoring (0.0 – 1.0)

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"Skill weight must be between 0 and 1, got {self.weight}")


@dataclass
class InterviewConfig:
    """
    Controls how the AI conducts the interview for this job.
    Decoupled from Job so it can be updated independently without
    changing the job's core identity.
    """

    max_questions: int = 10
    max_duration_minutes: int = 30
    topics: list[str] = field(default_factory=list)
    custom_instructions: Optional[str] = None  # injected into LLM system prompt

    def __post_init__(self) -> None:
        if self.max_questions < 1:
            raise ValueError("max_questions must be at least 1")
        if self.max_duration_minutes < 5:
            raise ValueError("max_duration_minutes must be at least 5")


class Job:
    """
    Aggregate root representing a company's job listing.

    Invariants enforced:
    - Interviews can only be started against an ACTIVE job.
    - Status transitions follow a strict directed graph.
    - Core fields (company_id, title) are immutable after creation.
    """

    _VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
        JobStatus.DRAFT: {JobStatus.ACTIVE},
        JobStatus.ACTIVE: {JobStatus.PAUSED, JobStatus.CLOSED},
        JobStatus.PAUSED: {JobStatus.ACTIVE, JobStatus.CLOSED},
        JobStatus.CLOSED: set(),
    }

    def __init__(
        self,
        *,
        company_id: uuid.UUID,
        title: str,
        description: str,
        experience_level: ExperienceLevel,
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
        self._company_id: uuid.UUID = company_id
        self._title: str = title.strip()
        self._description: str = description.strip()
        self._experience_level: ExperienceLevel = experience_level
        self._skills: list[SkillRequirement] = list(skills)
        self._interview_config: InterviewConfig = interview_config or InterviewConfig()
        self._status: JobStatus = status
        self._created_at: datetime = created_at or _utcnow()
        self._updated_at: datetime = updated_at or _utcnow()

    # ── Identity ───

    @property
    def id(self) -> uuid.UUID:
        return self._id

    @property
    def company_id(self) -> uuid.UUID:
        return self._company_id

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

    @property
    def experience_level(self) -> ExperienceLevel:
        return self._experience_level

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

    # ── Queries ──

    @property
    def is_open_for_interviews(self) -> bool:
        return self._status == JobStatus.ACTIVE

    @property
    def required_skills(self) -> list[SkillRequirement]:
        return [s for s in self._skills if s.required]

    @property
    def preferred_skills(self) -> list[SkillRequirement]:
        return [s for s in self._skills if not s.required]

    # ── Commands / State transitions ──

    def activate(self) -> None:
        """Publish the job — candidates can now be interviewed."""
        self._transition_to(JobStatus.ACTIVE)

    def pause(self) -> None:
        """Temporarily halt new interview creation without closing the job."""
        self._transition_to(JobStatus.PAUSED)

    def close(self) -> None:
        """Permanently close the job. No further interviews allowed."""
        self._transition_to(JobStatus.CLOSED)

    def update_description(self, description: str) -> None:
        if self._status == JobStatus.CLOSED:
            raise PermissionError("Cannot update a closed job")
        if not description.strip():
            raise ValueError("Description cannot be empty")
        self._description = description.strip()
        self._touch()

    def update_interview_config(self, config: InterviewConfig) -> None:
        if self._status == JobStatus.CLOSED:
            raise PermissionError("Cannot update interview config on a closed job")
        self._interview_config = config
        self._touch()

    def add_skill(self, skill: SkillRequirement) -> None:
        if self._status == JobStatus.CLOSED:
            raise PermissionError("Cannot modify skills on a closed job")
        if any(s.name.lower() == skill.name.lower() for s in self._skills):
            raise ValueError(f"Skill '{skill.name}' already exists")
        self._skills.append(skill)
        self._touch()

    def remove_skill(self, skill_name: str) -> None:
        if self._status == JobStatus.CLOSED:
            raise PermissionError("Cannot modify skills on a closed job")
        before = len(self._skills)
        self._skills = [s for s in self._skills if s.name.lower() != skill_name.lower()]
        if len(self._skills) == before:
            raise ValueError(f"Skill '{skill_name}' not found")
        if not self._skills:
            raise ValueError("Job must retain at least one skill requirement")
        self._touch()

    # ── Assertions (called by application layer) ─

    def assert_open_for_interviews(self) -> None:
        if not self.is_open_for_interviews:
            raise ValueError(
                f"Job '{self._title}' is not accepting interviews (status={self._status.value})"
            )

    # ── Internal helpers ──

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

    # ── Representation ──

    def __repr__(self) -> str:
        return (
            f"Job(id={self._id}, title={self._title!r}, "
            f"status={self._status.value}, company_id={self._company_id})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Job):
            return NotImplemented
        return self._id == other._id

    def __hash__(self) -> int:
        return hash(self._id)