from __future__ import annotations

import hashlib

from alembic import op
import sqlalchemy as sa


revision = "20260422_0002"
down_revision = "20260422_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("translation_cache", sa.Column("normalized_text_hash", sa.String(length=64), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, normalized_text FROM translation_cache")).fetchall()
    for row in rows:
        normalized_text = row.normalized_text or ""
        normalized_text_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        bind.execute(
            sa.text("UPDATE translation_cache SET normalized_text_hash = :normalized_text_hash WHERE id = :id"),
            {"normalized_text_hash": normalized_text_hash, "id": row.id},
        )

    op.alter_column("translation_cache", "normalized_text_hash", nullable=False)
    op.drop_constraint("uq_translation_cache_key", "translation_cache", type_="unique")
    op.create_unique_constraint(
        "uq_translation_cache_key",
        "translation_cache",
        ["normalized_text_hash", "source_language", "target_language"],
    )
    op.create_index(op.f("ix_translation_cache_normalized_text_hash"), "translation_cache", ["normalized_text_hash"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_translation_cache_normalized_text_hash"), table_name="translation_cache")
    op.drop_constraint("uq_translation_cache_key", "translation_cache", type_="unique")
    op.create_unique_constraint(
        "uq_translation_cache_key",
        "translation_cache",
        ["normalized_text", "source_language", "target_language"],
    )
    op.drop_column("translation_cache", "normalized_text_hash")
