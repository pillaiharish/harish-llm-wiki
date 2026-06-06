"""Shared helpers for generated static pages."""

from __future__ import annotations

import re
from pathlib import Path

from wiki.schemas import ResourceRecord
from wiki.storage import Storage


CHUNK_ID_RE = re.compile(r"([a-z_]+:[a-zA-Z0-9_-]+-[a-z]\d{3,6})")


def md_table_cell(text: str | None) -> str:
    """Escape text for Markdown table cells.

    Converts None to '', replaces newlines with spaces,
    collapses repeated whitespace, escapes pipe characters,
    and strips leading/trailing whitespace.
    """
    if text is None:
        return ""
    result = str(text)
    result = result.replace("\n", " ")
    result = re.sub(r"\s+", " ", result)
    result = result.replace("|", "\\|")
    return result.strip()


def resource_route(resource_id: str) -> str:
    """Return the canonical site route for a resource page."""
    return f"/resources/{resource_id.replace(':', '_')}"


def concept_route(slug: str) -> str:
    """Return the canonical site route for a concept page."""
    return f"/concepts/{slug}"


def topic_route(slug: str) -> str:
    """Return the canonical site route for a topic page."""
    return f"/topics/{slug}"


def learn_route(slug: str) -> str:
    """Return the canonical site route for a learn page."""
    return f"/learn/{slug}"


def read_note(record: ResourceRecord) -> str:
    if record.generated_note_path and Path(record.generated_note_path).exists():
        return Storage.read_text(Path(record.generated_note_path))
    return ""


def extract_section(content: str, heading: str) -> str:
    lines = content.splitlines()
    target = heading.lower()
    start = None
    level = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        text = stripped.lstrip("#").strip().lower()
        if text == target:
            start = index + 1
            level = len(stripped) - len(stripped.lstrip("#"))
            break
    if start is None or level is None:
        return ""
    end = len(lines)
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if not stripped.startswith("#"):
            continue
        next_level = len(stripped) - len(stripped.lstrip("#"))
        if next_level <= level:
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def bullet_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip().startswith(("-", "*"))]


def citation_count(content: str) -> int:
    return len(set(CHUNK_ID_RE.findall(content)))


def resource_link(record: ResourceRecord, title: str) -> str:
    escaped_title = md_table_cell(title)
    return f"[{escaped_title}]({resource_route(record.id)})"


def table_value(value: object) -> str:
    return md_table_cell(value)

