from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.config import settings
from app.services.epub import Segment


@dataclass(slots=True)
class JobCheckpoint:
    stored_filename: str
    original_title: str | None
    translated_title: str | None
    batch_size: int
    total_segments: int
    total_batches: int
    segments: list[Segment]
    translated_texts: list[str | None]


def checkpoint_dir() -> Path:
    target = settings.upload_dir / "_checkpoints"
    target.mkdir(parents=True, exist_ok=True)
    return target


def checkpoint_path(job_id: uuid.UUID) -> Path:
    return checkpoint_dir() / f"{job_id}.json"


def checkpoint_exists(job_id: uuid.UUID) -> bool:
    return checkpoint_path(job_id).exists()


def save_checkpoint(job_id: uuid.UUID, checkpoint: JobCheckpoint) -> Path:
    path = checkpoint_path(job_id)
    payload = {
        "stored_filename": checkpoint.stored_filename,
        "original_title": checkpoint.original_title,
        "translated_title": checkpoint.translated_title,
        "batch_size": checkpoint.batch_size,
        "total_segments": checkpoint.total_segments,
        "total_batches": checkpoint.total_batches,
        "segments": [asdict(segment) for segment in checkpoint.segments],
        "translated_texts": checkpoint.translated_texts,
    }
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)
    return path


def load_checkpoint(job_id: uuid.UUID) -> JobCheckpoint:
    payload = json.loads(checkpoint_path(job_id).read_text(encoding="utf-8"))
    segments = [Segment(**item) for item in payload["segments"]]
    return JobCheckpoint(
        stored_filename=payload["stored_filename"],
        original_title=payload.get("original_title"),
        translated_title=payload.get("translated_title"),
        batch_size=int(payload["batch_size"]),
        total_segments=int(payload["total_segments"]),
        total_batches=int(payload["total_batches"]),
        segments=segments,
        translated_texts=list(payload["translated_texts"]),
    )


def delete_checkpoint(job_id: uuid.UUID) -> None:
    checkpoint_path(job_id).unlink(missing_ok=True)
