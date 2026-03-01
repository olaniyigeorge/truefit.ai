"""
Handles candidate profile management and resume operations.
Coordinates between the Candidate aggregate and the StoragePort.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.truefit_core.common.utils import logger
from src.truefit_core.domain.candidate import Candidate, CandidateStatus, ContactInfo, ResumeRef
from src.truefit_core.application.ports import (
    CandidateRepository,
    StoragePort,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandidateService:
    def __init__(
        self,
        *,
        candidate_repo: CandidateRepository,
        storage: StoragePort,
    ) -> None:
        self._candidates = candidate_repo
        self._storage = storage

    async def register_candidate(
        self,
        *,
        full_name: str,
        email: str,
        phone: str | None = None,
        linkedin_url: str | None = None,
    ) -> Candidate:
        """
        Create and persist a new candidate.
        Raises ValueError if email is already registered.
        """
        existing = await self._candidates.get_by_email(email)
        if existing is not None:
            raise ValueError(f"A candidate with email '{email}' already exists")

        contact = ContactInfo(email=email, phone=phone, linkedin_url=linkedin_url)
        candidate = Candidate(full_name=full_name, contact=contact)
        await self._candidates.save(candidate)

        logger.info(f"Candidate registered: {candidate.id} — {email}")
        return candidate

    async def update_profile(
        self,
        candidate_id: uuid.UUID,
        *,
        full_name: str | None = None,
        phone: str | None = None,
        linkedin_url: str | None = None,
    ) -> Candidate:
        candidate = await self._get_or_raise(candidate_id)

        new_contact = None
        if phone is not None or linkedin_url is not None:
            new_contact = ContactInfo(
                email=candidate.contact.email,  # email is immutable
                phone=phone if phone is not None else candidate.contact.phone,
                linkedin_url=linkedin_url if linkedin_url is not None else candidate.contact.linkedin_url,
            )

        candidate.update_profile(full_name=full_name, contact=new_contact)
        await self._candidates.save(candidate)
        return candidate

    async def upload_resume(
        self,
        candidate_id: uuid.UUID,
        *,
        filename: str,
        data: bytes,
        content_type: str = "application/pdf",
    ) -> Candidate:
        """
        Upload resume bytes to storage and attach the reference to the candidate.
        Replaces any previously attached resume.
        """
        candidate = await self._get_or_raise(candidate_id)

        storage_key = f"resumes/{candidate_id}/{filename}"
        await self._storage.upload(
            key=storage_key,
            data=data,
            content_type=content_type,
        )

        resume_ref = ResumeRef(
            storage_key=storage_key,
            filename=filename,
            uploaded_at=_utcnow(),
            content_type=content_type,
        )
        candidate.attach_resume(resume_ref)
        await self._candidates.save(candidate)

        logger.info(f"Resume uploaded for candidate {candidate_id}: {storage_key}")
        return candidate

    async def delete_resume(self, candidate_id: uuid.UUID) -> Candidate:
        candidate = await self._get_or_raise(candidate_id)

        if candidate.resume is None:
            raise ValueError(f"Candidate {candidate_id} has no resume attached")

        await self._storage.delete(candidate.resume.storage_key)
        candidate.remove_resume()
        await self._candidates.save(candidate)

        logger.info(f"Resume removed for candidate {candidate_id}")
        return candidate

    async def get_resume_url(
        self, candidate_id: uuid.UUID, *, expires_in_seconds: int = 3600
    ) -> str:
        candidate = await self._get_or_raise(candidate_id)

        if candidate.resume is None:
            raise ValueError(f"Candidate {candidate_id} has no resume attached")

        return await self._storage.get_presigned_url(
            candidate.resume.storage_key,
            expires_in_seconds=expires_in_seconds,
        )

    # ── Internal helpers ──

    async def _get_or_raise(self, candidate_id: uuid.UUID) -> Candidate:
        candidate = await self._candidates.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        return candidate