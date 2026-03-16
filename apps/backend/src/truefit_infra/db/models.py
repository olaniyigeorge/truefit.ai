from __future__ import annotations
import enum
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, relationship, mapped_column


# -----
# Base
# -----

class Base(DeclarativeBase):
    pass



def utcnow() -> datetime:
    return datetime.now()


# ----------------------------
# Enums
# ----------------------------

class UserRole(str, enum.Enum):
    admin = "admin"
    recruiter = "recruiter"
    candidate = "candidate"


class JobStatus(str, enum.Enum):
    draft = "draft"
    open = "open"
    closed = "closed"


class ApplicationSource(str, enum.Enum):
    applied = "applied"
    invited = "invited"


class ApplicationStatus(str, enum.Enum):
    new = "new"
    interviewing = "interviewing"
    shortlisted = "shortlisted"
    rejected = "rejected"
    hired = "hired"


class SessionStatus(str, enum.Enum):
    created = "created"
    active = "active"
    ended = "ended"
    cancelled = "cancelled"
    failed = "failed"


class ParticipantType(str, enum.Enum):
    candidate = "candidate"
    recruiter = "recruiter"
    agent = "agent"
    system = "system"


class Speaker(str, enum.Enum):
    candidate = "candidate"
    agent = "agent"
    system = "system"


class Modality(str, enum.Enum):
    text = "text"
    audio = "audio"
    video = "video"
    mixed = "mixed"


class StorageProvider(str, enum.Enum):
    local = "local"
    gcs = "gcs"


class AssetKind(str, enum.Enum):
    audio_chunk = "audio_chunk"
    video_chunk = "video_chunk"
    recording = "recording"
    image = "image"
    resume = "resume"
    report = "report"


class Recommendation(str, enum.Enum):
    strong_yes = "strong_yes"
    yes = "yes"
    maybe = "maybe"
    no = "no"
    strong_no = "strong_no"


class SessionEventType(str, enum.Enum):
    ws_connected = "ws_connected"
    ws_disconnected = "ws_disconnected"
    rtc_connected = "rtc_connected"
    rtc_disconnected = "rtc_disconnected"
    interrupt_detected = "interrupt_detected"
    barge_in = "barge_in"
    agent_tool_call = "agent_tool_call"
    candidate_muted = "candidate_muted"
    candidate_unmuted = "candidate_unmuted"
    error = "error"


# -------
# Tables
# --------


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    contact: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default={}
    )
    billing: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default={}
    )

    logo_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    headcount: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ── Relationships ───
    creator: Mapped["User"] = relationship(
        "User",
        foreign_keys=[created_by],
        back_populates="orgs_created",
    )
    users: Mapped[list["User"]] = relationship(
        "User",
        foreign_keys="User.org_id",
        back_populates="org",
    )
    job_listings: Mapped[list["JobListing"]] = relationship(back_populates="org")
    rubrics: Mapped[list["Rubric"]] = relationship(back_populates="org")

    __table_args__ = (
        Index("ix_orgs_slug", "slug", unique=True),
        Index("ix_orgs_status", "status"),
        Index("ix_orgs_created_by", "created_by"),
    )

    def __repr__(self) -> str:
        return f"Org(id={self.id}, name={self.name!r}, slug={self.slug!r})"


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    org_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="SET NULL"),
        nullable=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    role: Mapped[UserRole] = mapped_column(String(32), nullable=False)  # stored as string enum
    auth_provider: Mapped[str] = mapped_column(String(64), nullable=False, default="firebase")
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    org: Mapped[Optional["Org"]] = relationship(
        "Org",
        foreign_keys=[org_id],
        back_populates="users",
    )
    orgs_created: Mapped[list["Org"]] = relationship(
        "Org",
        foreign_keys="Org.created_by",
        back_populates="creator",
    )
    candidate_profile: Mapped[Optional["CandidateProfile"]] = relationship(back_populates="user", uselist=False)
    created_jobs: Mapped[list["JobListing"]] = relationship(back_populates="created_by_user")


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    headline: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    years_experience: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    skills: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))

    resume_asset_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="candidate_profile")
    applications: Mapped[list["Application"]] = relationship(back_populates="candidate")



class JobListing(Base):
    __tablename__ = "job_listings"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft"
    )

    # Denormalised from requirements.experience_level for indexed filtering
    experience_level: Mapped[str] = mapped_column(String(32), nullable=False)

    # Structured skill data: [{name, required, weight, min_years}, ...]
    skills: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=[]
    )

    # Role-level requirements (education, certifications, location, etc.)
    requirements: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default={}
    )

    # AI interview configuration
    interview_config: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default={}
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ── Relationships ─
    org: Mapped["Org"] = relationship(back_populates="job_listings")
    created_by_user: Mapped["User"] = relationship(back_populates="created_jobs")
    applications: Mapped[list["Application"]] = relationship(back_populates="job")

    __table_args__ = (
        Index("ix_job_listings_org_id", "org_id"),
        Index("ix_job_listings_status", "status"),
        Index("ix_job_listings_experience_level", "experience_level"),
        Index("ix_job_listings_org_status", "org_id", "status"),
        Index("ix_job_listings_org_exp", "org_id", "experience_level"),
    )

    def __repr__(self) -> str:
        return (
            f"JobListing(id={self.id}, title={self.title!r}, "
            f"status={self.status}, org_id={self.org_id})"
        )

