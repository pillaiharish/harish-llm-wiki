"""Deterministic hybrid retrieval router (Prompt 30).

The :mod:`wiki.retrieval` package unifies the existing BM25
lexical backend (Prompt 28), the deterministic local vector
backend (Prompt 29), and a small, bounded graph-lite metadata
boost sourced from the existing knowledge graph (Prompt 23 +
24) into a single ranked, citation-aware chunk result list.

The package is **pure-Python and deterministic**: same indexes
+ same query + same mode = same ranking. It does not call any
LLM, does not import model embeddings, does not import
FAISS / Chroma / LanceDB / Qdrant / Milvus, and does not perform
graph traversal search. The graph-lite boost is a re-ranking
signal over an already-ranked candidate set, not a separate
retriever.

Public API
----------

- :func:`retrieve_hybrid` — the on-disk entry point used by
  the CLI. Reads the BM25 and vector indexes from the data dir.
- :func:`retrieve_hybrid_in_memory` — the in-memory entry point
  used by tests and by callers that already have the indexes in
  memory.
- :class:`RetrievalResult`, :class:`ComponentScores`,
  :class:`Explanation`, :class:`RetrievalResponse` — the public
  result dataclasses.
- :class:`ALLOWED_MODES`, :class:`DEFAULT_MODE`,
  :class:`DEFAULT_BM25_WEIGHT`, :class:`DEFAULT_VECTOR_WEIGHT`,
  :class:`DEFAULT_LIMIT`, :class:`MAX_LIMIT`,
  :class:`GRAPH_LITE_MAX_BOOST`, :class:`RETRIEVAL_SCHEMA_VERSION`
  — the public constants.
- :func:`iter_retrieval_issues`,
  :func:`iter_retrieval_result_issues` — the validators used by
  ``wiki validate`` and ``wiki smoke-site``.
"""

from wiki.retrieval.fusion import (
    apply_graph_lite_boost,
    linear_fuse,
    max_normalize,
    sort_keys_deterministically,
    topk,
)
from wiki.retrieval.router import (
    retrieve_hybrid,
    retrieve_hybrid_in_memory,
)
from wiki.retrieval.schema import (
    ALLOWED_MODES,
    ComponentScores,
    DEFAULT_BM25_WEIGHT,
    DEFAULT_LIMIT,
    DEFAULT_MODE,
    DEFAULT_VECTOR_WEIGHT,
    Explanation,
    GRAPH_LITE_MAX_BOOST,
    HYBRID_FETCH_FACTOR,
    MAX_LIMIT,
    RESOURCE_RELATIONSHIP_BOOST_MAX,
    RETRIEVAL_SCHEMA_VERSION,
    RetrievalResponse,
    RetrievalResult,
    SAME_TOPIC_BOOST_MAX,
    SHARED_CONCEPT_BOOST_MAX,
    SOURCE_TYPE_BOOST_MAX,
)
from wiki.retrieval.validate import (
    iter_retrieval_issues,
    iter_retrieval_result_issues,
)


__all__ = [
    "ALLOWED_MODES",
    "ComponentScores",
    "DEFAULT_BM25_WEIGHT",
    "DEFAULT_LIMIT",
    "DEFAULT_MODE",
    "DEFAULT_VECTOR_WEIGHT",
    "Explanation",
    "GRAPH_LITE_MAX_BOOST",
    "HYBRID_FETCH_FACTOR",
    "MAX_LIMIT",
    "RESOURCE_RELATIONSHIP_BOOST_MAX",
    "RETRIEVAL_SCHEMA_VERSION",
    "RetrievalResponse",
    "RetrievalResult",
    "SAME_TOPIC_BOOST_MAX",
    "SHARED_CONCEPT_BOOST_MAX",
    "SOURCE_TYPE_BOOST_MAX",
    "apply_graph_lite_boost",
    "iter_retrieval_issues",
    "iter_retrieval_result_issues",
    "linear_fuse",
    "max_normalize",
    "retrieve_hybrid",
    "retrieve_hybrid_in_memory",
    "sort_keys_deterministically",
    "topk",
]
