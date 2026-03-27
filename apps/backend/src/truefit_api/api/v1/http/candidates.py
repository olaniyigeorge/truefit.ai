"""

POST   /candidates                      Register a candidate
GET    /candidates/{candidate_id}       Get candidate profile
PATCH  /candidates/{candidate_id}       Update profile fields
POST   /candidates/{candidate_id}/resume  Upload resume (multipart)
DELETE /candidates/{candidate_id}/resume  Remove resume
GET    /candidates/{candidate_id}/resume  Get presigned download URL
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, EmailStr, Field

from src.truefit_core.domain.candidate import (
    Candidate,
    CandidateStatus,
    ContactInfo,
    ResumeRef,
)
from src.truefit_infra.db.database import db_manager
from src.truefit_infra.db.repositories.candidate_repository import (
    SQLAlchemyCandidateRepository,
)

router = APIRouter(prefix="/candidates", tags=["candidates"])

_MAX_RESUME_BYTES = 10 * 1024 * 1024  # 10 MB


# ── Dependency ───

def get_candidate_repo() -> SQLAlchemyCandidateRepository:
    return SQLAlchemyCandidateRepository(db_manager)


# ── Request schemas ───

class RegisterCandidateRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=200)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=30)
    linkedin_url: Optional[str] = Field(None, max_length=255)


class UpdateCandidateRequest(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=200)
    phone: Optional[str] = Field(None, max_length=30)
    linkedin_url: Optional[str] = Field(None, max_length=255)


# ── Response schemas ───

class ContactOut(BaseModel):
    email: str
    phone: Optional[str]
    linkedin_url: Optional[str]


class ResumeOut(BaseModel):
    storage_key: str
    filename: str
    content_type: str
    uploaded_at: str


class CandidateOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    headline: Optional[str]
    bio: Optional[str]
    location: Optional[str]
    skills: Optional[list[str]]
    contact: ContactOut
    status: str
    resume: Optional[ResumeOut]
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, c: Candidate) -> "CandidateOut":
        return cls(
            id=c.id,
            full_name=c.full_name,
            user_id=c._user_id,
            headline=c._headline,
            bio=c._bio,
            location=c._location,
            skills=c._skills,
            contact=ContactOut(
                email=c.contact.email,
                phone=c.contact.phone,
                linkedin_url=c.contact.linkedin_url,
            ),
            status=c.status.value,
            resume=ResumeOut(
                storage_key=c.resume.storage_key,
                filename=c.resume.filename,
                content_type=c.resume.content_type,
                uploaded_at=c.resume.uploaded_at.isoformat(),
            ) if c.resume else None,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
        )


# ── Endpoints ──

@router.post("", response_model=CandidateOut, status_code=status.HTTP_201_CREATED)
async def register_candidate(
    body: RegisterCandidateRequest,
    repo: SQLAlchemyCandidateRepository = Depends(get_candidate_repo),
):
    existing = await repo.get_by_email(body.email)
    if existing:
        raise HTTPException(409, detail=f"Candidate with email '{body.email}' already exists")

    contact = ContactInfo(
        email=body.email,
        phone=body.phone,
        linkedin_url=body.linkedin_url,
    )
    candidate = Candidate(full_name=body.full_name, contact=contact)
    await repo.save(candidate)
    return CandidateOut.from_domain(candidate)


@router.get("/{candidate_id}", response_model=CandidateOut)
async def get_candidate(
    candidate_id: uuid.UUID,
    repo: SQLAlchemyCandidateRepository = Depends(get_candidate_repo),
):
    candidate = await repo.get_by_id(candidate_id)
    if not candidate:
        raise HTTPException(404, detail=f"Candidate {candidate_id} not found")
    
    return CandidateOut.from_domain(candidate)

@router.get("", response_model=list[CandidateOut])
async def list_candidates(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: SQLAlchemyCandidateRepository = Depends(get_candidate_repo),
):
    candidates = await repo.list_all(limit=limit, offset=offset)
    return [CandidateOut.from_domain(c) for c in candidates]


@router.patch("/{candidate_id}", response_model=CandidateOut)
async def update_candidate(
    candidate_id: uuid.UUID,
    body: UpdateCandidateRequest,
    repo: SQLAlchemyCandidateRepository = Depends(get_candidate_repo),
):
    candidate = await repo.get_by_id(candidate_id)
    if not candidate:
        raise HTTPException(404, detail=f"Candidate {candidate_id} not found")

    if all(v is None for v in (body.full_name, body.phone, body.linkedin_url)):
        raise HTTPException(400, detail="At least one field must be provided")

    try:
        new_contact = None
        if body.phone is not None or body.linkedin_url is not None:
            new_contact = ContactInfo(
                email=candidate.contact.email,
                phone=body.phone if body.phone is not None else candidate.contact.phone,
                linkedin_url=body.linkedin_url if body.linkedin_url is not None else candidate.contact.linkedin_url,
            )
        candidate.update_profile(full_name=body.full_name, contact=new_contact)
        await repo.save(candidate)
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, detail=str(e))

    return CandidateOut.from_domain(candidate)


@router.post("/{candidate_id}/resume", response_model=CandidateOut)
async def upload_resume(
    candidate_id: uuid.UUID,
    file: UploadFile = File(...),
    repo: SQLAlchemyCandidateRepository = Depends(get_candidate_repo),
):
    candidate = await repo.get_by_id(candidate_id)
    if not candidate:
        raise HTTPException(404, detail=f"Candidate {candidate_id} not found")

    content_type = file.content_type or "application/octet-stream"
    if content_type not in ("application/pdf", "application/msword",
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"):
        raise HTTPException(400, detail="Resume must be PDF or Word document")

    data = await file.read()
    if len(data) > _MAX_RESUME_BYTES:
        raise HTTPException(413, detail="Resume exceeds 10 MB limit")

    # TODO: replace with StoragePort.upload() when wired
    # For now store key as a local reference for testing
    from datetime import datetime, timezone
    storage_key = f"resumes/{candidate_id}/{file.filename}"
    resume_ref = ResumeRef(
        storage_key=storage_key,
        filename=file.filename,
        uploaded_at=datetime.now(timezone.utc),
        content_type=content_type,
    )
    candidate.attach_resume(resume_ref)
    await repo.save(candidate)
    return CandidateOut.from_domain(candidate)


@router.delete("/{candidate_id}/resume", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    candidate_id: uuid.UUID,
    repo: SQLAlchemyCandidateRepository = Depends(get_candidate_repo),
):
    candidate = await repo.get_by_id(candidate_id)
    if not candidate:
        raise HTTPException(404, detail=f"Candidate {candidate_id} not found")
    if not candidate.resume:
        raise HTTPException(404, detail="No resume attached")

    candidate.remove_resume()
    await repo.save(candidate)


@router.get("/{candidate_id}/resume", response_model=dict)
async def get_resume_url(
    candidate_id: uuid.UUID,
    repo: SQLAlchemyCandidateRepository = Depends(get_candidate_repo),
):
    candidate = await repo.get_by_id(candidate_id)
    if not candidate:
        raise HTTPException(404, detail=f"Candidate {candidate_id} not found")
    if not candidate.resume:
        raise HTTPException(404, detail="No resume attached")

    # TODO: return presigned URL from StoragePort
    return {
        "storage_key": candidate.resume.storage_key,
        "filename": candidate.resume.filename,
        "url": f"/static/{candidate.resume.storage_key}",  # placeholder
    }