"""Deterministic RAG answer evaluator (Prompt 34 MVP closure).

The :mod:`wiki.rag_eval` package evaluates a
:class:`wiki.mock_answer.schema.MockAnswer` against the
:class:`wiki.context_pack.schema.ContextPack` it was built
from. The evaluator is **rule-based**: it does not call any
model, does not import any LLM-as-judge library, and does
not require any network access.

The evaluator checks the following invariants:

- the answer body is non-empty
- the answer body carries the MOCK / NO-LLM banner
- the answer declares ``is_mock=True`` and the
  ``mock_tag`` starts with the no-LLM prefix
- every citation label in the answer exists in the context
  pack (no hallucinated labels)
- the cited source ids exist in the context pack
- when the context has chunks, the answer cites at least one
  of them
- the answer covers a reasonable fraction of the context
  chunks (chunk coverage)
- the answer covers a reasonable fraction of the unique
  sources (source coverage)

The package produces a :class:`RagAnswerReport` envelope
plus a list of per-check :class:`RagCheckResult` records.
The report is deterministic: same answer + same pack = same
report.

Public API
----------

- :func:`eval_rag` — the on-disk entry point used by the
  CLI. Reads the BM25 and vector indexes from the data dir,
  builds a :class:`ContextPack`, generates the mock answer,
  and evaluates the pair.
- :func:`eval_rag_in_memory` — the in-memory entry point
  used by tests and by callers that already have a
  :class:`ContextPack` and a :class:`MockAnswer`.
- :func:`format_readable` — the readable CLI formatter
  (Markdown).
- :func:`format_json` — the JSON CLI formatter.
- :class:`RagAnswerReport`, :class:`RagCheckResult` — the
  public dataclasses.
- :data:`RAG_EVAL_SCHEMA_VERSION` — the schema version string.
"""

from wiki.rag_eval.builder import (
    RAG_EVAL_SCHEMA_VERSION,
    RagCheckResult,
    RagAnswerReport,
    eval_rag,
    eval_rag_in_memory,
)
from wiki.rag_eval.output import format_json, format_readable


__all__ = [
    "RAG_EVAL_SCHEMA_VERSION",
    "RagAnswerReport",
    "RagCheckResult",
    "eval_rag",
    "eval_rag_in_memory",
    "format_json",
    "format_readable",
]
