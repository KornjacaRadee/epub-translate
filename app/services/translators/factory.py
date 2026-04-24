from __future__ import annotations

from typing import Callable

from app.services.translators.gemini import GeminiTranslator
from app.services.translators.libretranslate import LibreTranslateClient


LogCallback = Callable[[str], None]


def get_translator(provider: str, log_callback: LogCallback | None = None):
    normalized = provider.strip().lower()
    if normalized == "gemini":
        return GeminiTranslator(log_callback=log_callback)
    if normalized == "libretranslate":
        return LibreTranslateClient(log_callback=log_callback)
    raise ValueError(f"Unknown translation provider: {provider}")
