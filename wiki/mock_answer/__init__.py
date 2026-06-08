"""Deterministic, no-LLM mock answer generator (Prompt 34 MVP closure).

The :mod:`wiki.mock_answer` package generates a small
extractive answer from a
:class:`wiki.context_pack.schema.ContextPack`. The package is
deliberately tiny and dependency-free: it does not call any
model, does not import any provider, and does not require
any network access.

The MVP closure uses an extractive summarizer: it picks the
top-scoring chunk, extracts a few sentences that mention
query terms, and prepends a clearly-labeled "MOCK / NO-LLM
ANSWER" banner. Every claim is followed by the citation
label of the chunk it came from, so the downstream evaluator
(:mod:`wiki.rag_eval`) can validate the citations.

The package is **not** a real answer generator: it cannot
paraphrase, it cannot combine information across chunks, and
it cannot reason about the user's question. It exists so the
V1 MVP has a deterministic, testable "answer" surface that
matches the no-LLM closure intent.

Public API
----------

- :func:`generate_mock_answer` — the on-disk entry point used
  by the CLI. Reads the BM25 and vector indexes from the
  data dir, builds a :class:`ContextPack`, and delegates to
  :func:`generate_mock_answer_from_pack`.
- :func:`generate_mock_answer_from_pack` — the in-memory
  entry point used by tests and by callers that already have
  a :class:`ContextPack`.
- :func:`format_readable` — the readable CLI formatter
  (Markdown).
- :func:`format_json` — the JSON CLI formatter.
- :class:`MockAnswer` — the public dataclass.
- :data:`MOCK_ANSWER_SCHEMA_VERSION`,
  :data:`MOCK_ANSWER_BANNER`,
  :data:`MOCK_ANSWER_TAG` — the public constants.
"""

from wiki.mock_answer.builder import (
    MOCK_ANSWER_BANNER,
    MOCK_ANSWER_SCHEMA_VERSION,
    MOCK_ANSWER_TAG,
    MOCK_ANSWER_VERSION,
    MockAnswer,
    generate_mock_answer,
    generate_mock_answer_from_pack,
)
from wiki.mock_answer.output import format_json, format_readable


__all__ = [
    "MOCK_ANSWER_BANNER",
    "MOCK_ANSWER_SCHEMA_VERSION",
    "MOCK_ANSWER_TAG",
    "MOCK_ANSWER_VERSION",
    "MockAnswer",
    "format_json",
    "format_readable",
    "generate_mock_answer",
    "generate_mock_answer_from_pack",
]
