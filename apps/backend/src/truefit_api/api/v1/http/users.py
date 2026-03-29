from __future__ import annotations

import uuid
import re
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator


from src.truefit_infra.db.database import db_manager
from src.truefit_infra.db.repositories.user_repository import SQLAlchemyUserRepository
from src.truefit_infra.db.repositories.org_repository import SQLAlchemyOrgRepository
from src.truefit_infra.db.repositories.candidate_profile_repository import (
    SQLAlchemyCandidateProfileRepository,
)

from src.truefit_core.application.services.user_service import (
    UserService,
    OrgCreateInput,
    CandidateProfileInput,
)

router = APIRouter(prefix="/users", tags=["users"])


def get_user_service() -> UserService:
    return UserService(
        user_repo=SQLAlchemyUserRepository(db_manager),
        org_repo=SQLAlchemyOrgRepository(db_manager),
        candidate_profile_repo=SQLAlchemyCandidateProfileRepository(db_manager),
    )


# ── Request schemas ──

AccountType = Literal["candidate", "org", "plain"]


class CandidateProfileIn(BaseModel):
    headline: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    years_experience: Optional[int] = None
    skills: list[str] = Field(default_factory=list)


_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class OrgIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=150)
    contact: dict[str, Any] = Field(default_factory=dict)
    billing: dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None
    industry: Optional[str] = None
    headcount: Optional[str] = None
    logo_url: Optional[str] = None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        v = v.strip()
        if not _SLUG_PATTERN.match(v):
            raise ValueError(
                "Invalid slug. Use lowercase letters/numbers and hyphens only (e.g. 'acme-corp')."
            )
        return v


class CreateUserRequest(BaseModel):
    email: EmailStr
    display_name: Optional[str] = Field(None, max_length=255)

    auth_provider: str = Field("seed", max_length=64)
    provider_subject: str = Field(..., max_length=255)

    account_type: AccountType = "candidate"
    candidate_profile: Optional[CandidateProfileIn] = None
    org: Optional[OrgIn] = None


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None
    role: Optional[str] = Field(None, pattern="^(candidate|recruiter)$")
    org_id: Optional[uuid.UUID] = None


class JoinOrgRequest(BaseModel):
    org_id: uuid.UUID


# ── Response schemas ───


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: Optional[str]
    role: str
    org_id: Optional[uuid.UUID]
    is_active: bool
    created_at: str
    updated_at: str


def _user_out(u) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        display_name=u.display_name,
        role=u.role.value if hasattr(u.role, "value") else str(u.role),
        org_id=u.org_id,
        is_active=u.is_active,
        created_at=u.created_at.isoformat(),
        updated_at=u.updated_at.isoformat(),
    )


class CreateUserResponse(BaseModel):
    user: UserOut
    org: Optional[dict[str, Any]] = None
    candidate_profile: Optional[dict[str, Any]] = None


# ── Endpoints ──


@router.post("", response_model=CreateUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    svc: UserService = Depends(get_user_service),
):
    try:
        result = await svc.create_user(
            email=str(body.email),
            display_name=body.display_name,
            auth_provider=body.auth_provider,
            provider_subject=body.provider_subject,
            account_type=body.account_type,
            org=OrgCreateInput(**body.org.model_dump()) if body.org else None,
            candidate_profile=(
                CandidateProfileInput(**body.candidate_profile.model_dump())
                if body.candidate_profile
                else None
            ),
        )
        return CreateUserResponse(
            user=_user_out(result["user"]),
            org=result["org"],
            candidate_profile=result["candidate_profile"],
        )
    except ValueError as e:
        msg = str(e)
        if "already exists" in msg:
            raise HTTPException(409, detail=msg)
        raise HTTPException(400, detail=msg)
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(500, detail=str(e))


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID,
    svc: UserService = Depends(get_user_service),
):
    user = await svc.get_user(user_id)
    if not user:
        raise HTTPException(404, detail=f"User {user_id} not found")
    return _user_out(user)


@router.get("/by-email/{email}", response_model=UserOut)
async def get_user_by_email(
    email: str,
    svc: UserService = Depends(get_user_service),
):
    user = await svc.get_user_by_email(email)
    if not user:
        raise HTTPException(404, detail=f"User with email '{email}' not found")
    return _user_out(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    svc: UserService = Depends(get_user_service),
):
    try:
        user = await svc.update_user(
            user_id=user_id,
            display_name=body.display_name,
            is_active=body.is_active,
            role=body.role,
            org_id=body.org_id,
        )
        return _user_out(user)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(404, detail=msg)
        raise HTTPException(400, detail=msg)


@router.post("/{user_id}/join-org", response_model=UserOut)
async def join_org(
    user_id: uuid.UUID,
    body: JoinOrgRequest,
    svc: UserService = Depends(get_user_service),
):
    try:
        user = await svc.join_org(user_id=user_id, org_id=body.org_id)
        return _user_out(user)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(404, detail=msg)
        raise HTTPException(400, detail=msg)
