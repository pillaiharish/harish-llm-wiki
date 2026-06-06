"""Graph-lite metadata boost (Prompt 30).

The graph-lite boost is a small, bounded, per-chunk additive
signal that nudges the hybrid retrieval ranking in favor of
chunks whose resources share topics, concepts, source types, or
resource-relationship edges with other resources in the
candidate set.

The boost is intentionally **not** a graph traversal: there is
no recursive walk over the graph. The module reads the on-disk
knowledge graph JSON exactly once per retrieval call (see the
"no unbounded traversal" requirement in ``prompt30.md``) and
builds three small ``resource_id -> set`` maps by a single linear
pass over the edges list. The boost per chunk is then a
function of the chunk's resource id, the candidate set's
resource ids, and the three maps.

The total boost per chunk is bounded by
:data:`wiki.retrieval.schema.GRAPH_LITE_MAX_BOOST` (0.10). The
boost is the sum of four sub-boosts, each capped at a fixed
sub-maximum:

- ``same_topic_boost`` (max 0.04)
- ``shared_concept_boost`` (max 0.03)
- ``source_type_boost`` (max 0.02)
- ``resource_relationship_boost`` (max 0.01)

The module is a read-only consumer of the on-disk knowledge
graph JSON. It does not import the graph builder, the
relationships detector, or the graph validator.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Optional

from wiki.config import config
from wiki.graph.schema import (
    EDGE_TYPE_RESOURCE_HAS_TOPIC,
    EDGE_TYPE_RESOURCE_MENTIONS_CONCEPT,
    RESOURCE_RELATIONSHIP_EDGE_TYPES,
)
from wiki.storage import Storage


# =============================================================================
# Public API
# =============================================================================


def build_boost_map(
    *,
    graph_path: Path | None = None,
    candidate_resource_ids: set[str] | None = None,
    candidate_source_types: set[str] | None = None,
    dominant_source_type: str | None = None,
    chunk_resource_id_to_chunk_ids: Mapping[str, set[str]] | None = None,
) -> dict[str, float]:
    """Build a per-chunk graph-lite boost map for the candidate set.

    The function is the public entry point for the router. It
    reads the on-disk knowledge graph JSON once and returns a
    ``{chunk_id: boost_value}`` map (one entry per chunk in the
    candidate set).

    Parameters
    ----------
    graph_path:
        Optional override for the on-disk knowledge graph
        bundle. Defaults to
        ``data_dir / site_generated / docs / public / graph / knowledge_graph.json``.
    candidate_resource_ids:
        The set of resource ids in the candidate set. Used to
        determine which resources "participate" in the boost
        computation. If ``None`` (or empty), the function
        returns an empty boost map.
    candidate_source_types:
        The set of source types in the candidate set. Used for
        the source-type preference sub-boost. If ``None``, the
        function computes the set from the graph nodes
        referenced by the candidate resource ids.
    dominant_source_type:
        Optional explicit dominant source type. If ``None``,
        the function computes the dominant source type from the
        candidate set (most common source type). If there is no
        clear dominant source type, the source-type sub-boost
        is zero for every chunk.
    chunk_resource_id_to_chunk_ids:
        ``{resource_id: set(chunk_id)}`` mapping. The function
        emits one boost value per chunk id in this map. If
        ``None``, the function returns an empty map (the caller
        is expected to build this map from the BM25/vector
        candidate set).

    Returns
    -------
    dict[str, float]
        ``{chunk_id: boost_value}`` with ``boost_value`` in
        ``[0.0, GRAPH_LITE_MAX_BOOST]``. The map is empty if
        the candidate set is empty, the graph file is missing,
        or the graph file has no nodes or edges.
    """
    if not candidate_resource_ids or not chunk_resource_id_to_chunk_ids:
        return {}

    payload = _read_graph_payload(graph_path)
    if not payload:
        return {}

    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return {}
    if not nodes or not edges:
        return {}

    # Build the three resource -> set maps by a single linear pass
    # over the edges. Resource ids in the graph are formatted
    # ``resource:<record_id_with_colons_replaced>``; we recover
    # the canonical record_id by stripping the ``resource:``
    # prefix and re-inserting the first colon (the resource id
    # namespace). This matches what the BM25/vector backends
    # surface as ``resource_id``.
    resource_to_topics: dict[str, set[str]] = {}
    resource_to_concepts: dict[str, set[str]] = {}
    resource_to_relationship_targets: dict[str, set[str]] = {}
    topic_to_resources: dict[str, set[str]] = {}
    concept_to_resources: dict[str, set[str]] = {}

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        edge_type = str(edge.get("type", ""))
        source_id = str(edge.get("source", ""))
        target_id = str(edge.get("target", ""))
        if not source_id or not target_id:
            continue
        if edge_type == EDGE_TYPE_RESOURCE_HAS_TOPIC:
            rid = _strip_resource_prefix(source_id)
            topic_slug = _strip_topic_prefix(target_id)
            if not rid or not topic_slug:
                continue
            resource_to_topics.setdefault(rid, set()).add(topic_slug)
            topic_to_resources.setdefault(topic_slug, set()).add(rid)
        elif edge_type == EDGE_TYPE_RESOURCE_MENTIONS_CONCEPT:
            rid = _strip_resource_prefix(source_id)
            concept_slug = _strip_concept_prefix(target_id)
            if not rid or not concept_slug:
                continue
            resource_to_concepts.setdefault(rid, set()).add(concept_slug)
            concept_to_resources.setdefault(concept_slug, set()).add(rid)
        elif edge_type in RESOURCE_RELATIONSHIP_EDGE_TYPES:
            source_rid = _strip_resource_prefix(source_id)
            target_rid = _strip_resource_prefix(target_id)
            if not source_rid or not target_rid:
                continue
            resource_to_relationship_targets.setdefault(
                source_rid, set()
            ).add(target_rid)
            # Also index the reverse direction so the boost is
            # symmetric regardless of edge direction.
            resource_to_relationship_targets.setdefault(
                target_rid, set()
            ).add(source_rid)

    # Compute the per-chunk boost.
    from wiki.retrieval.schema import (
        GRAPH_LITE_MAX_BOOST,
        RESOURCE_RELATIONSHIP_BOOST_MAX,
        SAME_TOPIC_BOOST_MAX,
        SHARED_CONCEPT_BOOST_MAX,
        SOURCE_TYPE_BOOST_MAX,
    )

    # Map source_type per resource from the graph nodes.
    resource_to_source_type: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if str(node.get("type", "")) != "resource":
            continue
        node_id = str(node.get("id", ""))
        rid = _strip_resource_prefix(node_id)
        if not rid:
            continue
        source_type = str((node.get("metadata") or {}).get("source_type", ""))
        if source_type:
            resource_to_source_type[rid] = source_type

    # Determine the dominant source type (most common in the
    # candidate set) if not provided.
    if dominant_source_type is None:
        if candidate_source_types is not None and len(candidate_source_types) == 1:
            dominant_source_type = next(iter(candidate_source_types))
        else:
            counts: Counter[str] = Counter()
            for rid in candidate_resource_ids:
                st = resource_to_source_type.get(rid)
                if st:
                    counts[st] += 1
            if counts:
                dominant_source_type = counts.most_common(1)[0][0]

    boost_map: dict[str, float] = {}
    candidate_set = set(candidate_resource_ids)

    for rid, chunk_ids in chunk_resource_id_to_chunk_ids.items():
        if not chunk_ids:
            continue
        # Skip resource ids that are not in the candidate set
        # (defensive: the caller is expected to filter, but
        # extra safety is cheap).
        if rid not in candidate_set:
            continue

        # 1. Same-topic boost: the chunk's resource shares at
        # least one canonical topic with another resource in
        # the candidate set. The boost is the full sub-max (it
        # is a yes/no signal at the chunk level, not a
        # proportional one).
        topics = resource_to_topics.get(rid, set())
        shared_topics: set[str] = set()
        if topics:
            for topic_slug in topics:
                other_resources = topic_to_resources.get(topic_slug, set())
                # Exclude self.
                other_resources = other_resources - {rid}
                if other_resources & candidate_set:
                    shared_topics.add(topic_slug)
        same_topic_boost = SAME_TOPIC_BOOST_MAX if shared_topics else 0.0

        # 2. Shared-concept boost: the chunk's resource mentions
        # at least one concept that another resource in the
        # candidate set also mentions.
        concepts = resource_to_concepts.get(rid, set())
        shared_concepts: set[str] = set()
        if concepts:
            for concept_slug in concepts:
                other_resources = concept_to_resources.get(concept_slug, set())
                other_resources = other_resources - {rid}
                if other_resources & candidate_set:
                    shared_concepts.add(concept_slug)
        shared_concept_boost = SHARED_CONCEPT_BOOST_MAX if shared_concepts else 0.0

        # 3. Source-type preference boost: the chunk's source
        # type is the most common source type in the candidate
        # set. The boost is small (0.02) and only applies when
        # the dominant source type is unambiguous.
        source_type_boost = 0.0
        if dominant_source_type:
            resource_source_type = resource_to_source_type.get(rid, "")
            if (
                resource_source_type
                and resource_source_type == dominant_source_type
            ):
                # Only apply when there is more than one
                # resource with this source type in the
                # candidate set; otherwise the "preference" is
                # trivial (the entire candidate set has the
                # same source type).
                if len(candidate_set) > 1:
                    same_type_count = sum(
                        1
                        for other_rid in candidate_set
                        if resource_to_source_type.get(other_rid)
                        == dominant_source_type
                    )
                    if same_type_count > 1:
                        source_type_boost = SOURCE_TYPE_BOOST_MAX

        # 4. Resource-relationship boost: the chunk's resource
        # has at least one RESOURCE_RELATIONSHIP_EDGE_TYPES
        # edge to another resource in the candidate set.
        rel_targets = resource_to_relationship_targets.get(rid, set())
        in_candidate = rel_targets & candidate_set
        rel_boost = (
            RESOURCE_RELATIONSHIP_BOOST_MAX if in_candidate else 0.0
        )

        # Sum and clamp to GRAPH_LITE_MAX_BOOST.
        total = (
            same_topic_boost
            + shared_concept_boost
            + source_type_boost
            + rel_boost
        )
        if total > GRAPH_LITE_MAX_BOOST:
            total = GRAPH_LITE_MAX_BOOST
        if total < 0.0:
            total = 0.0

        for chunk_id in chunk_ids:
            boost_map[str(chunk_id)] = float(total)

    return boost_map


def graph_path_for(*, data_dir: Path | None = None) -> Path:
    """Return the canonical path to the on-disk knowledge graph bundle.

    Mirrors the public path used by the VitePress site so the
    router and the static site agree on the bundle location.
    """
    base = (data_dir or config.LLM_WIKI_DATA_DIR) / "site_generated" / "docs" / "public" / "graph"
    return base / "knowledge_graph.json"


# =============================================================================
# Local helpers
# =============================================================================


def _read_graph_payload(graph_path: Path | None) -> dict | None:
    """Read the on-disk knowledge graph bundle.

    Returns ``None`` if the file is missing or malformed. The
    function is defensive: graph-lite mode is a re-ranking
    signal over an already-ranked candidate set, so a missing
    or malformed graph must not crash the retrieval call.
    """
    path = graph_path or graph_path_for()
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _strip_resource_prefix(node_id: str) -> str:
    """Strip the ``resource:`` prefix from a graph node id.

    The graph builder stores resource node ids as
    ``resource:<record_id_with_colons_replaced>`` (e.g.
    ``resource:pdf_0123...``). The retrieval layer uses the
    canonical record id (``pdf:0123...``) from the BM25/vector
    metadata. This helper converts the graph node id back to
    the canonical record id by re-inserting the first ``:``
    that was replaced with ``_``.

    For the canonical wiki record ids (``pdf:``, ``youtube:``,
    ``webpage:``, ``markdown:``, etc.) the conversion is
    reversible. For other namespaces the helper is defensive
    and falls back to the raw suffix.
    """
    if not node_id:
        return ""
    prefix = "resource:"
    if not node_id.startswith(prefix):
        return ""
    suffix = node_id[len(prefix):]
    # Re-introduce the first colon. The graph builder replaces
    # ``:`` with ``_`` in the resource id slug; the canonical
    # wiki namespaces always use a single ``:`` separator.
    known_namespaces = (
        "pdf",
        "youtube",
        "webpage",
        "markdown",
        "medium_markdown",
        "local_video",
        "local_audio",
        "local_transcript",
    )
    for ns in known_namespaces:
        if suffix.startswith(f"{ns}_"):
            return f"{ns}:" + suffix[len(ns) + 1:]
    # Fallback: insert a single colon after the first segment.
    if "_" in suffix:
        head, tail = suffix.split("_", 1)
        return f"{head}:{tail}"
    return suffix


def _strip_topic_prefix(node_id: str) -> str:
    """Strip the ``topic:`` prefix and return the slug."""
    prefix = "topic:"
    if node_id.startswith(prefix):
        return node_id[len(prefix):]
    return ""


def _strip_concept_prefix(node_id: str) -> str:
    """Strip the ``concept:`` prefix and return the slug."""
    prefix = "concept:"
    if node_id.startswith(prefix):
        return node_id[len(prefix):]
    return ""


__all__ = [
    "build_boost_map",
    "graph_path_for",
]
