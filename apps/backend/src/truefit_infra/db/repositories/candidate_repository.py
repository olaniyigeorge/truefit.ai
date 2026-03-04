"""
SQLAlchemy implementation of CandidateRepository.

Mapping layers
──────────────
_to_full_row(user_id, candidate)  Candidate domain object  →  full dict for initial INSERT
_to_update_row(candidate)         Candidate domain object  →  partial dict for upsert
_to_domain(profile, user, ...)    CandidateProfile + User rows → Candidate aggregate

The Candidate aggregate spans two DB tables:

  Domain field                  DB source
  ──────────────────────────────────────────────────────────────────────────
  id                            candidate_profiles.id
  full_name                     users.display_name
  contact.email                 users.email
  contact.phone                 (None — no dedicated column yet; extend via migration)
  contact.linkedin_url          (None — no dedicated column yet; extend via migration)
  status                        users.is_active  →  ACTIVE / BANNED
  resume.storage_key            media_assets.uri  (via resume_asset_id FK)
  resume.filename               media_assets.uri  (last path segment)
  resume.content_type           media_assets.content_type
  resume.uploaded_at            media_assets.created_at
  active_interview_job_ids      derived: applications + open interview_sessions
  created_at                    candidate_profiles.created_at
  updated_at                    candidate_profiles.updated_at

Design note — user_id gap
─────────────────────────
The abstract port's save(candidate) signature does not carry a user_id.
Because CandidateProfile.user_id is a non-nullable FK, initial profile creation
MUST know which user owns it.  Two strategies are therefore supported:

  1. create_for_user(user_id, candidate)  — use this at registration time
     AFTER the User row already exists (created by the auth adapter / Firebase sync).

  2. save(candidate)                      — use this for all subsequent mutations
     (update_profile, attach_resume, status changes).  On conflict-do-update
     it never overwrites user_id, so the FK value set during creation is preserved.
"""

from __future__ import annotations

import uuid
from datetime import timezone
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.truefit_core.application.ports import CandidateRepository
from src.truefit_core.domain.candidate import (
    Candidate,
    CandidateStatus,
    ContactInfo,
    ResumeRef,
)
from src.truefit_infra.db.database import DatabaseManager
from src.truefit_infra.db.models import (
    Application,
    CandidateProfile,
    InterviewSession,
    MediaAsset,
    SessionStatus,
    User,
)


