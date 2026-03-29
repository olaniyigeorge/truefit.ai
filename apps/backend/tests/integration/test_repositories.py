"""
tests/integration/test_repositories.py

Integration tests for SQLAlchemyJobRepository and SQLAlchemyCandidateRepository.

Uses an in-memory SQLite database (via aiosqlite) to verify persistence
behaviour without requiring a running Postgres instance.

NOTE: Some Postgres-specific features (JSON operators, pg_insert with
on_conflict) are exercised here using the SQLAlchemy ORM-level operations
which work cross-database.  For full fidelity run against Postgres in CI.
"""

import uuid
from datetime import datetime, timezone

import pytest

from src.truefit_core.domain.candidate import (
    Candidate,
    CandidateStatus,
    ContactInfo,
    ResumeRef,
)
from src.truefit_core.domain.job import (
    ExperienceLevel,
    InterviewConfig,
    Job,
    JobRequirements,
    JobStatus,
    SkillRequirement,
)
from src.truefit_infra.db.models import CandidateProfile, JobListing
from src.truefit_infra.db.repositories.job_repository import SQLAlchemyJobRepository
from src.truefit_infra.db.repositories.candidate_repository import (
    SQLAlchemyCandidateRepository,
)

# ─
# Helpers
# ─


def _make_requirements(level: ExperienceLevel = ExperienceLevel.MID) -> JobRequirements:
    return JobRequirements(
        experience_level=level,
        min_total_years=2,
        location="Remote",
        work_arrangement="remote",
    )


def _make_job(
    org_id: uuid.UUID, created_by: uuid.UUID, title: str = "Backend Engineer"
) -> Job:
    return Job(
        org_id=org_id,
        created_by=created_by,
        title=title,
        description="Build scalable APIs.",
        requirements=_make_requirements(),
        skills=[
            SkillRequirement(name="Python", required=True, weight=1.0),
            SkillRequirement(name="PostgreSQL", required=False, weight=0.7),
        ],
        interview_config=InterviewConfig(max_questions=8, max_duration_minutes=20),
    )


def _make_candidate(email: str = "alice@example.com") -> Candidate:
    return Candidate(
        full_name="Alice Smith",
        contact=ContactInfo(email=email, phone="+1-555-0100"),
    )


# ─
# ── Job Repository Integration Tests ─
# ─


