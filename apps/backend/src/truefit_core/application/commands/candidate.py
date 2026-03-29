from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from src.truefit_core.application.services import CandidateService
from src.truefit_core.domain.candidate import Candidate


@dataclass(frozen=True)
class RegisterCandidateCommand:
    full_name: str
    email: str
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None


@dataclass(frozen=True)
class UpdateCandidateProfileCommand:
    candidate_id: uuid.UUID
    full_name: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None


@dataclass(frozen=True)
class UploadResumeCommand:
    candidate_id: uuid.UUID
    filename: str
    data: bytes
    content_type: str = "application/pdf"


@dataclass(frozen=True)
class DeleteResumeCommand:
    candidate_id: uuid.UUID


# ──
# Response dataclasses
# ──


@dataclass(frozen=True)
class CandidateResponse:
    candidate_id: uuid.UUID
    full_name: str
    email: str
    phone: Optional[str]
    linkedin_url: Optional[str]
    status: str
    has_resume: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, c: Candidate) -> "CandidateResponse":
        return cls(
            candidate_id=c.id,
            full_name=c.full_name,
            email=c.contact.email,
            phone=c.contact.phone,
            linkedin_url=c.contact.linkedin_url,
            status=c.status.value,
            has_resume=c.resume is not None,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
        )


@dataclass(frozen=True)
class ResumeUploadResponse:
    candidate_id: uuid.UUID
    filename: str
    storage_key: str
    content_type: str


# ────
# Handlers
# ────


async def handle_register_candidate(
    cmd: RegisterCandidateCommand,
    *,
    candidate_service: CandidateService,
) -> CandidateResponse:
    if not cmd.full_name.strip():
        raise ValueError("full_name is required")
    if not cmd.email.strip():
        raise ValueError("email is required")

    candidate = await candidate_service.register_candidate(
        full_name=cmd.full_name,
        email=cmd.email,
        phone=cmd.phone,
        linkedin_url=cmd.linkedin_url,
    )
    return CandidateResponse.from_domain(candidate)


async def handle_update_candidate_profile(
    cmd: UpdateCandidateProfileCommand,
    *,
    candidate_service: CandidateService,
) -> CandidateResponse:
    if all(v is None for v in (cmd.full_name, cmd.phone, cmd.linkedin_url)):
        raise ValueError("At least one field must be provided to update")

    candidate = await candidate_service.update_profile(
        cmd.candidate_id,
        full_name=cmd.full_name,
        phone=cmd.phone,
        linkedin_url=cmd.linkedin_url,
    )
    return CandidateResponse.from_domain(candidate)


async def handle_upload_resume(
    cmd: UploadResumeCommand,
    *,
    candidate_service: CandidateService,
) -> ResumeUploadResponse:
    if not cmd.data:
        raise ValueError("Resume file data cannot be empty")
    if not cmd.filename.strip():
        raise ValueError("filename is required")

    candidate = await candidate_service.upload_resume(
        cmd.candidate_id,
        filename=cmd.filename,
        data=cmd.data,
        content_type=cmd.content_type,
    )

    return ResumeUploadResponse(
        candidate_id=candidate.id,
        filename=cmd.filename,
        storage_key=candidate.resume.storage_key,
        content_type=cmd.content_type,
    )


async def handle_delete_resume(
    cmd: DeleteResumeCommand,
    *,
    candidate_service: CandidateService,
) -> CandidateResponse:
    candidate = await candidate_service.delete_resume(cmd.candidate_id)
    return CandidateResponse.from_domain(candidate)
