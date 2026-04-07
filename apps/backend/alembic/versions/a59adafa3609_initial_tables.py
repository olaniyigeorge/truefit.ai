"""initial tables

Revision ID: a59adafa3609
Revises:
Create Date: 2026-03-09 14:27:51.519926

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a59adafa3609"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # ── TIER 1: No dependencies ─────

    # users created WITHOUT org_id FK (circular: users ↔ orgs)
    op.create_table(
        "users",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("org_id", sa.UUID(), nullable=True),  # FK added after orgs is created
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("auth_provider", sa.String(length=64), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    # ── TIER 2: Depends on users only

    # orgs depends on users.created_by
    op.create_table(
        "orgs",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=150), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "contact",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "billing",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("logo_url", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("headcount", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_orgs_created_by", "orgs", ["created_by"], unique=False)
    op.create_index("ix_orgs_slug", "orgs", ["slug"], unique=True)
    op.create_index("ix_orgs_status", "orgs", ["status"], unique=False)

    # Now that orgs exists, add the FK from users.org_id -> orgs.id
    op.create_foreign_key(
        "fk_users_org_id", "users", "orgs", ["org_id"], ["id"], ondelete="SET NULL"
    )

    # ── TIER 3: Depends on orgs ────

    op.create_table(
        "rubrics",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "rubric_criteria",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("rubric_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "weight",
            sa.Numeric(precision=6, scale=3),
            server_default=sa.text("1.0"),
            nullable=False,
        ),
        sa.Column(
            "max_score", sa.Integer(), server_default=sa.text("5"), nullable=False
        ),
        sa.Column(
            "order_index", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["rubric_id"], ["rubrics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rubric_id", "key", name="uq_rubric_criteria_rubric_key"),
    )

    op.create_table(
        "job_listings",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("experience_level", sa.String(length=32), nullable=False),
        sa.Column(
            "skills",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "requirements",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "interview_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_listings_experience_level",
        "job_listings",
        ["experience_level"],
        unique=False,
    )
    op.create_index(
        "ix_job_listings_org_exp",
        "job_listings",
        ["org_id", "experience_level"],
        unique=False,
    )
    op.create_index("ix_job_listings_org_id", "job_listings", ["org_id"], unique=False)
    op.create_index(
        "ix_job_listings_org_status", "job_listings", ["org_id", "status"], unique=False
    )
    op.create_index("ix_job_listings_status", "job_listings", ["status"], unique=False)

    # media_assets created WITHOUT session_id and turn_id FKs (circular dependency)
    # those FKs are added after interview_sessions and interview_turns are created
    op.create_table(
        "media_assets",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),  # FK added later
        sa.Column("turn_id", sa.UUID(), nullable=True),  # FK added later
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("storage_provider", sa.String(length=16), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_assets_owner",
        "media_assets",
        ["owner_type", "owner_id"],
        unique=False,
    )
    op.create_index(
        "ix_media_assets_session", "media_assets", ["session_id"], unique=False
    )
    op.create_index("ix_media_assets_turn", "media_assets", ["turn_id"], unique=False)

    # ── TIER 4: Depends on users + media_assets ──

    op.create_table(
        "candidate_profiles",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("headline", sa.String(length=255), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("years_experience", sa.Integer(), nullable=True),
        sa.Column(
            "skills",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("resume_asset_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["resume_asset_id"], ["media_assets.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    # ── TIER 5: Depends on candidate_profiles + job_listings ───

    op.create_table(
        "applications",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("candidate_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["candidate_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["job_listings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id", "candidate_id", name="uq_applications_job_candidate"
        ),
    )
    op.create_index(
        "ix_applications_job_status", "applications", ["job_id", "status"], unique=False
    )

    # ── TIER 6: Depends on applications ────

    op.create_table(
        "interview_sessions",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("application_id", sa.UUID(), nullable=False),
        sa.Column("round", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agent_version", sa.String(length=128), nullable=True),
        sa.Column(
            "context_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "realtime",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── TIER 7: Depends on interview_sessions ────

    op.create_table(
        "interview_turns",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(length=32), nullable=False),
        sa.Column("modality", sa.String(length=32), nullable=False),
        sa.Column("turn_text", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["interview_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "seq", name="uq_interview_turns_session_seq"),
    )
    op.create_index(
        "ix_interview_turns_session_seq",
        "interview_turns",
        ["session_id", "seq"],
        unique=False,
    )

    # Now add the deferred FKs on media_assets
    op.create_foreign_key(
        "fk_media_assets_session_id",
        "media_assets",
        "interview_sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_media_assets_turn_id",
        "media_assets",
        "interview_turns",
        ["turn_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "interview_participants",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("participant_type", sa.String(length=32), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "connection_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["interview_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "session_events",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["interview_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_session_events_session_at",
        "session_events",
        ["session_id", "at"],
        unique=False,
    )

    # ── TIER 8: Depends on interview_sessions + media_assets + interview_turns

    op.create_table(
        "transcripts",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=True),
        sa.Column("source_asset_id", sa.UUID(), nullable=False),
        sa.Column("engine", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("transcript_text", sa.Text(), nullable=False),
        sa.Column(
            "segments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["interview_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"], ["media_assets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["interview_turns.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transcripts_session", "transcripts", ["session_id"], unique=False
    )
    op.create_index("ix_transcripts_turn", "transcripts", ["turn_id"], unique=False)

    op.create_table(
        "evaluations",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("rubric_id", sa.UUID(), nullable=True),
        sa.Column("overall_score", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("recommendation", sa.String(length=32), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "strengths",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "concerns",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("report_asset_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["report_asset_id"], ["media_assets.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["rubric_id"], ["rubrics.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["interview_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_index(
        "ix_evaluations_recommendation", "evaluations", ["recommendation"], unique=False
    )

    op.create_table(
        "evaluation_scores",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("evaluation_id", sa.UUID(), nullable=False),
        sa.Column("criterion_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["criterion_id"], ["rubric_criteria.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"], ["evaluations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_id", "criterion_id", name="uq_eval_scores_eval_criterion"
        ),
    )
    op.create_index(
        "ix_eval_scores_eval", "evaluation_scores", ["evaluation_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop in reverse dependency order
    op.drop_index("ix_eval_scores_eval", table_name="evaluation_scores")
    op.drop_table("evaluation_scores")
    op.drop_index("ix_evaluations_recommendation", table_name="evaluations")
    op.drop_table("evaluations")
    op.drop_index("ix_transcripts_turn", table_name="transcripts")
    op.drop_index("ix_transcripts_session", table_name="transcripts")
    op.drop_table("transcripts")
    op.drop_index("ix_session_events_session_at", table_name="session_events")
    op.drop_table("session_events")
    op.drop_table("interview_participants")
    # Drop deferred FKs on media_assets before dropping the tables they reference
    op.drop_constraint("fk_media_assets_turn_id", "media_assets", type_="foreignkey")
    op.drop_constraint("fk_media_assets_session_id", "media_assets", type_="foreignkey")
    op.drop_index("ix_interview_turns_session_seq", table_name="interview_turns")
    op.drop_table("interview_turns")
    op.drop_table("interview_sessions")
    op.drop_index("ix_applications_job_status", table_name="applications")
    op.drop_table("applications")
    op.drop_table("candidate_profiles")
    op.drop_index("ix_media_assets_turn", table_name="media_assets")
    op.drop_index("ix_media_assets_session", table_name="media_assets")
    op.drop_index("ix_media_assets_owner", table_name="media_assets")
    op.drop_table("media_assets")
    op.drop_index("ix_job_listings_status", table_name="job_listings")
    op.drop_index("ix_job_listings_org_status", table_name="job_listings")
    op.drop_index("ix_job_listings_org_id", table_name="job_listings")
    op.drop_index("ix_job_listings_org_exp", table_name="job_listings")
    op.drop_index("ix_job_listings_experience_level", table_name="job_listings")
    op.drop_table("job_listings")
    op.drop_table("rubric_criteria")
    op.drop_table("rubrics")
    # Drop deferred FK on users before dropping orgs
    op.drop_constraint("fk_users_org_id", "users", type_="foreignkey")
    op.drop_index("ix_orgs_status", table_name="orgs")
    op.drop_index("ix_orgs_slug", table_name="orgs")
    op.drop_index("ix_orgs_created_by", table_name="orgs")
    op.drop_table("orgs")
    op.drop_table("users")
