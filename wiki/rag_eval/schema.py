"""Public schema for the RAG answer evaluator (Prompt 34 MVP closure).

This module defines the on-the-wire shape of a deterministic
RAG evaluation report. The report is the result of applying
the rule-based evaluator (:func:`wiki.rag_eval.builder.eval_rag_in_memory`)
to a :class:`wiki.mock_answer.schema.MockAnswer` and the
:class:`wiki.context_pack.schema.ContextPack` it was built
from.

The schema has two dataclasses:

- :class:`RagCheckResult` — one row per check. Each check
  has a stable ``id`` (e.g. ``cited_answer_has_citations``),
  a human-readable ``name``, a boolean ``passed``, and a
  short ``detail`` string for the failure path.
- :class:`RagAnswerReport` — the top-level envelope. It
  carries the schema metadata, the totals (checks, passed,
  failed, score), the per-check results, the answer and pack
  echoes (query, mode, body, citation labels, source ids,
  total_chunks, used_chars), and the small mock/no-LLM tag.

The dataclasses are frozen so the report is immutable and
the ``to_dict()`` projection is the contract for the JSON
CLI output and the static report page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# =============================================================================
# Constants
# =============================================================================


#: Schema version string for the RAG evaluator. Bumped only
#: when the public JSON shape changes in a breaking way.
RAG_EVAL_SCHEMA_VERSION: str = "rag_eval_v1"

#: Check ids. The order of the tuple is the order the
#: evaluator emits the checks in. Adding a new check is a
#: backwards-compatible change; removing a check is a
#: breaking change.
CHECK_HAS_BODY: str = "answer_has_body"
CHECK_MOCK_BANNER: str = "answer_marked_mock_no_llm"
CHECK_IS_MOCK_FLAG: str = "answer_is_mock_flag"
CHECK_CITATIONS_PRESENT: str = "cited_answer_has_citations"
CHECK_CITATIONS_VALID: str = "citations_exist_in_context"
CHECK_NO_HALLUCINATED_SOURCES: str = "no_hallucinated_source_ids"
CHECK_NON_EMPTY_WHEN_CONTEXT: str = "answer_non_empty_when_context"
CHECK_CHUNK_COVERAGE: str = "context_chunk_coverage"
CHECK_SOURCE_COVERAGE: str = "context_source_coverage"

#: Stable prefix for the mock tag. The evaluator greps the
#: body for this prefix (alongside the explicit banner) to
#: confirm the answer is mock/no-LLM.
MOCK_TAG_PREFIX: str = "no-llm"


# =============================================================================
# Check result
# =============================================================================


@dataclass(frozen=True)
class RagCheckResult:
    """A single rule-based check result.

    Fields
    ------
    id:
        Stable check id (see ``CHECK_*`` constants).
    name:
        Human-readable check name.
    passed:
        ``True`` when the check passed, ``False`` otherwise.
    detail:
        Short detail string. ``""`` when the check passed.
        The detail is intended for the readable CLI / report
        page; it is not parsed by downstream code.
    score:
        A small float in ``[0.0, 1.0]`` that represents how
        close the answer is to passing the check. ``1.0``
        when the check passed; for coverage checks the score
        is the actual coverage ratio. The score is the
        canonical way to aggregate the per-check results
        into a single number.
    """

    id: str
    name: str
    passed: bool
    detail: str = ""
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Project to a dict in stable field order."""
        return {
            "id": self.id,
            "name": self.name,
            "passed": bool(self.passed),
            "detail": self.detail,
            "score": float(self.score),
        }


# =============================================================================
# Report envelope
# =============================================================================


@dataclass(frozen=True)
class RagAnswerReport:
    """The deterministic RAG evaluation report.

    Fields
    ------
    schema_version:
        The :data:`RAG_EVAL_SCHEMA_VERSION` string. Always
        the first field of the JSON projection.
    query:
        The user query (echoed from the answer).
    mode:
        The retrieval mode (echoed from the pack).
    total_checks:
        The number of checks in :attr:`checks`.
    passed_checks:
        The number of checks with :attr:`RagCheckResult.passed` ``True``.
    failed_checks:
        The number of checks with :attr:`RagCheckResult.passed` ``False``.
    score:
        The aggregate score in ``[0.0, 1.0]``. Equal to
        ``passed_checks / total_checks`` when ``total_checks``
        is non-zero, else ``0.0``.
    is_mock:
        The ``is_mock`` flag from the answer (echoed).
    mock_tag:
        The ``mock_tag`` from the answer (echoed).
    answer_body:
        The verbatim answer body (echoed).
    answer_citation_labels:
        The list of citation labels the answer used (echoed).
    answer_source_ids:
        The list of source ids the answer used (echoed).
    total_chunks:
        The number of chunks in the context pack.
    used_chars:
        The total number of characters consumed by the
        ``chunks[].text`` fields of the context pack.
    checks:
        The list of :class:`RagCheckResult` records in the
        order the evaluator produced them.
    all_passed:
        ``True`` when every check passed.
    """

    schema_version: str
    query: str
    mode: str
    total_checks: int
    passed_checks: int
    failed_checks: int
    score: float
    is_mock: bool
    mock_tag: str
    answer_body: str
    answer_citation_labels: list = field(default_factory=list)
    answer_source_ids: list = field(default_factory=list)
    total_chunks: int = 0
    used_chars: int = 0
    checks: list = field(default_factory=list)
    all_passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Project to a dict in stable field order."""
        return {
            "schema_version": self.schema_version,
            "query": self.query,
            "mode": self.mode,
            "total_checks": int(self.total_checks),
            "passed_checks": int(self.passed_checks),
            "failed_checks": int(self.failed_checks),
            "score": float(self.score),
            "is_mock": bool(self.is_mock),
            "mock_tag": self.mock_tag,
            "answer_body": self.answer_body,
            "answer_citation_labels": list(self.answer_citation_labels),
            "answer_source_ids": list(self.answer_source_ids),
            "total_chunks": int(self.total_chunks),
            "used_chars": int(self.used_chars),
            "checks": [c.to_dict() for c in self.checks],
            "all_passed": bool(self.all_passed),
        }


__all__ = [
    "CHECK_CHUNK_COVERAGE",
    "CHECK_CITATIONS_PRESENT",
    "CHECK_CITATIONS_VALID",
    "CHECK_HAS_BODY",
    "CHECK_IS_MOCK_FLAG",
    "CHECK_MOCK_BANNER",
    "CHECK_NON_EMPTY_WHEN_CONTEXT",
    "CHECK_NO_HALLUCINATED_SOURCES",
    "CHECK_SOURCE_COVERAGE",
    "MOCK_TAG_PREFIX",
    "RAG_EVAL_SCHEMA_VERSION",
    "RagAnswerReport",
    "RagCheckResult",
]
