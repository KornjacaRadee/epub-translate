from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CreditTransactionType(StrEnum):
    FREE_SIGNUP_CREDIT = "free_signup_credit"
    PURCHASE = "purchase"
    SPEND = "spend"
    REFUND = "refund"
    ADMIN_ADJUSTMENT = "admin_adjustment"


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    transaction_type: Mapped[CreditTransactionType] = mapped_column(
        Enum(CreditTransactionType, name="credit_transaction_type"),
        index=True,
    )
    credit_amount: Mapped[int] = mapped_column(Integer())
    balance_after: Mapped[int] = mapped_column(Integer())
    paddle_event_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=True)
    paddle_transaction_id: Mapped[str] = mapped_column(String(255), nullable=True)
    package_key: Mapped[str] = mapped_column(String(64), nullable=True)
    payment_amount: Mapped[str] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(16), nullable=True)
    payment_status: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="credit_transactions")
    job = relationship("Job")