class SQLAlchemyCandidateRepository(CandidateRepository):
    """
    Concrete implementation of the CandidateRepository port.

    Reads join across candidate_profiles ⟵ users (email / display_name).
    Writes only to candidate_profiles; the User row is owned by auth infrastructure.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # ── CandidateRepository interface ─────────────────────────────────────

    async def save(self, candidate: Candidate) -> None:
        """
        Upsert the candidate profile (mutable fields only).

        Safe to call on any existing profile.
        Mutable fields updated on conflict: updated_at (and future profile fields).
        Immutable fields (user_id, created_at) are never overwritten.

        NOTE: For initial profile creation use create_for_user() which accepts
        a user_id. This method uses candidate.id as a placeholder for user_id
        in the VALUES clause, but that placeholder is never applied on conflict.
        """
        data = self._to_update_row(candidate)

        stmt = (
            pg_insert(CandidateProfile)
            .values(**data)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "headline":         data["headline"],
                    "bio":              data["bio"],
                    "location":         data["location"],
                    "years_experience": data["years_experience"],
                    "skills":           data["skills"],
                    "updated_at":       data["updated_at"],
                },
            )
        )

        async with self._db.get_session() as session:
            await session.execute(stmt)

    async def get_by_id(
        self,
        candidate_id: uuid.UUID,
        *,
        load_active_interviews: bool = True,
    ) -> Optional[Candidate]:
        """
        Fetch a Candidate by its profile UUID.

        :param load_active_interviews: When True (default) materialises the
            active_interview_job_ids set via a sub-query. Pass False for
            lightweight reads that don't need that data.
        """
        stmt = (
            select(CandidateProfile, User)
            .join(User, CandidateProfile.user_id == User.id)
            .where(CandidateProfile.id == candidate_id)
        )

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            row = result.first()
            if row is None:
                return None
            profile, user = row

            resume = await self._load_resume(session, profile.resume_asset_id)
            active_job_ids = (
                await self._load_active_interview_job_ids(session, candidate_id)
                if load_active_interviews
                else set()
            )

        return self._to_domain(
            profile, user,
            resume=resume,
            active_interview_job_ids=active_job_ids,
        )

    async def get_by_email(
        self,
        email: str,
        *,
        load_active_interviews: bool = True,
    ) -> Optional[Candidate]:
        """
        Fetch a Candidate whose linked User has the given email.
        Email uniqueness is enforced by the DB (users.email unique constraint).
        """
        stmt = (
            select(CandidateProfile, User)
            .join(User, CandidateProfile.user_id == User.id)
            .where(User.email == email)
        )

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            row = result.first()
            if row is None:
                return None
            profile, user = row

            resume = await self._load_resume(session, profile.resume_asset_id)
            active_job_ids = (
                await self._load_active_interview_job_ids(session, profile.id)
                if load_active_interviews
                else set()
            )

        return self._to_domain(
            profile, user,
            resume=resume,
            active_interview_job_ids=active_job_ids,
        )

    async def delete(self, candidate_id: uuid.UUID) -> None:
        """
        Hard-delete the CandidateProfile row.
        The User row is NOT deleted here — that is an auth/account concern.
        Applications and sessions cascade-delete via their FK constraints.
        """
        stmt = delete(CandidateProfile).where(CandidateProfile.id == candidate_id)

        async with self._db.get_session() as session:
            await session.execute(stmt)

    # ── Extended methods (beyond abstract port) ───────────────────────────

    async def create_for_user(
        self,
        user_id: uuid.UUID,
        candidate: Candidate,
    ) -> None:
        """
        Insert a new CandidateProfile row linked to an existing User.

        Use this at registration time — AFTER the User row already exists in
        the users table (created by the auth adapter / Firebase sync).

        Idempotent: if a profile for this candidate.id already exists the
        insert is a no-op (on_conflict_do_nothing).
        """
        data = self._to_full_row(user_id=user_id, candidate=candidate)

        stmt = (
            pg_insert(CandidateProfile)
            .values(**data)
            .on_conflict_do_nothing(index_elements=["id"])
        )

        async with self._db.get_session() as session:
            await session.execute(stmt)

    async def list_by_status(
        self,
        status: CandidateStatus,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Candidate]:
        """
        List candidates filtered by their effective status.

        ACTIVE    → User.is_active = True
        BANNED    → User.is_active = False
        WITHDRAWN → Returns empty list (managed as soft-delete at the app layer).
        """
        if status == CandidateStatus.WITHDRAWN:
            return []

        is_active_flag = status == CandidateStatus.ACTIVE

        stmt = (
            select(CandidateProfile, User)
            .join(User, CandidateProfile.user_id == User.id)
            .where(User.is_active == is_active_flag)
            .order_by(CandidateProfile.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [
            self._to_domain(profile, user, resume=None, active_interview_job_ids=set())
            for profile, user in rows
        ]

    async def count(self, *, status: Optional[CandidateStatus] = None) -> int:
        """Count candidate profiles, optionally filtered by status."""
        stmt = (
            select(func.count())
            .select_from(CandidateProfile)
            .join(User, CandidateProfile.user_id == User.id)
        )
        if status == CandidateStatus.ACTIVE:
            stmt = stmt.where(User.is_active == True)   # noqa: E712
        elif status == CandidateStatus.BANNED:
            stmt = stmt.where(User.is_active == False)  # noqa: E712

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            return result.scalar_one()

    async def exists(self, candidate_id: uuid.UUID) -> bool:
        """Check if a CandidateProfile row exists for the given UUID."""
        stmt = (
            select(func.count())
            .select_from(CandidateProfile)
            .where(CandidateProfile.id == candidate_id)
        )

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            return result.scalar_one() > 0

    # ── Private helpers ───────────────────────────────────────────────────

    @staticmethod
    async def _load_resume(
        session,
        resume_asset_id: Optional[uuid.UUID],
    ) -> Optional[ResumeRef]:
        """Fetch the MediaAsset for the resume and reconstruct a ResumeRef."""
        if resume_asset_id is None:
            return None

        result = await session.execute(
            select(MediaAsset).where(MediaAsset.id == resume_asset_id)
        )
        asset = result.scalar_one_or_none()
        if asset is None:
            return None

        filename = asset.uri.split("/")[-1] if asset.uri else "resume"
        uploaded_at = asset.created_at
        if uploaded_at.tzinfo is None:
            uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)

        return ResumeRef(
            storage_key=asset.uri,
            filename=filename,
            uploaded_at=uploaded_at,
            content_type=asset.content_type or "application/pdf",
        )

    @staticmethod
    async def _load_active_interview_job_ids(
        session,
        candidate_id: uuid.UUID,
    ) -> set[uuid.UUID]:
        """
        Derive the set of job IDs for which this candidate has an active
        interview session (status in {created, active}).

        Query path: candidate_profiles → applications → interview_sessions
        """
        active_statuses = {SessionStatus.created.value, SessionStatus.active.value}

        stmt = (
            select(Application.job_id)
            .join(InterviewSession, InterviewSession.application_id == Application.id)
            .where(
                Application.candidate_id == candidate_id,
                InterviewSession.status.in_(active_statuses),
            )
        )
        result = await session.execute(stmt)
        return {row[0] for row in result.all()}

    # ── Mapping: domain → DB row ──────────────────────────────────────────

    @staticmethod
    def _to_full_row(*, user_id: uuid.UUID, candidate: Candidate) -> dict:
        """
        Full row dict for initial INSERT (includes user_id and created_at).
        Used exclusively by create_for_user().
        """
        return {
            "id":               candidate.id,
            "user_id":          user_id,
            "headline":         None,
            "bio":              None,
            "location":         None,
            "years_experience": None,
            "skills":           [],
            "created_at":       candidate.created_at,
            "updated_at":       candidate.updated_at,
        }

    @staticmethod
    def _to_update_row(candidate: Candidate) -> dict:
        """
        Partial row dict for upsert via save().

        user_id uses candidate.id as a placeholder value — it is required in
        the VALUES clause by SQLAlchemy but is excluded from the SET clause in
        on_conflict_do_update, so the real FK stored by create_for_user() is
        always preserved.
        """
        return {
            "id":               candidate.id,
            "user_id":          candidate.id,   # placeholder; excluded from conflict update
            "headline":         None,
            "bio":              None,
            "location":         None,
            "years_experience": None,
            "skills":           [],
            "created_at":       candidate.created_at,
            "updated_at":       candidate.updated_at,
        }

    # ── Mapping: DB rows → domain ─────────────────────────────────────────

    @staticmethod
    def _to_domain(
        profile: CandidateProfile,
        user: User,
        *,
        resume: Optional[ResumeRef],
        active_interview_job_ids: set[uuid.UUID],
    ) -> Candidate:
        """
        Reconstruct a fully valid Candidate aggregate from a joined
        (CandidateProfile, User) row.

        Status mapping:
            User.is_active = True  → CandidateStatus.ACTIVE
            User.is_active = False → CandidateStatus.BANNED
            (WITHDRAWN is soft-state managed at the application layer.)

        Timestamps are coerced to UTC-aware datetimes if the DB returns naive values.
        """
        def _tz(dt):
            if dt is not None and dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        status = CandidateStatus.ACTIVE if user.is_active else CandidateStatus.BANNED

        contact = ContactInfo(
            email=user.email,
            phone=None,        # extend when a contact_meta JSONB column is added
            linkedin_url=None, # extend when a contact_meta JSONB column is added
        )

        return Candidate(
            candidate_id=profile.id,
            full_name=user.display_name or "",
            contact=contact,
            status=status,
            resume=resume,
            active_interview_job_ids=active_interview_job_ids,
            created_at=_tz(profile.created_at),
            updated_at=_tz(profile.updated_at),
        )
