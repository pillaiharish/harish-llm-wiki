"""Deterministic context-pack builder (Prompt 33).

The :mod:`wiki.context_pack` package converts a list of
:class:`wiki.retrieval.schema.RetrievalResult` objects into
a citation-ready context block for future RAG answer
generation. The pack is deterministic, no-LLM, and
pure-Python.

The package does **not** reimplement retrieval scoring and
it does **not** modify the chunk index, the BM25 index, the
vector index, or the graph backend. It reuses
:func:`wiki.retrieval.retrieve_hybrid` to fetch the ranked
result list and looks up the full chunk text from the
on-disk chunk index (``processed/chunk_index/chunks.json``).

Public API
----------

- :func:`build_context_pack` — the on-disk entry point used
  by the CLI. Reads the BM25 and vector indexes from the
  data dir.
- :func:`build_context_pack_in_memory` — the in-memory
  entry point used by tests and by callers that already
  have the :class:`RetrievalResult` list.
- :func:`build_context_pack_from_results` — the
  deterministic core used by both entry points.
- :func:`format_readable` — the readable CLI formatter
  (Markdown).
- :func:`format_json` — the JSON CLI formatter.
- :class:`ContextChunk`, :class:`ContextSource`,
  :class:`ContextPack` — the public dataclasses.
- :data:`CONTEXT_PACK_SCHEMA_VERSION`,
  :data:`DEFAULT_MODE`, :data:`DEFAULT_LIMIT`,
  :data:`DEFAULT_MAX_CHARS`, :data:`MAX_LIMIT` — the
  public constants.
"""

from wiki.context_pack.builder import (
    build_context_pack,
    build_context_pack_from_results,
    build_context_pack_in_memory,
)
from wiki.context_pack.output import format_json, format_readable
from wiki.context_pack.schema import (
    CITATION_LABEL_PREFIX,
    CONTEXT_PACK_SCHEMA_VERSION,
    ContextChunk,
    ContextPack,
    ContextSource,
    DEFAULT_LIMIT,
    DEFAULT_MAX_CHARS,
    DEFAULT_MODE,
    EMPTY_STRING,
    MAX_LIMIT,
    make_citation_label,
)


__all__ = [
    "CITATION_LABEL_PREFIX",
    "CONTEXT_PACK_SCHEMA_VERSION",
    "ContextChunk",
    "ContextPack",
    "ContextSource",
    "DEFAULT_LIMIT",
    "DEFAULT_MAX_CHARS",
    "DEFAULT_MODE",
    "EMPTY_STRING",
    "MAX_LIMIT",
    "build_context_pack",
    "build_context_pack_from_results",
    "build_context_pack_in_memory",
    "format_json",
    "format_readable",
    "make_citation_label",
]
