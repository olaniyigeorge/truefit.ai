"""
POST   /orgs                        Create org
GET    /orgs/{org_id}               Get by ID
GET    /orgs/slug/{slug}            Get by slug
GET    /orgs                        List all (paginated)
PATCH  /orgs/{org_id}               Update profile
PATCH  /orgs/{org_id}/billing       Update billing / plan
POST   /orgs/{org_id}/suspend       Suspend org
POST   /orgs/{org_id}/reactivate    Reactivate suspended org
POST   /orgs/{org_id}/deactivate    Permanently deactivate
DELETE /orgs/{org_id}               Hard delete (only DEACTIVATED orgs)
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from src.truefit_core.domain.org import (
    Org,
    OrgBilling,
    OrgContact,
    OrgPlan,
    OrgStatus,
)
from src.truefit_infra.db.database import db_manager
from src.truefit_infra.db.repositories.org_repository import SQLAlchemyOrgRepository

router = APIRouter(prefix="/orgs", tags=["orgs"])


# ── Dependency ───


def get_org_repo() -> SQLAlchemyOrgRepository:
    return SQLAlchemyOrgRepository(db_manager)


# ── Request schemas ───


class OrgContactIn(BaseModel):
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=30)
    website: Optional[str] = Field(None, max_length=255)


class OrgBillingIn(BaseModel):
    plan: str = "free"
    max_active_jobs: int = Field(3, ge=1)
    max_interviews_per_month: int = Field(50, ge=1)

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, v: str) -> str:
        try:
            OrgPlan(v)
        except ValueError:
            raise ValueError(f"plan must be one of: {[p.value for p in OrgPlan]}")
        return v


class CreateOrgRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: Optional[str] = Field(
        None,
        min_length=2,
        max_length=100,
        description="URL-safe identifier. Auto-generated from name if omitted.",
    )
    created_by: uuid.UUID
    contact: OrgContactIn
    description: Optional[str] = Field(None, max_length=2000)
    logo_url: Optional[str] = Field(None, max_length=512)
    industry: Optional[str] = Field(None, max_length=100)
    headcount: Optional[str] = Field(None)
    billing: Optional[OrgBillingIn] = None

    @field_validator("headcount")
    @classmethod
    def validate_headcount(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in {"1-10", "11-50", "51-200", "200+"}:
            raise ValueError("headcount must be one of: 1-10, 11-50, 51-200, 200+")
        return v


class UpdateOrgRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    logo_url: Optional[str] = Field(None, max_length=512)
    industry: Optional[str] = Field(None, max_length=100)
    headcount: Optional[str] = None
    contact: Optional[OrgContactIn] = None

    @field_validator("headcount")
    @classmethod
    def validate_headcount(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in {"1-10", "11-50", "51-200", "200+"}:
            raise ValueError("headcount must be one of: 1-10, 11-50, 51-200, 200+")
        return v


# ── Response schemas ──


class OrgContactOut(BaseModel):
    email: str
    phone: Optional[str]
    website: Optional[str]


class OrgBillingOut(BaseModel):
    plan: str
    max_active_jobs: int
    max_interviews_per_month: int


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    contact: OrgContactOut
    billing: OrgBillingOut
    logo_url: Optional[str]
    description: Optional[str]
    industry: Optional[str]
    headcount: Optional[str]
    created_by: uuid.UUID
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, org: Org) -> "OrgOut":
        return cls(
            id=org.id,
            name=org.name,
            slug=org.slug,
            status=org.status.value,
            contact=OrgContactOut(
                email=org.contact.email,
                phone=org.contact.phone,
                website=org.contact.website,
            ),
            billing=OrgBillingOut(
                plan=org.billing.plan.value,
                max_active_jobs=org.billing.max_active_jobs,
                max_interviews_per_month=org.billing.max_interviews_per_month,
            ),
            logo_url=org.logo_url,
            description=org.description,
            industry=org.industry,
            headcount=org.headcount,
            created_by=org.created_by,
            created_at=org.created_at.isoformat(),
            updated_at=org.updated_at.isoformat(),
        )


# ── Endpoints ──


@router.post("", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
async def create_org(
    body: CreateOrgRequest,
    repo: SQLAlchemyOrgRepository = Depends(get_org_repo),
):
    # Auto-generate slug from name if not provided
    slug = body.slug or Org.generate_slug(body.name)

    # Check slug availability before hitting the DB unique constraint
    if await repo.exists_by_slug(slug):
        raise HTTPException(
            status_code=409,
            detail=f"Slug '{slug}' is already taken. Provide a different slug.",
        )

    print(
        f"\n\nCreating org with name={body.name} slug={slug} created_by={body.created_by}\n\n"
    )
    contact = OrgContact(
        email=body.contact.email,
        phone=body.contact.phone,
        website=body.contact.website,
    )

    billing = None
    if body.billing:
        billing = OrgBilling(
            plan=OrgPlan(body.billing.plan),
            max_active_jobs=body.billing.max_active_jobs,
            max_interviews_per_month=body.billing.max_interviews_per_month,
        )

    try:
        org = Org(
            name=body.name,
            slug=slug,
            created_by=body.created_by,
            contact=contact,
            billing=billing,
            logo_url=body.logo_url,
            description=body.description,
            industry=body.industry,
            headcount=body.headcount,
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    await repo.save(org)
    return OrgOut.from_domain(org)


@router.get("/slug/{slug}", response_model=OrgOut)
async def get_org_by_slug(
    slug: str,
    repo: SQLAlchemyOrgRepository = Depends(get_org_repo),
):
    org = await repo.get_by_slug(slug)
    if not org:
        raise HTTPException(404, detail=f"Org with slug '{slug}' not found")
    return OrgOut.from_domain(org)


@router.get("/{org_id}", response_model=OrgOut)
async def get_org(
    org_id: uuid.UUID,
    repo: SQLAlchemyOrgRepository = Depends(get_org_repo),
):
    org = await repo.get_by_id(org_id)
    if not org:
        raise HTTPException(404, detail=f"Org {org_id} not found")
    return OrgOut.from_domain(org)


@router.get("", response_model=list[OrgOut])
async def list_orgs(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: SQLAlchemyOrgRepository = Depends(get_org_repo),
):
    if status_filter:
        try:
            s = OrgStatus(status_filter)
        except ValueError:
            raise HTTPException(400, detail=f"Invalid status: {status_filter}")
        print(
            f"\n\nListing orgs with status={s.value} limit={limit} offset={offset}\n\n"
        )
        orgs = await repo.list_by_status(s, limit=limit, offset=offset)
    else:
        orgs = await repo.list_all(limit=limit, offset=offset)

    return [OrgOut.from_domain(o) for o in orgs]


@router.patch("/{org_id}", response_model=OrgOut)
async def update_org(
    org_id: uuid.UUID,
    body: UpdateOrgRequest,
    repo: SQLAlchemyOrgRepository = Depends(get_org_repo),
):
    org = await repo.get_by_id(org_id)
    if not org:
        raise HTTPException(404, detail=f"Org {org_id} not found")

    if all(v is None for v in body.model_dump().values()):
        raise HTTPException(400, detail="At least one field must be provided")

    try:
        contact = None
        if body.contact:
            contact = OrgContact(
                email=body.contact.email,
                phone=body.contact.phone,
                website=body.contact.website,
            )
        org.update_profile(
            name=body.name,
            description=body.description,
            logo_url=body.logo_url,
            industry=body.industry,
            headcount=body.headcount,
            contact=contact,
        )
        await repo.save(org)
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, detail=str(e))

    return OrgOut.from_domain(org)


@router.patch("/{org_id}/billing", response_model=OrgOut)
async def update_billing(
    org_id: uuid.UUID,
    body: OrgBillingIn,
    repo: SQLAlchemyOrgRepository = Depends(get_org_repo),
):
    org = await repo.get_by_id(org_id)
    if not org:
        raise HTTPException(404, detail=f"Org {org_id} not found")

    try:
        org.update_billing(
            OrgBilling(
                plan=OrgPlan(body.plan),
                max_active_jobs=body.max_active_jobs,
                max_interviews_per_month=body.max_interviews_per_month,
            )
        )
        await repo.save(org)
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, detail=str(e))

    return OrgOut.from_domain(org)


@router.post("/{org_id}/suspend", response_model=OrgOut)
async def suspend_org(
    org_id: uuid.UUID,
    repo: SQLAlchemyOrgRepository = Depends(get_org_repo),
):
    org = await repo.get_by_id(org_id)
    if not org:
        raise HTTPException(404, detail=f"Org {org_id} not found")
    try:
        org.suspend()
        await repo.save(org)
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, detail=str(e))
    return OrgOut.from_domain(org)


@router.post("/{org_id}/reactivate", response_model=OrgOut)
async def reactivate_org(
    org_id: uuid.UUID,
    repo: SQLAlchemyOrgRepository = Depends(get_org_repo),
):
    org = await repo.get_by_id(org_id)
    if not org:
        raise HTTPException(404, detail=f"Org {org_id} not found")
    try:
        org.reactivate()
        await repo.save(org)
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, detail=str(e))
    return OrgOut.from_domain(org)


@router.post("/{org_id}/deactivate", response_model=OrgOut)
async def deactivate_org(
    org_id: uuid.UUID,
    repo: SQLAlchemyOrgRepository = Depends(get_org_repo),
):
    org = await repo.get_by_id(org_id)
    if not org:
        raise HTTPException(404, detail=f"Org {org_id} not found")
    try:
        org.deactivate()
        await repo.save(org)
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, detail=str(e))
    return OrgOut.from_domain(org)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org(
    org_id: uuid.UUID,
    repo: SQLAlchemyOrgRepository = Depends(get_org_repo),
):
    org = await repo.get_by_id(org_id)
    if not org:
        raise HTTPException(404, detail=f"Org {org_id} not found")
    if org.status != OrgStatus.DEACTIVATED:
        raise HTTPException(
            400,
            detail="Only DEACTIVATED orgs can be hard deleted. Deactivate first.",
        )
    await repo.delete(org_id)
