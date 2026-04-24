from __future__ import annotations

import re


WHITESPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
MOJIBAKE_MARKERS = ("Ð", "Ñ", "Ã", "â")

SERBIAN_CYRILLIC_TO_LATIN = {
    "А": "A",
    "а": "a",
    "Б": "B",
    "б": "b",
    "В": "V",
    "в": "v",
    "Г": "G",
    "г": "g",
    "Д": "D",
    "д": "d",
    "Ђ": "Đ",
    "ђ": "đ",
    "Е": "E",
    "е": "e",
    "Ж": "Ž",
    "ж": "ž",
    "З": "Z",
    "з": "z",
    "И": "I",
    "и": "i",
    "Ј": "J",
    "ј": "j",
    "К": "K",
    "к": "k",
    "Л": "L",
    "л": "l",
    "Љ": "Lj",
    "љ": "lj",
    "М": "M",
    "м": "m",
    "Н": "N",
    "н": "n",
    "Њ": "Nj",
    "њ": "nj",
    "О": "O",
    "о": "o",
    "П": "P",
    "п": "p",
    "Р": "R",
    "р": "r",
    "С": "S",
    "с": "s",
    "Т": "T",
    "т": "t",
    "Ћ": "Ć",
    "ћ": "ć",
    "У": "U",
    "у": "u",
    "Ф": "F",
    "ф": "f",
    "Х": "H",
    "х": "h",
    "Ц": "C",
    "ц": "c",
    "Ч": "Č",
    "ч": "č",
    "Џ": "Dž",
    "џ": "dž",
    "Ш": "Š",
    "ш": "š",
}

SERBIAN_MOJIBAKE_REPLACEMENTS = {
    "æ": "ć",
    "Æ": "Ć",
    "è": "č",
    "È": "Č",
    "ð": "đ",
    "Ð": "Đ",
    "þ": "š",
    "Þ": "Š",
    "Å¾": "ž",
    "Å½": "Ž",
    "Ĺľ": "ž",
    "Ĺ˝": "Ž",
    "Ä": "č",
    "ÄŒ": "Č",
    "Ä‡": "ć",
    "Ä†": "Ć",
    "Ä‘": "đ",
    "Ä": "Đ",
    "Å¡": "š",
    "Å ": "Š",
}


def normalize_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip()


def strip_html_tags(value: str) -> str:
    return normalize_text(TAG_RE.sub(" ", value))


def transliterate_serbian_cyrillic_to_latin(value: str) -> str:
    return "".join(SERBIAN_CYRILLIC_TO_LATIN.get(char, char) for char in value)


def _mojibake_score(value: str) -> int:
    return sum(value.count(marker) for marker in MOJIBAKE_MARKERS)


def maybe_recover_utf8_mojibake(value: str) -> str:
    if not any(marker in value for marker in MOJIBAKE_MARKERS):
        return value
    try:
        recovered = value.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    return recovered if _mojibake_score(recovered) < _mojibake_score(value) else value


def repair_common_serbian_mojibake(value: str) -> str:
    repaired = maybe_recover_utf8_mojibake(value)
    for broken, fixed in SERBIAN_MOJIBAKE_REPLACEMENTS.items():
        repaired = repaired.replace(broken, fixed)
    return repaired


def enforce_target_script(value: str, target_language: str) -> str:
    normalized_target = target_language.strip().lower()
    if normalized_target in {"sr", "sr-latn", "sr_latn", "serbian", "serbian-latin"}:
        repaired = repair_common_serbian_mojibake(value)
        return transliterate_serbian_cyrillic_to_latin(repaired)
    return value
