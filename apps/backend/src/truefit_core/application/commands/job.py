"""
Command handlers for job listing lifecycle.

Thin by design - most business logic lives in JobService or on the Job aggregate.
Handlers are responsible for:
  - Input validation before touching the domain
  - Calling the right service / repo method
  - Returning a clean response dataclass
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from src.truefit_core.application.services import JobService
from src.truefit_core.application.ports import JobRepository
from src.truefit_core.domain.job import (
    ExperienceLevel,
    InterviewConfig,
    Job,
    SkillRequirement,
)

# Input dataclasses


@dataclass(frozen=True)
class SkillInput:
    name: str
    required: bool = True
    weight: float = 1.0


@dataclass(frozen=True)
class InterviewConfigInput:
    max_questions: int = 10
    max_duration_minutes: int = 30
    topics: list[str] = field(default_factory=list)
    custom_instructions: Optional[str] = None


@dataclass(frozen=True)
class CreateJobCommand:
    org_id: uuid.UUID
    title: str
    description: str
    experience_level: str
    skills: list[SkillInput]
    interview_config: Optional[InterviewConfigInput] = None


@dataclass(frozen=True)
class ActivateJobCommand:
    job_id: uuid.UUID
    activated_by: uuid.UUID


@dataclass(frozen=True)
class UpdateJobCommand:
    job_id: uuid.UUID
    updated_by: uuid.UUID
    description: Optional[str] = None
    interview_config: Optional[InterviewConfigInput] = None


@dataclass(frozen=True)
class CloseJobCommand:
    job_id: uuid.UUID
    closed_by: uuid.UUID
    reason: Optional[str] = None  # "filled" | "cancelled" | "budget".


# Response dataclasses


@dataclass(frozen=True)
class JobResponse:
    job_id: uuid.UUID
    org_id: uuid.UUID
    title: str
    status: str
    experience_level: str
    skill_count: int
    max_questions: int
    max_duration_minutes: int
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, job: Job) -> "JobResponse":
        return cls(
            job_id=job.id,
            org_id=job.org_id,
            title=job.title,
            status=job.status.value,
            experience_level=job.experience_level.value,
            skill_count=len(job.skills),
            max_questions=job.interview_config.max_questions,
            max_duration_minutes=job.interview_config.max_duration_minutes,
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
        )


# Handlers


async def handle_create_job(
    cmd: CreateJobCommand,
    *,
    job_service: JobService,
) -> JobResponse:
    try:
        experience_level = ExperienceLevel(cmd.experience_level)
    except ValueError:
        valid = [e.value for e in ExperienceLevel]
        raise ValueError(
            f"Invalid experience_level '{cmd.experience_level}'. Must be one of: {valid}"
        )

    if not cmd.skills:
        raise ValueError("At least one skill is required to create a job")

    skills = [
        SkillRequirement(name=s.name, required=s.required, weight=s.weight)
        for s in cmd.skills
    ]

    interview_config = None
    if cmd.interview_config:
        interview_config = InterviewConfig(
            max_questions=cmd.interview_config.max_questions,
            max_duration_minutes=cmd.interview_config.max_duration_minutes,
            topics=list(cmd.interview_config.topics),
            custom_instructions=cmd.interview_config.custom_instructions,
        )

    job = await job_service.create_job(
        org_id=cmd.org_id,
        title=cmd.title,
        description=cmd.description,
        experience_level=experience_level,
        skills=skills,
        interview_config=interview_config,
    )

    return JobResponse.from_domain(job)


async def handle_activate_job(
    cmd: ActivateJobCommand,
    *,
    job_repo: JobRepository,
) -> JobResponse:
    job = await job_repo.get_by_id(cmd.job_id)
    if job is None:
        raise ValueError(f"Job {cmd.job_id} not found")

    job.activate()
    await job_repo.save(job)
    return JobResponse.from_domain(job)


async def handle_update_job(
    cmd: UpdateJobCommand,
    *,
    job_repo: JobRepository,
) -> JobResponse:
    job = await job_repo.get_by_id(cmd.job_id)
    if job is None:
        raise ValueError(f"Job {cmd.job_id} not found")

    if cmd.description is not None:
        job.update_description(cmd.description)

    if cmd.interview_config is not None:
        config = InterviewConfig(
            max_questions=cmd.interview_config.max_questions,
            max_duration_minutes=cmd.interview_config.max_duration_minutes,
            topics=list(cmd.interview_config.topics),
            custom_instructions=cmd.interview_config.custom_instructions,
        )
        job.update_interview_config(config)

    await job_repo.save(job)
    return JobResponse.from_domain(job)


async def handle_close_job(
    cmd: CloseJobCommand,
    *,
    job_service: JobService,
) -> JobResponse:
    job = await job_service.close_job(cmd.job_id)
    return JobResponse.from_domain(job)
