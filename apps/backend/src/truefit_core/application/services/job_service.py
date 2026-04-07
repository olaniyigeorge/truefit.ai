"""
Handles job lifecycle operations that require cross-aggregate coordination.
Single-aggregate operations (update description, add skill) are thin enough
to be handled directly in command handlers - this service handles the cases
that aren't.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.truefit_core.common.utils import logger
from src.truefit_core.domain.interview import InterviewStatus
from src.truefit_core.domain.job import (
    Job,
    ExperienceLevel,
    InterviewConfig,
    SkillRequirement,
)
from src.truefit_core.application.ports import (
    DomainEvent,
    InterviewRepository,
    JobRepository,
    QueuePort,
)

_EVENT_JOB_CLOSED = "job.closed"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobService:
    def __init__(
        self,
        *,
        job_repo: JobRepository,
        interview_repo: InterviewRepository,
        queue: QueuePort,
    ) -> None:
        self._jobs = job_repo
        self._interviews = interview_repo
        self._queue = queue

    async def create_job(
        self,
        *,
        org_id: uuid.UUID,
        title: str,
        description: str,
        experience_level: ExperienceLevel,
        skills: list[SkillRequirement],
        interview_config: InterviewConfig | None = None,
    ) -> Job:
        job = Job(
            org_id=org_id,
            title=title,
            description=description,
            experience_level=experience_level,
            skills=skills,
            interview_config=interview_config,
        )
        await self._jobs.save(job)
        logger.info(f"Job created: {job.id} - '{job.title}' for company {org_id}")
        return job

    async def close_job(self, job_id: uuid.UUID) -> Job:
        """
        Close a job and abandon any interviews that are still active.
        This is the only operation that touches both Job and Interview aggregates.
        """
        job = await self._jobs.get_by_id(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        job.close()
        await self._jobs.save(job)

        # Abandon all active interviews for this job
        active_interviews = await self._interviews.list_by_job(job_id, limit=500)
        abandoned_count = 0
        for interview in active_interviews:
            if interview.status == InterviewStatus.ACTIVE:
                interview.abandon(reason="job_closed")
                await self._interviews.save(interview)
                abandoned_count += 1

        await self._queue.publish(
            DomainEvent(
                event_type=_EVENT_JOB_CLOSED,
                aggregate_id=str(job_id),
                aggregate_type="Job",
                occurred_at=_utcnow_iso(),
                payload={
                    "job_id": str(job_id),
                    "org_id": str(job.org_id),
                    "interviews_abandoned": abandoned_count,
                },
            )
        )

        logger.info(
            f"Job {job_id} closed. {abandoned_count} active interview(s) abandoned."
        )
        return job
