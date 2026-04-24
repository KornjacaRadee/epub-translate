from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.job import Job, JobStatus
from app.models.user import User, UserTier
from app.services.jobs import ensure_can_start_job, find_active_duplicate_job, mark_stale_active_jobs


def test_free_tier_pool_limit_enforced(db_session):
    free_user = User(email="free@example.com", password_hash="x", tier=UserTier.FREE)
    db_session.add(free_user)
    db_session.commit()
    db_session.refresh(free_user)

    for idx in range(2):
        db_session.add(
            Job(
                id=uuid.uuid4(),
                user_id=free_user.id,
                user_tier=UserTier.FREE,
                status=JobStatus.TRANSLATING,
                original_filename=f"book-{idx}.epub",
                stored_filename=f"stored-{idx}.epub",
                file_size_bytes=100,
                source_language="en",
                target_language="sr-Latn",
                progress={},
            )
        )
    db_session.commit()

    with pytest.raises(ValueError):
        ensure_can_start_job(db_session, free_user, original_filename="new-book.epub")


def test_pro_user_bypasses_free_tier_pool_limit(db_session):
    pro_user = User(email="pro@example.com", password_hash="x", tier=UserTier.PRO)
    db_session.add(pro_user)
    db_session.commit()
    db_session.refresh(pro_user)

    ensure_can_start_job(db_session, pro_user, original_filename="new-book.epub")


def test_stale_jobs_are_marked_failed_and_removed_from_active_pool(db_session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.jobs.settings.stale_job_timeout_seconds", 60)
    free_user = User(email="stale@example.com", password_hash="x", tier=UserTier.FREE)
    db_session.add(free_user)
    db_session.commit()
    db_session.refresh(free_user)

    stale_job = Job(
        id=uuid.uuid4(),
        user_id=free_user.id,
        user_tier=UserTier.FREE,
        status=JobStatus.TRANSLATING,
        original_filename="atomic-habits.epub",
        stored_filename="stale.epub",
        file_size_bytes=100,
        source_language="en",
        target_language="sr-Latn",
        progress={"stage": JobStatus.TRANSLATING.value},
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    db_session.add(stale_job)
    db_session.commit()

    updated_count = mark_stale_active_jobs(db_session, user=free_user)
    db_session.refresh(stale_job)

    assert updated_count == 1
    assert stale_job.status == JobStatus.FAILED
    assert stale_job.progress["stage"] == JobStatus.FAILED.value
    assert "worker interruption" in stale_job.error_message
    ensure_can_start_job(db_session, free_user, original_filename="fresh-book.epub")


def test_duplicate_active_job_is_rejected(db_session):
    free_user = User(email="dup@example.com", password_hash="x", tier=UserTier.FREE)
    db_session.add(free_user)
    db_session.commit()
    db_session.refresh(free_user)

    active_job = Job(
        id=uuid.uuid4(),
        user_id=free_user.id,
        user_tier=UserTier.FREE,
        status=JobStatus.TRANSLATING,
        original_filename="Atomic Habits.epub",
        stored_filename="dup.epub",
        file_size_bytes=100,
        source_language="en",
        target_language="sr-Latn",
        progress={},
    )
    db_session.add(active_job)
    db_session.commit()

    duplicate = find_active_duplicate_job(db_session, user=free_user, original_filename="atomic habits.epub")
    assert duplicate is not None

    with pytest.raises(ValueError, match="already has an active translation job"):
        ensure_can_start_job(db_session, free_user, original_filename="atomic habits.epub")
