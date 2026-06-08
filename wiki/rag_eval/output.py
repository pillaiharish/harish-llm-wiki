"""Output formatters for the RAG answer evaluator (Prompt 34 MVP closure).

The output module provides two deterministic formatters for
:class:`wiki.rag_eval.schema.RagAnswerReport`:

- :func:`format_readable` — a small Markdown report intended
  for interactive CLI use. The report is stable enough for
  tests (no timestamps, no random ordering).
- :func:`format_json` — a deterministic JSON document. The
  ``schema_version`` is always the first field, the
  per-check results are in the same order the evaluator
  produced them, and the answer body is the verbatim
  generator output.

The formatters never raise on empty reports; the readable
formatter emits a small placeholder and the JSON formatter
emits a valid document with ``total_checks: 0``.
"""

from __future__ import annotations

import json
from typing import Any

from wiki.rag_eval.schema import RAG_EVAL_SCHEMA_VERSION, RagAnswerReport


def format_readable(report: RagAnswerReport) -> str:
    """Format a :class:`RagAnswerReport` as a stable Markdown report.

    The report contains the schema metadata, the totals, the
    per-check table, the answer body (verbatim, in a fenced
    block so the MOCK / NO-LLM banner is preserved), the
    citation labels, and the source ids.
    """
    lines: list[str] = []
    lines.append("# RAG Eval Report")
    lines.append("")
    lines.append(f"- Schema version: `{report.schema_version}`")
    lines.append(f"- Query: `{report.query}`")
    lines.append(f"- Mode: `{report.mode}`")
    lines.append(f"- Total checks: {report.total_checks}")
    lines.append(f"- Passed checks: {report.passed_checks}")
    lines.append(f"- Failed checks: {report.failed_checks}")
    lines.append(f"- Score: {report.score:.3f}")
    lines.append(f"- All passed: {report.all_passed}")
    lines.append(f"- Mock tag: `{report.mock_tag}`")
    lines.append(f"- Is mock: {report.is_mock}")
    lines.append(f"- Total chunks: {report.total_chunks}")
    lines.append(f"- Used chars: {report.used_chars}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    if report.checks:
        lines.extend([
            "| Check | Passed | Score | Detail |",
            "|---|---|---:|---|",
        ])
        for check in report.checks:
            detail = check.detail.replace("|", "\\|")
            lines.append(
                f"| {check.id} | {'yes' if check.passed else 'no'} | "
                f"{check.score:.3f} | {detail} |"
            )
    else:
        lines.append("_No checks were run._")
    lines.append("")
    if report.answer_citation_labels:
        lines.append("## Citation labels (from answer)")
        lines.append("")
        for label in report.answer_citation_labels:
            lines.append(f"- {label}")
        lines.append("")
    if report.answer_source_ids:
        lines.append("## Source ids (from answer)")
        lines.append("")
        for sid in report.answer_source_ids:
            lines.append(f"- `{sid}`")
        lines.append("")
    lines.append("## Answer body")
    lines.append("")
    lines.append("```markdown")
    lines.append((report.answer_body or "").rstrip())
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def format_json(report: RagAnswerReport) -> str:
    """Format a :class:`RagAnswerReport` as a deterministic JSON document.

    The top-level key order is fixed and matches the
    :meth:`RagAnswerReport.to_dict` projection. The
    ``checks`` list is in the same order the evaluator
    produced it.
    """
    payload: dict[str, Any] = report.to_dict()
    ordered: dict[str, Any] = {
        "schema_version": payload["schema_version"],
        "query": payload["query"],
        "mode": payload["mode"],
        "total_checks": payload["total_checks"],
        "passed_checks": payload["passed_checks"],
        "failed_checks": payload["failed_checks"],
        "score": payload["score"],
        "is_mock": payload["is_mock"],
        "mock_tag": payload["mock_tag"],
        "answer_body": payload["answer_body"],
        "answer_citation_labels": payload["answer_citation_labels"],
        "answer_source_ids": payload["answer_source_ids"],
        "total_chunks": payload["total_chunks"],
        "used_chars": payload["used_chars"],
        "checks": payload["checks"],
        "all_passed": payload["all_passed"],
    }
    return json.dumps(ordered, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


__all__ = [
    "format_json",
    "format_readable",
]


# Silence linter complaints about unused imports — these
# imports are part of the public type contract.
_ = RAG_EVAL_SCHEMA_VERSION
