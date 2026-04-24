from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.cache import cache_translation, get_cached_translation
from app.services.epub import Segment, extract_segments, read_book, rebuild_translated_epub
from app.services.glossary import Glossary
from app.services.text import enforce_target_script
from app.services.translators.base import Translator


@dataclass(slots=True)
class TranslationResult:
    translated_title: str | None
    result_path: Path


ProgressCallback = Callable[[dict], None]
LogCallback = Callable[[str], None]


def chunked(values: list[Segment], size: int) -> list[list[Segment]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def cache_language_key(translator: Translator, language: str) -> str:
    namespace = getattr(translator, "cache_namespace", "default")
    return f"{namespace}:{language}"


def display_language_name(language: str) -> str:
    normalized = language.strip().lower()
    if normalized in {"sr", "sr-latn", "serbian", "serbian latin"}:
        return "Serbian"
    return language


def translate_texts(
    db: Session,
    translator: Translator,
    texts: list[str],
    glossary: Glossary,
    source_language: str,
    target_language: str,
    log_callback: LogCallback | None = None,
) -> list[str]:
    results: list[str] = []
    missing: list[str] = []
    missing_indexes: list[int] = []

    cache_source_language = cache_language_key(translator, source_language)
    cache_target_language = cache_language_key(translator, target_language)

    for index, text in enumerate(texts):
        cached = get_cached_translation(db, text, cache_source_language, cache_target_language)
        if cached is not None:
            results.append(enforce_target_script(cached, target_language))
        else:
            results.append("")
            missing.append(text)
            missing_indexes.append(index)

    if missing:
        if log_callback:
            log_callback(
                f"Translating batch payload: {len(texts)} texts, {len(missing)} uncached, {len(texts) - len(missing)} cached"
            )
        protected_texts: list[str] = []
        replacements_by_index: list[dict[str, str]] = []
        for text in missing:
            protected, replacements = glossary.protect(text)
            protected_texts.append(protected)
            replacements_by_index.append(replacements)
        translated = translator.translate_batch(protected_texts, source_language, target_language)
        for slot, original, translated_text, replacements in zip(missing_indexes, missing, translated, replacements_by_index, strict=True):
            final_text = glossary.restore(translated_text, replacements)
            final_text = enforce_target_script(final_text, target_language)
            results[slot] = final_text
            cache_translation(db, original, final_text, cache_source_language, cache_target_language)
    return results


def translate_epub_file(
    db: Session,
    input_path: Path,
    translator: Translator,
    progress_callback: ProgressCallback | None = None,
    log_callback: LogCallback | None = None,
) -> TranslationResult:
    glossary = Glossary.load()
    if hasattr(translator, "ensure_language_supported"):
        translator.ensure_language_supported(settings.source_language, settings.target_language)
    book = read_book(input_path)
    segments = extract_segments(book)
    total_segments = len(segments)
    batch_size = 16
    total_batches = max(1, (total_segments + batch_size - 1) // batch_size) if total_segments else 1

    if log_callback:
        log_callback(f"EPUB parsed: {total_segments} translatable segments, batch size {batch_size}, total batches {total_batches}")

    if progress_callback:
        progress_callback(
            {
                "stage": "extracting",
                "segments_total": total_segments,
                "segments_translated": 0,
                "batches_total": total_batches,
                "batches_completed": 0,
                "percent": 0,
            }
        )

    translated_pairs: list[tuple[Segment, str]] = []
    translated_segments = 0
    completed_batches = 0

    for batch_index, batch in enumerate(chunked(segments, batch_size), start=1):
        if log_callback:
            log_callback(f"Starting batch {batch_index}/{total_batches} with {len(batch)} segments")
        translated = translate_texts(
            db,
            translator,
            [segment.original_text for segment in batch],
            glossary,
            settings.source_language,
            settings.target_language,
            log_callback=log_callback,
        )
        translated_pairs.extend(zip(batch, translated, strict=True))
        translated_segments += len(batch)
        completed_batches += 1
        if log_callback:
            log_callback(
                f"Completed batch {batch_index}/{total_batches}: {translated_segments}/{total_segments} segments translated"
            )
        if progress_callback:
            percent = int((translated_segments / total_segments) * 100) if total_segments else 100
            progress_callback(
                {
                    "stage": "translating",
                    "segments_total": total_segments,
                    "segments_translated": translated_segments,
                    "batches_total": total_batches,
                    "batches_completed": completed_batches,
                    "percent": percent,
                }
            )

    original_title = book.get_metadata("DC", "title")
    title_text = original_title[0][0] if original_title else None
    translated_title = None
    if title_text:
        if log_callback:
            log_callback("Translating title metadata")
        translated_title = translate_texts(
            db,
            translator,
            [title_text],
            glossary,
            settings.source_language,
            settings.target_language,
            log_callback=log_callback,
        )[0]
        translated_title = f"{translated_title} ({display_language_name(settings.target_language)})"

    if progress_callback:
        progress_callback(
            {
                "stage": "rebuilding",
                "segments_total": total_segments,
                "segments_translated": total_segments,
                "batches_total": total_batches,
                "batches_completed": total_batches,
                "percent": 100,
            }
        )

    if log_callback:
        log_callback("Rebuilding translated EPUB")
    result_path = rebuild_translated_epub(input_path, translated_pairs, translated_title)
    if log_callback:
        log_callback(f"Rebuild complete: {result_path.name}")
    return TranslationResult(translated_title=translated_title, result_path=result_path)
