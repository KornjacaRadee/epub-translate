from __future__ import annotations


def clean_translation_error(error: Exception | str | None) -> str:
    """Map noisy provider/library failures to messages users can act on."""
    if error is None:
        return "Translation failed. Please try again later."

    raw_message = str(error).strip()
    message = raw_message.lower()

    if not raw_message:
        return "Translation failed. Please try again later."

    if "gemini is not configured" in message or "gemini_api_key" in message or "api key" in message and "missing" in message:
        return "Gemini is not configured. Add GEMINI_API_KEY and try again."

    if "401" in message or "403" in message or "permission_denied" in message or "unauthorized" in message:
        return "The translation provider rejected the request. Check your API key and permissions."

    if "429" in message or "resource_exhausted" in message or "quota" in message or "rate limit" in message:
        return "The translation provider rate limit or quota was reached. Wait a moment, then try again."

    if "503" in message or "unavailable" in message or "high demand" in message:
        return "The translation provider is temporarily busy. Wait a moment, then try again."

    if "timeout" in message or "timed out" in message:
        return "The translation provider took too long to respond. Try again with the same file."

    if "connection refused" in message or "failed to establish" in message or "not reachable" in message:
        return "The translation service is not reachable. Check that the selected engine is running and configured."

    if "invalid json" in message or "unexpected translation payload" in message:
        return "The translation provider returned an invalid response. Try again, or reduce the Gemini batch size."

    if "lost structural wrappers" in message:
        return "The translated response changed the EPUB structure. Try again, or use a smaller batch size."

    if "not a zip file" in message or "bad zip file" in message or "epub" in message and "invalid" in message:
        return "This does not look like a valid EPUB file. Check the file and upload it again."

    return raw_message if len(raw_message) <= 220 else "Translation failed. Please try again later."
