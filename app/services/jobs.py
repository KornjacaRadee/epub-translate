from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.job import Job, JobStatus
from app.models.user import User, UserTier
from app.services.app_settings import get_global_free_active_job_limit


ACTIVE_FREE_STATUSES = (
    JobStatus.UPLOADED,
    JobStatus.VALIDATING,
    JobStatus.QUEUED,
    JobStatus.EXTRACTING,
    JobStatus.TRANSLATING,
    JobStatus.REBUILDING,
)


def active_job_statuses() -> tuple[JobStatus, ...]:
    return ACTIVE_FREE_STATUSES


def find_recoverable_jobs(db: Session, *, user: User | None = None) -> list[Job]:
    now = datetime.now(timezone.utc)
    recovery_cutoff = now - timedelta(seconds=settings.job_recovery_grace_seconds)
    stale_cutoff = now - timedelta(seconds=settings.stale_job_timeout_seconds)
    stmt = select(Job).where(
        Job.status.in_(active_job_statuses()),
        Job.updated_at <= recovery_cutoff,
        Job.updated_at > stale_cutoff,
    )
    if user is not None:
        stmt = stmt.where(Job.user_id == user.id)
    return list(db.scalars(stmt))


def mark_jobs_requeued(db: Session, jobs: list[Job]) -> int:
    if not jobs:
        return 0
    now = datetime.now(timezone.utc)
    for job in jobs:
        job.updated_at = now
        db.add(job)
    db.commit()
    return len(jobs)


def mark_stale_active_jobs(db: Session, *, user: User | None = None) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.stale_job_timeout_seconds)
    stmt = select(Job).where(
        Job.status.in_(active_job_statuses()),
        Job.updated_at < cutoff,
    )
    if user is not None:
        stmt = stmt.where(Job.user_id == user.id)

    stale_jobs = list(db.scalars(stmt))
    for job in stale_jobs:
        progress = dict(job.progress or {})
        progress["stage"] = JobStatus.FAILED.value
        progress["detail"] = "Job became stale after worker interruption. Please retry."
        job.status = JobStatus.FAILED
        job.error_message = "Job became stale after worker interruption. Please retry."
        job.progress = progress
        db.add(job)

    if stale_jobs:
        db.commit()

    return len(stale_jobs)


def count_active_free_jobs(db: Session) -> int:
    stmt = select(func.count(Job.id)).where(
        Job.user_tier == UserTier.FREE,
        Job.status.in_(ACTIVE_FREE_STATUSES),
    )
    return int(db.scalar(stmt) or 0)


def find_active_duplicate_job(db: Session, *, user: User, original_filename: str) -> Job | None:
    normalized_filename = (original_filename or "").strip().lower()
    if not normalized_filename:
        return None
    stmt = (
        select(Job)
        .where(
            Job.user_id == user.id,
            Job.status.in_(active_job_statuses()),
            func.lower(Job.original_filename) == normalized_filename,
        )
        .order_by(Job.created_at.desc())
    )
    return db.scalar(stmt)


def ensure_can_start_job(db: Session, user: User, *, original_filename: str) -> None:
    mark_stale_active_jobs(db)
    duplicate_job = find_active_duplicate_job(db, user=user, original_filename=original_filename)
    if duplicate_job is not None:
        raise ValueError("This EPUB already has an active translation job. Please wait for it to finish or fail before uploading it again.")
    if user.tier != UserTier.FREE:
        return
    if count_active_free_jobs(db) >= get_global_free_active_job_limit(db):
        raise ValueError("The free translation pool is currently busy. Please try again in a few minutes.")


def create_job(
    db: Session,
    *,
    user: User,
    original_filename: str,
    stored_filename: str,
    file_size_bytes: int,
    translator_provider: str,
    source_language: str,
    target_language: str,
) -> Job:
    job = Job(
        user_id=user.id,
        user_tier=user.tier,
        status=JobStatus.UPLOADED,
        original_filename=original_filename,
        stored_filename=stored_filename,
        file_size_bytes=file_size_bytes,
        translator_provider=translator_provider,
        source_language=source_language,
        target_language=target_language,
        progress={"stage": JobStatus.UPLOADED.value},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job_status(db: Session, job: Job, status: JobStatus, *, error_message: str | None = None, progress: dict | None = None) -> Job:
    job.status = status
    job.error_message = error_message
    if progress is not None:
        job.progress = progress
    if status == JobStatus.COMPLETED:
        job.completed_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job_for_user(db: Session, job_id: uuid.UUID, user: User) -> Job | None:
    stmt = select(Job).where(Job.id == job_id, Job.user_id == user.id)
    return db.scalar(stmt)


def get_job_by_id(db: Session, job_id: uuid.UUID) -> Job | None:
    return db.scalar(select(Job).where(Job.id == job_id))
