"""Deterministic resource-to-resource relationship detection.

Prompt 24 introduces six new edge types that connect two resource
nodes. The detector here is a pure function: it takes a list of
``resource_view`` dicts (small, pre-computed views of each resource
that the builder assembles from its existing caches) and returns
zero or more edge dicts in canonical (deterministic) order.

No I/O, no LLM calls, no embeddings, no BM25, no network. The
detector only reads already-derived graph state (canonical topic
slugs, concept slugs, source type, title, tags) and emits edges.

The signal model:

- shared topic intersection
- shared concept intersection
- shared title keywords (``TECH_KEYWORDS`` substring matches)
- same source type
- title depth hint (beginner / deep terms)

Each signal is independent and deterministic. The detector combines
them per-pair to decide which of the six edge types to emit, then
adds metadata (score, reasons, shared lists, source/target titles)
that downstream code (graph visualization, graph search) can read
without re-running the detection.
"""

from __future__ import annotations

import itertools
from typing import Any

from wiki.graph.schema import (
    EDGE_TYPE_RESOURCE_MAY_BE_PREREQUISITE_FOR_RESOURCE,
    EDGE_TYPE_RESOURCE_MAY_EXPAND_ON_RESOURCE,
    EDGE_TYPE_RESOURCE_SAME_SOURCE_TYPE_AS_RESOURCE,
    EDGE_TYPE_RESOURCE_SHARES_CONCEPT_WITH_RESOURCE,
    EDGE_TYPE_RESOURCE_SHARES_TOPIC_WITH_RESOURCE,
    EDGE_TYPE_RESOURCE_SIMILAR_TO_RESOURCE,
    make_edge_id,
    make_node_id,
    NODE_TYPE_RESOURCE,
    RESOURCE_RELATIONSHIP_EDGE_TYPES,
)

# -----------------------------------------------------------------------------
# Public configuration constants
# -----------------------------------------------------------------------------

# Technical keyword list used by ``_shared_keyword_signal``.
#
# This is a small, deterministic set of phrases that are likely to
# identify resources on similar technical subjects. Multi-word phrases
# are matched as substrings of the resource title (label); single
# tokens are matched case-insensitively. The list lives here rather
# than in ``wiki.resource_utils.TOPIC_DEFINITIONS`` to keep the change
# local to Prompt 24. A future prompt can refactor it into a shared
# module if other code paths want the same set.
#
# The list should be reviewed when new topics are added to the wiki.
TECH_KEYWORDS: tuple[str, ...] = (
    "vllm",
    "rag",
    "ollama",
    "faiss",
    "attention",
    "embeddings",
    "transformer",
    "fine-tuning",
    "finetuning",
    "rag-retrieval",
    "pagedattention",
    "quantization",
    "reinforcement learning",
    "rlhf",
    "dpo",
    "agent",
    "retrieval-augmented",
    "vector search",
    "bm25",
    "hybrid search",
    "asr",
    "whisper",
    "prompt injection",
)

# Phrases that mark a resource as covering beginner/intro material.
_BEGINNER_PHRASES: tuple[str, ...] = (
    "intro",
    "introduction",
    "beginner",
    "101",
    "basics",
    "primer",
    "overview",
    "what is",
    "getting started",
)

# Phrases that mark a resource as covering deeper/advanced material.
_DEEP_PHRASES: tuple[str, ...] = (
    "deep dive",
    "advanced",
    "in depth",
    "from scratch",
    "internals",
    "expert",
)

# Weights for each signal in the combined similarity score.
_WEIGHT_TOPIC = 2.0
_WEIGHT_CONCEPT = 3.0
_WEIGHT_KEYWORD = 1.0
_WEIGHT_SOURCE_TYPE = 0.5

# Threshold for the catch-all ``resource_similar_to_resource`` edge.
# The combined score (sum of triggered signal weights) must meet or
# exceed this. Set to 1.0 so that a single shared topic (weight 2.0)
# or two shared keywords (weight 1.0 each) is enough. Single-keyword
# matches (weight 1.0) are deliberately included to keep the
# catch-all cheap, but additional signals make it more confident.
_SIMILAR_THRESHOLD = 1.0

