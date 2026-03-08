from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandidateStatus(str, Enum):
    ACTIVE = "active"
    BANNED = "banned"
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True)
class ContactInfo:
    email: str
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.email or "@" not in self.email:
            raise ValueError(f"Invalid email address: {self.email!r}")


@dataclass(frozen=True)
class ResumeRef:
    storage_key: str
    filename: str
    uploaded_at: datetime
    content_type: str = "application/pdf"


class Candidate:
    """
    Aggregate root representing a job-seeker on the platform.

    Schema source of truth: candidate_profiles table
    ─────────────────────────────────────────────────
    id               uuid
    user_id          uuid (FK users.id)
    headline         varchar(255)
    bio              text
    location         varchar(255)
    years_experience integer
    skills           text[]
    resume_asset_id  uuid (FK media_assets.id)
    created_at       timestamptz
    updated_at       timestamptz

    Derived at read-time (not persisted on candidate_profiles):
    - full_name           ← users.display_name
    - contact             ← users.email + optional phone/linkedin
    - status              ← users.is_active
    - active_interview_job_ids ← join interview_sessions + applications
    - resume              ← ResumeRef resolved from media_assets
    """

    def __init__(
        self,
        *,
        contact: ContactInfo,
        full_name: str,
        candidate_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
        status: CandidateStatus = CandidateStatus.ACTIVE,
        headline: Optional[str] = None,
        bio: Optional[str] = None,
        location: Optional[str] = None,
        years_experience: Optional[int] = None,
        skills: Optional[list[str]] = None,
        resume: Optional[ResumeRef] = None,
        resume_asset_id: Optional[uuid.UUID] = None,
        active_interview_job_ids: Optional[set[uuid.UUID]] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> None:
        if not full_name.strip():
            raise ValueError("Candidate full name cannot be empty")

        self._id: uuid.UUID = candidate_id or uuid.uuid4()
        self._user_id: Optional[uuid.UUID] = user_id
        self._full_name: str = full_name.strip()
        self._contact: ContactInfo = contact
        self._status: CandidateStatus = status
        self._headline: Optional[str] = headline
        self._bio: Optional[str] = bio
        self._location: Optional[str] = location
        self._years_experience: Optional[int] = years_experience
        self._skills: list[str] = list(skills or [])
        self._resume: Optional[ResumeRef] = resume
        self._resume_asset_id: Optional[uuid.UUID] = resume_asset_id
        self._active_interview_job_ids: set[uuid.UUID] = (
            set(active_interview_job_ids) if active_interview_job_ids else set()
        )
        self._created_at: datetime = created_at or _utcnow()
        self._updated_at: datetime = updated_at or _utcnow()

    # ── Identity / properties ──────────────────────────────────────────────

    @property
    def id(self) -> uuid.UUID:
        return self._id

    @property
    def user_id(self) -> Optional[uuid.UUID]:
        return self._user_id

    @property
    def full_name(self) -> str:
        return self._full_name

    @property
    def contact(self) -> ContactInfo:
        return self._contact

    @property
    def status(self) -> CandidateStatus:
        return self._status

    @property
    def headline(self) -> Optional[str]:
        return self._headline

    @property
    def bio(self) -> Optional[str]:
        return self._bio

    @property
    def location(self) -> Optional[str]:
        return self._location

    @property
    def years_experience(self) -> Optional[int]:
        return self._years_experience

    @property
    def skills(self) -> list[str]:
        return list(self._skills)

    @property
    def resume(self) -> Optional[ResumeRef]:
        return self._resume

    @property
    def resume_asset_id(self) -> Optional[uuid.UUID]:
        return self._resume_asset_id

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    # ── Queries ───────────────────────────────────────────────────────────

    @property
    def is_eligible_to_interview(self) -> bool:
        return self._status == CandidateStatus.ACTIVE

    def has_active_interview_for(self, job_id: uuid.UUID) -> bool:
        return job_id in self._active_interview_job_ids

    # ── Commands ──────────────────────────────────────────────────────────

    def update_profile(
        self,
        *,
        full_name: Optional[str] = None,
        contact: Optional[ContactInfo] = None,
        headline: Optional[str] = None,
        bio: Optional[str] = None,
        location: Optional[str] = None,
        years_experience: Optional[int] = None,
        skills: Optional[list[str]] = None,
    ) -> None:
        self._assert_active()
        if full_name is not None:
            if not full_name.strip():
                raise ValueError("full_name cannot be empty")
            self._full_name = full_name.strip()
        if contact is not None:
            self._contact = contact
        if headline is not None:
            self._headline = headline
        if bio is not None:
            self._bio = bio
        if location is not None:
            self._location = location
        if years_experience is not None:
            self._years_experience = years_experience
        if skills is not None:
            self._skills = list(skills)
        self._touch()

    def attach_resume(self, resume: ResumeRef, resume_asset_id: uuid.UUID) -> None:
        self._assert_active()
        self._resume = resume
        self._resume_asset_id = resume_asset_id
        self._touch()

    def remove_resume(self) -> None:
        self._assert_active()
        self._resume = None
        self._resume_asset_id = None
        self._touch()

    def ban(self, *, reason: str) -> None:
        if self._status == CandidateStatus.BANNED:
            raise ValueError("Candidate is already banned")
        self._status = CandidateStatus.BANNED
        self._touch()

    def withdraw(self) -> None:
        if self._status == CandidateStatus.WITHDRAWN:
            raise ValueError("Candidate has already withdrawn")
        self._status = CandidateStatus.WITHDRAWN
        self._active_interview_job_ids.clear()
        self._touch()

    def register_active_interview(self, job_id: uuid.UUID) -> None:
        self._assert_active()
        if self.has_active_interview_for(job_id):
            raise ValueError(
                f"Candidate already has an active interview for job {job_id}"
            )
        self._active_interview_job_ids.add(job_id)
        self._touch()

    def release_active_interview(self, job_id: uuid.UUID) -> None:
        self._active_interview_job_ids.discard(job_id)
        self._touch()

    # ── Assertions ────────────────────────────────────────────────────────

    def assert_eligible_to_interview(self) -> None:
        if not self.is_eligible_to_interview:
            raise PermissionError(
                f"Candidate '{self._full_name}' is not eligible to interview "
                f"(status={self._status.value})"
            )

    # ── Internal ──────────────────────────────────────────────────────────

    def _assert_active(self) -> None:
        if self._status != CandidateStatus.ACTIVE:
            raise PermissionError(
                f"Cannot modify candidate in status '{self._status.value}'"
            )

    def _touch(self) -> None:
        self._updated_at = _utcnow()

    def __repr__(self) -> str:
        return (
            f"Candidate(id={self._id}, name={self._full_name!r}, "
            f"status={self._status.value})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Candidate):
            return NotImplemented
        return self._id == other._id

    def __hash__(self) -> int:
        return hash(self._id)