from __future__ import annotations

from typing import Protocol


class Translator(Protocol):
    cache_namespace: str
    batch_char_budget: int

    def translate_batch(
        self,
        texts: list[str],
        source_language: str,
        target_language: str,
        previous_context: str | None = None,
    ) -> list[str]:
        ...
