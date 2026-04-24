from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.config import settings


@dataclass(slots=True)
class GlossaryRule:
    source: str
    replacement: str


class Glossary:
    def __init__(self, rules: list[GlossaryRule]):
        self.rules = rules

    @classmethod
    def load(cls, path: Path | None = None) -> "Glossary":
        target = path or settings.glossary_path
        if not target.exists():
            return cls([])
        raw = target.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) if target.suffix.lower() in {".yaml", ".yml"} else json.loads(raw)
        rules = [GlossaryRule(source=item["source"], replacement=item["replacement"]) for item in data.get("terms", [])]
        return cls(rules)

    def protect(self, text: str) -> tuple[str, dict[str, str]]:
        protected = text
        replacements: dict[str, str] = {}
        for index, rule in enumerate(self.rules):
            token = f'<span class="epub-translate-glossary" translate="no" data-glossary-index="{index}">{rule.replacement}</span>'
            pattern = re.compile(re.escape(rule.source), re.IGNORECASE)
            if pattern.search(protected):
                protected = pattern.sub(token, protected)
                replacements[token] = rule.replacement
        return protected, replacements

    def restore(self, text: str, replacements: dict[str, str]) -> str:
        restored = text
        for token, replacement in replacements.items():
            restored = restored.replace(token, replacement)
        restored = re.sub(
            r'<span[^>]*class="epub-translate-glossary"[^>]*>(.*?)</span>',
            lambda match: match.group(1),
            restored,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return restored
