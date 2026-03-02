from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from src.truefit_core.domain.candidate import Candidate
from truefit_core.application.ports import CandidateRepository, StoragePort


@dataclass(frozen=True)
class GetCandidateResponse:
    candidate_id: uuid.UUID
    full_name: str
    email: str
    phone: Optional[str]
    linkedin_url: Optional[str]
    status: str
    has_resume: bool
    resume_filename: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, c: Candidate) -> "GetCandidateResponse":
        return cls(
            candidate_id=c.id,
            full_name=c.full_name,
            email=c.contact.email,
            phone=c.contact.phone,
            linkedin_url=c.contact.linkedin_url,
            status=c.status.value,
            has_resume=c.resume is not None,
            resume_filename=c.resume.filename if c.resume else None,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
        )


async def get_candidate(
    candidate_id: uuid.UUID,
    *,
    candidate_repo: CandidateRepository,
) -> GetCandidateResponse:
    candidate = await candidate_repo.get_by_id(candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    return GetCandidateResponse.from_domain(candidate)


async def get_resume_download_url(
    candidate_id: uuid.UUID,
    *,
    candidate_repo: CandidateRepository,
    storage: StoragePort,
    expires_in_seconds: int = 3600,
) -> str:
    candidate = await candidate_repo.get_by_id(candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    if candidate.resume is None:
        raise ValueError(f"Candidate {candidate_id} has no resume")
    return await storage.get_presigned_url(
        candidate.resume.storage_key,
        expires_in_seconds=expires_in_seconds,
    )