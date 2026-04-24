from __future__ import annotations

from app.services.translators.libretranslate import LibreTranslateClient
from app.tests.helpers import TimeoutFallbackSender


def test_timeout_fallback_splits_batches(monkeypatch):
    client = LibreTranslateClient(base_url="http://example.test")
    sender = TimeoutFallbackSender()
    monkeypatch.setattr(client, "_send_translate_request", sender)

    result = client.translate_batch(["a", "b", "c", "d"], "en", "sr")

    assert result == ["ok:a", "ok:b", "ok:c", "ok:d"]
    assert sender.calls[0] == ["a", "b", "c", "d"]
    assert ["a", "b"] in sender.calls
    assert ["c", "d"] in sender.calls
