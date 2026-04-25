from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.checkpoints import JobCheckpoint
from app.services.epub import Segment, extract_segments, read_book, rebuild_translated_epub
from app.services.glossary import Glossary
from app.services.text import strip_html_tags
from app.services.translation_pipeline import LogCallback, display_language_name, translate_texts
from app.services.translators.base import Translator


MERGEABLE_KINDS = {"body", "note", "caption"}
DEFAULT_BATCH_CHAR_BUDGET = 1800
MAX_UNIT_CHAR_BUDGET = 900
MAX_SEGMENTS_PER_UNIT = 3


@dataclass(slots=True)
class PreparedJob:
    checkpoint: JobCheckpoint


@dataclass(slots=True)
class TranslationUnit:
    segment_indexes: list[int]
    source_text: str


def estimate_segment_size(segment: Segment) -> int:
    return len(strip_html_tags(segment.original_text))


def should_merge_segments(current: list[int], previous: Segment, candidate: Segment, segments: list[Segment]) -> bool:
    if previous.item_id != candidate.item_id:
        return False
    if previous.content_kind != candidate.content_kind:
        return False
    if previous.content_kind not in MERGEABLE_KINDS:
        return False
    if candidate.order_in_item != previous.order_in_item + 1:
        return False
    if len(current) >= MAX_SEGMENTS_PER_UNIT:
        return False
    combined_size = sum(estimate_segment_size(segments[index]) for index in current) + estimate_segment_size(candidate)
    return combined_size <= MAX_UNIT_CHAR_BUDGET


def build_unit_source_text(segments: list[Segment]) -> str:
    if len(segments) == 1:
        return segments[0].original_text
    return "".join(
        f'<div data-epub-translate-segment="{index}">{segment.original_text}</div>'
        for index, segment in enumerate(segments)
    )


def build_translation_units(segments: list[Segment]) -> list[TranslationUnit]:
    units: list[TranslationUnit] = []
    current_indexes: list[int] = []
    for index, segment in enumerate(segments):
        if current_indexes:
            previous = segments[current_indexes[-1]]
            if not should_merge_segments(current_indexes, previous, segment, segments):
                units.append(
                    TranslationUnit(
                        segment_indexes=list(current_indexes),
                        source_text=build_unit_source_text([segments[item] for item in current_indexes]),
                    )
                )
                current_indexes = []
        current_indexes.append(index)
    if current_indexes:
        units.append(
            TranslationUnit(
                segment_indexes=list(current_indexes),
                source_text=build_unit_source_text([segments[item] for item in current_indexes]),
            )
        )
    return units


def build_batches(units: list[TranslationUnit], *, char_budget: int = DEFAULT_BATCH_CHAR_BUDGET) -> list[list[TranslationUnit]]:
    batches: list[list[TranslationUnit]] = []
    current: list[TranslationUnit] = []
    current_chars = 0
    for unit in units:
        unit_chars = max(1, len(strip_html_tags(unit.source_text)))
        if current and current_chars + unit_chars > char_budget:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(unit)
        current_chars += unit_chars
    if current:
        batches.append(current)
    return batches


def translator_batch_char_budget(translator: Translator) -> int:
    return int(getattr(translator, "batch_char_budget", DEFAULT_BATCH_CHAR_BUDGET) or DEFAULT_BATCH_CHAR_BUDGET)


def build_previous_context(
    units: list[TranslationUnit],
    upto_index: int,
    *,
    max_chars: int = 320,
    max_units: int = 2,
) -> str | None:
    if upto_index <= 0:
        return None
    recent_units = units[max(0, upto_index - max_units):upto_index]
    parts = [strip_html_tags(unit.source_text).strip() for unit in recent_units]
    context = "\n\n".join(part for part in parts if part).strip()
    if len(context) > max_chars:
        context = context[-max_chars:].strip()
    return context or None


def split_translated_unit(translated_html: str, segment_count: int) -> list[str]:
    if segment_count == 1:
        return [translated_html]
    soup = BeautifulSoup(translated_html, "html.parser")
    parts: list[str] = []
    for index in range(segment_count):
        wrapper = soup.find(attrs={"data-epub-translate-segment": str(index)})
        if wrapper is None:
            raise ValueError("Translated merged segment lost structural wrappers.")
        parts.append(wrapper.decode_contents())
    return parts


def translate_unit_with_fallback(
    db: Session,
    translator: Translator,
    glossary: Glossary,
    checkpoint: JobCheckpoint,
    unit: TranslationUnit,
    *,
    source_language: str | None = None,
    target_language: str | None = None,
    log_callback: LogCallback | None = None,
) -> list[str]:
    source_language = source_language or settings.source_language
    target_language = target_language or settings.target_language
    units = build_translation_units(checkpoint.segments)
    unit_index = next((index for index, item in enumerate(units) if item.segment_indexes == unit.segment_indexes), 0)
    previous_context = build_previous_context(units, unit_index)
    translated_unit = translate_texts(
        db,
        translator,
        [unit.source_text],
        glossary,
        source_language,
        target_language,
        previous_context=previous_context,
        log_callback=log_callback,
    )[0]
    try:
        return split_translated_unit(translated_unit, len(unit.segment_indexes))
    except ValueError:
        if len(unit.segment_indexes) == 1:
            raise
        if log_callback:
            log_callback(
                f"Merged unit lost wrappers for {len(unit.segment_indexes)} segments; retrying them individually"
            )
        segment_texts = [checkpoint.segments[index].original_text for index in unit.segment_indexes]
        return translate_texts(
            db,
            translator,
            segment_texts,
            glossary,
            source_language,
            target_language,
            previous_context=previous_context,
            log_callback=log_callback,
        )


