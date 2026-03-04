from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandidateStatus(str, Enum):
    """Lifecycle of a candidate within the platform."""
    ACTIVE = "active"
    BANNED = "banned"       # blocked from creating new sessions
    WITHDRAWN = "withdrawn" # self-requested removal


@dataclass(frozen=True)
class ContactInfo:
    """Value object — equality by value, not identity."""
    email: str
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.email or "@" not in self.email:
            raise ValueError(f"Invalid email address: {self.email!r}")


@dataclass(frozen=True)
class ResumeRef:
    """
    Points to a stored resume artifact; does NOT hold the file itself.
    Storage is owned by truefit_infra.StoragePort.
    """
    storage_key: str      # e.g. "resumes/<candidate_id>/<filename>"
    filename: str
    uploaded_at: datetime
    content_type: str = "application/pdf"


class Candidate:
    """
    Aggregate root representing a job-seeker on the platform.

    Invariants enforced:
    - A candidate can only have ONE active interview per job at a time.
    - Banned candidates cannot start new interview sessions.
    - Contact info and profile can be updated freely while ACTIVE.
    """

    def __init__(
        self,
        *,
        contact: ContactInfo,
        full_name: str,
        candidate_id: Optional[uuid.UUID] = None,
        status: CandidateStatus = CandidateStatus.ACTIVE,
        user_id: Optional[uuid.UUID] = None, # For linking to a User account if needed in the future
        headline: Optional[str] = None,
        bio: Optional[str] = None,
        location: Optional[str] = None,
        skills: Optional[list[str]] = None,
        resume: Optional[ResumeRef] = None,
        # Set of job IDs the candidate currently has an active interview for.
        # Kept here (not on Interview) so the invariant can be checked without
        # a DB round-trip in the domain layer.
        active_interview_job_ids: Optional[set[uuid.UUID]] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> None:
        if not full_name.strip():
            raise ValueError("Candidate full name cannot be empty")

        self._id: uuid.UUID = candidate_id or uuid.uuid4()
        self._full_name: str = full_name.strip()
        self._contact: ContactInfo = contact
        self._status: CandidateStatus = status
        self._user_id: Optional[uuid.UUID] = user_id
        self._headline: Optional[str] = headline
        self._bio: Optional[str] = bio
        self._location: Optional[str] = location
        self._skills: list[str] = skills or []
        self._resume: Optional[ResumeRef] = resume
        self._active_interview_job_ids: set[uuid.UUID] = (
            set(active_interview_job_ids) if active_interview_job_ids else set()
        )
        self._created_at: datetime = created_at or _utcnow()
        self._updated_at: datetime = updated_at or _utcnow()

    # ── Identity ───

    @property
    def id(self) -> uuid.UUID:
        return self._id

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
    def resume(self) -> Optional[ResumeRef]:
        return self._resume

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    # ── Queries ─

    @property
    def is_eligible_to_interview(self) -> bool:
        return self._status == CandidateStatus.ACTIVE

    def has_active_interview_for(self, job_id: uuid.UUID) -> bool:
        return job_id in self._active_interview_job_ids

    # ── Commands ──

    def update_profile(
        self,
        *,
        full_name: Optional[str] = None,
        contact: Optional[ContactInfo] = None,
    ) -> None:
        self._assert_active()
        if full_name is not None:
            if not full_name.strip():
                raise ValueError("full_name cannot be empty")
            self._full_name = full_name.strip()
        if contact is not None:
            self._contact = contact
        self._touch()

    def attach_resume(self, resume: ResumeRef) -> None:
        self._assert_active()
        self._resume = resume
        self._touch()

    def remove_resume(self) -> None:
        self._assert_active()
        self._resume = None
        self._touch()

    def ban(self, *, reason: str) -> None:  # noqa: ARG002  reason logged upstream
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

    # ── Interview tracking (called by InterviewStarted / InterviewEnded events)

    def register_active_interview(self, job_id: uuid.UUID) -> None:
        """
        Called when an interview session is created.
        Enforces the one-active-interview-per-job invariant.
        """
        self._assert_active()
        if self.has_active_interview_for(job_id):
            raise ValueError(
                f"Candidate already has an active interview for job {job_id}"
            )
        self._active_interview_job_ids.add(job_id)
        self._touch()

    def release_active_interview(self, job_id: uuid.UUID) -> None:
        """Called when an interview is completed or abandoned."""
        self._active_interview_job_ids.discard(job_id)
        self._touch()

    # ── Assertions ───

    def assert_eligible_to_interview(self) -> None:
        if not self.is_eligible_to_interview:
            raise PermissionError(
                f"Candidate '{self._full_name}' is not eligible to interview "
                f"(status={self._status.value})"
            )

    # ── Internal helpers ──

    def _assert_active(self) -> None:
        if self._status != CandidateStatus.ACTIVE:
            raise PermissionError(
                f"Cannot modify candidate in status '{self._status.value}'"
            )

    def _touch(self) -> None:
        self._updated_at = _utcnow()

    # ── Representation ───

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