class Rubric(Base):
    __tablename__ = "rubrics"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    org: Mapped["Org"] = relationship(back_populates="rubrics")
    criteria: Mapped[list["RubricCriterion"]] = relationship(back_populates="rubric", cascade="all, delete-orphan")


class RubricCriterion(Base):
    __tablename__ = "rubric_criteria"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    rubric_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("rubrics.id", ondelete="CASCADE"), nullable=False)

    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    weight: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, server_default=text("1.0"))
    max_score: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    rubric: Mapped["Rubric"] = relationship(back_populates="criteria")

    __table_args__ = (
        UniqueConstraint("rubric_id", "key", name="uq_rubric_criteria_rubric_key"),
    )


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    job_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("job_listings.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False)

    source: Mapped[ApplicationSource] = mapped_column(String(32), nullable=False, default=ApplicationSource.applied.value)
    status: Mapped[ApplicationStatus] = mapped_column(String(32), nullable=False, default=ApplicationStatus.new.value)

    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default={})

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    job: Mapped["JobListing"] = relationship(back_populates="applications")
    candidate: Mapped["CandidateProfile"] = relationship(back_populates="applications")
    sessions: Mapped[list["InterviewSession"]] = relationship(back_populates="application", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id", name="uq_applications_job_candidate"),
        Index("ix_applications_job_status", "job_id", "status"),
    )


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    application_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)

    round: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    status: Mapped[SessionStatus] = mapped_column(String(32), nullable=False, default=SessionStatus.created.value)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    agent_version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default={})
    realtime: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default={})

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    application: Mapped["Application"] = relationship(back_populates="sessions")
    participants: Mapped[list["InterviewParticipant"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    turns: Mapped[list["InterviewTurn"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    events: Mapped[list["SessionEvent"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    evaluation: Mapped[Optional["Evaluation"]] = relationship(back_populates="session", uselist=False)


class InterviewParticipant(Base):
    __tablename__ = "interview_participants"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)

    user_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    participant_type: Mapped[ParticipantType] = mapped_column(String(32), nullable=False)

    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    connection_meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default={})

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    session: Mapped["InterviewSession"] = relationship(back_populates="participants")


class InterviewTurn(Base):
    __tablename__ = "interview_turns"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)

    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[Speaker] = mapped_column(String(32), nullable=False)
    modality: Mapped[Modality] = mapped_column(String(32), nullable=False)

    turn_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default={})

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    session: Mapped["InterviewSession"] = relationship(back_populates="turns")

    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_interview_turns_session_seq"),
        Index("ix_interview_turns_session_seq", "session_id", "seq"),
    )


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))

    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)  # candidate | org | session (simple string)
    owner_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    session_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="SET NULL"), nullable=True)
    turn_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_turns.id", ondelete="SET NULL"), nullable=True)

    kind: Mapped[AssetKind] = mapped_column(String(32), nullable=False)
    storage_provider: Mapped[StorageProvider] = mapped_column(String(16), nullable=False, default=StorageProvider.local.value)
    uri: Mapped[str] = mapped_column(Text, nullable=False)

    content_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    checksum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_media_assets_session", "session_id"),
        Index("ix_media_assets_turn", "turn_id"),
        Index("ix_media_assets_owner", "owner_type", "owner_id"),
    )


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))

    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)
    turn_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_turns.id", ondelete="SET NULL"), nullable=True)

    source_asset_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False)

    engine: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    transcript_text: Mapped[str] = mapped_column(Text, nullable=False)
    segments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default={})

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_transcripts_session", "session_id"),
        Index("ix_transcripts_turn", "turn_id"),
    )


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, unique=True)

    rubric_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("rubrics.id", ondelete="SET NULL"), nullable=True)

    overall_score: Mapped[Optional[float]] = mapped_column(Numeric(8, 3), nullable=True)
    recommendation: Mapped[Optional[Recommendation]] = mapped_column(String(32), nullable=True)

    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strengths: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=[])
    concerns: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=[])

    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default={})
    report_asset_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    session: Mapped["InterviewSession"] = relationship(back_populates="evaluation")

    __table_args__ = (
        Index("ix_evaluations_recommendation", "recommendation"),
    )


class EvaluationScore(Base):
    __tablename__ = "evaluation_scores"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))

    evaluation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False)
    criterion_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("rubric_criteria.id", ondelete="RESTRICT"), nullable=False)

    score: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default={})

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("evaluation_id", "criterion_id", name="uq_eval_scores_eval_criterion"),
        Index("ix_eval_scores_eval", "evaluation_id"),
    )


class SessionEvent(Base):
    __tablename__ = "session_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)

    type: Mapped[SessionEventType] = mapped_column(String(64), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default={})

    session: Mapped["InterviewSession"] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_session_events_session_at", "session_id", "at"),
    )