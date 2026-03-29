from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ApplicationStatus(str, Enum):
    new = "new"
    interviewing = "interviewing"
    shortlisted = "shortlisted"
    rejected = "rejected"
    hired = "hired"


class ApplicationSource(str, Enum):
    applied = "applied"
    invited = "invited"


class Application:
    """
    Aggregate root for a candidate's application to a job.

    Lifecycle:  new → interviewing → shortlisted → hired
                                   ↘ rejected

    Invariants:
    - A candidate can only have one application per job (enforced at DB level too).
    - Status transitions are explicit — no arbitrary status assignment.
    - meta is a free-form dict for recruiter notes, scores, tags etc.
    """

    def __init__(
        self,
        *,
        job_id: uuid.UUID,
        candidate_id: uuid.UUID,
        source: ApplicationSource = ApplicationSource.applied,
        status: ApplicationStatus = ApplicationStatus.new,
        meta: Optional[dict[str, Any]] = None,
        application_id: Optional[uuid.UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> None:
        self._id = application_id or uuid.uuid4()
        self._job_id = job_id
        self._candidate_id = candidate_id
        self._source = source
        self._status = status
        self._meta = dict(meta or {})
        self._created_at = created_at or _utcnow()
        self._updated_at = updated_at or _utcnow()

    # Identity 

    @property
    def id(self) -> uuid.UUID:
        return self._id

    @property
    def job_id(self) -> uuid.UUID:
        return self._job_id

    @property
    def candidate_id(self) -> uuid.UUID:
        return self._candidate_id

    @property
    def source(self) -> ApplicationSource:
        return self._source

    @property
    def status(self) -> ApplicationStatus:
        return self._status

    @property
    def meta(self) -> dict[str, Any]:
        return dict(self._meta)

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    # Queries 

    @property
    def is_active(self) -> bool:
        return self._status in (
            ApplicationStatus.new,
            ApplicationStatus.interviewing,
        )

    @property
    def is_closed(self) -> bool:
        return self._status in (
            ApplicationStatus.hired,
            ApplicationStatus.rejected,
        )

    # Commands 

    def mark_interviewing(self) -> None:
        if self._status != ApplicationStatus.new:
            raise ValueError(
                f"Can only move to interviewing from new, current: {self._status.value}"
            )
        self._status = ApplicationStatus.interviewing
        self._touch()

    def shortlist(self) -> None:
        if self._status not in (ApplicationStatus.new, ApplicationStatus.interviewing):
            raise ValueError(
                f"Cannot shortlist application in status: {self._status.value}"
            )
        self._status = ApplicationStatus.shortlisted
        self._touch()

    def reject(self) -> None:
        if self.is_closed:
            raise ValueError(
                f"Application already closed with status: {self._status.value}"
            )
        self._status = ApplicationStatus.rejected
        self._touch()

    def hire(self) -> None:
        if self._status != ApplicationStatus.shortlisted:
            raise ValueError(
                f"Can only hire from shortlisted, current: {self._status.value}"
            )
        self._status = ApplicationStatus.hired
        self._touch()

    def update_meta(self, updates: dict[str, Any]) -> None:
        """Merge updates into meta dict — does not replace, only adds/overwrites keys."""
        self._meta.update(updates)
        self._touch()

    def withdraw(self) -> None:
        """Candidate withdraws — treated as a rejection for pipeline purposes."""
        if self.is_closed:
            raise ValueError(
                f"Application already closed with status: {self._status.value}"
            )
        self._status = ApplicationStatus.rejected
        self._meta["withdrawn"] = True
        self._touch()

    # Assertions 

    def assert_eligible_for_interview(self) -> None:
        if self._status not in (ApplicationStatus.new, ApplicationStatus.interviewing):
            raise PermissionError(
                f"Application is not eligible for interview: {self._status.value}"
            )

    # Internals

    def _touch(self) -> None:
        self._updated_at = _utcnow()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Application):
            return NotImplemented
        return self._id == other._id

    def __hash__(self) -> int:
        return hash(self._id)

    def __repr__(self) -> str:
        return (
            f"Application(id={self._id}, job_id={self._job_id}, "
            f"candidate_id={self._candidate_id}, status={self._status.value})"
        )
