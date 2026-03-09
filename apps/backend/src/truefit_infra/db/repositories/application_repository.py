from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.truefit_core.domain.application import (
    Application,
    ApplicationSource,
    ApplicationStatus,
)
from src.truefit_core.application.ports import ApplicationRepository
from src.truefit_infra.db.database import DatabaseManager
from src.truefit_infra.db.models import Application as ApplicationORM


class SQLAlchemyApplicationRepository(ApplicationRepository):

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def save(self, application: Application) -> None:
        async with self._db.get_session() as session:
            existing = await session.get(ApplicationORM, application.id)
            if existing is None:
                row = ApplicationORM(
                    id=application.id,
                    job_id=application.job_id,
                    candidate_id=application.candidate_id,
                    source=application.source.value,
                    status=application.status.value,
                    meta=application.meta,
                    created_at=application.created_at,
                    updated_at=application.updated_at,
                )
                session.add(row)
            else:
                existing.status     = application.status.value
                existing.meta       = application.meta
                existing.updated_at = application.updated_at
            await session.commit()

    async def get_by_id(self, application_id: uuid.UUID) -> Optional[Application]:
        async with self._db.get_session() as session:
            row = await session.get(ApplicationORM, application_id)
            return _to_domain(row) if row else None

    async def get_by_job_and_candidate(
        self, job_id: uuid.UUID, candidate_id: uuid.UUID
    ) -> Optional[Application]:
        async with self._db.get_session() as session:
            result = await session.execute(
                select(ApplicationORM).where(
                    ApplicationORM.job_id == job_id,
                    ApplicationORM.candidate_id == candidate_id,
                )
            )
            row = result.scalar_one_or_none()
            return _to_domain(row) if row else None

    async def list_by_job(
        self,
        job_id: uuid.UUID,
        *,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Application]:
        async with self._db.get_session() as session:
            q = select(ApplicationORM).where(ApplicationORM.job_id == job_id)
            if status:
                q = q.where(ApplicationORM.status == status)
            q = q.order_by(ApplicationORM.created_at.desc()).limit(limit).offset(offset)
            result = await session.execute(q)
            return [_to_domain(r) for r in result.scalars().all()]

    async def list_by_candidate(
        self,
        candidate_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Application]:
        async with self._db.get_session() as session:
            result = await session.execute(
                select(ApplicationORM)
                .where(ApplicationORM.candidate_id == candidate_id)
                .order_by(ApplicationORM.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return [_to_domain(r) for r in result.scalars().all()]

    async def delete(self, application_id: uuid.UUID) -> None:
        async with self._db.get_session() as session:
            row = await session.get(ApplicationORM, application_id)
            if row:
                await session.delete(row)
                await session.commit()


# ── Mapper ────────────────────────────────────────────────────────────────────

def _to_domain(row: ApplicationORM) -> Application:
    return Application(
        application_id=row.id,
        job_id=row.job_id,
        candidate_id=row.candidate_id,
        source=ApplicationSource(row.source),
        status=ApplicationStatus(row.status),
        meta=dict(row.meta or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )