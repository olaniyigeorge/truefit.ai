"""
tests/unit/application/test_candidate_service.py
──
Unit tests for CandidateService - mock-based, no database.

All external dependencies (CandidateRepository, StoragePort) are replaced
with MagicMock / AsyncMock instances so the tests verify only the service's
orchestration logic, not the infra adapters.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.truefit_core.application.services.candidate_service import CandidateService
from src.truefit_core.domain.candidate import (
    Candidate,
    CandidateStatus,
    ContactInfo,
    ResumeRef,
)

# ─
# Fixtures
# ─


def _make_contact(email: str = "alice@example.com") -> ContactInfo:
    return ContactInfo(email=email, phone="+1-555-0100")


def _make_candidate(email: str = "alice@example.com") -> Candidate:
    return Candidate(full_name="Alice Smith", contact=_make_contact(email))


@pytest.fixture()
def candidate_repo():
    repo = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=None)
    repo.get_by_email = AsyncMock(return_value=None)
    repo.save = AsyncMock(return_value=None)
    return repo


@pytest.fixture()
def storage():
    s = AsyncMock()
    s.upload = AsyncMock(
        return_value=MagicMock(url="https://cdn.example.com/resume.pdf")
    )
    s.delete = AsyncMock(return_value=None)
    s.get_presigned_url = AsyncMock(return_value="https://cdn.example.com/signed-url")
    return s


@pytest.fixture()
def service(candidate_repo, storage) -> CandidateService:
    return CandidateService(candidate_repo=candidate_repo, storage=storage)


# ─
# register_candidate
# ─


class TestRegisterCandidate:
    async def test_registers_new_candidate_successfully(self, service, candidate_repo):
        candidate = await service.register_candidate(
            full_name="Alice Smith",
            email="alice@example.com",
        )
        assert candidate.full_name == "Alice Smith"
        assert candidate.contact.email == "alice@example.com"
        candidate_repo.save.assert_awaited_once()

    async def test_raises_if_email_already_exists(self, service, candidate_repo):
        existing = _make_candidate()
        candidate_repo.get_by_email.return_value = existing

        with pytest.raises(ValueError, match="already exists"):
            await service.register_candidate(full_name="Bob", email="alice@example.com")

        candidate_repo.save.assert_not_awaited()

    async def test_optional_phone_and_linkedin_stored_on_contact(self, service):
        candidate = await service.register_candidate(
            full_name="Alice",
            email="alice2@example.com",
            phone="+1-555-9999",
            linkedin_url="https://linkedin.com/in/alice",
        )
        assert candidate.contact.phone == "+1-555-9999"
        assert candidate.contact.linkedin_url == "https://linkedin.com/in/alice"

    async def test_check_email_before_save(self, service, candidate_repo):
        """Ensures get_by_email is called BEFORE save - order matters."""
        call_order = []
        candidate_repo.get_by_email.side_effect = (
            lambda e: call_order.append("get") or None
        )
        candidate_repo.save.side_effect = lambda c: call_order.append("save")

        await service.register_candidate(full_name="Alice", email="new@example.com")
        assert call_order == ["get", "save"]


# ─
# update_profile
# ─


class TestUpdateProfile:
    async def test_update_full_name(self, service, candidate_repo):
        original = _make_candidate()
        candidate_repo.get_by_id.return_value = original

        result = await service.update_profile(original.id, full_name="Alice Johnson")
        assert result.full_name == "Alice Johnson"
        candidate_repo.save.assert_awaited_once()

    async def test_update_phone(self, service, candidate_repo):
        original = _make_candidate()
        candidate_repo.get_by_id.return_value = original

        result = await service.update_profile(original.id, phone="+1-888-0000")
        assert result.contact.phone == "+1-888-0000"

    async def test_update_linkedin(self, service, candidate_repo):
        original = _make_candidate()
        candidate_repo.get_by_id.return_value = original

        result = await service.update_profile(
            original.id, linkedin_url="https://linkedin.com/in/new"
        )
        assert result.contact.linkedin_url == "https://linkedin.com/in/new"

    async def test_update_preserves_existing_email(self, service, candidate_repo):
        original = _make_candidate("alice@example.com")
        candidate_repo.get_by_id.return_value = original

        result = await service.update_profile(original.id, phone="+1-000-0000")
        assert result.contact.email == "alice@example.com"

    async def test_raises_if_candidate_not_found(self, service, candidate_repo):
        candidate_repo.get_by_id.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await service.update_profile(uuid.uuid4(), full_name="Ghost")

    async def test_no_changes_still_calls_save(self, service, candidate_repo):
        original = _make_candidate()
        candidate_repo.get_by_id.return_value = original

        await service.update_profile(original.id)
        candidate_repo.save.assert_awaited_once()


# ─
# upload_resume
# ─


class TestUploadResume:
    async def test_upload_resume_attaches_ref(self, service, candidate_repo, storage):
        original = _make_candidate()
        candidate_repo.get_by_id.return_value = original

        result = await service.upload_resume(
            original.id,
            filename="cv.pdf",
            data=b"%PDF-1.4 content",
        )

        assert result.resume is not None
        assert result.resume.filename == "cv.pdf"
        storage.upload.assert_awaited_once()
        candidate_repo.save.assert_awaited_once()

    async def test_storage_key_uses_candidate_id(
        self, service, candidate_repo, storage
    ):
        candidate = _make_candidate()
        candidate_repo.get_by_id.return_value = candidate

        await service.upload_resume(candidate.id, filename="cv.pdf", data=b"data")

        call_kwargs = storage.upload.call_args.kwargs
        assert str(candidate.id) in call_kwargs["key"]
        assert call_kwargs["key"].endswith("cv.pdf")

    async def test_raises_if_candidate_not_found(self, service, candidate_repo):
        candidate_repo.get_by_id.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await service.upload_resume(uuid.uuid4(), filename="cv.pdf", data=b"data")

    async def test_custom_content_type_is_passed_to_storage(
        self, service, candidate_repo, storage
    ):
        candidate = _make_candidate()
        candidate_repo.get_by_id.return_value = candidate

        await service.upload_resume(
            candidate.id,
            filename="cv.docx",
            data=b"data",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        call_kwargs = storage.upload.call_args.kwargs
        assert "wordprocessingml" in call_kwargs["content_type"]


# ─
# delete_resume
# ─


class TestDeleteResume:
    async def test_delete_resume_removes_ref(self, service, candidate_repo, storage):
        candidate = _make_candidate()
        resume = ResumeRef(
            storage_key="resumes/abc/cv.pdf",
            filename="cv.pdf",
            uploaded_at=datetime.now(timezone.utc),
        )
        candidate.attach_resume(resume)
        candidate_repo.get_by_id.return_value = candidate

        result = await service.delete_resume(candidate.id)

        assert result.resume is None
        storage.delete.assert_awaited_once_with("resumes/abc/cv.pdf")
        candidate_repo.save.assert_awaited_once()

    async def test_delete_resume_raises_if_no_resume(self, service, candidate_repo):
        candidate = _make_candidate()
        candidate_repo.get_by_id.return_value = candidate

        with pytest.raises(ValueError, match="no resume"):
            await service.delete_resume(candidate.id)

    async def test_delete_resume_raises_if_candidate_not_found(
        self, service, candidate_repo
    ):
        candidate_repo.get_by_id.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await service.delete_resume(uuid.uuid4())


# ─
# get_resume_url
# ─


class TestGetResumeUrl:
    async def test_returns_presigned_url(self, service, candidate_repo, storage):
        candidate = _make_candidate()
        candidate.attach_resume(
            ResumeRef(
                storage_key="resumes/abc/cv.pdf",
                filename="cv.pdf",
                uploaded_at=datetime.now(timezone.utc),
            )
        )
        candidate_repo.get_by_id.return_value = candidate
        storage.get_presigned_url.return_value = "https://cdn.example.com/signed"

        url = await service.get_resume_url(candidate.id)
        assert url == "https://cdn.example.com/signed"

    async def test_raises_if_no_resume(self, service, candidate_repo):
        candidate = _make_candidate()
        candidate_repo.get_by_id.return_value = candidate

        with pytest.raises(ValueError, match="no resume"):
            await service.get_resume_url(candidate.id)

    async def test_passes_expiry_to_storage(self, service, candidate_repo, storage):
        candidate = _make_candidate()
        candidate.attach_resume(
            ResumeRef(
                storage_key="resumes/abc/cv.pdf",
                filename="cv.pdf",
                uploaded_at=datetime.now(timezone.utc),
            )
        )
        candidate_repo.get_by_id.return_value = candidate

        await service.get_resume_url(candidate.id, expires_in_seconds=600)
        storage.get_presigned_url.assert_awaited_once_with(
            "resumes/abc/cv.pdf", expires_in_seconds=600
        )