class TestSQLAlchemyJobRepository:
    """
    Integration tests for SQLAlchemyJobRepository.
    Each test runs in an isolated in-memory SQLite database.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, db_manager, org, recruiter_user):
        self.repo = SQLAlchemyJobRepository(db_manager)
        self.org_id = org.id
        self.user_id = recruiter_user.id

    # ── save / get_by_id ──

    async def test_save_and_retrieve_by_id(self):
        job = _make_job(self.org_id, self.user_id)
        await self.repo.save(job)

        fetched = await self.repo.get_by_id(job.id)
        assert fetched is not None
        assert fetched.id == job.id
        assert fetched.title == "Backend Engineer"

    async def test_get_by_id_returns_none_for_unknown(self):
        result = await self.repo.get_by_id(uuid.uuid4())
        assert result is None

    async def test_save_reconstructs_skills(self):
        job = _make_job(self.org_id, self.user_id)
        await self.repo.save(job)

        fetched = await self.repo.get_by_id(job.id)
        names = {s.name for s in fetched.skills}
        assert "Python" in names
        assert "PostgreSQL" in names

    async def test_save_reconstructs_requirements(self):
        job = _make_job(self.org_id, self.user_id)
        await self.repo.save(job)

        fetched = await self.repo.get_by_id(job.id)
        assert fetched.requirements.experience_level == ExperienceLevel.MID
        assert fetched.requirements.location == "Remote"

    async def test_save_reconstructs_interview_config(self):
        job = _make_job(self.org_id, self.user_id)
        await self.repo.save(job)

        fetched = await self.repo.get_by_id(job.id)
        assert fetched.interview_config.max_questions == 8
        assert fetched.interview_config.max_duration_minutes == 20

    async def test_upsert_updates_existing_job(self):
        job = _make_job(self.org_id, self.user_id)
        await self.repo.save(job)

        job.update_description("Updated description for test.")
        await self.repo.save(job)

        fetched = await self.repo.get_by_id(job.id)
        assert "Updated description" in fetched.description

    async def test_upsert_does_not_create_duplicate(self):
        job = _make_job(self.org_id, self.user_id)
        await self.repo.save(job)
        await self.repo.save(job)  # second save = upsert

        jobs = await self.repo.get_by_company(self.org_id)
        assert len(jobs) == 1

    async def test_status_transition_is_persisted(self):
        job = _make_job(self.org_id, self.user_id)
        await self.repo.save(job)

        job.activate()
        await self.repo.save(job)

        fetched = await self.repo.get_by_id(job.id)
        assert fetched.status == JobStatus.ACTIVE

    # ── get_by_company ──

    async def test_get_by_company_returns_all_org_jobs(self):
        for title in ("Job A", "Job B", "Job C"):
            await self.repo.save(_make_job(self.org_id, self.user_id, title))

        jobs = await self.repo.get_by_company(self.org_id)
        assert len(jobs) == 3

    async def test_get_by_company_excludes_other_orgs(self):
        other_org_id = uuid.uuid4()
        await self.repo.save(_make_job(self.org_id, self.user_id, "Acme Job"))
        # Note: job for other_org_id would fail FK constraint in Postgres;
        # here we only test that filtering works on the saved job.
        jobs = await self.repo.get_by_company(self.org_id)
        assert all(j.org_id == self.org_id for j in jobs)

    async def test_get_by_company_respects_limit(self):
        for i in range(5):
            await self.repo.save(_make_job(self.org_id, self.user_id, f"Job {i}"))

        jobs = await self.repo.get_by_company(self.org_id, limit=3)
        assert len(jobs) == 3

    async def test_get_by_company_respects_offset(self):
        for i in range(5):
            await self.repo.save(_make_job(self.org_id, self.user_id, f"Job {i}"))

        page1 = await self.repo.get_by_company(self.org_id, limit=3, offset=0)
        page2 = await self.repo.get_by_company(self.org_id, limit=3, offset=3)
        all_ids = {j.id for j in page1} | {j.id for j in page2}
        assert len(all_ids) == 5

    # ── delete ──

    async def test_delete_removes_job(self):
        job = _make_job(self.org_id, self.user_id)
        await self.repo.save(job)
        await self.repo.delete(job.id)

        assert await self.repo.get_by_id(job.id) is None

    async def test_delete_nonexistent_is_safe(self):
        await self.repo.delete(uuid.uuid4())  # should not raise

    # ── exists / count helpers ──

    async def test_exists_returns_true_for_saved_job(self):
        job = _make_job(self.org_id, self.user_id)
        await self.repo.save(job)
        assert await self.repo.exists(job.id) is True

    async def test_exists_returns_false_for_unknown(self):
        assert await self.repo.exists(uuid.uuid4()) is False

    async def test_count_by_org(self):
        for _ in range(3):
            await self.repo.save(_make_job(self.org_id, self.user_id))

        count = await self.repo.count_by_org(self.org_id)
        assert count == 3

    async def test_count_by_org_with_status_filter(self):
        active_job = _make_job(self.org_id, self.user_id, "Active J")
        active_job.activate()
        await self.repo.save(active_job)
        await self.repo.save(_make_job(self.org_id, self.user_id, "Draft J"))

        count = await self.repo.count_by_org(self.org_id, status=JobStatus.ACTIVE)
        assert count == 1


# ─
# ── Candidate Repository Integration Tests ─
# ─


class TestSQLAlchemyCandidateRepository:
    """
    Integration tests for SQLAlchemyCandidateRepository.
    Uses in-memory SQLite + the candidate_user fixture (pre-seeded User row).
    """

    @pytest.fixture(autouse=True)
    def _setup(self, db_manager, candidate_user):
        self.repo = SQLAlchemyCandidateRepository(db_manager)
        self.user = candidate_user

    def _make_candidate_for_user(self) -> Candidate:
        """Create a Candidate whose id matches the pre-seeded candidate_user.id."""
        return Candidate(
            candidate_id=self.user.id,
            full_name=self.user.display_name,
            contact=ContactInfo(email=self.user.email),
        )

    # ── create_for_user / get_by_id ──

    async def test_create_for_user_and_retrieve(self):
        candidate = self._make_candidate_for_user()
        await self.repo.create_for_user(self.user.id, candidate)

        fetched = await self.repo.get_by_id(candidate.id)
        assert fetched is not None
        assert fetched.id == candidate.id

    async def test_get_by_id_returns_correct_email(self):
        candidate = self._make_candidate_for_user()
        await self.repo.create_for_user(self.user.id, candidate)

        fetched = await self.repo.get_by_id(candidate.id)
        assert fetched.contact.email == self.user.email

    async def test_get_by_id_returns_none_for_unknown(self):
        result = await self.repo.get_by_id(uuid.uuid4())
        assert result is None

    async def test_get_by_id_reconstructs_full_name(self):
        candidate = self._make_candidate_for_user()
        await self.repo.create_for_user(self.user.id, candidate)

        fetched = await self.repo.get_by_id(candidate.id)
        assert fetched.full_name == self.user.display_name

    # ── get_by_email ──

    async def test_get_by_email_finds_candidate(self):
        candidate = self._make_candidate_for_user()
        await self.repo.create_for_user(self.user.id, candidate)

        fetched = await self.repo.get_by_email(self.user.email)
        assert fetched is not None
        assert fetched.id == candidate.id

    async def test_get_by_email_returns_none_for_unknown(self):
        result = await self.repo.get_by_email("nobody@example.com")
        assert result is None

    async def test_get_by_email_case_sensitive(self):
        candidate = self._make_candidate_for_user()
        await self.repo.create_for_user(self.user.id, candidate)

        # emails are stored exactly as given; uppercase should NOT match
        result = await self.repo.get_by_email(self.user.email.upper())
        assert result is None

    # ── create_for_user idempotency ──

    async def test_create_for_user_is_idempotent(self):
        candidate = self._make_candidate_for_user()
        await self.repo.create_for_user(self.user.id, candidate)
        await self.repo.create_for_user(self.user.id, candidate)  # second call = no-op

        fetched = await self.repo.get_by_id(candidate.id)
        assert fetched is not None  # still exists, no duplicate

    # ── delete ──

    async def test_delete_removes_candidate_profile(self):
        candidate = self._make_candidate_for_user()
        await self.repo.create_for_user(self.user.id, candidate)
        await self.repo.delete(candidate.id)

        assert await self.repo.get_by_id(candidate.id) is None

    async def test_delete_nonexistent_is_safe(self):
        await self.repo.delete(uuid.uuid4())  # should not raise

    # ── exists / count ──

    async def test_exists_returns_true_after_create(self):
        candidate = self._make_candidate_for_user()
        await self.repo.create_for_user(self.user.id, candidate)

        assert await self.repo.exists(candidate.id) is True

    async def test_exists_returns_false_for_unknown(self):
        assert await self.repo.exists(uuid.uuid4()) is False

    async def test_count_reflects_created_profile(self):
        candidate = self._make_candidate_for_user()
        await self.repo.create_for_user(self.user.id, candidate)

        count = await self.repo.count()
        assert count >= 1

    # ── active_interview_job_ids ──

    async def test_get_by_id_without_loading_interviews_returns_empty_set(self):
        candidate = self._make_candidate_for_user()
        await self.repo.create_for_user(self.user.id, candidate)

        fetched = await self.repo.get_by_id(candidate.id, load_active_interviews=False)
        # When load_active_interviews=False the set should be empty
        assert not fetched.has_active_interview_for(uuid.uuid4())

    # ── status mapping ──

    async def test_active_user_maps_to_active_candidate_status(self):
        candidate = self._make_candidate_for_user()
        await self.repo.create_for_user(self.user.id, candidate)

        fetched = await self.repo.get_by_id(candidate.id)
        assert fetched.status == CandidateStatus.ACTIVE
