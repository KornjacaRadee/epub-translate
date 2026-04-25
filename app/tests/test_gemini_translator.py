from __future__ import annotations

import pytest

from app.services.translators.gemini import GeminiTranslateError, GeminiTranslator


def test_gemini_quota_error_does_not_split_batch(monkeypatch):
    monkeypatch.setattr("app.services.translators.gemini.settings.gemini_api_key", "test-key")
    monkeypatch.setattr("app.services.translators.gemini.settings.gemini_retries", 1)
    monkeypatch.setattr("app.services.translators.gemini.time.sleep", lambda delay: None)

    translator = GeminiTranslator.__new__(GeminiTranslator)
    translator.api_key = "test-key"
    translator.model = "gemini-2.5-flash"
    translator.log_callback = None
    calls = []

    def fail(texts, source_language, target_language, previous_context=None):
        calls.append(list(texts))
        raise RuntimeError("429 RESOURCE_EXHAUSTED retryDelay': '59s'")

    translator._send_request = fail

    with pytest.raises(GeminiTranslateError):
        translator.translate_batch(["a", "b", "c", "d"], "English", "Serbian Latin")

    assert calls == [["a", "b", "c", "d"]]


def test_gemini_prompt_includes_previous_context():
    translator = GeminiTranslator.__new__(GeminiTranslator)

    prompt = translator._build_prompt(
        ["Current sentence."],
        "English",
        "Serbian Latin",
        previous_context="Previous sentence for meaning.",
    )

    assert "Context from previous passage, for meaning only." in prompt
    assert "Do not translate it unless it appears in the input array:" in prompt
    assert "Previous sentence for meaning." in prompt
