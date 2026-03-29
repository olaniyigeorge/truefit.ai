"""
SQLAlchemy implementation of OrgRepository.

Slug uniqueness is enforced at both domain (slug pattern validation) and
DB level (unique index). The repo catches IntegrityError on slug conflicts
and re-raises as a clean ValueError so the endpoint can return a 409.

SQLAlchemy implementation of OrgRepository against the orgs table.

This repo is intentionally small:
- create_org(): insert and return the ORM row as a dict (used by UserService provisioning)
- get_by_slug(), get_by_id()
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select, delete
from sqlalchemy.dialects.postgresql import Any, insert as pg_insert
from sqlalchemy.exc import IntegrityError

from src.truefit_core.domain.org import (
    Org,
    OrgBilling,
    OrgContact,
    OrgPlan,
    OrgStatus,
)
from src.truefit_infra.db.database import DatabaseManager
from src.truefit_infra.db.models import Org as OrgModel
from src.truefit_core.application.ports import OrgRepository


class SQLAlchemyOrgRepository(OrgRepository):

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def save(self, org: Org) -> None:
        data = self._to_row(org)
        stmt = (
            pg_insert(OrgModel)
            .values(**data)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "name": data["name"],
                    "status": data["status"],
                    "contact": data["contact"],
                    "billing": data["billing"],
                    "logo_url": data["logo_url"],
                    "description": data["description"],
                    "industry": data["industry"],
                    "headcount": data["headcount"],
                    "updated_at": data["updated_at"],
                },
            )
        )
        try:
            async with self._db.get_session() as session:
                await session.execute(stmt)
        except IntegrityError as e:
            if "slug" in str(e.orig):
                raise ValueError(f"Slug '{org.slug}' is already taken") from e
            raise

    async def get_by_id(self, org_id: uuid.UUID) -> Optional[Org]:
        stmt = select(OrgModel).where(OrgModel.id == org_id)
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_slug(self, slug: str) -> Optional[Org]:
        stmt = select(OrgModel).where(OrgModel.slug == slug)
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_all(self, *, limit: int = 50, offset: int = 0) -> list[Org]:
        stmt = (
            select(OrgModel)
            .order_by(OrgModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def list_by_status(
        self, status: OrgStatus, *, limit: int = 50, offset: int = 0
    ) -> list[Org]:
        stmt = (
            select(OrgModel)
            .where(OrgModel.status == status.value)
            .order_by(OrgModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def count(self) -> int:
        stmt = select(func.count()).select_from(OrgModel)
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            return result.scalar_one()

    async def exists_by_slug(self, slug: str) -> bool:
        stmt = select(func.count()).select_from(OrgModel).where(OrgModel.slug == slug)
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            return result.scalar_one() > 0

    async def delete(self, org_id: uuid.UUID) -> None:
        stmt = delete(OrgModel).where(OrgModel.id == org_id)
        async with self._db.get_session() as session:
            await session.execute(stmt)

    # Mapping: domain -> row 

    @staticmethod
    def _to_row(org: OrgModel) -> dict:
        b = org.billing
        c = org.contact
        return {
            "id": org.id,
            "created_by": org.created_by,
            "name": org.name,
            "slug": org.slug,
            "status": org.status.value,
            "contact": {
                "email": c.email,
                "phone": c.phone,
                "website": c.website,
            },
            "billing": {
                "plan": b.plan.value,
                "max_active_jobs": b.max_active_jobs,
                "max_interviews_per_month": b.max_interviews_per_month,
                "extra": b.extra,
            },
            "logo_url": org.logo_url,
            "description": org.description,
            "industry": org.industry,
            "headcount": org.headcount,
            "created_at": org.created_at,
            "updated_at": org.updated_at,
        }

    # Mapping: row -> domain 

    @staticmethod
    def _to_domain(row: OrgModel) -> Org:
        c = row.contact or {}
        contact = OrgContact(
            email=c.get("email", ""),
            phone=c.get("phone"),
            website=c.get("website"),
        )

        b = row.billing or {}
        billing = OrgBilling(
            plan=OrgPlan(b.get("plan", OrgPlan.FREE.value)),
            max_active_jobs=b.get("max_active_jobs", 3),
            max_interviews_per_month=b.get("max_interviews_per_month", 50),
            extra=b.get("extra", {}),
        )

        return Org(
            org_id=row.id,
            created_by=row.created_by,
            name=row.name,
            slug=row.slug,
            status=OrgStatus(row.status),
            contact=contact,
            billing=billing,
            logo_url=row.logo_url,
            description=row.description,
            industry=row.industry,
            headcount=row.headcount,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
