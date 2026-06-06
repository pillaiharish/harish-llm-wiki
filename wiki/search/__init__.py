"""Deterministic BM25-style lexical search backend (Prompt 28).

The BM25 backend reads the existing chunk index (Prompt 27) and
builds a deterministic inverted index for lexical search. It is
**not** a vector/embedding/semantic search system. The only
dependencies are Python's standard library and the existing
``wiki.chunks`` package.

Public API
----------

- :func:`tokenize` – the deterministic, dependency-free tokenizer
  used both at index time and at query time.
- :class:`BM25Scorer` – the BM25 score calculator. Pure dataclass,
  no I/O, unit-testable on its own.
- :class:`BM25IndexBuilder` / :func:`build_bm25_index` – read the
  chunk index and produce an in-memory inverted index.
- :func:`write_bm25_index` – write the deterministic
  ``index.json`` / ``manifest.json`` files (plus
  ``stats.json``).
- :func:`write_public_copy` – write a small public copy of the
  index into the site dir.
- :func:`iter_bm25_index_issues` – non-brittle validator that
  yields ``(severity, code, message)`` tuples.
- :class:`SearchResult` – the public search-result dataclass.
- :func:`search_bm25` – the search runtime that combines the
  on-disk index, the chunk-index text, and the BM25 scorer.
- :data:`BM25_SCHEMA_VERSION` – the schema version string.

This module does **not** add vector search, embeddings, FAISS,
Chroma, LanceDB, semantic search, Graph RAG retrieval, hybrid
ranking, LLM answer generation, or chatbot UI. Those belong to
later prompts.
"""

from __future__ import annotations

from wiki.search.tokenize import tokenize
from wiki.search.bm25 import (
    BM25_DEFAULT_B,
    BM25_DEFAULT_K1,
    BM25Scorer,
    Score,
    SearchResult,
)
from wiki.search.index import (
    BM25IndexBuilder,
    BM25IndexResult,
    build_bm25_index,
    load_bm25_index,
)
from wiki.search.export import (
    BM25_SCHEMA_VERSION,
    bm25_output_paths,
    public_bm25_paths,
    write_bm25_index,
    write_public_copy,
)
from wiki.search.validate import iter_bm25_index_issues
from wiki.search.search import search_bm25, search_bm25_in_memory


__all__ = [
    "BM25_DEFAULT_B",
    "BM25_DEFAULT_K1",
    "BM25Scorer",
    "BM25IndexBuilder",
    "BM25IndexResult",
    "BM25_SCHEMA_VERSION",
    "Score",
    "SearchResult",
    "bm25_output_paths",
    "build_bm25_index",
    "iter_bm25_index_issues",
    "load_bm25_index",
    "public_bm25_paths",
    "search_bm25",
    "search_bm25_in_memory",
    "tokenize",
    "write_bm25_index",
    "write_public_copy",
]
