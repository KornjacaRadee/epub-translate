from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.services.translators.libretranslate import LibreTranslateClient


GEMINI_LANGUAGE_SUGGESTIONS = [
    "Afrikaans",
    "Albanian",
    "Arabic",
    "Armenian",
    "Azerbaijani",
    "Basque",
    "Belarusian",
    "Bengali",
    "Bosnian",
    "Bulgarian",
    "Catalan",
    "Chinese Simplified",
    "Chinese Traditional",
    "Croatian",
    "Czech",
    "Danish",
    "Dutch",
    "English",
    "Estonian",
    "Finnish",
    "French",
    "Georgian",
    "German",
    "Greek",
    "Hebrew",
    "Hindi",
    "Hungarian",
    "Indonesian",
    "Italian",
    "Japanese",
    "Korean",
    "Latin",
    "Latvian",
    "Lithuanian",
    "Macedonian",
    "Norwegian",
    "Persian",
    "Polish",
    "Portuguese",
    "Portuguese Brazilian",
    "Romanian",
    "Russian",
    "Serbian",
    "Serbian Cyrillic",
    "Serbian Latin",
    "Slovak",
    "Slovenian",
    "Spanish",
    "Spanish Latin American",
    "Swedish",
    "Turkish",
    "Ukrainian",
    "Vietnamese",
]


@dataclass(slots=True)
class TranslationProviderOption:
    id: str
    label: str
    available: bool
    languages: list[str]
    reason: str | None = None


def libretranslate_option() -> TranslationProviderOption:
    if not settings.enable_libretranslate:
        return TranslationProviderOption("libretranslate", "LibreTranslate", False, [], "LibreTranslate is disabled.")
    try:
        languages = LibreTranslateClient().supported_languages()
    except Exception:
        return TranslationProviderOption("libretranslate", "LibreTranslate", False, [], "LibreTranslate is not reachable.")
    return TranslationProviderOption("libretranslate", "LibreTranslate", True, languages)


def gemini_option() -> TranslationProviderOption:
    if not settings.gemini_api_key:
        return TranslationProviderOption("gemini", "Gemini 2.5 Flash Lite", False, [], "Set GEMINI_API_KEY to enable Gemini.")
    return TranslationProviderOption("gemini", "Gemini 2.5 Flash Lite", True, GEMINI_LANGUAGE_SUGGESTIONS)


def available_translation_options() -> list[TranslationProviderOption]:
    return [option for option in [libretranslate_option(), gemini_option()] if option.available]


def all_translation_options() -> list[TranslationProviderOption]:
    return [libretranslate_option(), gemini_option()]


def validate_translation_request(provider: str, source_language: str, target_language: str) -> tuple[str, str, str]:
    provider = provider.strip().lower()
    source_language = source_language.strip()
    target_language = target_language.strip()
    options = {option.id: option for option in all_translation_options()}
    option = options.get(provider)
    if option is None:
        raise ValueError("Unknown translation provider.")
    if not option.available:
        raise ValueError(option.reason or f"{option.label} is not available.")
    if not source_language or not target_language:
        raise ValueError("Choose both source and target languages.")
    if provider == "libretranslate":
        supported = {language.lower(): language for language in option.languages}
        missing = [language for language in [source_language, target_language] if language.lower() not in supported]
        if missing:
            available = ", ".join(sorted(option.languages))
            raise ValueError(f"LibreTranslate does not support: {', '.join(missing)}. Available languages: {available}")
        source_language = supported[source_language.lower()]
        target_language = supported[target_language.lower()]
    return provider, source_language, target_language
