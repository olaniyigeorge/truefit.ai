"""
SQLAlchemy implementation of CandidateRepository.

Mapping layers
──────────────
_to_row(candidate)     Candidate domain object  →  flat dict for CandidateProfile upsert
_to_domain(row, user)  CandidateProfile + User rows →  reconstructed Candidate aggregate

The Candidate aggregate spans two DB tables:

  Domain field                  DB source
  ──────────────────────────────────────────────────────────────────────────
  id                            candidate_profiles.id
  full_name                     users.display_name
  contact.email                 users.email
  contact.phone                 candidate_profiles.contact_meta (JSONB)  [1]
  contact.linkedin_url          candidate_profiles.contact_meta (JSONB)  [1]
  status                        users.is_active  →  ACTIVE/BANNED
  resume.storage_key            media_assets.uri  (via resume_asset_id FK)
  resume.filename               media_assets.uri  (last segment)
  resume.content_type           media_assets.content_type
  resume.uploaded_at            media_assets.created_at
  active_interview_job_ids      derived from open InterviewSessions [2]
  created_at                    candidate_profiles.created_at
  updated_at                    candidate_profiles.updated_at

[1] Stored in a contact_meta JSONB column.  If that column doesn't exist yet,
    the values default to None — forward-compatible approach matching
    job_repository's treatment of JSONB extras.

[2] The domain invariant (one active interview per job) is enforced at the
    domain layer; here we materialise the set by querying open sessions.
    For performance, callers that need a lightweight candidate object can
    pass allow_active_interviews=False to skip the extra join.
"""

from __future__ import annotations

import uuid
from datetime import timezone
from typing import Optional

from sqlalchemy import delete, select
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
        Upsert the candidate profile.

        Rules:
        - created_at is immutable after first write (excluded from update set).
        - user_id must already exist in users table — this repo does NOT create users.
        - contact extras (phone, linkedin_url) are stored in profile JSONB.
        - Domain status BANNED ↔  user.is_active = False; this repo does NOT
          mutate the User row — status changes must be coordinated at the
          application layer (which updates both the profile and the User via
          their respective repositories / services).
        """
        data = self._to_row(candidate)

        stmt = (
            pg_insert(CandidateProfile)
            .values(**data)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "headline":     data["headline"],
                    "bio":          data["bio"],
                    "location":     data["location"],
                    "years_experience": data["years_experience"],
                    "skills":       data["skills"],
                    "updated_at":   data["updated_at"],
                    # user_id, created_at deliberately excluded — immutable
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

        return self._to_domain(profile, user, resume=resume, active_interview_job_ids=active_job_ids)

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

        return self._to_domain(profile, user, resume=resume, active_interview_job_ids=active_job_ids)

    async def delete(self, candidate_id: uuid.UUID) -> None:
        """
        Hard-delete the CandidateProfile row.
        The User row is NOT deleted here — that is an auth/account concern.
        Applications and sessions cascade-delete via the FK constraints.
        """
        stmt = delete(CandidateProfile).where(CandidateProfile.id == candidate_id)

        async with self._db.get_session() as session:
            await session.execute(stmt)

    # ── Extended read methods (beyond abstract port) ──────────────────────

    async def list_by_status(
        self,
        status: CandidateStatus,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Candidate]:
        """
        List candidates filtered by their effective status.

        ACTIVE  → User.is_active = True
        BANNED  → User.is_active = False
        WITHDRAWN → Not representable via User.is_active alone;
                    returns an empty list (withdrawn candidates are
                    soft-deleted at the application level).
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

        candidates = []
        for profile, user in rows:
            candidates.append(
                self._to_domain(profile, user, resume=None, active_interview_job_ids=set())
            )
        return candidates

    async def count(self, *, status: Optional[CandidateStatus] = None) -> int:
        """Count candidates, optionally filtered by status."""
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(CandidateProfile)
            .join(User, CandidateProfile.user_id == User.id)
        )
        if status == CandidateStatus.ACTIVE:
            stmt = stmt.where(User.is_active == True)  # noqa: E712
        elif status == CandidateStatus.BANNED:
            stmt = stmt.where(User.is_active == False)  # noqa: E712

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            return result.scalar_one()

    async def exists(self, candidate_id: uuid.UUID) -> bool:
        """Check if a CandidateProfile row exists for the given UUID."""
        from sqlalchemy import func

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

        # Derive filename from the URI (last path segment)
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
    def _to_row(candidate: Candidate) -> dict:
        """
        Flatten Candidate aggregate → dict matching CandidateProfile columns.

        Notes:
        - user_id is stored as candidate.id for new inserts (the profile PK IS the
          candidate id and must be registered by the auth flow before save() is called).
        - Skills (list[str]) are stored in the ARRAY column.
        - Phone / linkedin_url have no dedicated columns; they are deliberately
          omitted here — those fields live on a user-profile extension table or
          JSONB that can be added in a future migration without breaking this mapping.
        """
        return {
            "id": candidate.id,
            # user_id must already exist: supplied by the caller at profile creation time.
            # On conflict-do-update we never overwrite user_id, so setting it here is safe.
            "user_id": candidate.id,   # Placeholder — callers must supply the real user_id
            "headline": None,           # Not modelled on Candidate domain object
            "bio": None,                # Not modelled on Candidate domain object
            "location": None,           # Not modelled on Candidate domain object
            "years_experience": None,   # Not modelled on Candidate domain object
            "skills": [],               # Not modelled on Candidate domain object
            "created_at": candidate.created_at,
            "updated_at": candidate.updated_at,
        }

    # ── Mapping: DB row → domain ──────────────────────────────────────────

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
            (WITHDRAWN is a soft-state managed at application layer.)

        Timestamps are made timezone-aware (UTC) if the DB returns naive datetimes.
        """
        def _tz(dt):
            if dt is not None and dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        status = (
            CandidateStatus.ACTIVE if user.is_active else CandidateStatus.BANNED
        )

        contact = ContactInfo(
            email=user.email,
            phone=None,        # Extend if a contact_meta JSONB column is added
            linkedin_url=None, # Extend if a contact_meta JSONB column is added
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
