"""
truefit_infra/db/repositories/job_repository.py

SQLAlchemy implementation of JobRepository against the job_listings table.

Mapping layers
──────────────
_to_row(job)     Job domain object  →  flat dict for JobListing upsert
_to_domain(row)  JobListing ORM row   →  reconstructed Job aggregate

The two JSONB columns map to domain value objects as follows:

  DB column        Domain object
  ───────────────────────────────────────────────────────────────
  skills           list[SkillRequirement]   (name, required, weight, min_years)
  requirements     JobRequirements          (experience_level, min_total_years,
                                             education, certifications,
                                             location, work_arrangement, extra)
  interview_config InterviewConfig          (max_questions, max_duration_minutes,
                                             topics, custom_instructions)

experience_level is written to BOTH the requirements JSONB and the dedicated
experience_level column so filtering queries don't need a JSONB expression index.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.truefit_core.application.ports import JobRepository
from src.truefit_core.domain.job import (
    ExperienceLevel,
    InterviewConfig,
    Job,
    JobRequirements,
    JobStatus,
    SkillRequirement,
)
from src.truefit_infra.db.database import DatabaseManager
from src.truefit_infra.db.models import JobListing


class SQLAlchemyJobRepository(JobRepository):

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # ── JobRepository interface ───────────────────────────────────────────────

    async def save(self, job: Job) -> None:
        """
        Upsert the full job aggregate.
        Safe for both initial creation and all subsequent mutations.
        created_by and created_at are excluded from the update set —
        they are immutable after first write.
        """
        data = self._to_row(job)

        stmt = (
            pg_insert(JobListing)
            .values(**data)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "title":            data["title"],
                    "description":      data["description"],
                    "status":           data["status"],
                    "experience_level": data["experience_level"],
                    "skills":           data["skills"],
                    "requirements":     data["requirements"],
                    "interview_config": data["interview_config"],
                    "updated_at":       data["updated_at"],
                    # org_id, created_by, created_at deliberately excluded
                },
            )
        )

        async with self._db.get_session() as session:
            await session.execute(stmt)

    async def get_by_id(self, job_id: uuid.UUID) -> Optional[Job]:
        stmt = select(JobListing).where(JobListing.id == job_id)

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

        return self._to_domain(row) if row else None

    async def get_by_company(
        self,
        org_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Job]:
        """get_by_company maps to org_id."""
        stmt = (
            select(JobListing)
            .where(JobListing.org_id == org_id)
            .order_by(JobListing.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [self._to_domain(row) for row in rows]

    async def delete(self, job_id: uuid.UUID) -> None:
        stmt = delete(JobListing).where(JobListing.id == job_id)

        async with self._db.get_session() as session:
            await session.execute(stmt)

    # ── Extended read methods (beyond abstract port) ───

    async def get_by_org_and_status(
        self,
        org_id: uuid.UUID,
        status: JobStatus,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Job]:
        stmt = (
            select(JobListing)
            .where(
                JobListing.org_id == org_id,
                JobListing.status == status.value,
            )
            .order_by(JobListing.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [self._to_domain(row) for row in rows]

    async def get_by_org_and_experience(
        self,
        org_id: uuid.UUID,
        experience_level: ExperienceLevel,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Job]:
        stmt = (
            select(JobListing)
            .where(
                JobListing.org_id == org_id,
                JobListing.experience_level == experience_level.value,
            )
            .order_by(JobListing.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [self._to_domain(row) for row in rows]

    async def count_by_org(
        self,
        org_id: uuid.UUID,
        *,
        status: Optional[JobStatus] = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(JobListing)
            .where(JobListing.org_id == org_id)
        )
        if status:
            stmt = stmt.where(JobListing.status == status.value)

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            return result.scalar_one()

    async def exists(self, job_id: uuid.UUID) -> bool:
        stmt = select(func.count()).select_from(JobListing).where(JobListing.id == job_id)

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            return result.scalar_one() > 0

    # ── Mapping: domain → DB row ──

    @staticmethod
    def _to_row(job: Job) -> dict:
        """
        Flatten Job aggregate → dict matching JobListing columns exactly.

        experience_level is written to both the dedicated column AND inside
        the requirements JSONB so _to_domain can reconstruct without splitting.
        """
        req = job.requirements
        return {
            "id":               job.id,
            "org_id":           job.org_id,
            "created_by":       job.created_by,
            "title":            job.title,
            "description":      job.description,
            "status":           job.status.value,
            "experience_level": req.experience_level.value,  # denormalised column
            "skills": [
                {
                    "name":      s.name,
                    "required":  s.required,
                    "weight":    s.weight,
                    "min_years": s.min_years,
                }
                for s in job.skills
            ],
            "requirements": {
                "experience_level":  req.experience_level.value,
                "min_total_years":   req.min_total_years,
                "education":         req.education,
                "certifications":    req.certifications,
                "location":          req.location,
                "work_arrangement":  req.work_arrangement,
                "extra":             req.extra,
            },
            "interview_config": {
                "max_questions":        job.interview_config.max_questions,
                "max_duration_minutes": job.interview_config.max_duration_minutes,
                "topics":               job.interview_config.topics,
                "custom_instructions":  job.interview_config.custom_instructions,
            },
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }

    # ── Mapping: DB row → domain ──

    @staticmethod
    def _to_domain(row: JobListing) -> Job:
        """
        Reconstruct a fully valid Job aggregate from a JobListing row.

        Safe defaults on every JSONB key guard against rows written before
        a field was added — forward and backward compatible.
        """
        # ── Skills ──
        skills = [
            SkillRequirement(
                name=s["name"],
                required=s.get("required", True),
                weight=s.get("weight", 1.0),
                min_years=s.get("min_years"),
            )
            for s in (row.skills or [])
        ]

        # ── Requirements ───
        req = row.requirements or {}
        # experience_level: prefer the dedicated column (always up-to-date),
        # fall back to the JSONB value for rows created before the column existed.
        raw_exp = row.experience_level or req.get("experience_level", "mid")
        requirements = JobRequirements(
            experience_level=ExperienceLevel(raw_exp),
            min_total_years=req.get("min_total_years"),
            education=req.get("education"),
            certifications=req.get("certifications", []),
            location=req.get("location"),
            work_arrangement=req.get("work_arrangement"),
            extra=req.get("extra", {}),
        )

        # ── Interview config ───
        cfg = row.interview_config or {}
        interview_config = InterviewConfig(
            max_questions=cfg.get("max_questions", 10),
            max_duration_minutes=cfg.get("max_duration_minutes", 30),
            topics=cfg.get("topics", []),
            custom_instructions=cfg.get("custom_instructions"),
        )

        return Job(
            job_id=row.id,
            org_id=row.org_id,
            created_by=row.created_by,
            title=row.title,
            description=row.description,
            status=JobStatus(row.status),
            requirements=requirements,
            skills=skills,
            interview_config=interview_config,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )