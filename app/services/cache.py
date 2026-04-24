from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.translation_cache import TranslationCache
from app.services.text import normalize_text


def build_cache_key(normalized_text: str) -> str:
    return hashlib.sha256(f"v3\x00{normalized_text}".encode("utf-8")).hexdigest()


def get_cached_translation(db: Session, text: str, source_language: str, target_language: str) -> str | None:
    normalized = normalize_text(text)
    if not normalized:
        return text
    cache_key = build_cache_key(normalized)
    stmt = select(TranslationCache).where(
        TranslationCache.normalized_text_hash == cache_key,
        TranslationCache.source_language == source_language,
        TranslationCache.target_language == target_language,
    )
    item = db.scalar(stmt)
    if item and item.normalized_text == normalized:
        return item.translated_text
    return None


def cache_translation(db: Session, text: str, translated_text: str, source_language: str, target_language: str) -> None:
    normalized = normalize_text(text)
    if not normalized:
        return
    entry = TranslationCache(
        normalized_text_hash=build_cache_key(normalized),
        normalized_text=normalized,
        source_language=source_language,
        target_language=target_language,
        translated_text=translated_text,
    )
    db.add(entry)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
