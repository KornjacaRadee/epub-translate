from __future__ import annotations

import ebooklib
from ebooklib import epub

from app.services.epub import extract_segments, read_book
from app.services.translation_pipeline import translate_epub_file
from app.tests.helpers import FakeCyrillicTranslator, FakeMojibakeTranslator, FakeTranslator, build_sample_epub


def test_extract_segments_preserves_inline_html_and_classifies_content(tmp_path):
    epub_path = build_sample_epub(tmp_path / "sample.epub")
    book = read_book(epub_path)
    segments = extract_segments(book)
    assert any("Hello world" in segment.original_text for segment in segments)
    heading = next(segment for segment in segments if "Hello world" in segment.original_text)
    paragraph = next(segment for segment in segments if "important" in segment.original_text)
    assert heading.content_kind == "heading"
    assert "<em>important</em>" in paragraph.original_text
    assert '<a href="https://example.com">link</a>' in paragraph.original_text
    assert paragraph.placeholder_map == {}


def test_translate_epub_file_rebuilds_epub(db_session, tmp_path):
    epub_path = build_sample_epub(tmp_path / "sample.epub")
    result = translate_epub_file(db_session, epub_path, FakeTranslator())
    translated_book = epub.read_epub(str(result.result_path))
    docs = list(translated_book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    content = docs[0].get_content().decode("utf-8")
    assert "Zdravo svete" in content
    assert "<em>vazan</em>" in content
    assert "ZXPH" not in content
    assert "Primer knjige (Serbian)" == result.translated_title


def test_translate_epub_forces_serbian_latin_output(db_session, tmp_path):
    epub_path = build_sample_epub(tmp_path / "sample.epub")
    result = translate_epub_file(db_session, epub_path, FakeCyrillicTranslator())
    translated_book = epub.read_epub(str(result.result_path))
    docs = list(translated_book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    content = docs[0].get_content().decode("utf-8")
    assert "Zdravo svete" in content
    assert "Ово је" not in content
    assert "Primer knjige (Serbian)" == result.translated_title


def test_translate_epub_repairs_common_mojibake(db_session, tmp_path):
    epub_path = build_sample_epub(tmp_path / "sample.epub")
    result = translate_epub_file(db_session, epub_path, FakeMojibakeTranslator())
    translated_book = epub.read_epub(str(result.result_path))
    docs = list(translated_book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    content = docs[0].get_content().decode("utf-8")
    assert "važan" in content
    assert "vaæan" not in content
