from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260422_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    user_tier = postgresql.ENUM("FREE", "PRO", "ADMIN", name="user_tier", create_type=False)
    job_user_tier = postgresql.ENUM("FREE", "PRO", "ADMIN", name="job_user_tier", create_type=False)
    job_status = postgresql.ENUM(
        "UPLOADED",
        "VALIDATING",
        "QUEUED",
        "EXTRACTING",
        "TRANSLATING",
        "REBUILDING",
        "COMPLETED",
        "FAILED",
        name="job_status",
        create_type=False,
    )

    bind = op.get_bind()
    postgresql.ENUM("FREE", "PRO", "ADMIN", name="user_tier").create(bind, checkfirst=True)
    postgresql.ENUM("FREE", "PRO", "ADMIN", name="job_user_tier").create(bind, checkfirst=True)
    postgresql.ENUM(
        "UPLOADED",
        "VALIDATING",
        "QUEUED",
        "EXTRACTING",
        "TRANSLATING",
        "REBUILDING",
        "COMPLETED",
        "FAILED",
        name="job_status",
    ).create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("tier", user_tier, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_tier"), "users", ["tier"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("user_tier", job_user_tier, nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("result_filename", sa.String(length=255), nullable=True),
        sa.Column("visible_result_filename", sa.String(length=255), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("source_language", sa.String(length=32), nullable=False),
        sa.Column("target_language", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("translated_title", sa.String(length=512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_filename"),
    )
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    op.create_index(op.f("ix_jobs_user_id"), "jobs", ["user_id"], unique=False)
    op.create_index(op.f("ix_jobs_user_tier"), "jobs", ["user_tier"], unique=False)

    op.create_table(
        "translation_cache",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("source_language", sa.String(length=32), nullable=False),
        sa.Column("target_language", sa.String(length=32), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_text", "source_language", "target_language", name="uq_translation_cache_key"),
    )

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("translation_cache")
    op.drop_index(op.f("ix_jobs_user_tier"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_user_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_users_tier"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    bind = op.get_bind()
    postgresql.ENUM(name="job_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="job_user_tier").drop(bind, checkfirst=True)
    postgresql.ENUM(name="user_tier").drop(bind, checkfirst=True)
