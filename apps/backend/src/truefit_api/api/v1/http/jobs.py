"""
Job listing endpoints.

POST   /jobs                    Create a job (DRAFT)
GET    /jobs/{job_id}           Get a single job
GET    /jobs                    List jobs for an org
PATCH  /jobs/{job_id}           Update description / interview config / skills
POST   /jobs/{job_id}/activate  Transition DRAFT -> ACTIVE
POST   /jobs/{job_id}/pause     Transition ACTIVE -> PAUSED
POST   /jobs/{job_id}/close     Transition -> CLOSED (also abandons active interviews)
DELETE /jobs/{job_id}           Hard delete (DRAFT only)
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from src.truefit_core.domain.job import ExperienceLevel, JobStatus
from src.truefit_infra.db.database import DatabaseManager, db_manager
from src.truefit_infra.db.repositories.job_repository import SQLAlchemyJobRepository
from src.truefit_core.application.services.job_service import JobService
from src.truefit_core.domain.job import (
    InterviewConfig,
    Job,
    JobRequirements,
    SkillRequirement,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


# ── Dependency


def get_job_repo() -> SQLAlchemyJobRepository:
    return SQLAlchemyJobRepository(db_manager)


def get_job_service(
    repo: SQLAlchemyJobRepository = Depends(get_job_repo),
) -> JobService:
    # InterviewRepository injected as None here - wire fully when available
    return JobService(job_repo=repo, interview_repo=None, queue=None)


# ── Request schemas


class SkillIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    required: bool = True
    weight: float = Field(1.0, ge=0.0, le=1.0)
    min_years: Optional[int] = Field(None, ge=0)


class RequirementsIn(BaseModel):
    experience_level: str
    min_total_years: Optional[int] = Field(None, ge=0)
    education: Optional[str] = None
    certifications: list[str] = []
    location: Optional[str] = None
    work_arrangement: Optional[str] = None

    @field_validator("experience_level")
    @classmethod
    def validate_experience_level(cls, v: str) -> str:
        try:
            ExperienceLevel(v)
        except ValueError:
            valid = [e.value for e in ExperienceLevel]
            raise ValueError(f"Must be one of: {valid}")
        return v

    @field_validator("work_arrangement")
    @classmethod
    def validate_work_arrangement(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in ("remote", "hybrid", "onsite"):
            raise ValueError("work_arrangement must be remote, hybrid, or onsite")
        return v


class InterviewConfigIn(BaseModel):
    max_questions: int = Field(10, ge=1, le=50)
    max_duration_minutes: int = Field(30, ge=5, le=120)
    topics: list[str] = []
    custom_instructions: Optional[str] = None


class CreateJobRequest(BaseModel):
    org_id: uuid.UUID
    created_by: uuid.UUID
    title: str = Field(..., min_length=2, max_length=255)
    description: str = Field(..., min_length=10)
    requirements: RequirementsIn
    skills: list[SkillIn] = Field(..., min_length=1)
    interview_config: Optional[InterviewConfigIn] = None


class UpdateJobRequest(BaseModel):
    description: Optional[str] = Field(None, min_length=10)
    requirements: Optional[RequirementsIn] = None
    skills_add: Optional[list[SkillIn]] = None  # skills to add
    skills_remove: Optional[list[str]] = None  # skill names to remove
    interview_config: Optional[InterviewConfigIn] = None


# ── Response schema


class SkillOut(BaseModel):
    name: str
    required: bool
    weight: float
    min_years: Optional[int]


class RequirementsOut(BaseModel):
    experience_level: str
    min_total_years: Optional[int]
    education: Optional[str]
    certifications: list[str]
    location: Optional[str]
    work_arrangement: Optional[str]


class InterviewConfigOut(BaseModel):
    max_questions: int
    max_duration_minutes: int
    topics: list[str]
    custom_instructions: Optional[str]


class JobOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    created_by: uuid.UUID
    title: str
    description: str
    status: str
    requirements: RequirementsOut
    skills: list[SkillOut]
    interview_config: InterviewConfigOut
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, job: Job) -> "JobOut":
        req = job.requirements
        return cls(
            id=job.id,
            org_id=job.org_id,
            created_by=job.created_by,
            title=job.title,
            description=job.description,
            status=job.status.value,
            requirements=RequirementsOut(
                experience_level=req.experience_level.value,
                min_total_years=req.min_total_years,
                education=req.education,
                certifications=req.certifications,
                location=req.location,
                work_arrangement=req.work_arrangement,
            ),
            skills=[
                SkillOut(
                    name=s.name,
                    required=s.required,
                    weight=s.weight,
                    min_years=s.min_years,
                )
                for s in job.skills
            ],
            interview_config=InterviewConfigOut(
                max_questions=job.interview_config.max_questions,
                max_duration_minutes=job.interview_config.max_duration_minutes,
                topics=job.interview_config.topics,
                custom_instructions=job.interview_config.custom_instructions,
            ),
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
        )


# ── Endpoints


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: CreateJobRequest,
    repo: SQLAlchemyJobRepository = Depends(get_job_repo),
):
    requirements = JobRequirements(
        experience_level=ExperienceLevel(body.requirements.experience_level),
        min_total_years=body.requirements.min_total_years,
        education=body.requirements.education,
        certifications=body.requirements.certifications,
        location=body.requirements.location,
        work_arrangement=body.requirements.work_arrangement,
    )
    skills = [
        SkillRequirement(
            name=s.name,
            required=s.required,
            weight=s.weight,
            min_years=s.min_years,
        )
        for s in body.skills
    ]
    interview_config = None
    if body.interview_config:
        interview_config = InterviewConfig(
            max_questions=body.interview_config.max_questions,
            max_duration_minutes=body.interview_config.max_duration_minutes,
            topics=body.interview_config.topics,
            custom_instructions=body.interview_config.custom_instructions,
        )

    job = Job(
        org_id=body.org_id,
        created_by=body.created_by,
        title=body.title,
        description=body.description,
        requirements=requirements,
        skills=skills,
        interview_config=interview_config,
    )
    await repo.save(job)
    return JobOut.from_domain(job)


@router.get("/active", response_model=list[JobOut])
async def list_active_jobs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: SQLAlchemyJobRepository = Depends(get_job_repo),
):
    """List all active jobs across all orgs - for candidate job discovery."""
    jobs = await repo.list_all_active(limit=limit, offset=offset)
    return [JobOut.from_domain(j) for j in jobs]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: uuid.UUID,
    repo: SQLAlchemyJobRepository = Depends(get_job_repo),
):
    job = await repo.get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return JobOut.from_domain(job)


@router.get("", response_model=list[JobOut])
async def list_jobs(
    org_id: uuid.UUID = Query(...),
    status_filter: Optional[str] = Query(None, alias="status"),
    experience_level: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: SQLAlchemyJobRepository = Depends(get_job_repo),
):
    if status_filter:
        try:
            s = JobStatus(status_filter)
        except ValueError:
            raise HTTPException(400, detail=f"Invalid status: {status_filter}")
        jobs = await repo.get_by_org_and_status(org_id, s, limit=limit, offset=offset)

    elif experience_level:
        try:
            exp = ExperienceLevel(experience_level)
        except ValueError:
            raise HTTPException(
                400, detail=f"Invalid experience_level: {experience_level}"
            )
        jobs = await repo.get_by_org_and_experience(
            org_id, exp, limit=limit, offset=offset
        )

    else:
        jobs = await repo.get_by_company(org_id, limit=limit, offset=offset)

    return [JobOut.from_domain(j) for j in jobs]


@router.patch("/{job_id}", response_model=JobOut)
async def update_job(
    job_id: uuid.UUID,
    body: UpdateJobRequest,
    repo: SQLAlchemyJobRepository = Depends(get_job_repo),
):
    job = await repo.get_by_id(job_id)
    if not job:
        raise HTTPException(404, detail=f"Job {job_id} not found")

    try:
        if body.description:
            job.update_description(body.description)

        if body.requirements:
            req = JobRequirements(
                experience_level=ExperienceLevel(body.requirements.experience_level),
                min_total_years=body.requirements.min_total_years,
                education=body.requirements.education,
                certifications=body.requirements.certifications,
                location=body.requirements.location,
                work_arrangement=body.requirements.work_arrangement,
            )
            job.update_requirements(req)

        for skill_name in body.skills_remove or []:
            job.remove_skill(skill_name)

        for s in body.skills_add or []:
            job.add_skill(
                SkillRequirement(
                    name=s.name,
                    required=s.required,
                    weight=s.weight,
                    min_years=s.min_years,
                )
            )

        if body.interview_config:
            job.update_interview_config(
                InterviewConfig(
                    max_questions=body.interview_config.max_questions,
                    max_duration_minutes=body.interview_config.max_duration_minutes,
                    topics=body.interview_config.topics,
                    custom_instructions=body.interview_config.custom_instructions,
                )
            )

        await repo.save(job)
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, detail=str(e))

    return JobOut.from_domain(job)


@router.post("/{job_id}/activate", response_model=JobOut)
async def activate_job(
    job_id: uuid.UUID,
    repo: SQLAlchemyJobRepository = Depends(get_job_repo),
):
    job = await repo.get_by_id(job_id)
    if not job:
        raise HTTPException(404, detail=f"Job {job_id} not found")
    try:
        job.activate()
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    await repo.save(job)
    return JobOut.from_domain(job)


@router.post("/{job_id}/pause", response_model=JobOut)
async def pause_job(
    job_id: uuid.UUID,
    repo: SQLAlchemyJobRepository = Depends(get_job_repo),
):
    job = await repo.get_by_id(job_id)
    if not job:
        raise HTTPException(404, detail=f"Job {job_id} not found")
    try:
        job.pause()
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    await repo.save(job)
    return JobOut.from_domain(job)


@router.post("/{job_id}/close", response_model=JobOut)
async def close_job(
    job_id: uuid.UUID,
    repo: SQLAlchemyJobRepository = Depends(get_job_repo),
):
    job = await repo.get_by_id(job_id)
    if not job:
        raise HTTPException(404, detail=f"Job {job_id} not found")
    try:
        job.close()
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    await repo.save(job)
    return JobOut.from_domain(job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: uuid.UUID,
    repo: SQLAlchemyJobRepository = Depends(get_job_repo),
):
    job = await repo.get_by_id(job_id)
    if not job:
        raise HTTPException(404, detail=f"Job {job_id} not found")
    if job.status != JobStatus.DRAFT:
        raise HTTPException(400, detail="Only DRAFT jobs can be hard deleted")
    await repo.delete(job_id)
