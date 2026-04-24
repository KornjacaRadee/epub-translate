from __future__ import annotations

from app.services.translation_pipeline import translate_epub_file
from app.tests.helpers import FakeTranslator, build_sample_epub


def test_translate_epub_reports_progress(db_session, tmp_path):
    epub_path = build_sample_epub(tmp_path / "sample.epub")
    updates: list[dict] = []

    def on_progress(progress: dict) -> None:
        updates.append(progress.copy())

    translate_epub_file(db_session, epub_path, FakeTranslator(), progress_callback=on_progress)

    assert updates
    assert updates[0]["stage"] == "extracting"
    assert updates[-1]["stage"] == "rebuilding"
    assert updates[-1]["percent"] == 100
    assert updates[-1]["segments_translated"] == updates[-1]["segments_total"]
