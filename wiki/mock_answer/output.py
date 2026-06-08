"""Output formatters for the mock-answer generator (Prompt 34 MVP closure).

The output module provides two deterministic formatters for
:class:`wiki.mock_answer.schema.MockAnswer`:

- :func:`format_readable` — a small Markdown report intended
  for interactive CLI use. The report is stable enough for
  tests (no timestamps, no random ordering).
- :func:`format_json` — a deterministic JSON document. The
  ``schema_version`` is always the first field, the citation
  list is in citation order, and the body is the verbatim
  generator output.

The formatters never raise on empty answers; the readable
formatter emits a small placeholder and the JSON formatter
emits a valid document with ``total_chunks: 0``.
"""

from __future__ import annotations

import json
from typing import Any

from wiki.mock_answer.schema import MOCK_ANSWER_BANNER, MockAnswer, NO_CONTEXT_BODY


def format_readable(answer: MockAnswer) -> str:
    """Format a :class:`MockAnswer` as a stable Markdown report.

    The report contains the schema metadata, the answer body,
    and the list of citation labels. The body is included
    verbatim inside a fenced block so the MOCK / NO-LLM banner
    is preserved.
    """
    lines: list[str] = []
    lines.append("# Mock Answer")
    lines.append("")
    lines.append(f"- Schema version: `{answer.schema_version}`")
    lines.append(f"- Answer version: `{answer.answer_version}`")
    lines.append(f"- Query: `{answer.query}`")
    lines.append(f"- Mode: `{answer.mode}`")
    lines.append(f"- Total chunks: {answer.total_chunks}")
    lines.append(f"- Used chars: {answer.used_chars}")
    lines.append(f"- Mock tag: `{answer.mock_tag}`")
    lines.append(f"- Is mock: {answer.is_mock}")
    lines.append("")
    if answer.citation_labels:
        lines.append("## Citation labels")
        lines.append("")
        for label in answer.citation_labels:
            lines.append(f"- {label}")
        lines.append("")
    else:
        lines.append("## Citation labels")
        lines.append("")
        lines.append("_No citation labels were used._")
        lines.append("")
    if answer.source_ids:
        lines.append("## Source ids")
        lines.append("")
        for sid in answer.source_ids:
            lines.append(f"- `{sid}`")
        lines.append("")
    if answer.used_chunk_ids:
        lines.append("## Used chunk ids")
        lines.append("")
        for cid, rank in zip(answer.used_chunk_ids, answer.used_chunk_ranks):
            lines.append(f"- rank {rank}: `{cid}`")
        lines.append("")
    lines.append("## Body")
    lines.append("")
    lines.append("```markdown")
    lines.append(answer.body.rstrip())
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def format_json(answer: MockAnswer) -> str:
    """Format a :class:`MockAnswer` as a deterministic JSON document.

    The top-level key order is fixed and matches the
    :meth:`MockAnswer.to_dict` projection.
    """
    payload: dict[str, Any] = answer.to_dict()
    ordered: dict[str, Any] = {
        "schema_version": payload["schema_version"],
        "answer_version": payload["answer_version"],
        "query": payload["query"],
        "mode": payload["mode"],
        "body": payload["body"],
        "citation_labels": payload["citation_labels"],
        "source_ids": payload["source_ids"],
        "total_chunks": payload["total_chunks"],
        "used_chars": payload["used_chars"],
        "mock_tag": payload["mock_tag"],
        "is_mock": payload["is_mock"],
        "used_chunk_ids": payload["used_chunk_ids"],
        "used_chunk_ranks": payload["used_chunk_ranks"],
    }
    return json.dumps(ordered, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


__all__ = [
    "format_json",
    "format_readable",
]


# Silence linter complaints about unused imports — these
# imports are part of the public type contract.
_ = (MOCK_ANSWER_BANNER, NO_CONTEXT_BODY)
