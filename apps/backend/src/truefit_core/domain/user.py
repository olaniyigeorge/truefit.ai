from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4


class UserRole(str, enum.Enum):
    admin = "admin"
    recruiter = "recruiter"
    candidate = "candidate"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class User:
    id: UUID
    email: str
    display_name: str | None
    role: UserRole
    auth_provider: str
    provider_subject: str
    org_id: UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        email: str,
        display_name: str | None,
        role: UserRole,
        auth_provider: str,
        provider_subject: str,
        org_id: UUID | None = None,
    ) -> "User":
        now = utcnow()
        return cls(
            id=uuid4(),
            email=email.lower(),
            display_name=display_name,
            role=role,
            auth_provider=auth_provider,
            provider_subject=provider_subject,
            org_id=org_id,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

    def set_org(self, org_id: UUID | None) -> None:
        self.org_id = org_id
        self.updated_at = utcnow()

    def update_profile(
        self, *, display_name: str | None = None, is_active: bool | None = None
    ) -> None:
        if display_name is not None:
            self.display_name = display_name
        if is_active is not None:
            self.is_active = is_active
        self.updated_at = utcnow()
