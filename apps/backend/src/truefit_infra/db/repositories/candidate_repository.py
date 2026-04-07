from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Set

from sqlalchemy import distinct, func, select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
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

    # Write

    async def save(self, candidate: Candidate) -> None:
        """
        Only persists columns that exist on candidate_profiles.
        full_name / status / contact live on `users` - not touched here.
        active_interview_job_ids is derived at read-time via joins - not stored.
        resume is stored as resume_asset_id FK - update only if a ResumeRef exists.
        """
        data = self._to_row(candidate)
        insert_stmt = pg_insert(CandidateProfileModel).values(**data)
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "headline": insert_stmt.excluded.headline,
                "bio": insert_stmt.excluded.bio,
                "location": insert_stmt.excluded.location,
                "years_experience": insert_stmt.excluded.years_experience,
                "skills": insert_stmt.excluded.skills,
                "resume_asset_id": insert_stmt.excluded.resume_asset_id,
                "updated_at": insert_stmt.excluded.updated_at,
            },
        )
        async with self._db.get_session() as session:
            await session.execute(stmt)

    # Read

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
                session=session, candidate_profile_id=profile.id
            )
            resume_ref = await self._resume_ref_for_profile(
                session=session, resume_asset_id=profile.resume_asset_id
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
                session=session, candidate_profile_id=profile.id
            )
            resume_ref = await self._resume_ref_for_profile(
                session=session, resume_asset_id=profile.resume_asset_id
            )
        return self._to_domain(profile, active_job_ids, resume_ref)

    async def list_all(self, *, limit: int = 50, offset: int = 0) -> list[Candidate]:
        stmt = (
            select(CandidateProfileModel)
            .join(UserModel, CandidateProfileModel.user_id == UserModel.id)
            .where(UserModel.role == "candidate")
            .options(joinedload(CandidateProfileModel.user))
            .order_by(CandidateProfileModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            profiles = result.scalars().all()
            # Batch: fetch active_job_ids for all profiles within same session
            candidates = []
            for profile in profiles:
                active_job_ids = await self._active_job_ids_for_candidate_profile(
                    session=session, candidate_profile_id=profile.id
                )
                resume_ref = await self._resume_ref_for_profile(
                    session=session, resume_asset_id=profile.resume_asset_id
                )
                candidates.append(self._to_domain(profile, active_job_ids, resume_ref))
        return candidates

    async def delete(self, candidate_id: uuid.UUID) -> None:
        stmt = delete(CandidateProfileModel).where(
            CandidateProfileModel.id == candidate_id
        )
        async with self._db.get_session() as session:
            await session.execute(stmt)

    async def count(self) -> int:
        stmt = select(func.count()).select_from(CandidateProfileModel)
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            return result.scalar_one()

    # Private helpers

    @staticmethod
    async def _active_job_ids_for_candidate_profile(
        *, session, candidate_profile_id: uuid.UUID
    ) -> Set[uuid.UUID]:
        stmt = (
            select(distinct(ApplicationModel.job_id))
            .join(
                InterviewSessionModel,
                InterviewSessionModel.application_id == ApplicationModel.id,
            )
            .where(
                ApplicationModel.candidate_id == candidate_profile_id,
                InterviewSessionModel.status == "active",
            )
        )
        res = await session.execute(stmt)
        return set(res.scalars().all())

    @staticmethod
    async def _resume_ref_for_profile(
        *, session, resume_asset_id: Optional[uuid.UUID]
    ) -> Optional[ResumeRef]:
        if not resume_asset_id:
            return None
        res = await session.execute(
            select(MediaAssetModel).where(MediaAssetModel.id == resume_asset_id)
        )
        asset = res.scalar_one_or_none()
        if not asset:
            return None
        uri = asset.uri or ""
        return ResumeRef(
            storage_key=uri,
            filename=uri.split("/")[-1] if uri else "resume",
            uploaded_at=asset.created_at,
            content_type=asset.content_type or "application/pdf",
        )

    # Mappers

    @staticmethod
    def _to_row(candidate: Candidate) -> dict:
        """
        Maps only to candidate_profiles columns.
        Derived/user fields are intentionally excluded.
        """
        return {
            "id": candidate.id,
            "user_id": candidate.user_id,
            "headline": getattr(candidate, "headline", None),
            "bio": getattr(candidate, "bio", None),
            "location": getattr(candidate, "location", None),
            "years_experience": getattr(candidate, "years_experience", None),
            "skills": list(getattr(candidate, "skills", []) or []),
            # resume_asset_id: only set if domain model carries it directly
            # (ResumeRef is resolved via MediaAsset at read-time)
            "resume_asset_id": getattr(candidate, "resume_asset_id", None),
            "updated_at": datetime.now(timezone.utc),
        }

    @staticmethod
    def _to_domain(
        profile: CandidateProfileModel,
        active_job_ids: Set[uuid.UUID],
        resume_ref: Optional[ResumeRef],
    ) -> Candidate:
        u = profile.user
        contact = ContactInfo(
            email=u.email,
            phone=getattr(u, "phone", None),
            linkedin_url=getattr(u, "linkedin_url", None)
            or getattr(u, "website_url", None),
        )
        status = (
            CandidateStatus.ACTIVE
            if getattr(u, "is_active", True)
            else CandidateStatus.BANNED
        )
        return Candidate(
            candidate_id=profile.id,
            user_id=profile.user_id,
            full_name=u.display_name or u.email.split("@")[0],
            headline=profile.headline,
            bio=profile.bio,
            location=profile.location,
            years_experience=profile.years_experience,
            skills=list(profile.skills or []),
            contact=contact,
            status=status,
            resume=resume_ref,
            active_interview_job_ids=active_job_ids,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )
