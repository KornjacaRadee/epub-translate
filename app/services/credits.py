from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.credit_transaction import CreditTransaction, CreditTransactionType
from app.models.job import Job
from app.models.user import User


SIGNUP_CREDITS = 1


@dataclass(frozen=True, slots=True)
class CreditPackage:
    key: str
    credits: int
    price_label: str
    currency: str
    settings_price_attr: str


CREDIT_PACKAGES: dict[str, CreditPackage] = {
    "credits_10": CreditPackage("credits_10", 10, "2.99", "EUR", "paddle_price_id_10_credits"),
    "credits_50": CreditPackage("credits_50", 50, "7.99", "EUR", "paddle_price_id_50_credits"),
    "credits_120": CreditPackage("credits_120", 120, "14.99", "EUR", "paddle_price_id_120_credits"),
}


def translation_job_credit_cost() -> int:
    if not credits_enabled():
        return 0
    # TODO: Replace this fixed default with dynamic pricing based on EPUB length or token estimate.
    return max(1, settings.translation_job_credit_cost)


def credits_enabled() -> bool:
    return settings.environment != "local"


def credit_error_message(required: int) -> str:
    return f"You need {required} credits to translate this book. Buy credits to continue."


def package_price_id(package: CreditPackage) -> str | None:
    return getattr(settings, package.settings_price_attr)


def available_credit_packages() -> list[CreditPackage]:
    return list(CREDIT_PACKAGES.values())


def get_credit_package(package_key: str) -> CreditPackage:
    package = CREDIT_PACKAGES.get(package_key)
    if package is None:
        raise ValueError("Unknown credit package.")
    return package


def create_credit_transaction(
    db: Session,
    *,
    user: User,
    transaction_type: CreditTransactionType,
    credit_amount: int,
    job: Job | None = None,
    paddle_event_id: str | None = None,
    paddle_transaction_id: str | None = None,
    package_key: str | None = None,
    payment_amount: str | None = None,
    currency: str | None = None,
    payment_status: str | None = None,
) -> CreditTransaction:
    user.credit_balance += credit_amount
    transaction = CreditTransaction(
        user_id=user.id,
        job_id=job.id if job else None,
        transaction_type=transaction_type,
        credit_amount=credit_amount,
        balance_after=user.credit_balance,
        paddle_event_id=paddle_event_id,
        paddle_transaction_id=paddle_transaction_id,
        package_key=package_key,
        payment_amount=payment_amount,
        currency=currency,
        payment_status=payment_status,
    )
    db.add(user)
    db.add(transaction)
    db.flush()
    return transaction


def grant_signup_credit(db: Session, user: User) -> CreditTransaction | None:
    if not credits_enabled():
        return None
    return create_credit_transaction(
        db,
        user=user,
        transaction_type=CreditTransactionType.FREE_SIGNUP_CREDIT,
        credit_amount=SIGNUP_CREDITS,
    )


def ensure_user_has_credits(user: User, required: int | None = None) -> None:
    if not credits_enabled():
        return
    required = required if required is not None else translation_job_credit_cost()
    if user.credit_balance < required:
        raise ValueError(credit_error_message(required))


def spend_credits_for_job(db: Session, *, user: User, job: Job, credits: int) -> CreditTransaction | None:
    if not credits_enabled() or credits <= 0:
        return None
    locked_user = db.get(User, user.id, with_for_update=True) or user
    ensure_user_has_credits(locked_user, credits)
    transaction = create_credit_transaction(
        db,
        user=locked_user,
        transaction_type=CreditTransactionType.SPEND,
        credit_amount=-credits,
        job=job,
    )
    job.credits_charged = credits
    job.credit_spend_transaction_id = transaction.id
    db.add(job)
    db.flush()
    return transaction


def paddle_event_already_processed(db: Session, paddle_event_id: str) -> bool:
    return db.scalar(
        select(CreditTransaction.id).where(CreditTransaction.paddle_event_id == paddle_event_id)
    ) is not None


def add_purchase_credits(
    db: Session,
    *,
    user_id: uuid.UUID,
    package_key: str,
    paddle_event_id: str,
    paddle_transaction_id: str | None,
    payment_amount: str | None,
    currency: str | None,
    payment_status: str | None,
) -> CreditTransaction | None:
    if paddle_event_already_processed(db, paddle_event_id):
        return None
    package = get_credit_package(package_key)
    user = db.get(User, user_id, with_for_update=True)
    if user is None:
        raise ValueError("Payment user was not found.")
    transaction = create_credit_transaction(
        db,
        user=user,
        transaction_type=CreditTransactionType.PURCHASE,
        credit_amount=package.credits,
        paddle_event_id=paddle_event_id,
        paddle_transaction_id=paddle_transaction_id,
        package_key=package.key,
        payment_amount=payment_amount,
        currency=currency,
        payment_status=payment_status,
    )
    return transaction


def mark_job_failed_for_refund(db: Session, job: Job, *, detail: str) -> None:
    job.failed_at = datetime.now(timezone.utc)
    db.add(job)
    db.flush()


def find_refundable_failed_jobs(db: Session) -> list[Job]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.refund_delay_minutes)
    return list(
        db.scalars(
            select(Job)
            .where(Job.failed_at.is_not(None))
            .where(Job.failed_at <= cutoff)
            .where(Job.refunded_at.is_(None))
            .where(Job.credits_charged > 0)
        )
    )


def refund_failed_job(db: Session, job: Job) -> CreditTransaction | None:
    locked_job = db.get(Job, job.id, with_for_update=True)
    if locked_job is None or locked_job.refunded_at is not None or locked_job.credits_charged <= 0:
        return None
    user = db.get(User, locked_job.user_id, with_for_update=True)
    if user is None:
        return None
    transaction = create_credit_transaction(
        db,
        user=user,
        transaction_type=CreditTransactionType.REFUND,
        credit_amount=locked_job.credits_charged,
        job=locked_job,
    )
    locked_job.refunded_at = datetime.now(timezone.utc)
    db.add(locked_job)
    db.flush()
    return transaction
