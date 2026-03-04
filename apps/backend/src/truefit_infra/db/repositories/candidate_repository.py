"""
SQLAlchemy implementation of CandidateRepository.

Mapping notes
─────────────
contact JSONB     ↔  ContactInfo(email, phone, linkedin_url)
resume  JSONB     ↔  ResumeRef(storage_key, filename, uploaded_at, content_type)
active_interview_job_ids JSONB  ↔  set[uuid.UUID]

Email uniqueness is enforced by a partial unique index on contact->>'email'.
The repo checks before insert and raises a clean ValueError on conflict
so the endpoint can return 409 without catching IntegrityError everywhere.
"""

from __future__ import annotations

import uuid
from typing import Optional, Set

from sqlalchemy import distinct, func, select, delete, text
from sqlalchemy.dialects.postgresql import Any, insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from src.truefit_core.application.ports import CandidateRepository
from src.truefit_core.domain.candidate import (
    Candidate,
    CandidateStatus,
    ContactInfo,
    ResumeRef,
)
from src.truefit_infra.db.database import DatabaseManager
from src.truefit_infra.db.models import (
    CandidateProfile as CandidateProfileModel,
    User as UserModel,
    Application as ApplicationModel,
    InterviewSession as InterviewSessionModel,
    MediaAsset as MediaAssetModel,
)



