from __future__ import annotations

from pathlib import Path
import re

from ebooklib import epub
import httpx


def build_sample_epub(path: Path, title: str = "Sample Book") -> Path:
    book = epub.EpubBook()
    book.set_identifier("sample-id")
    book.set_title(title)
    book.set_language("en")

    chapter = epub.EpubHtml(title="Chapter 1", file_name="chapter1.xhtml", lang="en")
    chapter.content = """
    <html xmlns="http://www.w3.org/1999/xhtml">
      <body>
        <h1>Hello world</h1>
        <p>This is <em>important</em> text with a <a href="https://example.com">link</a>.</p>
      </body>
    </html>
    """
    book.add_item(chapter)
    book.toc = (chapter,)
    book.spine = ["nav", chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)
    return path


class FakeTranslator:
    def translate_batch(self, texts: list[str], source_language: str, target_language: str) -> list[str]:
        translated: list[str] = []
        for text in texts:
            value = text
            value = value.replace("Hello world", "Zdravo svete")
            value = value.replace("This is", "Ovo je")
            value = value.replace("important", "vazan")
            value = value.replace("text with a", "tekst sa")
            value = value.replace("link", "vezom")
            value = value.replace("Sample Book", "Primer knjige")
            translated.append(value)
        return translated


class FakeCyrillicTranslator:
    def translate_batch(self, texts: list[str], source_language: str, target_language: str) -> list[str]:
        translated: list[str] = []
        for text in texts:
            value = text
            value = value.replace("Hello world", "Здраво свете")
            value = value.replace("This is", "Ово је")
            value = value.replace("important", "важан")
            value = value.replace("text with a", "текст са")
            value = value.replace("link", "везом")
            value = value.replace("Sample Book", "Пример књиге")
            translated.append(value)
        return translated


class FakeMojibakeTranslator:
    def translate_batch(self, texts: list[str], source_language: str, target_language: str) -> list[str]:
        translated: list[str] = []
        for text in texts:
            value = text
            value = value.replace("Hello world", "Zdravo svete")
            value = value.replace("This is", "Ovo je")
            value = value.replace("important", "vaÅ¾an")
            value = value.replace("text with a", "tekst sa")
            value = value.replace("link", "vezom")
            value = value.replace("Sample Book", "Primer knjige")
            translated.append(value)
        return translated


class TimeoutFallbackSender:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, texts: list[str], source_language: str, target_language: str) -> list[str]:
        self.calls.append(list(texts))
        if len(texts) > 1:
            raise httpx.TimeoutException("timed out")
        return [f"ok:{texts[0]}"]


def extract_csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "CSRF token not found"
    return match.group(1)
