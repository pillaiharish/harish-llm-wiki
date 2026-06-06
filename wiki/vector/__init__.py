"""Deterministic local vector search backend (Prompt 29).

The vector backend reads the existing chunk index (Prompt 27) and
builds a deterministic, in-process vector index for lexical
vector similarity search. It is **not** a model-based embedding
backend; the vectorizer is a small pure-Python hashing TF-IDF
implementation.

Public API
----------

- :func:`tokenize` - the deterministic, dependency-free tokenizer
  used both at index time and at query time. Byte-identical
  contract to :func:`wiki.search.tokenize.tokenize`.
- :class:`HashingTfidfVectorizer` - the pure-Python hashing
  vectorizer with TF-IDF weighting, L2 normalization, and cosine
  similarity.
- :class:`VectorizerConfig` and :class:`VectorizerState` - the
  vectorizer configuration and the state learned at index time.
- :class:`VectorIndexBuilder` and :func:`build_vector_index` -
  read the chunk index and produce an in-memory vector index.
- :func:`write_vector_index` - write the deterministic
  ``index.json`` / ``manifest.json`` files (plus
  ``stats.json``).
- :func:`write_public_copy` - write a small public copy of the
  index into the site dir.
- :func:`iter_vector_index_issues` - non-brittle validator that
  yields ``(severity, code, message)`` tuples.
- :class:`SearchResult` - the public search-result dataclass.
- :func:`search_vector` - the search runtime that combines the
  on-disk index, the chunk-index text, and the cosine scorer.
- :data:`VECTOR_SCHEMA_VERSION` - the schema version string.

This module does **not** add model-based embeddings (Ollama,
sentence-transformers, OpenAI), vector databases (FAISS, Chroma,
LanceDB, Qdrant, Milvus), semantic search, Graph RAG retrieval,
hybrid ranking, LLM answer generation, or chatbot UI. Those belong
to later prompts.
"""

from __future__ import annotations

from wiki.vector.export import (
    VECTOR_SCHEMA_VERSION,
    public_vector_paths,
    vector_output_paths,
    write_public_copy,
    write_vector_index,
)
from wiki.vector.index import (
    TEXT_PREVIEW_CHARS,
    VectorIndexBuilder,
    VectorIndexResult,
    build_vector_index,
    load_vector_index,
)
from wiki.vector.search import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    SearchResult,
    search_vector,
    search_vector_in_memory,
)
from wiki.vector.tokenize import (
    DEFAULT_MIN_TOKEN_LENGTH,
    STOPWORDS,
    tokenize,
    token_count,
)
from wiki.vector.validate import iter_vector_index_issues
from wiki.vector.vectorizer import (
    DEFAULT_DIMENSION,
    DEFAULT_FIELD_WEIGHTS,
    HASH_FAMILY,
    HashingTfidfVectorizer,
    NORM,
    VectorizerConfig,
    VectorizerState,
)


__all__ = [
    "DEFAULT_DIMENSION",
    "DEFAULT_FIELD_WEIGHTS",
    "DEFAULT_LIMIT",
    "DEFAULT_MIN_TOKEN_LENGTH",
    "HASH_FAMILY",
    "HashingTfidfVectorizer",
    "MAX_LIMIT",
    "NORM",
    "SearchResult",
    "STOPWORDS",
    "TEXT_PREVIEW_CHARS",
    "VECTOR_SCHEMA_VERSION",
    "VectorIndexBuilder",
    "VectorIndexResult",
    "VectorizerConfig",
    "VectorizerState",
    "build_vector_index",
    "iter_vector_index_issues",
    "load_vector_index",
    "public_vector_paths",
    "search_vector",
    "search_vector_in_memory",
    "token_count",
    "tokenize",
    "vector_output_paths",
    "write_public_copy",
    "write_vector_index",
]
