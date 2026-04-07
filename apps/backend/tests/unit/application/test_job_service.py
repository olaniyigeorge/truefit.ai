"""
tests/unit/application/test_job_service.py

Unit tests for JobService - mock-based, no database.

Dependencies (JobRepository, InterviewRepository, QueuePort) are replaced
with AsyncMock so these tests verify only the service's orchestration logic.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.truefit_core.application.services.job_service import JobService
from src.truefit_core.domain.interview import Interview, InterviewStatus
from src.truefit_core.domain.job import (
    ExperienceLevel,
    InterviewConfig,
    Job,
    JobRequirements,
    JobStatus,
    SkillRequirement,
)

# ─
# Helpers
# ─


def _make_requirements() -> JobRequirements:
    return JobRequirements(experience_level=ExperienceLevel.MID)


def _make_skill(name: str = "Python") -> SkillRequirement:
    return SkillRequirement(name=name)


def _make_job(status: JobStatus = JobStatus.DRAFT) -> Job:
    return Job(
        org_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        title="Backend Engineer",
        description="Build great APIs.",
        requirements=_make_requirements(),
        skills=[_make_skill("Python"), _make_skill("PostgreSQL")],
        status=status,
    )


def _make_active_interview(job_id: uuid.UUID) -> Interview:
    iv = Interview(
        job_id=job_id,
        candidate_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        max_questions=10,
        max_duration_minutes=30,
        status=InterviewStatus.SCHEDULED,
    )
    iv.start()
    return iv


# ─
# Fixtures
# ─


@pytest.fixture()
def job_repo():
    r = AsyncMock()
    r.save = AsyncMock(return_value=None)
    r.get_by_id = AsyncMock(return_value=None)
    return r


@pytest.fixture()
def interview_repo():
    r = AsyncMock()
    r.save = AsyncMock(return_value=None)
    r.list_by_job = AsyncMock(return_value=[])
    return r


@pytest.fixture()
def queue():
    q = AsyncMock()
    q.publish = AsyncMock(return_value=None)
    return q


@pytest.fixture()
def service(job_repo, interview_repo, queue) -> JobService:
    return JobService(job_repo=job_repo, interview_repo=interview_repo, queue=queue)


# ─
# create_job
# ─


class TestCreateJob:
    async def test_creates_job_and_saves(self, service, job_repo):
        job = await service.create_job(
            org_id=uuid.uuid4(),
            title="ML Engineer",
            description="Train models.",
            experience_level=ExperienceLevel.SENIOR,
            skills=[_make_skill("Python"), _make_skill("PyTorch")],
        )
        assert job.title == "ML Engineer"
        assert job.status == JobStatus.DRAFT
        job_repo.save.assert_awaited_once()

    async def test_custom_interview_config_is_passed_through(self, service, job_repo):
        cfg = InterviewConfig(max_questions=5)
        job = await service.create_job(
            org_id=uuid.uuid4(),
            title="Analyst",
            description="Analyse things.",
            experience_level=ExperienceLevel.JUNIOR,
            skills=[_make_skill()],
            interview_config=cfg,
        )
        assert job.interview_config.max_questions == 5

    async def test_returns_job_domain_object(self, service):
        job = await service.create_job(
            org_id=uuid.uuid4(),
            title="DevOps",
            description="CI/CD pipelines.",
            experience_level=ExperienceLevel.MID,
            skills=[_make_skill("Kubernetes")],
        )
        assert isinstance(job, Job)

    async def test_created_job_has_draft_status(self, service):
        job = await service.create_job(
            org_id=uuid.uuid4(),
            title="QA Engineer",
            description="Quality gates.",
            experience_level=ExperienceLevel.MID,
            skills=[_make_skill("Selenium")],
        )
        assert job.status == JobStatus.DRAFT


# ─
# close_job
# ─


class TestCloseJob:
    async def test_closes_active_job_successfully(self, service, job_repo, queue):
        job = _make_job(status=JobStatus.ACTIVE)
        job_repo.get_by_id.return_value = job

        result = await service.close_job(job.id)

        assert result.status == JobStatus.CLOSED
        job_repo.save.assert_awaited()

    async def test_raises_if_job_not_found(self, service, job_repo):
        job_repo.get_by_id.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await service.close_job(uuid.uuid4())

    async def test_publishes_job_closed_event(self, service, job_repo, queue):
        job = _make_job(status=JobStatus.ACTIVE)
        job_repo.get_by_id.return_value = job

        await service.close_job(job.id)

        queue.publish.assert_awaited_once()
        event = queue.publish.call_args.args[0]
        assert event.event_type == "job.closed"
        assert str(job.id) in event.payload["job_id"]

    async def test_abandons_active_interviews_when_closing(
        self, service, job_repo, interview_repo, queue
    ):
        job = _make_job(status=JobStatus.ACTIVE)
        job_repo.get_by_id.return_value = job

        active_interview = _make_active_interview(job.id)
        interview_repo.list_by_job.return_value = [active_interview]

        await service.close_job(job.id)

        assert active_interview.status == InterviewStatus.ABANDONED
        interview_repo.save.assert_awaited()

    async def test_event_payload_contains_abandoned_count(
        self, service, job_repo, interview_repo, queue
    ):
        job = _make_job(status=JobStatus.ACTIVE)
        job_repo.get_by_id.return_value = job

        # Two active interviews
        iv1 = _make_active_interview(job.id)
        iv2 = _make_active_interview(job.id)
        interview_repo.list_by_job.return_value = [iv1, iv2]

        await service.close_job(job.id)

        event = queue.publish.call_args.args[0]
        assert event.payload["interviews_abandoned"] == 2

    async def test_completed_interviews_are_not_abandoned(
        self, service, job_repo, interview_repo, queue
    ):
        job = _make_job(status=JobStatus.ACTIVE)
        job_repo.get_by_id.return_value = job

        active_iv = _make_active_interview(job.id)
        completed_iv = Interview(
            job_id=job.id,
            candidate_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            max_questions=10,
            max_duration_minutes=30,
            status=InterviewStatus.COMPLETED,
        )
        interview_repo.list_by_job.return_value = [active_iv, completed_iv]

        await service.close_job(job.id)

        # Only the active one was saved (abandoned)
        assert active_iv.status == InterviewStatus.ABANDONED
        assert completed_iv.status == InterviewStatus.COMPLETED

    async def test_closing_draft_job_raises_invalid_transition(
        self, service, job_repo, queue
    ):
        draft_job = _make_job(status=JobStatus.DRAFT)
        job_repo.get_by_id.return_value = draft_job

        with pytest.raises(ValueError, match="Invalid status transition"):
            await service.close_job(draft_job.id)
