from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TranslationCache(Base):
    __tablename__ = "translation_cache"
    __table_args__ = (
        UniqueConstraint("normalized_text_hash", "source_language", "target_language", name="uq_translation_cache_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    normalized_text_hash: Mapped[str] = mapped_column(String(64), index=True)
    normalized_text: Mapped[str] = mapped_column(Text())
    source_language: Mapped[str] = mapped_column(String(140))
    target_language: Mapped[str] = mapped_column(String(140))
    translated_text: Mapped[str] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
