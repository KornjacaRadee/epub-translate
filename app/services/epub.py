from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup, NavigableString, Tag
import ebooklib
from ebooklib import epub

from app.services.text import normalize_text


BLOCK_TAGS = {
    "p",
    "li",
    "blockquote",
    "figcaption",
    "td",
    "th",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "title",
    "caption",
    "dd",
    "dt",
}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "title"}
SKIP_TAGS = {"script", "style", "noscript"}
NOTE_EPUB_TYPES = {"footnote", "endnote", "note", "rearnote"}


@dataclass(slots=True)
class Segment:
    item_id: str
    order_in_item: int
    original_text: str
    placeholder_map: dict[str, str]
    content_kind: str


def is_translatable_tag(tag: Tag) -> bool:
    if tag.name in SKIP_TAGS:
        return False
    if tag.get("aria-hidden") == "true":
        return False
    if tag.has_attr("hidden"):
        return False
    return tag.name in BLOCK_TAGS


def _serialize_contents_with_placeholders(tag: Tag) -> tuple[str, dict[str, str]]:
    parts: list[str] = []

    def walk(node: Tag) -> None:
        for child in node.contents:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            elif isinstance(child, Tag):
                if child.name in SKIP_TAGS:
                    continue
                child_copy = BeautifulSoup(str(child), "html.parser")
                for skipped in child_copy.find_all(SKIP_TAGS):
                    skipped.decompose()
                parts.append(str(child_copy))

    walk(tag)
    rendered = "".join(parts).strip()
    return rendered, {}


def restore_placeholder_markup(text: str, placeholder_map: dict[str, str]) -> str:
    restored = text
    for token, markup in placeholder_map.items():
        restored = restored.replace(token, markup)
    return restored


def classify_segment(tag: Tag, item: epub.EpubHtml) -> str:
    file_name = (getattr(item, "file_name", "") or "").lower()
    epub_type = " ".join(str(tag.get(attr, "")) for attr in ("epub:type", "type", "role")).lower()
    if "nav" in file_name or tag.find_parent("nav") is not None:
        return "navigation"
    if tag.name in HEADING_TAGS:
        return "heading"
    if any(note_type in epub_type for note_type in NOTE_EPUB_TYPES):
        return "note"
    if tag.name in {"caption", "figcaption"}:
        return "caption"
    if tag.find_all("a") and normalize_text(tag.get_text(" ", strip=True)):
        direct_children = [child for child in tag.children if isinstance(child, Tag)]
        if direct_children and all(child.name == "a" for child in direct_children):
            return "link"
    return "body"


def has_translatable_ancestor(tag: Tag) -> bool:
    parent = tag.parent
    while isinstance(parent, Tag):
        if is_translatable_tag(parent):
            return True
        parent = parent.parent
    return False


def extract_segments(book: epub.EpubBook) -> list[Segment]:
    segments: list[Segment] = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        if not soup:
            continue
        order_in_item = 0
        for tag in soup.find_all(is_translatable_tag):
            if has_translatable_ancestor(tag):
                continue
            original_text, placeholder_map = _serialize_contents_with_placeholders(tag)
            if normalize_text(original_text):
                segments.append(
                    Segment(
                        item_id=item.get_id(),
                        order_in_item=order_in_item,
                        original_text=original_text,
                        placeholder_map=placeholder_map,
                        content_kind=classify_segment(tag, item),
                    )
                )
                order_in_item += 1
    return segments


def apply_translations(book: epub.EpubBook, translations: Iterable[tuple[Segment, str]]) -> epub.EpubBook:
    grouped: dict[str, list[tuple[Segment, str]]] = {}
    for segment, translated in translations:
        grouped.setdefault(segment.item_id, []).append((segment, translated))

    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        updates = grouped.get(item.get_id(), [])
        if not updates:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        ordered_targets = [tag for tag in soup.find_all(is_translatable_tag) if not has_translatable_ancestor(tag)]
        for segment, translated in updates:
            target = ordered_targets[segment.order_in_item]
            rendered = restore_placeholder_markup(translated, segment.placeholder_map)
            for child in list(target.contents):
                child.extract()
            fragment = BeautifulSoup(f"<wrapper>{rendered}</wrapper>", "html.parser").wrapper
            if fragment is None:
                target.string = translated
                continue
            for child in list(fragment.children):
                target.append(child)
        item.set_content(str(soup).encode("utf-8"))
    return book


def update_metadata_title(book: epub.EpubBook, title: str | None) -> None:
    if not title:
        return
    book.set_title(title)


def read_book(path: Path) -> epub.EpubBook:
    return epub.read_epub(str(path))


def write_book(book: epub.EpubBook, output_path: Path) -> None:
    epub.write_epub(str(output_path), book)


def rebuild_translated_epub(input_path: Path, translated_segments: list[tuple[Segment, str]], translated_title: str | None) -> Path:
    book = read_book(input_path)
    book = apply_translations(book, translated_segments)
    update_metadata_title(book, translated_title)
    tmp_dir = Path(tempfile.mkdtemp(prefix="epub-translate-"))
    output_path = tmp_dir / input_path.name
    write_book(book, output_path)
    return output_path