class SQLAlchemyCandidateRepository(CandidateRepository):

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # ── CandidateRepository interface ──

    async def save(self, candidate: Candidate) -> None:
        data = self._to_row(candidate)
        stmt = (
            pg_insert(CandidateProfileModel)
            .values(**data)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "full_name":                 data["full_name"],
                    "status":                    data["status"],
                    "contact":                   data["contact"],
                    "resume":                    data["resume"],
                    "active_interview_job_ids":  data["active_interview_job_ids"],
                    "updated_at":                data["updated_at"],
                },
            )
        )
        try:
            async with self._db.get_session() as session:
                await session.execute(stmt)
        except IntegrityError as e:
            if "ix_candidates_email" in str(e.orig) or "contact" in str(e.orig):
                raise ValueError(
                    f"A candidate with this email already exists"
                ) from e
            raise

    async def list_all(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[Candidate]:
        stmt = (
            select(CandidateProfileModel)
            .order_by(CandidateProfileModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def delete(self, candidate_id: uuid.UUID) -> None:
        stmt = delete(CandidateProfileModel).where(CandidateProfileModel.id == candidate_id)
        async with self._db.get_session() as session:
            await session.execute(stmt)

    async def count(self) -> int:
        stmt = select(func.count()).select_from(CandidateProfileModel)
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            return result.scalar_one()


    
    async def get_by_id(self, candidate_profile_id: uuid.UUID) -> Optional[Candidate]:
        stmt = (
            select(CandidateProfileModel)
            .options(joinedload(CandidateProfileModel.user))
            .where(CandidateProfileModel.id == candidate_profile_id)
        )

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            profile = result.scalar_one_or_none()
            if not profile:
                return None

            active_job_ids = await self._active_job_ids_for_candidate_profile(
                session=session,
                candidate_profile_id=profile.id,
            )

            resume_ref = await self._resume_ref_for_profile(
                session=session,
                resume_asset_id=profile.resume_asset_id,
            )
            return self._to_domain(profile, active_job_ids, resume_ref)

    async def get_by_email(self, email: str) -> Optional[Candidate]:
        email_norm = email.lower().strip()

        stmt = (
            select(CandidateProfileModel)
            .join(UserModel, CandidateProfileModel.user_id == UserModel.id)
            .options(joinedload(CandidateProfileModel.user))
            .where(UserModel.email == email_norm)
        )

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            profile = result.scalar_one_or_none()
            if not profile:
                return None

            active_job_ids = await self._active_job_ids_for_candidate_profile(
                session=session,
                candidate_profile_id=profile.id,
            )

            resume_ref = await self._resume_ref_for_profile(
                session=session,
                resume_asset_id=profile.resume_asset_id,
            )

            return self._to_domain(profile, active_job_ids, resume_ref)

    async def _active_job_ids_for_candidate_profile(
        self, *, session, candidate_profile_id: uuid.UUID
    ) -> Set[uuid.UUID]:
        """
        applications(candidate_id = candidate_profiles.id)
          -> interview_sessions(status='active')
          -> applications.job_id
        """
        stmt = (
            select(distinct(ApplicationModel.job_id))
            .join(InterviewSessionModel, InterviewSessionModel.application_id == ApplicationModel.id)
            .where(
                ApplicationModel.candidate_id == candidate_profile_id,
                InterviewSessionModel.status == "active",  # or SessionStatus.active.value
            )
        )
        res = await session.execute(stmt)
        return set(res.scalars().all())

    async def _resume_ref_for_profile(
        self,
        *,
        session,
        resume_asset_id: Optional[uuid.UUID],
    ) -> Optional[ResumeRef]:
        if not resume_asset_id:
            return None

        stmt = select(MediaAssetModel).where(MediaAssetModel.id == resume_asset_id)
        res = await session.execute(stmt)
        asset = res.scalar_one_or_none()
        if not asset:
            return None

        # Map MediaAsset -> ResumeRef
        # Using `uri` as storage_key (works if uri is your storage key / path)
        uri = asset.uri
        filename = (uri.split("/")[-1] if uri else "resume")

        return ResumeRef(
            storage_key=uri,
            filename=filename,
            uploaded_at=asset.created_at,
            content_type=asset.content_type or "application/pdf",
        )

    

    # ── Mapping: domain → row ───

    @staticmethod
    def _to_domain(
        profile: CandidateProfileModel,
        active_job_ids: Set[uuid.UUID],
        resume_ref: Optional[ResumeRef],
    ) -> Candidate:
        u = profile.user

        # TODO: plug phone/website fields to user.
        phone = getattr(u, "phone", None)
        linkedin_url = getattr(u, "linkedin_url", None) or getattr(u, "website_url", None)

        contact = ContactInfo(
            email=u.email,
            phone=phone,
            linkedin_url=linkedin_url,
        )

        full_name = u.display_name or u.email.split("@")[0]

        # CandidateStatus derived from user.is_active (or always ACTIVE)
        status = CandidateStatus.ACTIVE if getattr(u, "is_active", True) else CandidateStatus.BANNED

        return Candidate(
            candidate_id=profile.id,
            user_id=profile.user_id,
            headline=profile.headline,
            bio=profile.bio,
            location=profile.location,
            full_name=full_name,
            contact=contact,
            status=status,
            resume=resume_ref,
            active_interview_job_ids=active_job_ids,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    @staticmethod
    def _to_view(profile: CandidateProfileModel, active_job_ids: list[uuid.UUID]) -> Candidate:
        u = profile.user

        # TODO: plug phone/website fields, plug them here.
        phone = getattr(u, "phone", None)
        website = getattr(u, "website_url", None)

        return Candidate(
            id=profile.id,
            user_id=profile.user_id,
            full_name=u.display_name,
            contact=ContactInfo(
                email=u.email,
                phone=phone,
                website=website,
            ),
            headline=profile.headline,
            bio=profile.bio,
            location=profile.location,
            years_experience=profile.years_experience,
            skills=profile.skills or [],
            resume=profile.resume_asset_id,
            active_interview_job_ids=active_job_ids,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    @staticmethod
    def _to_row(candidate: Candidate) -> dict:
        c = candidate.contact
        resume = None
        if candidate.resume:
            r = candidate.resume
            resume = {
                "storage_key":  r.storage_key,
                "filename":     r.filename,
                "uploaded_at":  r.uploaded_at.isoformat(),
                "content_type": r.content_type,
            }
        return {
            "id":        candidate.id,
            "full_name": candidate.full_name,
            "status":    candidate.status.value,
            "contact": {
                "email":        c.email,
                "phone":        c.phone,
                "linkedin_url": c.linkedin_url,
            },
            "resume": resume,
            # Store as list of UUID strings for JSONB compatibility
            "active_interview_job_ids": [
                str(job_id)
                for job_id in candidate._active_interview_job_ids
            ],
            "created_at": candidate.created_at,
            "updated_at": candidate.updated_at,
        }

