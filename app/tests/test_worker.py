from __future__ import annotations

import uuid

from app.models.job import JobStatus
from app.tasks.worker import merge_progress, resume_translation_job


def test_merge_progress_overrides_existing_percent_without_conflict():
    progress = merge_progress("rebuilding", {"stage": "translating", "percent": 87, "segments_total": 294}, percent=100)

    assert progress["stage"] == "rebuilding"
    assert progress["percent"] == 100
    assert progress["segments_total"] == 294


def test_resume_translation_job_requeues_extract_for_uploaded(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr("app.tasks.worker.extract_job.delay", lambda job_id: captured.append(job_id))

    mode = resume_translation_job(uuid.uuid4(), status=JobStatus.UPLOADED, progress={"stage": "uploaded"})

    assert mode == "extract"
    assert captured
