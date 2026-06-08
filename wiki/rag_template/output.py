"""Output formatters for the RAG prompt-template package (Prompt 34 MVP closure).

The output module provides two deterministic formatters for
:class:`wiki.rag_template.schema.RagPrompt`:

- :func:`format_readable` — a small Markdown report intended
  for interactive CLI use. The report is stable enough for
  tests (no timestamps, no random ordering).
- :func:`format_json` — a deterministic JSON document. The
  ``schema_version`` is always the first field, and the
  nested ``context_pack`` dict preserves the order produced
  by :meth:`wiki.context_pack.schema.ContextPack.to_dict`.

The formatters never raise on empty prompts; they emit a
small placeholder for the readable formatter and a valid
JSON document with ``total_chunks: 0`` for the JSON
formatter.
"""

from __future__ import annotations

import json
from typing import Any

from wiki.rag_template.schema import RagPrompt


def format_readable(prompt: RagPrompt) -> str:
    """Format a :class:`RagPrompt` as a stable Markdown report.

    The report contains the system message, the user message,
    and a small header with the schema metadata. The
    ``context_pack`` dict is **not** inlined into the readable
    report: it is the JSON projection of the upstream
    :class:`wiki.context_pack.schema.ContextPack` and is
    surfaced verbatim by the JSON formatter.
    """
    lines: list[str] = []
    lines.append("# RAG Prompt")
    lines.append("")
    lines.append(f"- Schema version: `{prompt.schema_version}`")
    lines.append(f"- Template: `{prompt.template_name}`")
    lines.append(f"- Query: `{prompt.query}`")
    lines.append(f"- Total chunks: {prompt.total_chunks}")
    lines.append(f"- Total sources: {prompt.total_sources}")
    lines.append(f"- Used chars: {prompt.used_chars}")
    lines.append(f"- Mock tag: `{prompt.mock_tag}`")
    lines.append(f"- Is mock: {prompt.is_mock}")
    lines.append(f"- Citation rule: {prompt.citation_rule}")
    lines.append("")
    lines.append("## System message")
    lines.append("")
    lines.append("```")
    lines.append(prompt.system_message.rstrip())
    lines.append("```")
    lines.append("")
    lines.append("## User message")
    lines.append("")
    lines.append("```markdown")
    lines.append(prompt.user_message.rstrip())
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def format_json(prompt: RagPrompt) -> str:
    """Format a :class:`RagPrompt` as a deterministic JSON document.

    The top-level key order is fixed and matches the
    :meth:`RagPrompt.to_dict` projection. The nested
    ``context_pack`` dict preserves the upstream order.
    """
    payload: dict[str, Any] = prompt.to_dict()
    ordered: dict[str, Any] = {
        "schema_version": payload["schema_version"],
        "template_name": payload["template_name"],
        "query": payload["query"],
        "instruction_template": payload["instruction_template"],
        "system_message": payload["system_message"],
        "user_message": payload["user_message"],
        "context_pack": payload["context_pack"],
        "citation_rule": payload["citation_rule"],
        "used_chars": payload["used_chars"],
        "total_chunks": payload["total_chunks"],
        "total_sources": payload["total_sources"],
        "mock_tag": payload["mock_tag"],
        "is_mock": payload["is_mock"],
    }
    return json.dumps(ordered, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


__all__ = [
    "format_json",
    "format_readable",
]
