from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260424_0003"
down_revision = "20260422_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("translator_provider", sa.String(length=32), nullable=False, server_default="libretranslate"),
    )
    op.alter_column("jobs", "source_language", existing_type=sa.String(length=32), type_=sa.String(length=100))
    op.alter_column("jobs", "target_language", existing_type=sa.String(length=32), type_=sa.String(length=100))
    op.alter_column("translation_cache", "source_language", existing_type=sa.String(length=32), type_=sa.String(length=140))
    op.alter_column("translation_cache", "target_language", existing_type=sa.String(length=32), type_=sa.String(length=140))
    op.alter_column("jobs", "translator_provider", server_default=None)


def downgrade() -> None:
    op.alter_column("translation_cache", "target_language", existing_type=sa.String(length=140), type_=sa.String(length=32))
    op.alter_column("translation_cache", "source_language", existing_type=sa.String(length=140), type_=sa.String(length=32))
    op.alter_column("jobs", "target_language", existing_type=sa.String(length=100), type_=sa.String(length=32))
    op.alter_column("jobs", "source_language", existing_type=sa.String(length=100), type_=sa.String(length=32))
    op.drop_column("jobs", "translator_provider")
