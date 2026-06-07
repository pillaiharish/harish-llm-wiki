"""Output formatters for the context pack (Prompt 33).

The output module provides two deterministic formatters for
:class:`wiki.context_pack.schema.ContextPack`:

- :func:`format_readable` — a small Markdown report intended
  for interactive CLI use. The report is stable enough for
  tests (no timestamps, no random ordering).
- :func:`format_json` — a deterministic JSON document. The
  ``schema_version`` is always the first field, the
  ``chunks`` and ``sources`` lists are in stable order, and
  the per-chunk text respects the trim.

The formatters never raise on empty packs; they emit a small
``(empty pack)`` placeholder for the readable formatter and
a valid JSON document with ``total_chunks: 0`` for the JSON
formatter.
"""

from __future__ import annotations

import json
from typing import Any

from wiki.context_pack.schema import (
    CONTEXT_PACK_SCHEMA_VERSION,
    ContextPack,
)


# =============================================================================
# Readable formatter
# =============================================================================


def format_readable(pack: ContextPack) -> str:
    """Format a :class:`ContextPack` as a stable Markdown report.

    The report is a deterministic string with no timestamps.
    Empty packs emit a one-line placeholder so the CLI does
    not produce blank output.
    """
    lines: list[str] = []
    lines.append("# Context Pack")
    lines.append("")
    lines.append(f"- Schema version: `{pack.schema_version}`")
    lines.append(f"- Query: `{pack.query}`")
    lines.append(f"- Mode: `{pack.mode}`")
    lines.append(f"- Limit: {pack.limit}")
    lines.append(f"- Max chars (per chunk): {pack.max_chars}")
    lines.append(f"- Total chunks: {pack.total_chunks}")
    lines.append(f"- Used chars: {pack.used_chars}")

    if not pack.chunks:
        lines.append("")
        lines.append("No chunks.")
        return "\n".join(lines) + "\n"

    lines.append("")
    lines.append("## Chunks")
    lines.append("")
    for chunk in pack.chunks:
        lines.append(f"### {chunk.citation_label} (rank {chunk.rank})")
        lines.append("")
        lines.append(
            f"- Resource: `{chunk.resource_id}`"
            + (f" — {chunk.title}" if chunk.title else "")
        )
        lines.append(f"- Source type: `{chunk.source_type or 'unknown'}`")
        lines.append(f"- Score: {chunk.score:.6f}")
        lines.append(f"- Chunk id: `{chunk.chunk_id}`")
        if chunk.truncated:
            lines.append(
                f"- Text (trimmed to {pack.max_chars} chars):"
            )
        else:
            lines.append("- Text:")
        lines.append("")
        # Use a fenced code block to keep the text verbatim
        # and avoid Markdown injection from the chunk
        # contents.
        lines.append("```")
        lines.append(chunk.text)
        lines.append("```")
        lines.append("")

    lines.append("## Sources")
    lines.append("")
    for source in pack.sources:
        lines.append(
            f"- {source.citation_label} "
            f"`{source.resource_id}`"
            + (f" — {source.title}" if source.title else "")
            + f" ({source.source_type or 'unknown'})"
        )
        for cid in source.chunk_ids:
            lines.append(f"    - chunk: `{cid}`")
    lines.append("")
    return "\n".join(lines)


# =============================================================================
# JSON formatter
# =============================================================================


def format_json(pack: ContextPack) -> str:
    """Format a :class:`ContextPack` as a deterministic JSON document.

    The top-level key order is fixed and matches the
    :meth:`ContextPack.to_dict` projection. The output
    contains no timestamps and no random ordering.
    """
    payload: dict[str, Any] = pack.to_dict()
    ordered: dict[str, Any] = {
        "schema_version": payload["schema_version"],
        "query": payload["query"],
        "mode": payload["mode"],
        "limit": payload["limit"],
        "max_chars": payload["max_chars"],
        "used_chars": payload["used_chars"],
        "total_chunks": payload["total_chunks"],
        "chunks": payload["chunks"],
        "sources": payload["sources"],
    }
    return json.dumps(ordered, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


__all__ = [
    "format_json",
    "format_readable",
]
