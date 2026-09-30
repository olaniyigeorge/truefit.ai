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
from sqlalchemy import select

from src.truefit_core.domain.application import (
    Application,
    ApplicationSource,
    ApplicationStatus,
)
from src.truefit_infra.auth.authorization import (
    CANDIDATE,
    _forbidden,
    _same,
    can_view_as_org_member,
    ensure_org_member,
    is_admin,
)
from src.truefit_infra.auth.middleware import TokenPayload, get_current_user
from src.truefit_infra.db.database import db_manager
from src.truefit_infra.db.models import CandidateProfile as CandidateProfileModel
from src.truefit_infra.db.repositories.application_repository import (
    SQLAlchemyApplicationRepository,
)
from src.truefit_infra.db.repositories.job_repository import SQLAlchemyJobRepository

router = APIRouter(prefix="/applications", tags=["applications"])


# Dependencies


def get_application_repo() -> SQLAlchemyApplicationRepository:
    return SQLAlchemyApplicationRepository(db_manager)


class CandidateOwnership:
    """Maps candidate profiles to their owning users (candidate_profiles.user_id)."""

    async def owner_user_id(self, candidate_id: uuid.UUID) -> Optional[uuid.UUID]:
        stmt = select(CandidateProfileModel.user_id).where(
            CandidateProfileModel.id == candidate_id
        )
        async with db_manager.get_session() as session:
            return (await session.execute(stmt)).scalar_one_or_none()

    async def profile_id_for_user(self, user_id: uuid.UUID) -> Optional[uuid.UUID]:
        stmt = select(CandidateProfileModel.id).where(
            CandidateProfileModel.user_id == user_id
        )
        async with db_manager.get_session() as session:
            return (await session.execute(stmt)).scalars().first()


def get_candidate_ownership() -> CandidateOwnership:
    return CandidateOwnership()


def get_job_repo() -> SQLAlchemyJobRepository:
    return SQLAlchemyJobRepository(db_manager)


async def _job_org_id(job_repo, job_id: uuid.UUID) -> Optional[uuid.UUID]:
    job = await job_repo.get_by_id(job_id)
    return job.org_id if job else None


async def _ensure_owner_or_job_org(
    user: TokenPayload, application: Application, ownership, job_repo
) -> None:
    """Admin, the owning candidate, or a recruiter of the application's job org."""
    if is_admin(user):
        return
    owner = await ownership.owner_user_id(application.candidate_id)
    if _same(user.user_id, owner):
        return
    ensure_org_member(user, await _job_org_id(job_repo, application.job_id))


async def _ensure_job_org(user: TokenPayload, application: Application, job_repo) -> None:
    ensure_org_member(user, await _job_org_id(job_repo, application.job_id))


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
    ownership: CandidateOwnership = Depends(get_candidate_ownership),
    user: TokenPayload = Depends(get_current_user),
) -> ApplicationOut:
    # Only admins, or the candidate who owns the profile, may apply on its behalf.
    if not is_admin(user):
        owner = await ownership.owner_user_id(body.candidate_id)
        if user.role != CANDIDATE or not _same(user.user_id, owner):
            raise _forbidden()

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
    ownership: CandidateOwnership = Depends(get_candidate_ownership),
    job_repo: SQLAlchemyJobRepository = Depends(get_job_repo),
    user: TokenPayload = Depends(get_current_user),
) -> ApplicationOut:
    application = await repo.get_by_id(application_id)
    if not application:
        raise HTTPException(404, detail=f"Application {application_id} not found")
    await _ensure_owner_or_job_org(user, application, ownership, job_repo)
    return ApplicationOut.from_domain(application)


async def _list_for_candidate(
    user: TokenPayload,
    job_id: Optional[uuid.UUID],
    candidate_id: Optional[uuid.UUID],
    status_filter: Optional[ApplicationStatus],
    limit: int,
    offset: int,
    repo,
    ownership,
) -> list[ApplicationOut]:
    """Candidates only ever see their own applications."""
    own_profile = await ownership.profile_id_for_user(uuid.UUID(str(user.user_id)))
    if candidate_id and not (
        _same(candidate_id, own_profile) or _same(candidate_id, user.user_id)
    ):
        raise _forbidden()
    if own_profile is None:
        return []
    applications = await repo.list_by_candidate(
        own_profile, limit=limit, offset=offset
    )
    return [
        ApplicationOut.from_domain(a)
        for a in applications
        if (not job_id or a.job_id == job_id)
        and (not status_filter or a.status == status_filter)
    ]


@router.get("", response_model=list[ApplicationOut])
async def list_applications(
    job_id: Optional[uuid.UUID] = Query(None),
    candidate_id: Optional[uuid.UUID] = Query(None),
    status: Optional[ApplicationStatus] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: SQLAlchemyApplicationRepository = Depends(get_application_repo),
    ownership: CandidateOwnership = Depends(get_candidate_ownership),
    job_repo: SQLAlchemyJobRepository = Depends(get_job_repo),
    user: TokenPayload = Depends(get_current_user),
) -> list[ApplicationOut]:
    if not is_admin(user):
        if user.role == CANDIDATE:
            return await _list_for_candidate(
                user, job_id, candidate_id, status, limit, offset, repo, ownership
            )
        # Recruiters: only applications for jobs in their own org.
        if not job_id and not candidate_id:
            raise HTTPException(400, detail="Provide job_id or candidate_id")
        if job_id:
            ensure_org_member(user, await _job_org_id(job_repo, job_id))
        else:
            applications = await repo.list_by_candidate(
                candidate_id, limit=limit, offset=offset
            )
            orgs: dict[uuid.UUID, Optional[uuid.UUID]] = {}
            visible = []
            for a in applications:
                if a.job_id not in orgs:
                    orgs[a.job_id] = await _job_org_id(job_repo, a.job_id)
                if can_view_as_org_member(user, orgs[a.job_id]):
                    visible.append(a)
            return [ApplicationOut.from_domain(a) for a in visible]

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
    job_repo: SQLAlchemyJobRepository = Depends(get_job_repo),
    user: TokenPayload = Depends(get_current_user),
) -> ApplicationOut:
    application = await repo.get_by_id(application_id)
    if not application:
        raise HTTPException(404, detail=f"Application {application_id} not found")
    await _ensure_job_org(user, application, job_repo)

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
    ownership: CandidateOwnership = Depends(get_candidate_ownership),
    job_repo: SQLAlchemyJobRepository = Depends(get_job_repo),
    user: TokenPayload = Depends(get_current_user),
) -> None:
    application = await repo.get_by_id(application_id)
    if not application:
        raise HTTPException(404, detail=f"Application {application_id} not found")
    await _ensure_owner_or_job_org(user, application, ownership, job_repo)

    try:
        application.withdraw()
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    await repo.save(application)
