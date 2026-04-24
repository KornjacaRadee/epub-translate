from __future__ import annotations

import re
import uuid
from pathlib import Path


SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(filename: str) -> str:
    base = Path(filename).name
    cleaned = SAFE_FILENAME_RE.sub("_", base).strip("._")
    return cleaned or f"file-{uuid.uuid4().hex}.epub"


def translated_filename_from_title(title: str | None, fallback_original: str) -> str:
    ext = Path(fallback_original).suffix or ".epub"
    stem = sanitize_filename(title or Path(fallback_original).stem)
    if not stem.lower().endswith(".epub"):
        return f"{stem}{ext}"
    return stem
