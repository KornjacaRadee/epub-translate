from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.services.filenames import sanitize_filename


EPUB_MIME_TYPES = {"application/epub+zip", "application/octet-stream"}


def ensure_storage_dirs() -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.result_dir.mkdir(parents=True, exist_ok=True)


def validate_epub_upload(upload: UploadFile, size: int) -> None:
    if size > settings.max_upload_size_bytes:
        raise ValueError("File is too large. Maximum size is 50 MB.")
    filename = sanitize_filename(upload.filename or "book.epub")
    if not filename.lower().endswith(".epub"):
        raise ValueError("Only EPUB files are supported.")
    content_type = (upload.content_type or "").lower()
    if content_type and content_type not in EPUB_MIME_TYPES:
        raise ValueError("Uploaded file does not look like a valid EPUB.")


def save_upload(upload: UploadFile) -> tuple[str, int]:
    ensure_storage_dirs()
    filename = sanitize_filename(upload.filename or "book.epub")
    stored_filename = f"{uuid.uuid4().hex}-{filename}"
    target_path = settings.upload_dir / stored_filename
    size = 0
    with target_path.open("wb") as fh:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_size_bytes:
                target_path.unlink(missing_ok=True)
                raise ValueError("File is too large. Maximum size is 50 MB.")
            fh.write(chunk)
    validate_epub_upload(upload, size)
    return stored_filename, size


def upload_path(stored_filename: str) -> Path:
    return settings.upload_dir / Path(stored_filename).name


def result_path(stored_filename: str) -> Path:
    return settings.result_dir / Path(stored_filename).name


def move_result(temp_path: Path, final_filename: str) -> str:
    ensure_storage_dirs()
    safe_name = sanitize_filename(final_filename)
    final_path = settings.result_dir / f"{uuid.uuid4().hex}-{safe_name}"
    shutil.move(str(temp_path), final_path)
    return final_path.name
