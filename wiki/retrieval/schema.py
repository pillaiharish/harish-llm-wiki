"""Public schema for the hybrid retrieval router (Prompt 30).

This module defines the on-the-wire shape of a hybrid retrieval
result. The dataclasses are frozen so the result list is immutable
and the deterministic ``to_dict()`` projection is the contract for
the JSON CLI output and the static report page.

The schema is intentionally aligned with the BM25 and vector
backend search results (see :mod:`wiki.search.bm25` and
:mod:`wiki.vector.search`) so the router can be used as a drop-in
unified retrieval surface.

Required result schema (per ``prompt30.md`` §"Required result
schema"):

- ``rank`` (int)
- ``score`` (float)
- ``chunk_id`` (str)
- ``resource_id`` (str)
- ``title`` (str)
- ``source_type`` (str)
- ``text_preview`` (str)
- ``citation_label`` (str)
- ``resource_route`` (str)
- ``source_ref`` (dict)
- ``mode`` (str) — one of ``bm25``, ``vector``, ``hybrid``,
  ``graph-lite``.
- ``component_scores`` — :class:`ComponentScores` (always present,
  even when empty for non-graph-lite modes).
- ``matched_terms`` (list[str])
- ``explanation`` — :class:`Explanation` (always present; the
  ``verbose`` flag controls whether the per-factor details are
  included in the JSON output).
- ``metadata`` (dict) — small bag of source URL, tags, topics.

The module has no project imports. The dataclasses are plain
frozen Python types that can be unit-tested without any of the
BM25, vector, or graph modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# =============================================================================
# Constants
# =============================================================================


#: Allowed retrieval modes. The set is frozen and used by the CLI
#: to validate ``--mode`` arguments.
ALLOWED_MODES: frozenset[str] = frozenset(
    {"bm25", "vector", "hybrid", "graph-lite"}
)

#: Default mode used when the caller does not specify one.
DEFAULT_MODE: str = "hybrid"

#: Default number of results returned by :func:`retrieve_hybrid`.
DEFAULT_LIMIT: int = 10

#: Hard cap on the number of results. The CLI rejects
#: ``--limit`` values greater than this.
MAX_LIMIT: int = 100

#: Default ``bm25_weight`` for hybrid fusion. Used by the CLI and
#: the public router API.
DEFAULT_BM25_WEIGHT: float = 0.55

#: Default ``vector_weight`` for hybrid fusion. Used by the CLI
#: and the public router API.
DEFAULT_VECTOR_WEIGHT: float = 0.45

#: Maximum total graph-lite boost (per chunk, additive). The boost
#: is the sum of four sub-boosts, each capped at a fixed sub-max
#: (see :mod:`wiki.retrieval.graph_lite`).
GRAPH_LITE_MAX_BOOST: float = 0.10

#: Sub-maximum for the same-topic contribution to the graph-lite
#: boost.
SAME_TOPIC_BOOST_MAX: float = 0.04

#: Sub-maximum for the shared-concept contribution to the
#: graph-lite boost.
SHARED_CONCEPT_BOOST_MAX: float = 0.03

#: Sub-maximum for the source-type preference contribution to the
#: graph-lite boost.
SOURCE_TYPE_BOOST_MAX: float = 0.02

#: Sub-maximum for the resource-relationship edge contribution to
#: the graph-lite boost.
RESOURCE_RELATIONSHIP_BOOST_MAX: float = 0.01

#: Schema version string for the retrieval result. Bumped only
#: when the public JSON shape changes in a breaking way.
RETRIEVAL_SCHEMA_VERSION: str = "retrieval_v1"

#: Multiplier on ``limit`` to fetch a wider candidate set when
#: fusing BM25 and vector scores. Fixed by the plan for
#: determinism; see :mod:`wiki.retrieval.router`.
HYBRID_FETCH_FACTOR: int = 3


# =============================================================================
# Component scores
# =============================================================================


@dataclass(frozen=True)
class ComponentScores:
    """Per-component score breakdown for a single result.

    All six fields are always present so the schema is stable
    across all four modes (``bm25``, ``vector``, ``hybrid``,
    ``graph-lite``). For modes that do not exercise a given
    backend the field is zero.

    Fields
    ------
    bm25:
        Raw BM25 score. Zero for ``vector`` and ``graph-lite`` if
        the chunk was not in the BM25 top-K (it is still
        meaningful in ``graph-lite`` if the chunk was in both
        backends' top-K).
    vector:
        Raw vector cosine score. Zero for ``bm25`` mode.
    graph_boost:
        Additive graph-lite boost value (always in
        ``[0.0, GRAPH_LITE_MAX_BOOST]``). Zero for non-graph-lite
        modes.
    normalized_bm25:
        Max-normalized BM25 score in ``[0.0, 1.0]``. Zero when
        the candidate set has no BM25 contribution or the max is
        zero.
    normalized_vector:
        Max-normalized vector score in ``[0.0, 1.0]``. Zero when
        the candidate set has no vector contribution or the max is
        zero.
    final:
        Final fused score (BM25/vector linear combination plus the
        graph-lite boost, if any). Used for ranking.
    """

    bm25: float
    vector: float
    graph_boost: float
    normalized_bm25: float
    normalized_vector: float
    final: float

    def to_dict(self) -> dict[str, Any]:
        """Project to a dict in stable field order."""
        return {
            "bm25": self.bm25,
            "vector": self.vector,
            "graph_boost": self.graph_boost,
            "normalized_bm25": self.normalized_bm25,
            "normalized_vector": self.normalized_vector,
            "final": self.final,
        }


# =============================================================================
# Explanation block
# =============================================================================


@dataclass(frozen=True)
class Explanation:
    """Verbose explanation block for a single result.

    The block carries the per-factor graph-lite details
    (``shared_topics``, ``shared_concepts``,
    ``resource_relationship_targets``, and the
    ``source_type_preference`` boolean) and the small summary
    blocks (``weights`` and ``normalization``) that describe the
    scoring formula and the normalization maxes.

    The ``weights`` and ``normalization`` sub-blocks are always
    present in ``to_dict()``. The per-factor details are emitted
    only when ``verbose=True`` (the ``--explain`` CLI flag), so
    the default JSON output is small and stable.
    """

    shared_topics: list = field(default_factory=list)
    shared_concepts: list = field(default_factory=list)
    source_type_preference: bool = False
    resource_relationship_targets: list = field(default_factory=list)
    weights: dict = field(default_factory=dict)
    normalization: dict = field(default_factory=dict)

    def to_dict(self, *, verbose: bool = False) -> dict[str, Any]:
        """Project to a dict in stable field order.

        When ``verbose`` is ``True``, the per-factor details
        (``shared_topics``, ``shared_concepts``,
        ``source_type_preference``, and
        ``resource_relationship_targets``) are included in the
        output. When ``verbose`` is ``False``, only the
        ``weights`` and ``normalization`` sub-blocks are
        included, which keeps the default JSON output small.
        """
        out: dict[str, Any] = {
            "weights": dict(self.weights),
            "normalization": dict(self.normalization),
        }
        if verbose:
            out.update(
                {
                    "shared_topics": list(self.shared_topics),
                    "shared_concepts": list(self.shared_concepts),
                    "source_type_preference": bool(self.source_type_preference),
                    "resource_relationship_targets": list(
                        self.resource_relationship_targets
                    ),
                }
            )
        return out


# =============================================================================
# Retrieval result
# =============================================================================


@dataclass(frozen=True)
class RetrievalResult:
    """The public hybrid-retrieval result schema.

    The dataclass is the unified retrieval surface for the wiki's
    hybrid router. Its field order is the canonical JSON
    serialization order, matching the schema required by
    ``prompt30.md`` §"Required result schema".

    The ``mode`` field is the mode the router was invoked with,
    not the underlying backend that contributed the chunk. The
    ``component_scores`` block exposes the per-component raw and
    normalized scores, and the ``explanation`` block carries the
    graph-lite details plus the summary scoring info.
    """

    rank: int
    score: float
    chunk_id: str
    resource_id: str
    title: str
    source_type: str
    text_preview: str
    citation_label: str
    resource_route: str
    source_ref: dict = field(default_factory=dict)
    mode: str = DEFAULT_MODE
    component_scores: ComponentScores = field(
        default_factory=lambda: ComponentScores(
            bm25=0.0,
            vector=0.0,
            graph_boost=0.0,
            normalized_bm25=0.0,
            normalized_vector=0.0,
            final=0.0,
        )
    )
    matched_terms: list = field(default_factory=list)
    explanation: Explanation = field(default_factory=Explanation)
    metadata: dict = field(default_factory=dict)

    def to_dict(self, *, verbose: bool = False) -> dict[str, Any]:
        """Project to a dict in stable field order.

        The ``verbose`` flag is forwarded to
        :meth:`Explanation.to_dict` to gate the per-factor
        details. The default output (``verbose=False``) is
        small and stable; ``verbose=True`` mirrors the
        ``--explain`` CLI output.
        """
        return {
            "rank": self.rank,
            "score": self.score,
            "chunk_id": self.chunk_id,
            "resource_id": self.resource_id,
            "title": self.title,
            "source_type": self.source_type,
            "text_preview": self.text_preview,
            "citation_label": self.citation_label,
            "resource_route": self.resource_route,
            "source_ref": dict(self.source_ref),
            "mode": self.mode,
            "component_scores": self.component_scores.to_dict(),
            "matched_terms": list(self.matched_terms),
            "explanation": self.explanation.to_dict(verbose=verbose),
            "metadata": dict(self.metadata),
        }


# =============================================================================
# Response envelope (optional convenience wrapper)
# =============================================================================


@dataclass(frozen=True)
class RetrievalResponse:
    """The full response envelope.

    The router can return a list of :class:`RetrievalResult`
    objects directly; this envelope is provided for callers that
    want a single object carrying the mode, weights, and the
    result list. It is not used by the CLI (which emits a JSON
    array of result dicts), but it is useful for tests and for
    future internal callers.
    """

    mode: str
    query: str
    weights: dict
    results: list = field(default_factory=list)

    def to_dict(self, *, verbose: bool = False) -> dict[str, Any]:
        """Project to a dict in stable field order."""
        return {
            "mode": self.mode,
            "query": self.query,
            "weights": dict(self.weights),
            "results": [r.to_dict(verbose=verbose) for r in self.results],
        }


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
]
