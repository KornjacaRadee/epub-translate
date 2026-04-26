from __future__ import annotations

import json
import re
import time
from typing import Callable

from app.core.config import settings


class GeminiTranslateError(RuntimeError):
    pass


LogCallback = Callable[[str], None]


class GeminiTranslator:
    cache_namespace = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        log_callback: LogCallback | None = None,
    ):
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.gemini_model
        self.batch_char_budget = settings.gemini_batch_char_budget
        self.log_callback = log_callback
        if not self.api_key:
            raise GeminiTranslateError("Gemini is not configured. Set GEMINI_API_KEY to use Gemini translation.")
        try:
            from google import genai
        except ModuleNotFoundError as exc:
            raise GeminiTranslateError("Gemini support requires the google-genai package.") from exc
        self.client = genai.Client(api_key=self.api_key)

    def _log(self, message: str) -> None:
        if self.log_callback:
            self.log_callback(message)

    def healthcheck(self) -> bool:
        from google.genai import types

        response = self.client.models.generate_content(
            model=self.model,
            contents="Reply with only: ok",
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=8,
            ),
        )
        return "ok" in (response.text or "").lower()

    def ensure_language_supported(self, source_language: str, target_language: str) -> None:
        if not source_language.strip() or not target_language.strip():
            raise GeminiTranslateError("Gemini translation needs both source and target languages.")

    def _build_prompt(
        self,
        texts: list[str],
        source_language: str,
        target_language: str,
        previous_context: str | None = None,
    ) -> str:
        payload = json.dumps(texts, ensure_ascii=False)
        context_block = ""
        if previous_context:
            context_block = (
                "Previous context for continuity only:\n"
                "- Use it to understand characters, pronouns, tone, terminology, and scene continuity.\n"
                "- Do not translate, summarize, copy, or include this context unless the same text appears in the input JSON array.\n\n"
                f"{previous_context}\n\n"
            )
        return (
            "You are a professional literary translator and editor.\n"
            "Translate each item in this JSON array for a real ebook reader.\n\n"
            f"Source language: {source_language}\n"
            f"Target language: {target_language}\n\n"
            f"{context_block}"
            "Main goal:\n"
            "- Produce a natural, fluent, readable translation in the target language.\n"
            "- Preserve the original meaning, tone, emotion, and narrative flow.\n"
            "- Do not translate word-for-word when it sounds unnatural.\n"
            "- Rewrite sentence structure when needed so it reads like native writing.\n"
            "- Keep dialogue natural and easy to understand.\n"
            "- Keep character names, places, brands, invented terms, and proper nouns unchanged unless they have a standard translation.\n"
            "- Preserve consistency of terminology across all items.\n\n"
            "HTML and formatting rules:\n"
            "- Preserve all HTML tags exactly.\n"
            "- Preserve all attributes exactly, including href, src, class, id, style, data-* and aria-* attributes.\n"
            "- Preserve HTML entities exactly when they are part of formatting.\n"
            "- Preserve placeholders exactly, such as {name}, {{value}}, %s, %d, $1, [[token]], <var>.\n"
            "- Translate only human-readable text content.\n"
            "- Do not remove, reorder, merge, or split items.\n\n"
            "Output rules:\n"
            "- Return only a valid JSON array of strings.\n"
            "- The output array must have exactly the same length and order as the input array.\n"
            "- Do not add explanations, markdown, numbering, comments, or wrapper objects.\n"
            "- Escape quotes and special characters correctly so the result is valid JSON.\n\n"
            "Quality check before answering:\n"
            "- Check that the translation is fluent and understandable.\n"
            "- Check that no HTML, attributes, placeholders, or array items were changed incorrectly.\n\n"
            f"Input JSON array:\n{payload}"
        )

    def _parse_response(self, text: str, expected_count: int) -> list[str]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
            cleaned = cleaned.removesuffix("```").strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise GeminiTranslateError("Gemini returned invalid JSON.") from exc
        if not isinstance(parsed, list) or len(parsed) != expected_count:
            raise GeminiTranslateError("Gemini returned an unexpected translation payload.")
        return [str(item) for item in parsed]

    def _send_request(
        self,
        texts: list[str],
        source_language: str,
        target_language: str,
        previous_context: str | None = None,
    ) -> list[str]:
        from google.genai import types

        prompt = self._build_prompt(texts, source_language, target_language, previous_context=previous_context)
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            ),
        )
        if not response.text:
            raise GeminiTranslateError("Gemini returned an empty translation response.")
        return self._parse_response(response.text, len(texts))

    def _retry_delay_seconds(self, exc: Exception, attempt: int) -> float:
        message = str(exc)
        retry_delay_match = re.search(r"retryDelay['\"]?: ['\"]?(\d+(?:\.\d+)?)s", message)
        if retry_delay_match:
            return min(float(retry_delay_match.group(1)) + 1, 90)
        retry_in_match = re.search(r"retry in (\d+(?:\.\d+)?)s", message, flags=re.IGNORECASE)
        if retry_in_match:
            return min(float(retry_in_match.group(1)) + 1, 90)
        if self._is_capacity_or_quota_error(exc):
            return min(10 * (attempt + 1), 60)
        return min(2 ** attempt, 5)

    def _is_capacity_or_quota_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return any(
            marker in message
            for marker in [
                "429",
                "503",
                "resource_exhausted",
                "unavailable",
                "quota",
                "high demand",
            ]
        )

    def translate_batch(
        self,
        texts: list[str],
        source_language: str,
        target_language: str,
        previous_context: str | None = None,
    ) -> list[str]:
        if not texts:
            return []
        last_error: Exception | None = None
        for attempt in range(settings.gemini_retries):
            try:
                self._log(f"Gemini request start: {len(texts)} texts, attempt {attempt + 1}/{settings.gemini_retries}")
                translated = self._send_request(
                    texts,
                    source_language,
                    target_language,
                    previous_context=previous_context,
                )
                self._log(f"Gemini request complete: {len(texts)} texts")
                return translated
            except Exception as exc:
                last_error = exc
                self._log(f"Gemini request error: {exc}")
                if (
                    len(texts) > 1
                    and attempt == settings.gemini_retries - 1
                    and not self._is_capacity_or_quota_error(exc)
                ):
                    midpoint = max(1, len(texts) // 2)
                    self._log(f"Splitting Gemini batch of {len(texts)} texts into {midpoint} and {len(texts) - midpoint}")
                    left = self.translate_batch(
                        texts[:midpoint],
                        source_language,
                        target_language,
                        previous_context=previous_context,
                    )
                    right = self.translate_batch(
                        texts[midpoint:],
                        source_language,
                        target_language,
                        previous_context=previous_context,
                    )
                    return left + right
                if attempt == settings.gemini_retries - 1:
                    break
                delay = self._retry_delay_seconds(exc, attempt)
                self._log(f"Waiting {delay:.0f}s before retrying Gemini")
                time.sleep(delay)
        raise GeminiTranslateError(f"Gemini translation failed: {last_error}")
