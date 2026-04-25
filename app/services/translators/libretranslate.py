from __future__ import annotations

import json
import time
from typing import Callable

import httpx

from app.core.config import settings


class LibreTranslateError(RuntimeError):
    pass


LogCallback = Callable[[str], None]


class LibreTranslateClient:
    cache_namespace = "libretranslate"
    batch_char_budget = 1800

    def __init__(self, base_url: str | None = None, log_callback: LogCallback | None = None):
        self.base_url = (base_url or settings.libretranslate_url).rstrip("/")
        self.log_callback = log_callback

    def _log(self, message: str) -> None:
        if self.log_callback:
            self.log_callback(message)

    def healthcheck(self) -> bool:
        with httpx.Client(timeout=10) as client:
            response = client.get(f"{self.base_url}/languages")
            response.raise_for_status()
            return True

    def supported_languages(self) -> list[str]:
        with httpx.Client(timeout=10) as client:
            response = client.get(f"{self.base_url}/languages")
            response.raise_for_status()
        data = response.json()
        return [str(item.get("code")) for item in data if item.get("code")]

    def ensure_language_supported(self, source_language: str, target_language: str) -> None:
        supported = {code.lower(): code for code in self.supported_languages()}
        missing: list[str] = []
        if source_language.lower() not in supported:
            missing.append(source_language)
        if target_language.lower() not in supported:
            missing.append(target_language)
        if missing:
            available = ", ".join(sorted(supported.values()))
            raise LibreTranslateError(
                f"Configured LibreTranslate instance does not support: {', '.join(missing)}. "
                f"Available languages: {available}"
            )

    def _send_translate_request(self, texts: list[str], source_language: str, target_language: str) -> list[str]:
        last_error: Exception | None = None
        payload = {
            "q": texts,
            "source": source_language,
            "target": target_language,
            "format": "html",
        }
        if settings.libretranslate_api_key:
            payload["api_key"] = settings.libretranslate_api_key

        for attempt in range(settings.libretranslate_retries):
            try:
                self._log(
                    f"LibreTranslate request start: {len(texts)} texts, attempt {attempt + 1}/{settings.libretranslate_retries}"
                )
                with httpx.Client(timeout=settings.libretranslate_timeout_seconds) as client:
                    response = client.post(f"{self.base_url}/translate", json=payload)
                    response.raise_for_status()
                self._log(f"LibreTranslate request complete: {len(texts)} texts")
                data = response.json()
                translated = data.get("translatedText")
                if isinstance(translated, list):
                    return [str(item) for item in translated]
                if isinstance(translated, str):
                    return [translated]
                raise LibreTranslateError("Unexpected translation response payload.")
            except httpx.TimeoutException as exc:
                last_error = exc
                self._log(f"LibreTranslate request timeout: {len(texts)} texts on attempt {attempt + 1}")
                if attempt == settings.libretranslate_retries - 1:
                    raise
                time.sleep(min(2 ** attempt, 5))
            except httpx.HTTPStatusError as exc:
                last_error = exc
                detail = exc.response.text
                try:
                    parsed = exc.response.json()
                    detail = parsed.get("error") or json.dumps(parsed)
                except Exception:
                    pass
                self._log(f"LibreTranslate HTTP error {exc.response.status_code}: {detail}")
                if exc.response.status_code == 400:
                    raise LibreTranslateError(f"LibreTranslate rejected the request: {detail}") from exc
                if attempt == settings.libretranslate_retries - 1:
                    raise LibreTranslateError(f"LibreTranslate request failed: {detail}") from exc
                time.sleep(min(2 ** attempt, 5))
            except Exception as exc:
                last_error = exc
                self._log(f"LibreTranslate request error: {exc}")
                if attempt == settings.libretranslate_retries - 1:
                    raise
                time.sleep(min(2 ** attempt, 5))

        raise LibreTranslateError(f"LibreTranslate request failed: {last_error}")

    def _translate_with_timeout_fallback(self, texts: list[str], source_language: str, target_language: str) -> list[str]:
        try:
            return self._send_translate_request(texts, source_language, target_language)
        except httpx.TimeoutException as exc:
            if len(texts) <= 1:
                raise LibreTranslateError("LibreTranslate request failed: timed out") from exc
            midpoint = max(1, len(texts) // 2)
            self._log(
                f"Splitting timed out batch of {len(texts)} texts into {midpoint} and {len(texts) - midpoint}"
            )
            left = self._translate_with_timeout_fallback(texts[:midpoint], source_language, target_language)
            right = self._translate_with_timeout_fallback(texts[midpoint:], source_language, target_language)
            return left + right

    def translate_batch(
        self,
        texts: list[str],
        source_language: str,
        target_language: str,
        previous_context: str | None = None,
    ) -> list[str]:
        if not texts:
            return []
        try:
            return self._translate_with_timeout_fallback(texts, source_language, target_language)
        except LibreTranslateError:
            raise
        except httpx.TimeoutException as exc:
            raise LibreTranslateError("LibreTranslate request failed: timed out") from exc
        except Exception as exc:
            raise LibreTranslateError(f"LibreTranslate request failed: {exc}") from exc
