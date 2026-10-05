"""
tests/unit/domain/test_candidate.py
──
Unit tests for the Candidate aggregate root.
No database, no I/O - pure domain logic.
"""

import uuid
from datetime import datetime, timezone

import pytest

from src.truefit_core.domain.candidate import (
    Candidate,
    CandidateStatus,
    ContactInfo,
    ResumeRef,
)

# ─
# Fixtures
# ─


def make_contact(email: str = "alice@example.com") -> ContactInfo:
    return ContactInfo(
        email=email, phone="+1-555-0100", linkedin_url="https://linkedin.com/in/alice"
    )


def make_candidate(
    full_name: str = "Alice Smith",
    email: str = "alice@example.com",
    status: CandidateStatus = CandidateStatus.ACTIVE,
) -> Candidate:
    return Candidate(
        full_name=full_name,
        contact=make_contact(email),
        status=status,
    )


def make_resume(key: str = "resumes/abc/cv.pdf") -> ResumeRef:
    return ResumeRef(
        storage_key=key,
        filename="cv.pdf",
        uploaded_at=datetime.now(timezone.utc),
    )


# ─
# ContactInfo value object
# ─


class TestContactInfo:
    def test_valid_contact_creates_successfully(self):
        contact = ContactInfo(email="bob@example.com", phone="+44-7700-900100")
        assert contact.email == "bob@example.com"

    def test_missing_at_sign_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid email"):
            ContactInfo(email="not-an-email")

    def test_empty_email_raises_value_error(self):
        with pytest.raises(ValueError):
            ContactInfo(email="")

    def test_optional_fields_default_to_none(self):
        contact = ContactInfo(email="min@example.com")
        assert contact.phone is None
        assert contact.linkedin_url is None

    def test_contact_info_equality_by_value(self):
        a = ContactInfo(email="same@example.com")
        b = ContactInfo(email="same@example.com")
        assert a == b

    def test_contact_info_inequality(self):
        a = ContactInfo(email="one@example.com")
        b = ContactInfo(email="two@example.com")
        assert a != b


# ─
# Candidate - construction & validation
# ─


class TestCandidateConstruction:
    def test_basic_creation_succeeds(self):
        c = make_candidate()
        assert c.full_name == "Alice Smith"
        assert c.status == CandidateStatus.ACTIVE
        assert c.id is not None

    def test_each_candidate_gets_unique_id(self):
        a = make_candidate()
        b = make_candidate()
        assert a.id != b.id

    def test_explicit_id_is_respected(self):
        fixed_id = uuid.uuid4()
        c = Candidate(
            candidate_id=fixed_id,
            full_name="Dave",
            contact=make_contact("dave@example.com"),
        )
        assert c.id == fixed_id

    def test_empty_full_name_raises_value_error(self):
        with pytest.raises(ValueError, match="full name cannot be empty"):
            Candidate(full_name="   ", contact=make_contact())

    def test_whitespace_full_name_is_stripped(self):
        c = Candidate(full_name="  Bob  ", contact=make_contact("bob@example.com"))
        assert c.full_name == "Bob"

    def test_default_status_is_active(self):
        c = make_candidate()
        assert c.status == CandidateStatus.ACTIVE

    def test_timestamps_are_utc_aware(self):
        c = make_candidate()
        assert c.created_at.tzinfo is not None
        assert c.updated_at.tzinfo is not None

    def test_explicit_timestamps_are_stored(self):
        ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        c = Candidate(
            full_name="Eve",
            contact=make_contact("eve@example.com"),
            created_at=ts,
            updated_at=ts,
        )
        assert c.created_at == ts

    def test_candidate_equality_by_id(self):
        fixed_id = uuid.uuid4()
        a = Candidate(
            candidate_id=fixed_id, full_name="A", contact=make_contact("a@x.com")
        )
        b = Candidate(
            candidate_id=fixed_id, full_name="B", contact=make_contact("b@x.com")
        )
        assert a == b

    def test_different_candidates_are_not_equal(self):
        a = make_candidate(email="a@x.com")
        b = make_candidate(email="b@x.com")
        assert a != b

    def test_candidate_is_hashable(self):
        c = make_candidate()
        s = {c}
        assert c in s


# ─
# Candidate - eligibility queries
# ─


class TestCandidateEligibility:
    def test_active_candidate_is_eligible(self):
        assert make_candidate().is_eligible_to_interview is True

    def test_banned_candidate_is_not_eligible(self):
        c = make_candidate(status=CandidateStatus.BANNED)
        assert c.is_eligible_to_interview is False

    def test_withdrawn_candidate_is_not_eligible(self):
        c = make_candidate(status=CandidateStatus.WITHDRAWN)
        assert c.is_eligible_to_interview is False

    def test_assert_eligible_does_not_raise_for_active(self):
        make_candidate().assert_eligible_to_interview()  # should not raise

    def test_assert_eligible_raises_for_banned(self):
        c = make_candidate(status=CandidateStatus.BANNED)
        with pytest.raises(PermissionError):
            c.assert_eligible_to_interview()


# ─
# Candidate - profile updates
# ─


