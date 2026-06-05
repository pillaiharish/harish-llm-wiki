"""Schema constants and ID helpers for the knowledge graph.

All node and edge IDs are deterministic strings formed from a
type prefix and a stable slug, so re-running the builder on the same
input always produces the same IDs.

Schema version history:

- 1.0.0 (Prompt 23) – initial schema
- 1.0.0 (Prompt 24) – additive: 6 resource-to-resource relationship
  edge types. Backward-compatible; the schema_version string is
  unchanged. See ``RESOURCE_RELATIONSHIP_EDGE_TYPES``.
"""

from __future__ import annotations

from typing import Any, Iterable

# -----------------------------------------------------------------------------
# Schema version
# -----------------------------------------------------------------------------

SCHEMA_VERSION = "1.0.0"


# -----------------------------------------------------------------------------
# Node type constants
# -----------------------------------------------------------------------------

NODE_TYPE_TOPIC = "topic"
NODE_TYPE_TAG = "tag"
NODE_TYPE_RESOURCE = "resource"
NODE_TYPE_CONCEPT = "concept"
NODE_TYPE_LEARN_CHAPTER = "learn_chapter"
NODE_TYPE_REVIEW_PAGE = "review_page"

ALLOWED_NODE_TYPES: frozenset[str] = frozenset(
    {
        NODE_TYPE_TOPIC,
        NODE_TYPE_TAG,
        NODE_TYPE_RESOURCE,
        NODE_TYPE_CONCEPT,
        NODE_TYPE_LEARN_CHAPTER,
        NODE_TYPE_REVIEW_PAGE,
    }
)


# -----------------------------------------------------------------------------
# Edge type constants
# -----------------------------------------------------------------------------

EDGE_TYPE_RESOURCE_HAS_TOPIC = "resource_has_topic"
EDGE_TYPE_RESOURCE_HAS_TAG = "resource_has_tag"
EDGE_TYPE_TOPIC_HAS_RESOURCE = "topic_has_resource"
EDGE_TYPE_TOPIC_RELATED_TO_TOPIC = "topic_related_to_topic"
EDGE_TYPE_RESOURCE_MENTIONS_CONCEPT = "resource_mentions_concept"
EDGE_TYPE_CONCEPT_IN_TOPIC = "concept_in_topic"
EDGE_TYPE_LEARN_CHAPTER_USES_RESOURCE = "learn_chapter_uses_resource"
EDGE_TYPE_REVIEW_PAGE_REVIEWS_RESOURCE = "review_page_reviews_resource"
# Resource-to-resource relationship edges (Prompt 24)
EDGE_TYPE_RESOURCE_SIMILAR_TO_RESOURCE = "resource_similar_to_resource"
EDGE_TYPE_RESOURCE_SHARES_TOPIC_WITH_RESOURCE = "resource_shares_topic_with_resource"
EDGE_TYPE_RESOURCE_SHARES_CONCEPT_WITH_RESOURCE = "resource_shares_concept_with_resource"
EDGE_TYPE_RESOURCE_SAME_SOURCE_TYPE_AS_RESOURCE = "resource_same_source_type_as_resource"
EDGE_TYPE_RESOURCE_MAY_BE_PREREQUISITE_FOR_RESOURCE = (
    "resource_may_be_prerequisite_for_resource"
)
EDGE_TYPE_RESOURCE_MAY_EXPAND_ON_RESOURCE = "resource_may_expand_on_resource"

ALLOWED_EDGE_TYPES: frozenset[str] = frozenset(
    {
        EDGE_TYPE_RESOURCE_HAS_TOPIC,
        EDGE_TYPE_RESOURCE_HAS_TAG,
        EDGE_TYPE_TOPIC_HAS_RESOURCE,
        EDGE_TYPE_TOPIC_RELATED_TO_TOPIC,
        EDGE_TYPE_RESOURCE_MENTIONS_CONCEPT,
        EDGE_TYPE_CONCEPT_IN_TOPIC,
        EDGE_TYPE_LEARN_CHAPTER_USES_RESOURCE,
        EDGE_TYPE_REVIEW_PAGE_REVIEWS_RESOURCE,
        EDGE_TYPE_RESOURCE_SIMILAR_TO_RESOURCE,
        EDGE_TYPE_RESOURCE_SHARES_TOPIC_WITH_RESOURCE,
        EDGE_TYPE_RESOURCE_SHARES_CONCEPT_WITH_RESOURCE,
        EDGE_TYPE_RESOURCE_SAME_SOURCE_TYPE_AS_RESOURCE,
        EDGE_TYPE_RESOURCE_MAY_BE_PREREQUISITE_FOR_RESOURCE,
        EDGE_TYPE_RESOURCE_MAY_EXPAND_ON_RESOURCE,
    }
)


