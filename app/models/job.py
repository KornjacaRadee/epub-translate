from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import UserTier


class JobStatus(StrEnum):
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    QUEUED = "queued"
    EXTRACTING = "extracting"
    TRANSLATING = "translating"
    REBUILDING = "rebuilding"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user_tier: Mapped[UserTier] = mapped_column(Enum(UserTier, name="job_user_tier"), index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, name="job_status"), default=JobStatus.UPLOADED, index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True)
    result_filename: Mapped[str] = mapped_column(String(255), nullable=True)
    visible_result_filename: Mapped[str] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(Integer())
    translator_provider: Mapped[str] = mapped_column(String(32), default="libretranslate")
    source_language: Mapped[str] = mapped_column(String(100), default="en")
    target_language: Mapped[str] = mapped_column(String(100), default="sr")
    title: Mapped[str] = mapped_column(String(512), nullable=True)
    translated_title: Mapped[str] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str] = mapped_column(Text(), nullable=True)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="jobs")
