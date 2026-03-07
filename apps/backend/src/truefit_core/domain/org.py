"""
Aggregate root representing an organisation (company) on the platform.

Invariants
──────────
- An org must always have a name and a valid slug.
- Only ACTIVE orgs can create job listings.
- Slug is immutable after creation — it's used in URLs and external references.
- Status transitions are strictly controlled.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class OrgStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"   # billing / policy issue — jobs paused
    DEACTIVATED = "deactivated"  # permanently off


class OrgPlan(str, Enum):
    FREE = "free"
    STARTER = "starter"
    GROWTH = "growth"
    ENTERPRISE = "enterprise"


@dataclass
class OrgBilling:
    """
    Billing metadata. Not a payment processor record —
    just enough for the platform to know what the org is entitled to.
    """
    plan: OrgPlan = OrgPlan.FREE
    max_active_jobs: int = 3
    max_interviews_per_month: int = 50
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_active_jobs < 1:
            raise ValueError("max_active_jobs must be at least 1")
        if self.max_interviews_per_month < 1:
            raise ValueError("max_interviews_per_month must be at least 1")


@dataclass(frozen=True)
class OrgContact:
    """Primary contact for the organisation."""
    email: str
    phone: Optional[str] = None
    website: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.email or "@" not in self.email:
            raise ValueError(f"Invalid contact email: {self.email!r}")


class Org:
    """
    Aggregate root for an organisation.

    An org owns job listings, interview sessions, and evaluations.
    Users belong to orgs (managed separately via auth/membership layer).
    """

    _VALID_TRANSITIONS: dict[OrgStatus, set[OrgStatus]] = {
        OrgStatus.ACTIVE:      {OrgStatus.SUSPENDED, OrgStatus.DEACTIVATED},
        OrgStatus.SUSPENDED:   {OrgStatus.ACTIVE, OrgStatus.DEACTIVATED},
        OrgStatus.DEACTIVATED: set(),
    }

    def __init__(
        self,
        *,
        name: str,
        slug: str,
        contact: OrgContact,
        created_by: uuid.UUID,
        org_id: Optional[uuid.UUID] = None,
        status: OrgStatus = OrgStatus.ACTIVE,
        billing: Optional[OrgBilling] = None,
        logo_url: Optional[str] = None,
        description: Optional[str] = None,
        industry: Optional[str] = None,
        headcount: Optional[str] = None,   # "1-10" | "11-50" | "51-200" | "200+"
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> None:
        if not name.strip():
            raise ValueError("Org name cannot be empty")
        if not _SLUG_PATTERN.match(slug):
            raise ValueError(
                f"Invalid slug '{slug}'. Must be lowercase alphanumeric with hyphens only "
                f"(e.g. 'acme-corp')"
            )

        self._id: uuid.UUID = org_id or uuid.uuid4()
        self._name: str = name.strip()
        self._slug: str = slug  
        self._contact: OrgContact = contact
        self._created_by: uuid.UUID = created_by
        self._status: OrgStatus = status
        self._billing: OrgBilling = billing or OrgBilling()
        self._logo_url: Optional[str] = logo_url
        self._description: Optional[str] = description
        self._industry: Optional[str] = industry
        self._headcount: Optional[str] = headcount
        self._created_at: datetime = created_at or _utcnow()
        self._updated_at: datetime = updated_at or _utcnow()

    # ── Identity ───

    @property
    def id(self) -> uuid.UUID:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def slug(self) -> str:
        return self._slug

    @property
    def contact(self) -> OrgContact:
        return self._contact

    @property
    def created_by(self) -> uuid.UUID:
        return self._created_by

    @property
    def status(self) -> OrgStatus:
        return self._status

    @property
    def billing(self) -> OrgBilling:
        return self._billing

    @property
    def logo_url(self) -> Optional[str]:
        return self._logo_url

    @property
    def description(self) -> Optional[str]:
        return self._description

    @property
    def industry(self) -> Optional[str]:
        return self._industry

    @property
    def headcount(self) -> Optional[str]:
        return self._headcount

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    # ── Derived ──

    @property
    def is_active(self) -> bool:
        return self._status == OrgStatus.ACTIVE

    @property
    def plan(self) -> OrgPlan:
        return self._billing.plan

    # ── Commands ───

    def update_profile(
        self,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        logo_url: Optional[str] = None,
        industry: Optional[str] = None,
        headcount: Optional[str] = None,
        contact: Optional[OrgContact] = None,
    ) -> None:
        self._assert_not_deactivated()
        if name is not None:
            if not name.strip():
                raise ValueError("Org name cannot be empty")
            self._name = name.strip()
        if description is not None:
            self._description = description
        if logo_url is not None:
            self._logo_url = logo_url
        if industry is not None:
            self._industry = industry
        if headcount is not None:
            valid = {"1-10", "11-50", "51-200", "200+"}
            if headcount not in valid:
                raise ValueError(f"headcount must be one of {valid}")
            self._headcount = headcount
        if contact is not None:
            self._contact = contact
        self._touch()

    def update_billing(self, billing: OrgBilling) -> None:
        self._assert_not_deactivated()
        self._billing = billing
        self._touch()

    def suspend(self) -> None:
        self._transition_to(OrgStatus.SUSPENDED)

    def reactivate(self) -> None:
        self._transition_to(OrgStatus.ACTIVE)

    def deactivate(self) -> None:
        self._transition_to(OrgStatus.DEACTIVATED)

    # ── Assertions ───

    def assert_can_create_jobs(self) -> None:
        if not self.is_active:
            raise PermissionError(
                f"Org '{self._name}' cannot create job listings "
                f"(status={self._status.value})"
            )

    # ── Helpers ──

    @staticmethod
    def generate_slug(name: str) -> str:
        """Generate a URL-safe slug from an org name."""
        slug = name.lower().strip()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        return slug or "org"

    def _assert_not_deactivated(self) -> None:
        if self._status == OrgStatus.DEACTIVATED:
            raise PermissionError(f"Cannot modify a deactivated org (id={self._id})")

    def _transition_to(self, new_status: OrgStatus) -> None:
        allowed = self._VALID_TRANSITIONS[self._status]
        if new_status not in allowed:
            raise ValueError(
                f"Invalid status transition: {self._status.value} → {new_status.value}"
            )
        self._status = new_status
        self._touch()

    def _touch(self) -> None:
        self._updated_at = _utcnow()

    # ── Representation ──

    def __repr__(self) -> str:
        return (
            f"Org(id={self._id}, name={self._name!r}, "
            f"slug={self._slug!r}, status={self._status.value})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Org):
            return NotImplemented
        return self._id == other._id

    def __hash__(self) -> int:
        return hash(self._id)