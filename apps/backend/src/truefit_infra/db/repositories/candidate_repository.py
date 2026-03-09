from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Set

from sqlalchemy import distinct, func, select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
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

    # ── Write ─────────────────────────────────────────────────────────────────

    async def save(self, candidate: Candidate) -> None:
        """
        Only persists columns that exist on candidate_profiles.
        full_name / status / contact live on `users` — not touched here.
        active_interview_job_ids is derived at read-time via joins — not stored.
        resume is stored as resume_asset_id FK — update only if a ResumeRef exists.
        """
        data = self._to_row(candidate)
        insert_stmt = pg_insert(CandidateProfileModel).values(**data)
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "headline":         insert_stmt.excluded.headline,
                "bio":              insert_stmt.excluded.bio,
                "location":         insert_stmt.excluded.location,
                "years_experience": insert_stmt.excluded.years_experience,
                "skills":           insert_stmt.excluded.skills,
                "resume_asset_id":  insert_stmt.excluded.resume_asset_id,
                "updated_at":       insert_stmt.excluded.updated_at,
            },
        )
        async with self._db.get_session() as session:
            await session.execute(stmt)

    # ── Read ──────────────────────────────────────────────────────────────────

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

    # ── Private helpers ───────────────────────────────────────────────────────

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

    # ── Mappers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _to_row(candidate: Candidate) -> dict:
        """
        Maps only to candidate_profiles columns.
        Derived/user fields are intentionally excluded.
        """
        return {
            "id":               candidate.id,
            "user_id":          candidate.user_id,
            "headline":         getattr(candidate, "headline", None),
            "bio":              getattr(candidate, "bio", None),
            "location":         getattr(candidate, "location", None),
            "years_experience": getattr(candidate, "years_experience", None),
            "skills":           list(getattr(candidate, "skills", []) or []),
            # resume_asset_id: only set if domain model carries it directly
            # (ResumeRef is resolved via MediaAsset at read-time)
            "resume_asset_id":  getattr(candidate, "resume_asset_id", None),
            "updated_at":       datetime.now(timezone.utc),
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
            linkedin_url=getattr(u, "linkedin_url", None) or getattr(u, "website_url", None),
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

# """
# SQLAlchemy implementation of CandidateRepository.

# Mapping layers
# ──────────────
# _to_full_row(user_id, candidate)  Candidate domain object  →  full dict for initial INSERT
# _to_update_row(candidate)         Candidate domain object  →  partial dict for upsert
# _to_domain(profile, user, ...)    CandidateProfile + User rows → Candidate aggregate

# The Candidate aggregate spans two DB tables:

#   Domain field                  DB source
#   ──────────────────────────────────────────────────────────────────────────
#   id                            candidate_profiles.id
#   full_name                     users.display_name
#   contact.email                 users.email
#   contact.phone                 (None — no dedicated column yet; extend via migration)
#   contact.linkedin_url          (None — no dedicated column yet; extend via migration)
#   status                        users.is_active  →  ACTIVE / BANNED
#   resume.storage_key            media_assets.uri  (via resume_asset_id FK)
#   resume.filename               media_assets.uri  (last path segment)
#   resume.content_type           media_assets.content_type
#   resume.uploaded_at            media_assets.created_at
#   active_interview_job_ids      derived: applications + open interview_sessions
#   created_at                    candidate_profiles.created_at
#   updated_at                    candidate_profiles.updated_at

# Design note — user_id gap
# ─────────────────────────
# The abstract port's save(candidate) signature does not carry a user_id.
# Because CandidateProfile.user_id is a non-nullable FK, initial profile creation
# MUST know which user owns it.  Two strategies are therefore supported:

#   1. create_for_user(user_id, candidate)  — use this at registration time
#      AFTER the User row already exists (created by the auth adapter / Firebase sync).

#   2. save(candidate)                      — use this for all subsequent mutations
#      (update_profile, attach_resume, status changes).  On conflict-do-update
#      it never overwrites user_id, so the FK value set during creation is preserved.
# """

# from __future__ import annotations

# import uuid
# from datetime import timezone
# from typing import Optional

# from sqlalchemy import delete, func, select
# from sqlalchemy.dialects.postgresql import insert as pg_insert

# from src.truefit_core.application.ports import CandidateRepository
# from src.truefit_core.domain.candidate import (
#     Candidate,
#     CandidateStatus,
#     ContactInfo,
#     ResumeRef,
# )
# from src.truefit_infra.db.database import DatabaseManager
# from src.truefit_infra.db.models import (
#     Application,
#     CandidateProfile,
#     InterviewSession,
#     MediaAsset,
#     SessionStatus,
#     User,
# )


# class SQLAlchemyCandidateRepository(CandidateRepository):
#     """
#     Concrete implementation of the CandidateRepository port.

#     Reads join across candidate_profiles ⟵ users (email / display_name).
#     Writes only to candidate_profiles; the User row is owned by auth infrastructure.
#     """

#     def __init__(self, db: DatabaseManager) -> None:
#         self._db = db

#     # ── CandidateRepository interface ─────────────────────────────────────

#     async def save(self, candidate: Candidate) -> None:
#         """
#         Upsert the candidate profile (mutable fields only).

#         Safe to call on any existing profile.
#         Mutable fields updated on conflict: updated_at (and future profile fields).
#         Immutable fields (user_id, created_at) are never overwritten.

#         NOTE: For initial profile creation use create_for_user() which accepts
#         a user_id. This method uses candidate.id as a placeholder for user_id
#         in the VALUES clause, but that placeholder is never applied on conflict.
#         """
#         data = self._to_update_row(candidate)

#         stmt = (
#             pg_insert(CandidateProfile)
#             .values(**data)
#             .on_conflict_do_update(
#                 index_elements=["id"],
#                 set_={
#                     "headline":         data["headline"],
#                     "bio":              data["bio"],
#                     "location":         data["location"],
#                     "years_experience": data["years_experience"],
#                     "skills":           data["skills"],
#                     "updated_at":       data["updated_at"],
#                 },
#             )
#         )

#         async with self._db.get_session() as session:
#             await session.execute(stmt)

#     async def get_by_id(
#         self,
#         candidate_id: uuid.UUID,
#         *,
#         load_active_interviews: bool = True,
#     ) -> Optional[Candidate]:
#         """
#         Fetch a Candidate by its profile UUID.

#         :param load_active_interviews: When True (default) materialises the
#             active_interview_job_ids set via a sub-query. Pass False for
#             lightweight reads that don't need that data.
#         """
#         stmt = (
#             select(CandidateProfile, User)
#             .join(User, CandidateProfile.user_id == User.id)
#             .where(CandidateProfile.id == candidate_id)
#         )

#         async with self._db.get_session() as session:
#             result = await session.execute(stmt)
#             row = result.first()
#             if row is None:
#                 return None
#             profile, user = row

#             resume = await self._load_resume(session, profile.resume_asset_id)
#             active_job_ids = (
#                 await self._load_active_interview_job_ids(session, candidate_id)
#                 if load_active_interviews
#                 else set()
#             )

#         return self._to_domain(
#             profile, user,
#             resume=resume,
#             active_interview_job_ids=active_job_ids,
#         )

#     async def get_by_email(
#         self,
#         email: str,
#         *,
#         load_active_interviews: bool = True,
#     ) -> Optional[Candidate]:
#         """
#         Fetch a Candidate whose linked User has the given email.
#         Email uniqueness is enforced by the DB (users.email unique constraint).
#         """
#         stmt = (
#             select(CandidateProfile, User)
#             .join(User, CandidateProfile.user_id == User.id)
#             .where(User.email == email)
#         )

#         async with self._db.get_session() as session:
#             result = await session.execute(stmt)
#             row = result.first()
#             if row is None:
#                 return None
#             profile, user = row

#             resume = await self._load_resume(session, profile.resume_asset_id)
#             active_job_ids = (
#                 await self._load_active_interview_job_ids(session, profile.id)
#                 if load_active_interviews
#                 else set()
#             )

#         return self._to_domain(
#             profile, user,
#             resume=resume,
#             active_interview_job_ids=active_job_ids,
#         )

#     async def delete(self, candidate_id: uuid.UUID) -> None:
#         """
#         Hard-delete the CandidateProfile row.
#         The User row is NOT deleted here — that is an auth/account concern.
#         Applications and sessions cascade-delete via their FK constraints.
#         """
#         stmt = delete(CandidateProfile).where(CandidateProfile.id == candidate_id)

#         async with self._db.get_session() as session:
#             await session.execute(stmt)

#     # ── Extended methods (beyond abstract port) ───────────────────────────

#     async def create_for_user(
#         self,
#         user_id: uuid.UUID,
#         candidate: Candidate,
#     ) -> None:
#         """
#         Insert a new CandidateProfile row linked to an existing User.

#         Use this at registration time — AFTER the User row already exists in
#         the users table (created by the auth adapter / Firebase sync).

#         Idempotent: if a profile for this candidate.id already exists the
#         insert is a no-op (on_conflict_do_nothing).
#         """
#         data = self._to_full_row(user_id=user_id, candidate=candidate)

#         stmt = (
#             pg_insert(CandidateProfile)
#             .values(**data)
#             .on_conflict_do_nothing(index_elements=["id"])
#         )

#         async with self._db.get_session() as session:
#             await session.execute(stmt)

#     async def list_by_status(
#         self,
#         status: CandidateStatus,
#         *,
#         limit: int = 50,
#         offset: int = 0,
#     ) -> list[Candidate]:
#         """
#         List candidates filtered by their effective status.

#         ACTIVE    → User.is_active = True
#         BANNED    → User.is_active = False
#         WITHDRAWN → Returns empty list (managed as soft-delete at the app layer).
#         """
#         if status == CandidateStatus.WITHDRAWN:
#             return []

#         is_active_flag = status == CandidateStatus.ACTIVE

#         stmt = (
#             select(CandidateProfile, User)
#             .join(User, CandidateProfile.user_id == User.id)
#             .where(User.is_active == is_active_flag)
#             .order_by(CandidateProfile.created_at.desc())
#             .limit(limit)
#             .offset(offset)
#         )

#         async with self._db.get_session() as session:
#             result = await session.execute(stmt)
#             rows = result.all()

#         return [
#             self._to_domain(profile, user, resume=None, active_interview_job_ids=set())
#             for profile, user in rows
#         ]

#     async def count(self, *, status: Optional[CandidateStatus] = None) -> int:
#         """Count candidate profiles, optionally filtered by status."""
#         stmt = (
#             select(func.count())
#             .select_from(CandidateProfile)
#             .join(User, CandidateProfile.user_id == User.id)
#         )
#         if status == CandidateStatus.ACTIVE:
#             stmt = stmt.where(User.is_active == True)   # noqa: E712
#         elif status == CandidateStatus.BANNED:
#             stmt = stmt.where(User.is_active == False)  # noqa: E712

#         async with self._db.get_session() as session:
#             result = await session.execute(stmt)
#             return result.scalar_one()

#     async def exists(self, candidate_id: uuid.UUID) -> bool:
#         """Check if a CandidateProfile row exists for the given UUID."""
#         stmt = (
#             select(func.count())
#             .select_from(CandidateProfile)
#             .where(CandidateProfile.id == candidate_id)
#         )

#         async with self._db.get_session() as session:
#             result = await session.execute(stmt)
#             return result.scalar_one() > 0

#     # ── Private helpers ───────────────────────────────────────────────────

#     @staticmethod
#     async def _load_resume(
#         session,
#         resume_asset_id: Optional[uuid.UUID],
#     ) -> Optional[ResumeRef]:
#         """Fetch the MediaAsset for the resume and reconstruct a ResumeRef."""
#         if resume_asset_id is None:
#             return None

#         result = await session.execute(
#             select(MediaAsset).where(MediaAsset.id == resume_asset_id)
#         )
#         asset = result.scalar_one_or_none()
#         if asset is None:
#             return None

#         filename = asset.uri.split("/")[-1] if asset.uri else "resume"
#         uploaded_at = asset.created_at
#         if uploaded_at.tzinfo is None:
#             uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)

#         return ResumeRef(
#             storage_key=asset.uri,
#             filename=filename,
#             uploaded_at=uploaded_at,
#             content_type=asset.content_type or "application/pdf",
#         )

#     @staticmethod
#     async def _load_active_interview_job_ids(
#         session,
#         candidate_id: uuid.UUID,
#     ) -> set[uuid.UUID]:
#         """
#         Derive the set of job IDs for which this candidate has an active
#         interview session (status in {created, active}).

#         Query path: candidate_profiles → applications → interview_sessions
#         """
#         active_statuses = {SessionStatus.created.value, SessionStatus.active.value}

#         stmt = (
#             select(Application.job_id)
#             .join(InterviewSession, InterviewSession.application_id == Application.id)
#             .where(
#                 Application.candidate_id == candidate_id,
#                 InterviewSession.status.in_(active_statuses),
#             )
#         )
#         result = await session.execute(stmt)
#         return {row[0] for row in result.all()}

#     # ── Mapping: domain → DB row ──────────────────────────────────────────

#     @staticmethod
#     def _to_full_row(*, user_id: uuid.UUID, candidate: Candidate) -> dict:
#         """
#         Full row dict for initial INSERT (includes user_id and created_at).
#         Used exclusively by create_for_user().
#         """
#         return {
#             "id":               candidate.id,
#             "user_id":          user_id,
#             "headline":         None,
#             "bio":              None,
#             "location":         None,
#             "years_experience": None,
#             "skills":           [],
#             "created_at":       candidate.created_at,
#             "updated_at":       candidate.updated_at,
#         }

#     @staticmethod
#     def _to_update_row(candidate: Candidate) -> dict:
#         """
#         Partial row dict for upsert via save().

#         user_id uses candidate.id as a placeholder value — it is required in
#         the VALUES clause by SQLAlchemy but is excluded from the SET clause in
#         on_conflict_do_update, so the real FK stored by create_for_user() is
#         always preserved.
#         """
#         return {
#             "id":               candidate.id,
#             "user_id":          candidate.id,   # placeholder; excluded from conflict update
#             "headline":         None,
#             "bio":              None,
#             "location":         None,
#             "years_experience": None,
#             "skills":           [],
#             "created_at":       candidate.created_at,
#             "updated_at":       candidate.updated_at,
#         }

#     # ── Mapping: DB rows → domain ─────────────────────────────────────────

#     @staticmethod
#     def _to_domain(
#         profile: CandidateProfile,
#         user: User,
#         *,
#         resume: Optional[ResumeRef],
#         active_interview_job_ids: set[uuid.UUID],
#     ) -> Candidate:
#         """
#         Reconstruct a fully valid Candidate aggregate from a joined
#         (CandidateProfile, User) row.

#         Status mapping:
#             User.is_active = True  → CandidateStatus.ACTIVE
#             User.is_active = False → CandidateStatus.BANNED
#             (WITHDRAWN is soft-state managed at the application layer.)

#         Timestamps are coerced to UTC-aware datetimes if the DB returns naive values.
#         """
#         def _tz(dt):
#             if dt is not None and dt.tzinfo is None:
#                 return dt.replace(tzinfo=timezone.utc)
#             return dt

#         status = CandidateStatus.ACTIVE if user.is_active else CandidateStatus.BANNED

#         contact = ContactInfo(
#             email=user.email,
#             phone=None,        # extend when a contact_meta JSONB column is added
#             linkedin_url=None, # extend when a contact_meta JSONB column is added
#         )

#         return Candidate(
#             candidate_id=profile.id,
#             full_name=user.display_name or "",
#             contact=contact,
#             status=status,
#             resume=resume,
#             active_interview_job_ids=active_interview_job_ids,
#             created_at=_tz(profile.created_at),
#             updated_at=_tz(profile.updated_at),
#         )
