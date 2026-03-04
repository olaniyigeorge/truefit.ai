"""
tests/unit/domain/test_job.py
──────────────────────────────
Unit tests for the Job aggregate root and its value objects.
No database, no I/O — pure domain logic.
"""

import uuid

import pytest

from src.truefit_core.domain.job import (
    ExperienceLevel,
    InterviewConfig,
    Job,
    JobRequirements,
    JobStatus,
    SkillRequirement,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def make_skill(name: str = "Python", required: bool = True, weight: float = 1.0) -> SkillRequirement:
    return SkillRequirement(name=name, required=required, weight=weight)


def make_requirements(level: ExperienceLevel = ExperienceLevel.MID) -> JobRequirements:
    return JobRequirements(
        experience_level=level,
        min_total_years=3,
        location="Remote",
        work_arrangement="remote",
    )


def make_job(
    title: str = "Backend Engineer",
    description: str = "Build scalable APIs.",
    status: JobStatus = JobStatus.DRAFT,
    skills: list[SkillRequirement] | None = None,
) -> Job:
    return Job(
        org_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        title=title,
        description=description,
        requirements=make_requirements(),
        skills=skills or [make_skill("Python"), make_skill("PostgreSQL", required=False)],
        status=status,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SkillRequirement value object
# ─────────────────────────────────────────────────────────────────────────────


class TestSkillRequirement:
    def test_valid_skill_creates_successfully(self):
        s = SkillRequirement(name="Python", weight=0.9)
        assert s.name == "Python"
        assert s.weight == 0.9

    def test_empty_name_raises_value_error(self):
        with pytest.raises(ValueError, match="Skill name cannot be empty"):
            SkillRequirement(name="  ")

    def test_weight_above_1_raises(self):
        with pytest.raises(ValueError, match="weight"):
            SkillRequirement(name="Go", weight=1.1)

    def test_weight_below_0_raises(self):
        with pytest.raises(ValueError, match="weight"):
            SkillRequirement(name="Go", weight=-0.1)

    def test_negative_min_years_raises(self):
        with pytest.raises(ValueError, match="min_years"):
            SkillRequirement(name="Go", min_years=-1)

    def test_zero_min_years_is_valid(self):
        s = SkillRequirement(name="Go", min_years=0)
        assert s.min_years == 0

    def test_defaults_to_required_true(self):
        assert SkillRequirement(name="Rust").required is True

    def test_defaults_to_weight_1(self):
        assert SkillRequirement(name="Rust").weight == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# JobRequirements value object
# ─────────────────────────────────────────────────────────────────────────────


class TestJobRequirements:
    def test_valid_requirements(self):
        req = make_requirements(ExperienceLevel.SENIOR)
        assert req.experience_level == ExperienceLevel.SENIOR

    def test_negative_min_total_years_raises(self):
        with pytest.raises(ValueError, match="min_total_years"):
            JobRequirements(experience_level=ExperienceLevel.MID, min_total_years=-1)

    def test_certifications_default_to_empty_list(self):
        req = JobRequirements(experience_level=ExperienceLevel.JUNIOR)
        assert req.certifications == []

    def test_extra_defaults_to_empty_dict(self):
        req = JobRequirements(experience_level=ExperienceLevel.INTERN)
        assert req.extra == {}


# ─────────────────────────────────────────────────────────────────────────────
# InterviewConfig value object
# ─────────────────────────────────────────────────────────────────────────────


class TestInterviewConfig:
    def test_default_config_is_valid(self):
        cfg = InterviewConfig()
        assert cfg.max_questions == 10
        assert cfg.max_duration_minutes == 30

    def test_max_questions_below_1_raises(self):
        with pytest.raises(ValueError, match="max_questions"):
            InterviewConfig(max_questions=0)

    def test_max_duration_below_5_raises(self):
        with pytest.raises(ValueError, match="max_duration_minutes"):
            InterviewConfig(max_duration_minutes=4)

    def test_custom_config(self):
        cfg = InterviewConfig(max_questions=5, max_duration_minutes=15, topics=["DSA", "System Design"])
        assert cfg.max_questions == 5
        assert "DSA" in cfg.topics


# ─────────────────────────────────────────────────────────────────────────────
# Job — construction & validation
# ─────────────────────────────────────────────────────────────────────────────


class TestJobConstruction:
    def test_basic_creation_succeeds(self):
        job = make_job()
        assert job.title == "Backend Engineer"
        assert job.status == JobStatus.DRAFT

    def test_empty_title_raises(self):
        with pytest.raises(ValueError, match="title cannot be empty"):
            make_job(title="  ")

    def test_empty_description_raises(self):
        with pytest.raises(ValueError, match="description cannot be empty"):
            make_job(description="")

    def test_no_skills_raises(self):
        with pytest.raises(ValueError, match="At least one skill"):
            make_job(skills=[])

    def test_explicit_job_id_is_respected(self):
        fixed_id = uuid.uuid4()
        job = Job(
            job_id=fixed_id,
            org_id=uuid.uuid4(),
            created_by=uuid.uuid4(),
            title="Dev",
            description="Desc",
            requirements=make_requirements(),
            skills=[make_skill()],
        )
        assert job.id == fixed_id

    def test_title_is_stripped(self):
        job = make_job(title="  My Job  ")
        assert job.title == "My Job"

    def test_default_interview_config_is_created(self):
        job = make_job()
        assert job.interview_config.max_questions == 10

    def test_custom_interview_config_is_stored(self):
        cfg = InterviewConfig(max_questions=5)
        job = Job(
            org_id=uuid.uuid4(),
            created_by=uuid.uuid4(),
            title="Analyst",
            description="Analyse.",
            requirements=make_requirements(),
            skills=[make_skill()],
            interview_config=cfg,
        )
        assert job.interview_config.max_questions == 5

    def test_job_equality_by_id(self):
        fixed_id = uuid.uuid4()
        org = uuid.uuid4()
        creator = uuid.uuid4()
        a = Job(job_id=fixed_id, org_id=org, created_by=creator, title="A", description="D",
                requirements=make_requirements(), skills=[make_skill()])
        b = Job(job_id=fixed_id, org_id=org, created_by=creator, title="B", description="D2",
                requirements=make_requirements(), skills=[make_skill()])
        assert a == b

    def test_job_is_hashable(self):
        job = make_job()
        s = {job}
        assert job in s


# ─────────────────────────────────────────────────────────────────────────────
# Job — status transitions
# ─────────────────────────────────────────────────────────────────────────────


class TestJobStatusTransitions:
    def test_draft_can_activate(self):
        job = make_job()
        job.activate()
        assert job.status == JobStatus.ACTIVE

    def test_active_job_is_open_for_interviews(self):
        job = make_job()
        job.activate()
        assert job.is_open_for_interviews is True

    def test_draft_job_is_not_open_for_interviews(self):
        job = make_job()
        assert job.is_open_for_interviews is False

    def test_active_can_pause(self):
        job = make_job()
        job.activate()
        job.pause()
        assert job.status == JobStatus.PAUSED

    def test_active_can_close(self):
        job = make_job()
        job.activate()
        job.close()
        assert job.status == JobStatus.CLOSED

    def test_paused_can_reactivate(self):
        job = make_job()
        job.activate()
        job.pause()
        job.activate()
        assert job.status == JobStatus.ACTIVE

    def test_paused_can_close(self):
        job = make_job()
        job.activate()
        job.pause()
        job.close()
        assert job.status == JobStatus.CLOSED

    def test_closed_job_cannot_transition(self):
        job = make_job()
        job.activate()
        job.close()
        with pytest.raises(ValueError, match="Invalid status transition"):
            job.activate()

    def test_draft_cannot_pause_directly(self):
        job = make_job()
        with pytest.raises(ValueError, match="Invalid status transition"):
            job.pause()

    def test_draft_cannot_close_directly(self):
        job = make_job()
        with pytest.raises(ValueError, match="Invalid status transition"):
            job.close()

    def test_assert_open_raises_for_draft(self):
        with pytest.raises(ValueError, match="not accepting interviews"):
            make_job().assert_open_for_interviews()

    def test_assert_open_does_not_raise_for_active(self):
        job = make_job()
        job.activate()
        job.assert_open_for_interviews()  # should not raise

    def test_transition_updates_timestamp(self):
        job = make_job()
        before = job.updated_at
        job.activate()
        assert job.updated_at >= before


# ─────────────────────────────────────────────────────────────────────────────
# Job — description & requirements mutations
# ─────────────────────────────────────────────────────────────────────────────


class TestJobMutations:
    def test_update_description(self):
        job = make_job()
        job.update_description("New detailed description for the role.")
        assert "New detailed" in job.description

    def test_update_description_empty_raises(self):
        job = make_job()
        with pytest.raises(ValueError, match="Description cannot be empty"):
            job.update_description("   ")

    def test_closed_job_cannot_update_description(self):
        job = make_job()
        job.activate()
        job.close()
        with pytest.raises(PermissionError, match="Cannot modify a closed job"):
            job.update_description("New desc")

    def test_update_requirements(self):
        job = make_job()
        new_req = JobRequirements(experience_level=ExperienceLevel.SENIOR, min_total_years=7)
        job.update_requirements(new_req)
        assert job.requirements.experience_level == ExperienceLevel.SENIOR
        assert job.experience_level == ExperienceLevel.SENIOR

    def test_update_interview_config(self):
        job = make_job()
        new_cfg = InterviewConfig(max_questions=15, max_duration_minutes=45)
        job.update_interview_config(new_cfg)
        assert job.interview_config.max_questions == 15

    def test_closed_job_cannot_update_requirements(self):
        job = make_job()
        job.activate()
        job.close()
        with pytest.raises(PermissionError):
            job.update_requirements(make_requirements())


# ─────────────────────────────────────────────────────────────────────────────
# Job — skill management
# ─────────────────────────────────────────────────────────────────────────────


class TestJobSkillManagement:
    def test_add_skill(self):
        job = make_job()
        job.add_skill(SkillRequirement(name="Docker"))
        names = [s.name for s in job.skills]
        assert "Docker" in names

    def test_add_duplicate_skill_raises(self):
        job = make_job(skills=[make_skill("Python")])
        with pytest.raises(ValueError, match="already exists"):
            job.add_skill(make_skill("Python"))

    def test_add_duplicate_skill_case_insensitive(self):
        job = make_job(skills=[make_skill("Python")])
        with pytest.raises(ValueError, match="already exists"):
            job.add_skill(make_skill("python"))

    def test_remove_skill(self):
        job = make_job(skills=[make_skill("Python"), make_skill("Go")])
        job.remove_skill("Python")
        names = [s.name for s in job.skills]
        assert "Python" not in names
        assert "Go" in names

    def test_remove_nonexistent_skill_raises(self):
        job = make_job()
        with pytest.raises(ValueError, match="not found"):
            job.remove_skill("Haskell")

    def test_cannot_remove_last_skill(self):
        job = make_job(skills=[make_skill("Python")])
        with pytest.raises(ValueError, match="at least one skill"):
            job.remove_skill("Python")

    def test_update_skill_weight(self):
        job = make_job(skills=[make_skill("Python", weight=1.0)])
        job.update_skill("Python", weight=0.5)
        py = next(s for s in job.skills if s.name == "Python")
        assert py.weight == 0.5

    def test_update_skill_required_flag(self):
        job = make_job(skills=[make_skill("Python", required=True)])
        job.update_skill("Python", required=False)
        py = next(s for s in job.skills if s.name == "Python")
        assert py.required is False

    def test_update_skill_min_years(self):
        job = make_job(skills=[make_skill("Python")])
        job.update_skill("Python", min_years=3)
        py = next(s for s in job.skills if s.name == "Python")
        assert py.min_years == 3

    def test_update_nonexistent_skill_raises(self):
        job = make_job()
        with pytest.raises(ValueError, match="not found"):
            job.update_skill("Erlang", weight=0.5)

    def test_closed_job_cannot_add_skill(self):
        job = make_job()
        job.activate()
        job.close()
        with pytest.raises(PermissionError):
            job.add_skill(make_skill("Docker"))

    def test_required_skills_filter(self):
        job = make_job(skills=[
            make_skill("Python", required=True),
            make_skill("Docker", required=False),
        ])
        assert all(s.required for s in job.required_skills)

    def test_preferred_skills_filter(self):
        job = make_job(skills=[
            make_skill("Python", required=True),
            make_skill("Docker", required=False),
        ])
        assert all(not s.required for s in job.preferred_skills)

    def test_skills_property_returns_copy(self):
        job = make_job()
        skills_copy = job.skills
        skills_copy.append(make_skill("Haskell"))
        assert "Haskell" not in [s.name for s in job.skills]
