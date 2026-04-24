from __future__ import annotations

from app.services.cache import cache_translation, get_cached_translation
from app.services.glossary import Glossary, GlossaryRule
from app.services.text import enforce_target_script


def test_translation_cache_round_trip(db_session):
    assert get_cached_translation(db_session, "Hello", "en", "sr-Latn") is None
    cache_translation(db_session, "Hello", "Zdravo", "en", "sr-Latn")
    assert get_cached_translation(db_session, " Hello  ", "en", "sr-Latn") == "Zdravo"


def test_translation_cache_supports_long_paragraphs(db_session):
    text = ("Atomic Habits long paragraph " * 200).strip()
    translated = ("Atomske navike dugi pasus " * 200).strip()
    cache_translation(db_session, text, translated, "en", "sr")
    assert get_cached_translation(db_session, text, "en", "sr") == translated


def test_enforce_target_script_transliterates_serbian_to_latin():
    assert enforce_target_script("Атомске навике", "sr") == "Atomske navike"
    assert enforce_target_script("Лак и доказан начин", "sr-Latn") == "Lak i dokazan način"


def test_glossary_protect_and_restore():
    glossary = Glossary([GlossaryRule(source="LibreTranslate", replacement="LibreTranslate")])
    protected, replacements = glossary.protect("LibreTranslate is available")
    assert 'translate="no"' in protected
    restored = glossary.restore(protected.replace("is available", "je dostupan"), replacements)
    assert restored == "LibreTranslate je dostupan"
