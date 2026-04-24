from __future__ import annotations

from typing import Protocol


class Translator(Protocol):
    def translate_batch(self, texts: list[str], source_language: str, target_language: str) -> list[str]:
        ...