# Set of edge types that connect two resource nodes (Prompt 24).
# Used by the graph builder, the validator, and the relationships
# detector to filter on resource-to-resource edges specifically.
RESOURCE_RELATIONSHIP_EDGE_TYPES: frozenset[str] = frozenset(
    {
        EDGE_TYPE_RESOURCE_SIMILAR_TO_RESOURCE,
        EDGE_TYPE_RESOURCE_SHARES_TOPIC_WITH_RESOURCE,
        EDGE_TYPE_RESOURCE_SHARES_CONCEPT_WITH_RESOURCE,
        EDGE_TYPE_RESOURCE_SAME_SOURCE_TYPE_AS_RESOURCE,
        EDGE_TYPE_RESOURCE_MAY_BE_PREREQUISITE_FOR_RESOURCE,
        EDGE_TYPE_RESOURCE_MAY_EXPAND_ON_RESOURCE,
    }
)


# -----------------------------------------------------------------------------
# Blocked alias topic slugs
#
# These slugs must never appear as real graph topic nodes. They are
# input synonyms only and are normalized away at the topic_matches()
# layer. Re-declared here so the graph package has zero hard
# dependency on the order in which wiki.resource_utils is imported.
# -----------------------------------------------------------------------------

BLOCKED_ALIAS_TOPIC_SLUGS: frozenset[str] = frozenset(
    {
        "rag",
        "retrieval",
        "security",
        "ai-safety",
        "optimization-training",
        "training",
    }
)


# -----------------------------------------------------------------------------
# ID helpers
# -----------------------------------------------------------------------------

def make_node_id(node_type: str, slug: str) -> str:
    """Return a deterministic graph node ID.

    Format: ``<type>:<slug>``

    Slug must not contain ``:`` (callers are responsible for cleaning
    the slug first). Empty slugs raise ``ValueError`` because empty
    IDs are never useful.
    """
    if not node_type:
        raise ValueError("node_type must not be empty")
    if not slug:
        raise ValueError("slug must not be empty")
    if ":" in node_type:
        raise ValueError(f"node_type must not contain ':' (got {node_type!r})")
    if ":" in slug:
        raise ValueError(f"slug must not contain ':' (got {slug!r})")
    if node_type not in ALLOWED_NODE_TYPES:
        raise ValueError(f"unknown node_type: {node_type!r}")
    return f"{node_type}:{slug}"


def make_edge_id(edge_type: str, source_id: str, target_id: str) -> str:
    """Return a deterministic graph edge ID.

    Format: ``<edge_type>:<source_id>:<target_id>``

    Source and target IDs are expected to already be node IDs (output
    of :func:`make_node_id`).
    """
    if not edge_type:
        raise ValueError("edge_type must not be empty")
    if not source_id:
        raise ValueError("source_id must not be empty")
    if not target_id:
        raise ValueError("target_id must not be empty")
    if edge_type not in ALLOWED_EDGE_TYPES:
        raise ValueError(f"unknown edge_type: {edge_type!r}")
    if ":" in source_id:
        # we still allow node IDs which contain ':' in their slug,
        # so this is just a sanity check that source_id is not empty
        pass
    return f"{edge_type}:{source_id}:{target_id}"


def parse_node_id(node_id: str) -> tuple[str, str]:
    """Split a node ID into ``(type, slug)``."""
    if ":" not in node_id:
        raise ValueError(f"node_id must contain ':' (got {node_id!r})")
    node_type, slug = node_id.split(":", 1)
    return node_type, slug


# -----------------------------------------------------------------------------
# Dict factories (deterministic key order)
# -----------------------------------------------------------------------------

def node_payload(
    *,
    node_type: str,
    slug: str,
    label: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a node dict with stable key order.

    Stable order is required so the JSON export is byte-stable across
    runs (we use ``json.dump(sort_keys=False)`` and rely on the dict
    literal ordering produced here).
    """
    return {
        "id": make_node_id(node_type, slug),
        "type": node_type,
        "label": label,
        "slug": slug,
        "metadata": dict(metadata) if metadata else {},
    }


def edge_payload(
    *,
    edge_type: str,
    source_id: str,
    target_id: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an edge dict with stable key order."""
    return {
        "id": make_edge_id(edge_type, source_id, target_id),
        "type": edge_type,
        "source": source_id,
        "target": target_id,
        "metadata": dict(metadata) if metadata else {},
    }


def slugify(value: str) -> str:
    """Normalize a free-form label into a safe slug (lowercase, dashes)."""
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return cleaned


def dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    """Return a list with duplicates removed, preserving first occurrence."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
