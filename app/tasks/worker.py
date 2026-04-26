from __future__ import annotations

import logging
import uuid

from app.db.session import SessionLocal
from app.models.job import JobStatus
from app.tasks.celery_app import celery_app
from app.services.credits import find_refundable_failed_jobs, refund_failed_job
from app.services.checkpoints import checkpoint_exists, delete_checkpoint, load_checkpoint, save_checkpoint
from app.services.filenames import translated_filename_from_title
from app.services.jobs import get_job_by_id, update_job_status
from app.services.storage import move_result, upload_path
from app.services.translation_job import (
    build_progress as build_translation_progress,
    prepare_translation_job,
    rebuild_from_checkpoint,
    translate_checkpoint_batch,
    translate_checkpoint_title,
)
from app.services.translators.factory import get_translator

logger = logging.getLogger(__name__)


def queue_translation_job(job_id: uuid.UUID) -> None:
    extract_job.delay(str(job_id))


def resume_translation_job(job_id: uuid.UUID, *, status: JobStatus, progress: dict | None = None) -> str:
    if status in {JobStatus.UPLOADED, JobStatus.VALIDATING, JobStatus.QUEUED, JobStatus.EXTRACTING}:
        extract_job.delay(str(job_id))
        return "extract"
    if not checkpoint_exists(job_id):
        extract_job.delay(str(job_id))
        return "extract"

    batches_completed = int((progress or {}).get("batches_completed") or 0)
    checkpoint = load_checkpoint(job_id)
    if status == JobStatus.REBUILDING or batches_completed >= checkpoint.total_batches:
        finalize_job.delay(str(job_id))
        return "finalize"

    translate_batch_job.delay(str(job_id), batches_completed)
    return "batch"


def without_stage(progress: dict | None) -> dict:
    if not progress:
        return {}
    return {key: value for key, value in progress.items() if key != "stage"}


def build_progress(stage: str, **extra: object) -> dict:
    progress = {"stage": stage, **extra}
    return progress


def merge_progress(stage: str, progress: dict | None = None, **overrides: object) -> dict:
    merged = without_stage(progress)
    merged.update(overrides)
    return build_progress(stage, **merged)


@celery_app.task(name="app.tasks.worker.extract_job")
def extract_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        logger.info("Job %s received by worker", job_id)
        job = get_job_by_id(db, uuid.UUID(job_id))
        if not job:
            logger.warning("Job %s not found in database", job_id)
            return
        update_job_status(db, job, JobStatus.VALIDATING, progress={"stage": JobStatus.VALIDATING.value})
        source_path = upload_path(job.stored_filename)
        logger.info("Job %s validating upload %s", job_id, source_path.name)
        update_job_status(db, job, JobStatus.QUEUED, progress=build_progress(JobStatus.QUEUED.value))
        update_job_status(db, job, JobStatus.EXTRACTING, progress=build_progress(JobStatus.EXTRACTING.value))

        def log_step(message: str) -> None:
            logger.info("Job %s: %s", job_id, message)

        prepared = prepare_translation_job(
            source_path,
            get_translator(job.translator_provider, log_step),
            source_language=job.source_language,
            target_language=job.target_language,
            log_callback=log_step,
        )
        checkpoint = prepared.checkpoint
        save_checkpoint(uuid.UUID(job_id), checkpoint)
        job.title = checkpoint.original_title or job.original_filename
        db.add(job)
        db.commit()
        db.refresh(job)
        update_job_status(
            db,
            job,
            JobStatus.TRANSLATING,
            progress=build_translation_progress(
                JobStatus.TRANSLATING.value,
                total_segments=checkpoint.total_segments,
                translated_segments=0,
                total_batches=checkpoint.total_batches,
                completed_batches=0,
            ),
        )
        translate_batch_job.delay(job_id, 0)
    except Exception as exc:
        db.rollback()
        current = get_job_by_id(db, uuid.UUID(job_id))
        if current:
            detail = str(exc)
            logger.exception("Job %s failed during extraction: %s", job_id, detail)
            update_job_status(
                db,
                current,
                JobStatus.FAILED,
                error_message=detail if detail else "Translation failed. Please try again later.",
                progress=merge_progress(JobStatus.FAILED.value, current.progress, detail=detail),
            )
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker.process_pending_credit_refunds")
def process_pending_credit_refunds() -> int:
    db = SessionLocal()
    refunded = 0
    try:
        for job in find_refundable_failed_jobs(db):
            try:
                transaction = refund_failed_job(db, job)
                if transaction is not None:
                    db.commit()
                    refunded += 1
                else:
                    db.rollback()
            except Exception:
                db.rollback()
                logger.exception("Failed to process credit refund for job %s", job.id)
        return refunded
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker.translate_batch_job")
def translate_batch_job(job_id: str, batch_index: int) -> None:
    db = SessionLocal()
    try:
        logger.info("Job %s batch %s received by worker", job_id, batch_index + 1)
        job_uuid = uuid.UUID(job_id)
        job = get_job_by_id(db, job_uuid)
        if not job:
            logger.warning("Job %s not found in database", job_id)
            return
        checkpoint = load_checkpoint(job_uuid)

        if batch_index >= checkpoint.total_batches:
            finalize_job.delay(job_id)
            return

        def log_step(message: str) -> None:
            logger.info("Job %s: %s", job_id, message)

        checkpoint, progress = translate_checkpoint_batch(
            db,
            checkpoint,
            get_translator(job.translator_provider, log_step),
            batch_index,
            source_language=job.source_language,
            target_language=job.target_language,
            log_callback=log_step,
        )
        save_checkpoint(job_uuid, checkpoint)
        update_job_status(db, job, JobStatus.TRANSLATING, progress=progress)

        next_batch_index = batch_index + 1
        if next_batch_index < checkpoint.total_batches:
            translate_batch_job.delay(job_id, next_batch_index)
        else:
            finalize_job.delay(job_id)
    except Exception as exc:
        db.rollback()
        current = get_job_by_id(db, uuid.UUID(job_id))
        if current:
            detail = str(exc)
            logger.exception("Job %s failed during batch %s: %s", job_id, batch_index + 1, detail)
            update_job_status(
                db,
                current,
                JobStatus.FAILED,
                error_message=detail if detail else "Translation failed. Please try again later.",
                progress=merge_progress(JobStatus.FAILED.value, current.progress, detail=detail),
            )
    finally:
        db.close()


