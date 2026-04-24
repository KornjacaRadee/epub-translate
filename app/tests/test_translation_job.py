from __future__ import annotations

from app.services.epub import Segment
from app.services.glossary import Glossary
from app.services.translation_job import build_batches, build_translation_units, translate_unit_with_fallback


def make_segment(item_id: str, order: int, text: str, kind: str) -> Segment:
    return Segment(
        item_id=item_id,
        order_in_item=order,
        original_text=text,
        placeholder_map={},
        content_kind=kind,
    )


def test_build_translation_units_merges_small_adjacent_body_segments():
    segments = [
        make_segment("item-1", 0, "<p>First sentence.</p>", "body"),
        make_segment("item-1", 1, "<p>Second sentence.</p>", "body"),
        make_segment("item-1", 2, "<h2>Heading</h2>", "heading"),
    ]

    units = build_translation_units(segments)

    assert len(units) == 2
    assert units[0].segment_indexes == [0, 1]
    assert 'data-epub-translate-segment="0"' in units[0].source_text
    assert units[1].segment_indexes == [2]


def test_build_batches_uses_character_budget():
    units = build_translation_units(
        [
            make_segment("item-1", 0, "<p>" + ("a" * 700) + "</p>", "body"),
            make_segment("item-1", 1, "<p>" + ("b" * 700) + "</p>", "body"),
            make_segment("item-1", 2, "<p>" + ("c" * 700) + "</p>", "body"),
        ]
    )

    batches = build_batches(units, char_budget=1000)

    assert len(batches) >= 2


class WrapperDroppingTranslator:
    def translate_batch(self, texts: list[str], source_language: str, target_language: str) -> list[str]:
        return ["Prvi. Drugi."] if len(texts) == 1 else ["Prvi.", "Drugi."]


def test_translate_unit_with_fallback_retries_individual_segments(db_session):
    checkpoint_segments = [
        make_segment("item-1", 0, "<p>First.</p>", "body"),
        make_segment("item-1", 1, "<p>Second.</p>", "body"),
    ]
    unit = build_translation_units(checkpoint_segments)[0]

    class CheckpointStub:
        segments = checkpoint_segments

    translated_parts = translate_unit_with_fallback(
        db_session,
        WrapperDroppingTranslator(),
        Glossary([]),
        CheckpointStub(),
        unit,
    )

    assert translated_parts == ["Prvi.", "Drugi."]
