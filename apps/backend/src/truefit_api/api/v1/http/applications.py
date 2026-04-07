"""
POST   /applications                          Create application
GET    /applications/{application_id}          Get single application
GET    /applications                           List by job_id or candidate_id
PATCH  /applications/{application_id}/status   Update status
DELETE /applications/{application_id}          Withdraw/delete
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from src.truefit_core.domain.application import (
    Application,
    ApplicationSource,
    ApplicationStatus,
)
from src.truefit_infra.db.database import db_manager
from src.truefit_infra.db.repositories.application_repository import (
    SQLAlchemyApplicationRepository,
)

router = APIRouter(prefix="/applications", tags=["applications"])


# Dependencies


def get_application_repo() -> SQLAlchemyApplicationRepository:
    return SQLAlchemyApplicationRepository(db_manager)


# Schemas


class CreateApplicationRequest(BaseModel):
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    source: ApplicationSource = ApplicationSource.applied
    meta: dict[str, Any] = {}


class UpdateStatusRequest(BaseModel):
    status: ApplicationStatus
    meta_updates: dict[str, Any] = {}


class ApplicationOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    source: str
    status: str
    meta: dict[str, Any]
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, a: Application) -> "ApplicationOut":
        return cls(
            id=a.id,
            job_id=a.job_id,
            candidate_id=a.candidate_id,
            source=a.source.value,
            status=a.status.value,
            meta=a.meta,
            created_at=a.created_at.isoformat(),
            updated_at=a.updated_at.isoformat(),
        )


# Endpoints


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
async def create_application(
    body: CreateApplicationRequest,
    repo: SQLAlchemyApplicationRepository = Depends(get_application_repo),
) -> ApplicationOut:
    # Enforce unique constraint at domain layer before hitting DB
    existing = await repo.get_by_job_and_candidate(body.job_id, body.candidate_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Application already exists for this job and candidate",
        )

    application = Application(
        job_id=body.job_id,
        candidate_id=body.candidate_id,
        source=body.source,
        meta=body.meta,
    )
    await repo.save(application)
    return ApplicationOut.from_domain(application)


@router.get("/{application_id}", response_model=ApplicationOut)
async def get_application(
    application_id: uuid.UUID,
    repo: SQLAlchemyApplicationRepository = Depends(get_application_repo),
) -> ApplicationOut:
    application = await repo.get_by_id(application_id)
    if not application:
        raise HTTPException(404, detail=f"Application {application_id} not found")
    return ApplicationOut.from_domain(application)


@router.get("", response_model=list[ApplicationOut])
async def list_applications(
    job_id: Optional[uuid.UUID] = Query(None),
    candidate_id: Optional[uuid.UUID] = Query(None),
    status: Optional[ApplicationStatus] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: SQLAlchemyApplicationRepository = Depends(get_application_repo),
) -> list[ApplicationOut]:
    if not job_id and not candidate_id:
        raise HTTPException(400, detail="Provide job_id or candidate_id")

    if job_id:
        applications = await repo.list_by_job(
            job_id,
            status=status.value if status else None,
            limit=limit,
            offset=offset,
        )
    else:
        applications = await repo.list_by_candidate(
            candidate_id, limit=limit, offset=offset
        )

    return [ApplicationOut.from_domain(a) for a in applications]


@router.patch("/{application_id}/status", response_model=ApplicationOut)
async def update_status(
    application_id: uuid.UUID,
    body: UpdateStatusRequest,
    repo: SQLAlchemyApplicationRepository = Depends(get_application_repo),
) -> ApplicationOut:
    application = await repo.get_by_id(application_id)
    if not application:
        raise HTTPException(404, detail=f"Application {application_id} not found")

    try:
        match body.status:
            case ApplicationStatus.interviewing:
                application.mark_interviewing()
            case ApplicationStatus.shortlisted:
                application.shortlist()
            case ApplicationStatus.rejected:
                application.reject()
            case ApplicationStatus.hired:
                application.hire()
            case _:
                raise HTTPException(
                    400, detail=f"Cannot manually set status to: {body.status.value}"
                )

        if body.meta_updates:
            application.update_meta(body.meta_updates)

    except (ValueError, PermissionError) as e:
        raise HTTPException(400, detail=str(e))

    await repo.save(application)
    return ApplicationOut.from_domain(application)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_application(
    application_id: uuid.UUID,
    repo: SQLAlchemyApplicationRepository = Depends(get_application_repo),
) -> None:
    application = await repo.get_by_id(application_id)
    if not application:
        raise HTTPException(404, detail=f"Application {application_id} not found")

    try:
        application.withdraw()
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    await repo.save(application)