class TestCandidateProfileUpdate:
    def test_update_full_name(self):
        c = make_candidate()
        before = c.updated_at
        c.update_profile(full_name="Alice Johnson")
        assert c.full_name == "Alice Johnson"
        assert c.updated_at >= before

    def test_update_contact(self):
        c = make_candidate()
        new_contact = ContactInfo(email="alice@example.com", phone="+1-999-0001")
        c.update_profile(contact=new_contact)
        assert c.contact.phone == "+1-999-0001"

    def test_update_profile_strips_whitespace(self):
        c = make_candidate()
        c.update_profile(full_name="  Padded  ")
        assert c.full_name == "Padded"

    def test_update_profile_empty_name_raises(self):
        c = make_candidate()
        with pytest.raises(ValueError, match="cannot be empty"):
            c.update_profile(full_name="   ")

    def test_banned_candidate_cannot_update_profile(self):
        c = make_candidate(status=CandidateStatus.BANNED)
        with pytest.raises(PermissionError):
            c.update_profile(full_name="New Name")

    def test_withdrawn_candidate_cannot_update_profile(self):
        c = make_candidate(status=CandidateStatus.WITHDRAWN)
        with pytest.raises(PermissionError):
            c.update_profile(full_name="New Name")


# ─
# Candidate - resume management
# ─


class TestCandidateResume:
    def test_attach_resume_to_active_candidate(self):
        c = make_candidate()
        resume = make_resume()
        c.attach_resume(resume)
        assert c.resume == resume

    def test_resume_defaults_to_none(self):
        assert make_candidate().resume is None

    def test_attach_resume_updates_timestamp(self):
        c = make_candidate()
        before = c.updated_at
        c.attach_resume(make_resume())
        assert c.updated_at >= before

    def test_can_replace_existing_resume(self):
        c = make_candidate()
        c.attach_resume(make_resume("resumes/abc/cv_v1.pdf"))
        new_resume = make_resume("resumes/abc/cv_v2.pdf")
        c.attach_resume(new_resume)
        assert c.resume.storage_key == "resumes/abc/cv_v2.pdf"

    def test_remove_resume(self):
        c = make_candidate()
        c.attach_resume(make_resume())
        c.remove_resume()
        assert c.resume is None

    def test_banned_candidate_cannot_attach_resume(self):
        c = make_candidate(status=CandidateStatus.BANNED)
        with pytest.raises(PermissionError):
            c.attach_resume(make_resume())


# ─
# Candidate - status transitions
# ─


class TestCandidateStatusTransitions:
    def test_active_candidate_can_be_banned(self):
        c = make_candidate()
        c.ban(reason="policy_violation")
        assert c.status == CandidateStatus.BANNED

    def test_banning_already_banned_candidate_raises(self):
        c = make_candidate(status=CandidateStatus.BANNED)
        with pytest.raises(ValueError, match="already banned"):
            c.ban(reason="double_ban")

    def test_candidate_can_withdraw(self):
        c = make_candidate()
        c.withdraw()
        assert c.status == CandidateStatus.WITHDRAWN

    def test_withdrawn_candidate_clears_active_interviews(self):
        job_id = uuid.uuid4()
        c = make_candidate()
        c.register_active_interview(job_id)
        c.withdraw()
        assert not c.has_active_interview_for(job_id)

    def test_double_withdraw_raises(self):
        c = make_candidate()
        c.withdraw()
        with pytest.raises(ValueError, match="already withdrawn"):
            c.withdraw()


# ─
# Candidate - active interview tracking
# ─


class TestCandidateInterviewTracking:
    def test_register_active_interview(self):
        job_id = uuid.uuid4()
        c = make_candidate()
        c.register_active_interview(job_id)
        assert c.has_active_interview_for(job_id) is True

    def test_has_no_active_interview_initially(self):
        c = make_candidate()
        assert c.has_active_interview_for(uuid.uuid4()) is False

    def test_cannot_register_duplicate_interview_for_same_job(self):
        job_id = uuid.uuid4()
        c = make_candidate()
        c.register_active_interview(job_id)
        with pytest.raises(ValueError, match="already has an active interview"):
            c.register_active_interview(job_id)

    def test_can_register_interviews_for_different_jobs(self):
        c = make_candidate()
        job_a, job_b = uuid.uuid4(), uuid.uuid4()
        c.register_active_interview(job_a)
        c.register_active_interview(job_b)
        assert c.has_active_interview_for(job_a)
        assert c.has_active_interview_for(job_b)

    def test_release_active_interview(self):
        job_id = uuid.uuid4()
        c = make_candidate()
        c.register_active_interview(job_id)
        c.release_active_interview(job_id)
        assert c.has_active_interview_for(job_id) is False

    def test_release_nonexistent_interview_is_safe(self):
        c = make_candidate()
        c.release_active_interview(uuid.uuid4())  # should not raise

    def test_banned_candidate_cannot_register_interview(self):
        c = make_candidate(status=CandidateStatus.BANNED)
        with pytest.raises(PermissionError):
            c.register_active_interview(uuid.uuid4())
