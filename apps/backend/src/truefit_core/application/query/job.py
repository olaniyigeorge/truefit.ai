from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from truefit_core.application.ports import  JobRepository, StoragePort
from truefit_core.application.query import PaginationParams
from truefit_core.domain.interview import Interview
from truefit_core.domain.job import Job


@dataclass(frozen=True)
class GetJobResponse:
    job_id: uuid.UUID
    org_id: uuid.UUID
    title: str
    description: str
    status: str
    experience_level: str
    skills: list[dict]
    interview_config: dict
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, job: Job) -> "GetJobResponse":
        return cls(
            job_id=job.id,
            org_id=job.org_id,
            title=job.title,
            description=job.description,
            status=job.status.value,
            experience_level=job.experience_level.value,
            skills=[
                {"name": s.name, "required": s.required, "weight": s.weight}
                for s in job.skills
            ],
            interview_config={
                "max_questions": job.interview_config.max_questions,
                "max_duration_minutes": job.interview_config.max_duration_minutes,
                "topics": job.interview_config.topics,
                "custom_instructions": job.interview_config.custom_instructions,
            },
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
        )


async def get_job(
    job_id: uuid.UUID,
    *,
    job_repo: JobRepository,
) -> GetJobResponse:
    job = await job_repo.get_by_id(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    return GetJobResponse.from_domain(job)


async def list_company_jobs(
    org_id: uuid.UUID,
    *,
    job_repo: JobRepository,
    pagination: PaginationParams = PaginationParams(),
) -> list[GetJobResponse]:
    jobs = await job_repo.get_by_company(
        org_id, limit=pagination.limit, offset=pagination.offset
    )
    return [GetJobResponse.from_domain(j) for j in jobs]



