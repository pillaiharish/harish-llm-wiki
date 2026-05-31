"""Citation resolver: load chunks, linkify citations, render source chunks section."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

from wiki.resource_utils import anchor_slug, short_citation_label
from wiki.schemas import YouTubeChunk, WebpageChunk, MarkdownChunk, SourceChunk


CITATION_PATTERN = re.compile(r"\[(?:source:\s*)?([a-z]+:[a-zA-Z0-9_-]+-[a-z]\d{3,4})\]")

FENCED_CODE_RE = re.compile(r"```[\s\S]*?```", re.DOTALL)


def load_chunks(norm_dir: Path) -> Iterator[SourceChunk]:
    """Load chunks from a normalized directory's chunks.jsonl."""
    chunks_path = norm_dir / "chunks.jsonl"
    if not chunks_path.exists():
        return
    for data in _read_jsonl(chunks_path):
        source_type = data.get("source_type")
        if source_type == "youtube":
            yield YouTubeChunk.model_validate(data)
        elif source_type == "webpage":
            yield WebpageChunk.model_validate(data)
        elif source_type == "markdown":
            yield MarkdownChunk.model_validate(data)


def load_chunk_map(norm_dir: Path) -> dict[str, SourceChunk]:
    """Return a mapping from chunk_id to SourceChunk for all chunks in norm_dir."""
    result: dict[str, SourceChunk] = {}
    for chunk in load_chunks(norm_dir):
        result[str(chunk.chunk_id)] = chunk
    return result


def citation_anchor(chunk_id: str) -> str:
    """Return a stable VitePress-safe anchor slug for a chunk ID."""
    return anchor_slug(chunk_id)


def _extract_text_outside_code_blocks(text: str) -> list[tuple[int, int]]:
    """Return list of (start, end) spans covering fenced code blocks."""
    spans: list[tuple[int, int]] = []
    for m in FENCED_CODE_RE.finditer(text):
        spans.append((m.start(), m.end()))
    return spans


def _is_inside_code_block(position: int, code_spans: list[tuple[int, int]]) -> bool:
    """Return True if the position falls inside any code block span."""
    for start, end in code_spans:
        if start <= position < end:
            return True
    return False


def linkify_citations(markdown: str, chunk_map: dict[str, SourceChunk]) -> tuple[str, set[str], list[str]]:
    """Convert raw citation tokens to clickable Markdown links.

    Returns (processed_markdown, cited_chunk_ids, missing_chunk_ids).
    Does not modify text inside fenced code blocks.
    """
    code_spans = _extract_text_outside_code_blocks(markdown)
    cited_ids: set[str] = set()
    missing_ids: list[str] = []
    result_parts: list[str] = []
    last_end = 0

    for m in CITATION_PATTERN.finditer(markdown):
        start, end = m.start(), m.end()
        if _is_inside_code_block(start, code_spans):
            continue
        chunk_id = m.group(1)
        result_parts.append(markdown[last_end:start])
        if chunk_id in chunk_map:
            anchor = citation_anchor(chunk_id)
            label = short_citation_label(chunk_id)
            result_parts.append(f"[{label}](#{anchor})<!-- {chunk_id} -->")
            cited_ids.add(chunk_id)
        else:
            result_parts.append(f"[missing source chunk: {chunk_id}]")
            missing_ids.append(chunk_id)
        last_end = end

    result_parts.append(markdown[last_end:])
    return "".join(result_parts), cited_ids, missing_ids


def _format_chunk_excerpt(chunk: SourceChunk) -> str:
    """Format a short text excerpt for a chunk's details section."""
    text = chunk.text[:500]
    if len(chunk.text) > 500:
        text = text.rstrip() + "..."
    return text


def _format_timestamp_url(chunk: SourceChunk) -> str | None:
    """Return a timestamped YouTube URL if the chunk has start_time, else None."""
    if isinstance(chunk, YouTubeChunk) and chunk.start_time is not None:
        video_id = getattr(chunk, "resource_id", "")
        if video_id and video_id.startswith("youtube:"):
            video_id = video_id.split(":", 1)[1]
        if video_id:
            return f"https://youtube.com/watch?v={video_id}&t={int(chunk.start_time)}"
    return None


def render_source_chunks_section(
    chunk_map: dict[str, SourceChunk],
    cited_ids: set[str],
    source_url: str = "",
) -> str:
    """Render the Source chunks section as Markdown with HTML details/summary.

    Only renders chunks that are cited in the note.
    """
    if not cited_ids:
        return "\n\n## Source chunks\n\n_No source chunks were cited._\n"

    lines = ["\n\n## Source chunks\n"]
    for chunk_id in sorted(cited_ids):
        chunk = chunk_map.get(chunk_id)
        if chunk is None:
            lines.append(f"\n<a id=\"{citation_anchor(chunk_id)}\"></a>\n")
            lines.append(f"[missing source chunk: {chunk_id}]\n")
            continue

        anchor = citation_anchor(chunk_id)
        label = getattr(chunk, "citation_label_formatted", None) or chunk.citation_label
        url = _format_timestamp_url(chunk)
        source_type = chunk.source_type.value

        lines.append(f"\n<a id=\"{anchor}\"></a>\n")
        lines.append("<details>\n")

        if isinstance(chunk, YouTubeChunk):
            summary = f"{chunk_id} — {label}"
        elif isinstance(chunk, (WebpageChunk, MarkdownChunk)):
            heading = getattr(chunk, "section_heading", None) or ""
            para = getattr(chunk, "paragraph_index", None)
            detail = f"section \"{heading}\", paragraph {para}" if heading and para is not None else heading or label
            summary = f"{chunk_id} — {detail}"
        else:
            summary = f"{chunk_id} — {label}"

        lines.append(f"<summary>{summary}</summary>\n\n")

        if url:
            lines.append(f"Source URL: {url}\n\n")
        elif source_url:
            lines.append(f"Source URL: {source_url}\n\n")

        lines.append(f"Source type: {source_type}\n\n")
        lines.append(f"> {_format_chunk_excerpt(chunk)}\n\n")
        lines.append("</details>\n")

    lines.append("")
    return "".join(lines)


def strip_source_chunks_section(markdown: str) -> str:
    """Remove an existing Source chunks section from markdown.

    Ensures idempotency: calling build-site --refresh multiple times
    does not duplicate the Source chunks section.
    """
    lines = markdown.splitlines()
    result: list[str] = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if stripped.lower() == "## source chunks":
            skip = True
            continue
        if skip and stripped.startswith("## "):
            skip = False
            result.append(line)
            continue
        if skip and stripped.startswith("<a id="):
            continue
        if skip and stripped.startswith("<details>"):
            continue
        if skip and stripped.startswith("</details>"):
            continue
        if skip and stripped.startswith("<summary>"):
            continue
        if skip and stripped.startswith("Source URL:") or (skip and stripped.startswith("Source type:")):
            continue
        if skip and stripped.startswith("> "):
            continue
        if skip and stripped == "":
            continue
        if skip:
            continue
        result.append(line)
    return "\n".join(result).rstrip()


def _read_jsonl(path: Path) -> Iterator[dict]:
    """Read JSONL file and yield parsed dicts."""
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