@celery_app.task(name="app.tasks.worker.finalize_job")
def finalize_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        logger.info("Job %s finalization received by worker", job_id)
        job_uuid = uuid.UUID(job_id)
        job = get_job_by_id(db, job_uuid)
        if not job:
            logger.warning("Job %s not found in database", job_id)
            return
        checkpoint = load_checkpoint(job_uuid)

        def log_step(message: str) -> None:
            logger.info("Job %s: %s", job_id, message)

        checkpoint = translate_checkpoint_title(
            db,
            checkpoint,
            get_translator(job.translator_provider, log_step),
            source_language=job.source_language,
            target_language=job.target_language,
            log_callback=log_step,
        )
        save_checkpoint(job_uuid, checkpoint)
        update_job_status(
            db,
            job,
            JobStatus.REBUILDING,
            progress=merge_progress(
                JobStatus.REBUILDING.value,
                job.progress,
                segments_total=checkpoint.total_segments,
                segments_translated=checkpoint.total_segments,
                batches_total=checkpoint.total_batches,
                batches_completed=checkpoint.total_batches,
                percent=100,
            ),
        )

        source_path = upload_path(job.stored_filename)
        result_path = rebuild_from_checkpoint(source_path, checkpoint, log_callback=log_step)
        visible_name = translated_filename_from_title(checkpoint.translated_title, job.original_filename)
        logger.info("Job %s moving rebuilt EPUB into results as %s", job_id, visible_name)
        stored_result_name = move_result(result_path, visible_name)

        job.result_filename = stored_result_name
        job.visible_result_filename = visible_name
        job.translated_title = checkpoint.translated_title
        db.add(job)
        db.commit()
        db.refresh(job)
        update_job_status(
            db,
            job,
            JobStatus.COMPLETED,
            progress=merge_progress(
                JobStatus.COMPLETED.value,
                job.progress,
                percent=100,
                segments_total=checkpoint.total_segments,
                segments_translated=checkpoint.total_segments,
                batches_total=checkpoint.total_batches,
                batches_completed=checkpoint.total_batches,
            ),
        )
        delete_checkpoint(job_uuid)
        logger.info("Job %s completed successfully", job_id)
    except Exception as exc:
        db.rollback()
        current = get_job_by_id(db, uuid.UUID(job_id))
        if current:
            detail = str(exc)
            logger.exception("Job %s failed during finalization: %s", job_id, detail)
            update_job_status(
                db,
                current,
                JobStatus.FAILED,
                error_message=detail if detail else "Translation failed. Please try again later.",
                progress=merge_progress(JobStatus.FAILED.value, current.progress, detail=detail),
            )
    finally:
        db.close()