# Number of decimal places for score rounding (keeps JSON stable
# across runs when scores are derived from the same inputs).
_SCORE_DECIMALS = 4


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def detect_resource_relationships(
    resource_views: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a list of relationship edge dicts in canonical order.

    The input ``resource_views`` is a list of dicts. Each view has the
    following keys (see ``build_resource_views``):

    - ``id`` (str) – stable resource id, e.g. ``"webpage:test-c0001"``
    - ``slug`` (str) – resource slug (id with ``:`` replaced by ``_``)
    - ``label`` (str) – human-readable title used for substring matching
    - ``source_type`` (str) – resource source type, e.g. ``"webpage"``
    - ``topics`` (set[str]) – canonical topic slugs already on the
      resource (from the builder's ``_resource_topics`` cache)
    - ``concepts`` (set[str]) – concept slugs already on the resource
      (from the builder's ``_resource_concepts`` cache)
    - ``tags`` (set[str]) – normalized user tags

    The output is a list of edge dicts. Each edge has the standard
    shape ``{id, type, source, target, metadata}`` produced by
    :func:`wiki.graph.schema.edge_payload`. The metadata includes:

    - ``score`` (float) – combined similarity score, rounded to 4 dp
    - ``reasons`` (list[str]) – sorted list of signal names that fired
    - ``shared_topics`` (list[str]) – sorted list of shared topic slugs
    - ``shared_concepts`` (list[str]) – sorted list of shared concept slugs
    - ``shared_keywords`` (list[str]) – sorted list of matched keywords
    - ``source_resource_title`` (str) – source resource title
    - ``target_resource_title`` (str) – target resource title

    The output is sorted by edge id (``<type>:<source>:<target>``) so
    the result is byte-stable across runs.
    """
    if not resource_views:
        return []

    # Sort resources by stable id before pair enumeration.
    views = sorted(resource_views, key=lambda v: v["id"])

    edges: list[dict[str, Any]] = []
    for view_a, view_b in itertools.combinations(views, 2):
        edges.extend(_evaluate_pair(view_a, view_b))

    # Deterministic order: by edge id, which is
    # ``<type>:<source_node_id>:<target_node_id>``.
    edges.sort(key=lambda e: e["id"])
    return edges


def build_resource_views(
    *,
    resources: list[dict[str, Any]],
    resource_topics: dict[str, set[str]],
    resource_concepts: dict[str, set[str]],
) -> list[dict[str, Any]]:
    """Build ``resource_view`` dicts from raw resource nodes and caches.

    The builder calls this once at the top of
    ``_build_resource_relationship_edges`` and passes the result to
    :func:`detect_resource_relationships`.

    - ``resources`` – list of resource node dicts from
      ``self._nodes``. Each must have at least ``id``, ``slug``,
      ``label``, and ``metadata``. The metadata should include
      ``source_type``.
    - ``resource_topics`` – mapping of resource_id (the original id
      string, e.g. ``"webpage:test"``) to a set of canonical topic
      slugs. The builder already maintains this as
      ``self._resource_topics``.
    - ``resource_concepts`` – mapping of resource_id to a set of
      concept slugs, from ``self._resource_concepts``.

    The returned list is a list of view dicts in a stable order (by
    resource id), with empty sets filled in for resources that have
    no topics or concepts (this keeps the detector branch-free).
    """
    views: list[dict[str, Any]] = []
    for node in sorted(resources, key=lambda n: n["id"]):
        # The graph node id is ``resource:<slug>``; we want the
        # original resource id (``webpage:test``) to look up
        # topic/concept caches. The slug is the original id with
        # ``:`` replaced by ``_`` (see GraphBuilder._build_resource_nodes).
        resource_id = _original_resource_id_from_node(node)
        topics = set(resource_topics.get(resource_id, set()) or set())
        concepts = set(resource_concepts.get(resource_id, set()) or set())
        label = str(node.get("label", "") or "")
        metadata = node.get("metadata") or {}
        source_type = str(metadata.get("source_type", "") or "")
        tags = set(metadata.get("tags", set()) or set())
        views.append(
            {
                "id": resource_id,
                "slug": str(node.get("slug", "") or ""),
                "label": label,
                "source_type": source_type,
                "topics": topics,
                "concepts": concepts,
                "tags": tags,
            }
        )
    return views


# -----------------------------------------------------------------------------
# Per-pair evaluation
# -----------------------------------------------------------------------------


def _evaluate_pair(
    a: dict[str, Any], b: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return zero or more edges for a single unordered resource pair."""
    # Canonical id sort: id_a < id_b. The ``resource_similar_to_resource``
    # and other symmetric edges always have source < target in id order.
    if a["id"] <= b["id"]:
        view_a, view_b = a, b
    else:
        view_a, view_b = b, a

    source_id = make_node_id(NODE_TYPE_RESOURCE, view_a["slug"])
    target_id = make_node_id(NODE_TYPE_RESOURCE, view_b["slug"])

    # Per-signal evaluation. Each returns (score, shared_items, reason).
    topic_score, shared_topics = _shared_topic_signal(view_a, view_b)
    concept_score, shared_concepts = _shared_concept_signal(view_a, view_b)
    keyword_score, shared_keywords = _shared_keyword_signal(view_a, view_b)
    same_source = _same_source_type_signal(view_a, view_b)
    depth_a, depth_b, shared_depth_signal = _depth_signal(view_a, view_b)

    combined_score = round(
        topic_score + concept_score + keyword_score + same_source,
        _SCORE_DECIMALS,
    )

    reasons: list[str] = []
    if shared_topics:
        reasons.append("shared_topics")
    if shared_concepts:
        reasons.append("shared_concepts")
    if shared_keywords:
        reasons.append("shared_keywords")
    if same_source and (shared_topics or shared_concepts or shared_keywords):
        reasons.append("same_source_type")
    if shared_depth_signal:
        reasons.append("depth_difference")
    reasons.sort()

    metadata_base = {
        "score": combined_score,
        "reasons": reasons,
        "shared_topics": shared_topics,
        "shared_concepts": shared_concepts,
        "shared_keywords": shared_keywords,
        "source_resource_title": view_a.get("label", ""),
        "target_resource_title": view_b.get("label", ""),
    }

    edges: list[dict[str, Any]] = []

    # Symmetric edges: each gets its own metadata, with the relevant
    # ``shared_*`` list populated and other lists empty.
    if shared_topics:
        meta = dict(metadata_base)
        meta["shared_topics"] = shared_topics
        meta["shared_concepts"] = []
        meta["shared_keywords"] = []
        meta["reasons"] = ["shared_topics"]
        meta["score"] = round(topic_score, _SCORE_DECIMALS)
        edges.append(
            _make_relationship_edge(
                EDGE_TYPE_RESOURCE_SHARES_TOPIC_WITH_RESOURCE,
                source_id,
                target_id,
                meta,
            )
        )

    if shared_concepts:
        meta = dict(metadata_base)
        meta["shared_topics"] = []
        meta["shared_concepts"] = shared_concepts
        meta["shared_keywords"] = []
        meta["reasons"] = ["shared_concepts"]
        meta["score"] = round(concept_score, _SCORE_DECIMALS)
        edges.append(
            _make_relationship_edge(
                EDGE_TYPE_RESOURCE_SHARES_CONCEPT_WITH_RESOURCE,
                source_id,
                target_id,
                meta,
            )
        )

    if same_source and (shared_topics or shared_concepts or shared_keywords):
        meta = dict(metadata_base)
        meta["shared_topics"] = list(shared_topics)
        meta["shared_concepts"] = list(shared_concepts)
        meta["shared_keywords"] = list(shared_keywords)
        meta["reasons"] = sorted(
            [r for r in reasons if r != "depth_difference"]
        )
        meta["score"] = round(same_source, _SCORE_DECIMALS)
        edges.append(
            _make_relationship_edge(
                EDGE_TYPE_RESOURCE_SAME_SOURCE_TYPE_AS_RESOURCE,
                source_id,
                target_id,
                meta,
            )
        )

    if combined_score >= _SIMILAR_THRESHOLD:
        # The catch-all: include all shared lists and the full reasons
        # list. The depth_difference reason only appears here if it
        # would also be present in the metadata, which it would not
        # be in the depth case (see below).
        meta = dict(metadata_base)
        meta["reasons"] = [r for r in reasons if r != "depth_difference"]
        meta["score"] = combined_score
        edges.append(
            _make_relationship_edge(
                EDGE_TYPE_RESOURCE_SIMILAR_TO_RESOURCE,
                source_id,
                target_id,
                meta,
            )
        )

    # Asymmetric depth edges. These are only emitted when both:
    # - the resources share at least one topic, and
    # - the depth signal differs between the two.
    # The direction is shallower -> deeper (the deeper resource
    # is presumably an expansion of the shallower one).
    if shared_topics and shared_depth_signal:
        if depth_a < depth_b:
            # view_a is shallower, view_b is deeper
            depth_meta = dict(metadata_base)
            depth_meta["reasons"] = ["depth_difference", "shared_topics"]
            depth_meta["score"] = combined_score
            edges.append(
                _make_relationship_edge(
                    EDGE_TYPE_RESOURCE_MAY_BE_PREREQUISITE_FOR_RESOURCE,
                    source_id,
                    target_id,
                    depth_meta,
                )
            )
        elif depth_b < depth_a:
            # view_b is shallower, view_a is deeper
            depth_meta = dict(metadata_base)
            depth_meta["reasons"] = ["depth_difference", "shared_topics"]
            depth_meta["score"] = combined_score
            edges.append(
                _make_relationship_edge(
                    EDGE_TYPE_RESOURCE_MAY_BE_PREREQUISITE_FOR_RESOURCE,
                    target_id,
                    source_id,
                    depth_meta,
                )
            )
        if depth_a > depth_b:
            edges.append(
                _make_relationship_edge(
                    EDGE_TYPE_RESOURCE_MAY_EXPAND_ON_RESOURCE,
                    source_id,
                    target_id,
                    dict(metadata_base),
                )
            )
        elif depth_b > depth_a:
            edges.append(
                _make_relationship_edge(
                    EDGE_TYPE_RESOURCE_MAY_EXPAND_ON_RESOURCE,
                    target_id,
                    source_id,
                    dict(metadata_base),
                )
            )

    return edges


# -----------------------------------------------------------------------------
# Signal functions
# -----------------------------------------------------------------------------


def _shared_topic_signal(
    a: dict[str, Any], b: dict[str, Any]
) -> tuple[float, list[str]]:
    """Return (score, sorted_intersection) of shared canonical topics."""
    intersection = sorted(a["topics"] & b["topics"])
    return _WEIGHT_TOPIC * len(intersection), intersection


def _shared_concept_signal(
    a: dict[str, Any], b: dict[str, Any]
) -> tuple[float, list[str]]:
    """Return (score, sorted_intersection) of shared concept slugs."""
    intersection = sorted(a["concepts"] & b["concepts"])
    return _WEIGHT_CONCEPT * len(intersection), intersection


def _shared_keyword_signal(
    a: dict[str, Any], b: dict[str, Any]
) -> tuple[float, list[str]]:
    """Return (score, sorted_intersection) of shared technical keywords.

    Matches are case-insensitive substring matches on the resource
    ``label`` (title). Multi-word keywords use substring matching
    rather than tokenization to keep things deterministic and
    free of tokenization surprises.
    """
    a_label = a.get("label", "").lower()
    b_label = b.get("label", "").lower()
    if not a_label or not b_label:
        return 0.0, []
    matched: list[str] = []
    for keyword in TECH_KEYWORDS:
        kw = keyword.lower()
        if kw in a_label and kw in b_label:
            matched.append(keyword)
    matched.sort()
    return _WEIGHT_KEYWORD * len(matched), matched


def _same_source_type_signal(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Return 0.5 if both resources share a source type, else 0.0."""
    if a["source_type"] and a["source_type"] == b["source_type"]:
        return _WEIGHT_SOURCE_TYPE
    return 0.0


def _depth_signal(
    a: dict[str, Any], b: dict[str, Any]
) -> tuple[int, int, bool]:
    """Return (depth_a, depth_b, shared_signal).

    ``depth_a`` and ``depth_b`` are in ``{-1, 0, +1}``: -1 for
    beginner/intro, 0 for neutral, +1 for deep/advanced. The
    third element is ``True`` when the two depths differ and both
    are non-zero, which is the condition for emitting the
    prerequisite/expansion edges.

    Conflicting beginner and deep phrases in the same title are
    resolved by taking the net score: each beginner phrase gives
    -1, each deep phrase gives +1, the total is the final value.
    """
    da = _depth_score_for_label(a.get("label", ""))
    db = _depth_score_for_label(b.get("label", ""))
    shared = da != db and da != 0 and db != 0
    return da, db, shared


def _depth_score_for_label(label: str) -> int:
    """Return the net depth score for a single resource label."""
    if not label:
        return 0
    text = label.lower()
    score = 0
    for phrase in _BEGINNER_PHRASES:
        if phrase in text:
            score -= 1
    for phrase in _DEEP_PHRASES:
        if phrase in text:
            score += 1
    # Clamp to {-1, 0, +1}.
    if score > 0:
        return 1
    if score < 0:
        return -1
    return 0


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _make_relationship_edge(
    edge_type: str,
    source_id: str,
    target_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Build a relationship edge dict in the standard shape."""
    return {
        "id": make_edge_id(edge_type, source_id, target_id),
        "type": edge_type,
        "source": source_id,
        "target": target_id,
        "metadata": dict(metadata),
    }


def _original_resource_id_from_node(node: dict[str, Any]) -> str:
    """Extract the original resource id (``webpage:test``) from a graph node.

    The graph node id is ``resource:<slug>``. The slug is the
    original id with ``:`` replaced by ``_`` (see
    :meth:`GraphBuilder._build_resource_nodes`). We reverse that
    transformation using the first ``:`` in the slug as a hint.

    We do not attempt to invert ``_`` -> ``:`` blindly (a resource
    whose id already contains ``_`` would round-trip incorrectly).
    Instead we read the slug and only substitute ``_`` back to
    ``:`` once, taking the ``source_type`` from the metadata
    (``<source_type>:<rest>``). If we cannot recover the original
    id safely, we fall back to the slug, which is good enough for
    the detector because the caches are keyed by the original id.
    """
    metadata = node.get("metadata") or {}
    source_type = str(metadata.get("source_type") or "")
    slug = str(node.get("slug") or "")
    if source_type and slug.startswith(f"{source_type}_"):
        return f"{source_type}:{slug[len(source_type) + 1 :]}"
    # Fall back: best effort. The detector only needs the value to
    # match ``_resource_topics``/``_resource_concepts`` keys, which
    # are the same dicts the builder populated from
    # ``record.id``. If the keys don't match, the detector simply
    # sees empty topic/concept sets for that resource.
    return slug


def relationship_edge_types() -> frozenset[str]:
    """Return the set of all resource-to-resource relationship edge types.

    Convenience accessor for tests and the validator. Re-exports
    :data:`wiki.graph.schema.RESOURCE_RELATIONSHIP_EDGE_TYPES`.
    """
    return RESOURCE_RELATIONSHIP_EDGE_TYPES


__all__ = [
    "detect_resource_relationships",
    "build_resource_views",
    "TECH_KEYWORDS",
    "relationship_edge_types",
]