def prepare_translation_job(
    input_path: Path,
    translator: Translator,
    *,
    source_language: str | None = None,
    target_language: str | None = None,
    log_callback: LogCallback | None = None,
) -> PreparedJob:
    source_language = source_language or settings.source_language
    target_language = target_language or settings.target_language
    if hasattr(translator, "ensure_language_supported"):
        translator.ensure_language_supported(source_language, target_language)
    book = read_book(input_path)
    segments = extract_segments(book)
    units = build_translation_units(segments)
    batch_char_budget = translator_batch_char_budget(translator)
    batches = build_batches(units, char_budget=batch_char_budget)
    original_title = None
    title_metadata = book.get_metadata("DC", "title")
    if title_metadata:
        original_title = title_metadata[0][0]
    total_segments = len(segments)
    total_batches = len(batches) or 1
    if log_callback:
        log_callback(
            f"EPUB parsed: {total_segments} translatable segments, {len(units)} translation units, character-budget batches {total_batches}"
        )
    checkpoint = JobCheckpoint(
        stored_filename=input_path.name,
        original_title=original_title,
        translated_title=None,
        batch_size=batch_char_budget,
        total_segments=total_segments,
        total_batches=total_batches,
        segments=segments,
        translated_texts=[None] * total_segments,
    )
    return PreparedJob(checkpoint=checkpoint)


def build_progress(stage: str, *, total_segments: int, translated_segments: int, total_batches: int, completed_batches: int) -> dict:
    percent = int((translated_segments / total_segments) * 100) if total_segments else 100
    return {
        "stage": stage,
        "segments_total": total_segments,
        "segments_translated": translated_segments,
        "batches_total": total_batches,
        "batches_completed": completed_batches,
        "percent": percent,
    }


def translate_checkpoint_batch(
    db: Session,
    checkpoint: JobCheckpoint,
    translator: Translator,
    batch_index: int,
    *,
    source_language: str | None = None,
    target_language: str | None = None,
    log_callback: LogCallback | None = None,
) -> tuple[JobCheckpoint, dict]:
    source_language = source_language or settings.source_language
    target_language = target_language or settings.target_language
    units = build_translation_units(checkpoint.segments)
    batches = build_batches(units, char_budget=checkpoint.batch_size)
    batch_units = batches[batch_index]
    previous_context = build_previous_context(units, sum(len(batch) for batch in batches[:batch_index]))
    unit_segment_count = sum(len(unit.segment_indexes) for unit in batch_units)
    if log_callback:
        log_callback(
            f"Starting batch {batch_index + 1}/{checkpoint.total_batches} with {len(batch_units)} units covering {unit_segment_count} segments"
        )
    glossary = Glossary.load()
    translated = translate_texts(
        db,
        translator,
        [unit.source_text for unit in batch_units],
        glossary,
        source_language,
        target_language,
        previous_context=previous_context,
        log_callback=log_callback,
    )
    for unit, translated_unit in zip(batch_units, translated, strict=True):
        try:
            translated_parts = split_translated_unit(translated_unit, len(unit.segment_indexes))
        except ValueError:
            if len(unit.segment_indexes) == 1:
                raise
            if log_callback:
                log_callback(
                    f"Merged unit lost wrappers for {len(unit.segment_indexes)} segments; retrying them individually"
                )
            segment_texts = [checkpoint.segments[index].original_text for index in unit.segment_indexes]
            translated_parts = translate_texts(
                db,
                translator,
                segment_texts,
                glossary,
                source_language,
                target_language,
                previous_context=previous_context,
                log_callback=log_callback,
            )
        for segment_index, translated_part in zip(unit.segment_indexes, translated_parts, strict=True):
            checkpoint.translated_texts[segment_index] = translated_part
    translated_segments = sum(1 for item in checkpoint.translated_texts if item is not None)
    completed_batches = min(batch_index + 1, checkpoint.total_batches)
    if log_callback:
        log_callback(
            f"Completed batch {batch_index + 1}/{checkpoint.total_batches}: {translated_segments}/{checkpoint.total_segments} segments translated"
        )
    return checkpoint, build_progress(
        "translating",
        total_segments=checkpoint.total_segments,
        translated_segments=translated_segments,
        total_batches=checkpoint.total_batches,
        completed_batches=completed_batches,
    )


def translate_checkpoint_title(
    db: Session,
    checkpoint: JobCheckpoint,
    translator: Translator,
    *,
    source_language: str | None = None,
    target_language: str | None = None,
    log_callback: LogCallback | None = None,
) -> JobCheckpoint:
    source_language = source_language or settings.source_language
    target_language = target_language or settings.target_language
    if not checkpoint.original_title:
        checkpoint.translated_title = None
        return checkpoint
    if log_callback:
        log_callback("Translating title metadata")
    glossary = Glossary.load()
    checkpoint.translated_title = translate_texts(
        db,
        translator,
        [checkpoint.original_title],
        glossary,
        source_language,
        target_language,
        log_callback=log_callback,
    )[0]
    checkpoint.translated_title = f"{checkpoint.translated_title} ({display_language_name(target_language)})"
    return checkpoint


def rebuild_from_checkpoint(input_path: Path, checkpoint: JobCheckpoint, *, log_callback: LogCallback | None = None) -> Path:
    translated_pairs = [
        (segment, translated)
        for segment, translated in zip(checkpoint.segments, checkpoint.translated_texts, strict=True)
        if translated is not None
    ]
    if log_callback:
        log_callback("Rebuilding translated EPUB")
    result_path = rebuild_translated_epub(input_path, translated_pairs, checkpoint.translated_title)
    if log_callback:
        log_callback(f"Rebuild complete: {result_path.name}")
    return result_path
