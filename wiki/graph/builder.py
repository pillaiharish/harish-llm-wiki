"""Build the knowledge graph from the registry and derived data.

The builder is deterministic: two calls with the same input produce
the same node and edge lists (in the same order). This is the
foundation for the rest of the graph feature work in later prompts.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wiki.config import config
from wiki.generate.page_utils import read_note, resource_route
from wiki.graph.relationships import (
    build_resource_views,
    detect_resource_relationships,
)
from wiki.graph.schema import (
    BLOCKED_ALIAS_TOPIC_SLUGS,
    EDGE_TYPE_CONCEPT_IN_TOPIC,
    EDGE_TYPE_LEARN_CHAPTER_USES_RESOURCE,
    EDGE_TYPE_RESOURCE_HAS_TAG,
    EDGE_TYPE_RESOURCE_HAS_TOPIC,
    EDGE_TYPE_RESOURCE_MENTIONS_CONCEPT,
    EDGE_TYPE_REVIEW_PAGE_REVIEWS_RESOURCE,
    EDGE_TYPE_TOPIC_HAS_RESOURCE,
    EDGE_TYPE_TOPIC_RELATED_TO_TOPIC,
    NODE_TYPE_CONCEPT,
    NODE_TYPE_LEARN_CHAPTER,
    NODE_TYPE_RESOURCE,
    NODE_TYPE_REVIEW_PAGE,
    NODE_TYPE_TAG,
    NODE_TYPE_TOPIC,
    dedupe_preserve_order,
    edge_payload,
    make_node_id,
    node_payload,
    slugify,
)
from wiki.resource_utils import (
    TOPIC_DEFINITIONS,
    dedupe_records,
    display_title,
    learned_date,
    source_url,
    topic_matches,
)
from wiki.schemas import ResourceRecord
from wiki.storage import Storage


REVIEW_CATEGORIES: tuple[str, ...] = (
    "weak",
    "fallback",
    "failed",
    "missing_citations",
    "stale",
    "manual",
    "untitled",
)


class GraphBuilder:
    """Build deterministic knowledge graph nodes and edges."""

    def __init__(self, *, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or config.LLM_WIKI_DATA_DIR
        self._nodes: list[dict[str, Any]] = []
        self._edges: list[dict[str, Any]] = []
        self._seen_node_ids: set[str] = set()
        self._seen_edge_ids: set[str] = set()
        self._seen_edge_triples: set[tuple[str, str, str]] = set()
        self._duplicate_edges_removed = 0
        # Cache: resource_id -> set of canonical topic slugs matched
        self._resource_topics: dict[str, set[str]] = {}
        # Cache: resource_id -> set of concept slugs referenced
        self._resource_concepts: dict[str, set[str]] = {}

    # ------------------------------------------------------------------ public

    def build(self, records: list[ResourceRecord]) -> dict[str, Any]:
        """Build the full graph and return the dict for export."""
        self._nodes = []
        self._edges = []
        self._seen_node_ids = set()
        self._seen_edge_ids = set()
        self._seen_edge_triples = set()
        self._duplicate_edges_removed = 0
        self._resource_topics = {}
        self._resource_concepts = {}

        records = list(dedupe_records(records))

        self._build_topic_nodes()
        self._build_resource_nodes(records)
        self._build_tag_nodes(records)
        self._build_concept_nodes()
        self._build_learn_chapter_nodes()
        self._build_review_page_nodes()

        self._build_resource_topic_edges(records)
        self._build_resource_tag_edges(records)
        self._build_resource_concept_edges()
        self._build_learn_chapter_resource_edges()
        self._build_review_page_resource_edges()
        self._build_topic_related_edges()
        self._build_resource_relationship_edges()

        # Deterministic ordering for the JSON output
        self._nodes.sort(key=lambda n: n["id"])
        self._edges.sort(key=lambda e: e["id"])

        stats = self._stats()
        return {
            "schema_version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "nodes": self._nodes,
            "edges": self._edges,
            "stats": stats,
        }

    # --------------------------------------------------------------- builders

    def _build_topic_nodes(self) -> None:
        for slug in sorted(TOPIC_DEFINITIONS.keys()):
            if slug in BLOCKED_ALIAS_TOPIC_SLUGS:
                # Defensive: TOPIC_DEFINITIONS is already alias-free, but
                # the guard makes the rule explicit.
                continue
            definition = TOPIC_DEFINITIONS[slug]
            metadata = {
                "keyword_count": len(definition.get("keywords", [])),
                "learning_path_steps": len(definition.get("learning_path", [])),
            }
            self._add_node(
                node_payload(
                    node_type=NODE_TYPE_TOPIC,
                    slug=slug,
                    label=definition.get("name", slug),
                    metadata=metadata,
                )
            )

    def _build_resource_nodes(self, records: list[ResourceRecord]) -> None:
        for record in records:
            slug = record.id.replace(":", "_")
            metadata = {
                "source_type": record.source_type.value,
                "status": record.status.value,
                "url": source_url(record),
                "date": learned_date(record).date().isoformat(),
            }
            self._add_node(
                node_payload(
                    node_type=NODE_TYPE_RESOURCE,
                    slug=slug,
                    label=display_title(record, mark_missing=True),
                    metadata=metadata,
                )
            )

    def _build_tag_nodes(self, records: list[ResourceRecord]) -> None:
        tags: set[str] = set()
        for record in records:
            for tag in record.tags or []:
                if not tag:
                    continue
                normalized = str(tag).strip().lower()
                if normalized:
                    tags.add(normalized)
        for tag in sorted(tags):
            self._add_node(
                node_payload(
                    node_type=NODE_TYPE_TAG,
                    slug=tag,
                    label=tag,
                    metadata={"source": "resource"},
                )
            )

    def _build_concept_nodes(self) -> None:
        concepts_dir = self.data_dir / "processed" / "concepts"
        if not concepts_dir.exists():
            return
        for path in sorted(concepts_dir.glob("*.md")):
            if path.name == "index.md":
                continue
            content = _safe_read(path)
            label = _first_h1(content) or path.stem
            needs_review = "needs review" in content.lower()
            self._add_node(
                node_payload(
                    node_type=NODE_TYPE_CONCEPT,
                    slug=path.stem,
                    label=label,
                    metadata={"needs_review": needs_review},
                )
            )

    def _build_learn_chapter_nodes(self) -> None:
        learn_dir = self.data_dir / "processed" / "learn"
        if not learn_dir.exists():
            return
        for path in sorted(learn_dir.glob("*.md")):
            if path.name == "index.md":
                continue
            content = _safe_read(path)
            label = _first_h1(content) or path.stem
            metadata = {"resource_count": _learn_resource_count(content)}
            self._add_node(
                node_payload(
                    node_type=NODE_TYPE_LEARN_CHAPTER,
                    slug=path.stem,
                    label=label,
                    metadata=metadata,
                )
            )

    def _build_review_page_nodes(self) -> None:
        review_dir = self.data_dir / "processed" / "review"
        if not review_dir.exists():
            return
        for category in REVIEW_CATEGORIES:
            node_id = make_node_id(NODE_TYPE_REVIEW_PAGE, category)
            if node_id in self._seen_node_ids:
                continue
            # Find the matching markdown file (e.g. weak-notes.md)
            candidates = [
                review_dir / f"{category}-notes.md",
                review_dir / f"{category}.md",
            ]
            label = category.replace("_", " ").title()
            for candidate in candidates:
                if candidate.exists():
                    content = _safe_read(candidate)
                    label = _first_h1(content) or label
                    break
            self._add_node(
                node_payload(
                    node_type=NODE_TYPE_REVIEW_PAGE,
                    slug=category,
                    label=label,
                    metadata={},
                )
            )

    # ------------------------------------------------------------------ edges

    def _build_resource_topic_edges(self, records: list[ResourceRecord]) -> None:
        for record in records:
            note = read_note(record)
            topics = topic_matches(record, note)
            if not topics:
                continue
            resource_id = make_node_id(
                NODE_TYPE_RESOURCE, record.id.replace(":", "_")
            )
            for topic_slug in topics:
                if topic_slug in BLOCKED_ALIAS_TOPIC_SLUGS:
                    continue
                topic_id = make_node_id(NODE_TYPE_TOPIC, topic_slug)
                self._resource_topics.setdefault(record.id, set()).add(topic_slug)
                self._add_edge(
                    edge_payload(
                        edge_type=EDGE_TYPE_RESOURCE_HAS_TOPIC,
                        source_id=resource_id,
                        target_id=topic_id,
                    )
                )
                self._add_edge(
                    edge_payload(
                        edge_type=EDGE_TYPE_TOPIC_HAS_RESOURCE,
                        source_id=topic_id,
                        target_id=resource_id,
                    )
                )

    def _build_resource_tag_edges(self, records: list[ResourceRecord]) -> None:
        for record in records:
            if not record.tags:
                continue
            resource_id = make_node_id(
                NODE_TYPE_RESOURCE, record.id.replace(":", "_")
            )
            for tag in record.tags:
                if not tag:
                    continue
                normalized = str(tag).strip().lower()
                if not normalized:
                    continue
                tag_id = make_node_id(NODE_TYPE_TAG, normalized)
                self._add_edge(
                    edge_payload(
                        edge_type=EDGE_TYPE_RESOURCE_HAS_TAG,
                        source_id=resource_id,
                        target_id=tag_id,
                    )
                )

    def _build_resource_concept_edges(self) -> None:
        """Connect resources to concepts.

        Two strategies, in order:

        1. Read the canonical concept JSON files
           ``processed/concepts/<slug>.json``. Each file lists
           ``resources[].resource_id`` entries that link back to the
           wiki resource. This is the source-of-truth mapping.
        2. Fall back to text-match: if the concept's source-backed
           summary is present, link to resources whose note mentions
           the concept slug.
        """
        concepts_dir = self.data_dir / "processed" / "concepts"
        if not concepts_dir.exists():
            return
        for path in sorted(concepts_dir.glob("*.json")):
            slug = path.stem
            concept_id = make_node_id(NODE_TYPE_CONCEPT, slug)
            try:
                payload = Storage.read_json(path)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            resources = payload.get("resources") or []
            if not isinstance(resources, list):
                continue
            for entry in resources:
                if not isinstance(entry, dict):
                    continue
                resource_id_value = entry.get("resource_id")
                if not resource_id_value:
                    continue
                resource_id = make_node_id(
                    NODE_TYPE_RESOURCE, str(resource_id_value).replace(":", "_")
                )
                self._add_edge(
                    edge_payload(
                        edge_type=EDGE_TYPE_RESOURCE_MENTIONS_CONCEPT,
                        source_id=resource_id,
                        target_id=concept_id,
                    )
                )
                self._resource_concepts.setdefault(
                    str(resource_id_value), set()
                ).add(slug)

        # If JSON didn't have any resources for a concept, fall back to
        # text match. This keeps the graph useful for concepts written
        # before the JSON file existed.
        for path in sorted(concepts_dir.glob("*.md")):
            if path.name == "index.md":
                continue
            concept_slug = path.stem
            concept_id = make_node_id(NODE_TYPE_CONCEPT, concept_slug)
            content = _safe_read(path).lower()
            if not content:
                continue
            if concept_slug in self._covered_concept_resources():
                continue
            for record in _load_records_from_registry():
                if record.id in self._covered_concept_resources().get(concept_slug, set()):
                    continue
                note = read_note(record).lower()
                if not note:
                    continue
                if concept_slug in note or concept_slug.replace("-", " ") in note:
                    resource_id = make_node_id(
                        NODE_TYPE_RESOURCE, record.id.replace(":", "_")
                    )
                    self._add_edge(
                        edge_payload(
                            edge_type=EDGE_TYPE_RESOURCE_MENTIONS_CONCEPT,
                            source_id=resource_id,
                            target_id=concept_id,
                        )
                    )
                    self._resource_concepts.setdefault(
                        record.id, set()
                    ).add(concept_slug)

        # concept_in_topic edges: for every (concept, topic) pair where
        # at least one resource that mentions the concept also matches
        # the topic.
        resource_topic_map = self._resource_topics
        concept_topics: dict[str, set[str]] = {}
        for resource_id, concept_slugs in self._resource_concepts.items():
            topics = resource_topic_map.get(resource_id, set())
            for concept_slug in concept_slugs:
                concept_topics.setdefault(concept_slug, set()).update(topics)
        for concept_slug, topic_slugs in concept_topics.items():
            concept_id = make_node_id(NODE_TYPE_CONCEPT, concept_slug)
            for topic_slug in topic_slugs:
                topic_id = make_node_id(NODE_TYPE_TOPIC, topic_slug)
                self._add_edge(
                    edge_payload(
                        edge_type=EDGE_TYPE_CONCEPT_IN_TOPIC,
                        source_id=concept_id,
                        target_id=topic_id,
                    )
                )

    def _covered_concept_resources(self) -> dict[str, set[str]]:
        """Map of concept_slug -> set of resource_ids already linked."""
        covered: dict[str, set[str]] = {}
        for resource_id, concept_slugs in self._resource_concepts.items():
            for concept_slug in concept_slugs:
                covered.setdefault(concept_slug, set()).add(resource_id)
        return covered

    def _build_learn_chapter_resource_edges(self) -> None:
        """Connect Learn chapters to the resources that built them."""
        # The learn generator stores resource ids in
        # ``processed/learn/learn.json`` under
        # ``chapters.<slug>.resource_ids``. Use that as the source of
        # truth. If the JSON is missing, fall back to a text match in
        # the chapter markdown.
        learn_json = self.data_dir / "processed" / "learn" / "learn.json"
        if learn_json.exists():
            try:
                payload = Storage.read_json(learn_json)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                chapters = payload.get("chapters") or {}
                if isinstance(chapters, dict):
                    for slug, data in sorted(chapters.items()):
                        chapter_id = make_node_id(NODE_TYPE_LEARN_CHAPTER, slug)
                        if not isinstance(data, dict):
                            continue
                        resource_ids = data.get("resource_ids") or []
                        if not isinstance(resource_ids, list):
                            continue
                        for resource_id_value in resource_ids:
                            if not resource_id_value:
                                continue
                            resource_id = make_node_id(
                                NODE_TYPE_RESOURCE,
                                str(resource_id_value).replace(":", "_"),
                            )
                            self._add_edge(
                                edge_payload(
                                    edge_type=EDGE_TYPE_LEARN_CHAPTER_USES_RESOURCE,
                                    source_id=chapter_id,
                                    target_id=resource_id,
                                )
                            )
                    return

        # Text-match fallback
        learn_dir = self.data_dir / "processed" / "learn"
        if not learn_dir.exists():
            return
        for path in sorted(learn_dir.glob("*.md")):
            if path.name == "index.md":
                continue
            chapter_slug = path.stem
            chapter_id = make_node_id(NODE_TYPE_LEARN_CHAPTER, chapter_slug)
            content = _safe_read(path)
            for record in _load_records_from_registry():
                marker = f"({resource_route(record.id)})"
                if marker in content:
                    resource_id = make_node_id(
                        NODE_TYPE_RESOURCE, record.id.replace(":", "_")
                    )
                    self._add_edge(
                        edge_payload(
                            edge_type=EDGE_TYPE_LEARN_CHAPTER_USES_RESOURCE,
                            source_id=chapter_id,
                            target_id=resource_id,
                        )
                    )

    def _build_review_page_resource_edges(self) -> None:
        """Connect review pages to the resources they review."""
        review_json = self.data_dir / "processed" / "review" / "review.json"
        if not review_json.exists():
            return
        try:
            payload = Storage.read_json(review_json)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        for category in REVIEW_CATEGORIES:
            items = payload.get(category)
            if not isinstance(items, list):
                continue
            review_id = make_node_id(NODE_TYPE_REVIEW_PAGE, category)
            for item in items:
                if not isinstance(item, dict):
                    continue
                resource_id_value = item.get("id")
                if not resource_id_value:
                    continue
                resource_id = make_node_id(
                    NODE_TYPE_RESOURCE, str(resource_id_value).replace(":", "_")
                )
                self._add_edge(
                    edge_payload(
                        edge_type=EDGE_TYPE_REVIEW_PAGE_REVIEWS_RESOURCE,
                        source_id=review_id,
                        target_id=resource_id,
                    )
                )

    def _build_topic_related_edges(self) -> None:
        """Placeholder topic-topic edges.

        Prompt 23 has no explicit topic-topic data source. We mark all
        canonical topics as related to each other (a fully connected
        subgraph) so the graph still has topic-topic structure.
        Prompt 24 (``Resource Relationship Detection``) will replace
        this with data-driven relations.
        """
        slugs = sorted(TOPIC_DEFINITIONS.keys())
        for source_slug in slugs:
            if source_slug in BLOCKED_ALIAS_TOPIC_SLUGS:
                continue
            source_id = make_node_id(NODE_TYPE_TOPIC, source_slug)
            for target_slug in slugs:
                if target_slug == source_slug:
                    continue
                if target_slug in BLOCKED_ALIAS_TOPIC_SLUGS:
                    continue
                # Use sorted order to keep the edge set canonical.
                if source_slug > target_slug:
                    continue
                target_id = make_node_id(NODE_TYPE_TOPIC, target_slug)
                self._add_edge(
                    edge_payload(
                        edge_type=EDGE_TYPE_TOPIC_RELATED_TO_TOPIC,
                        source_id=source_id,
                        target_id=target_id,
                        metadata={"deterministic": True, "placeholder": True},
                    )
                )

    def _build_resource_relationship_edges(self) -> None:
        """Build resource-to-resource relationship edges (Prompt 24).

        This calls the deterministic detector in
        :mod:`wiki.graph.relationships` with the resource views built
        from ``self._resource_topics`` and ``self._resource_concepts``
        caches plus the resource node metadata. Each returned edge is
        inserted via :meth:`_add_edge` so the existing dedupe and
        endpoint-checks apply unchanged.
        """
        resource_nodes = [n for n in self._nodes if n["type"] == NODE_TYPE_RESOURCE]
        if len(resource_nodes) < 2:
            # No pairs to consider.
            return
        views = build_resource_views(
            resources=resource_nodes,
            resource_topics=self._resource_topics,
            resource_concepts=self._resource_concepts,
        )
        edges = detect_resource_relationships(views)
        for edge in edges:
            self._add_edge(edge)


    # --------------------------------------------------------------- helpers

    def _add_node(self, node: dict[str, Any]) -> None:
        node_id = node["id"]
        if node_id in self._seen_node_ids:
            return
        self._seen_node_ids.add(node_id)
        self._nodes.append(node)

    def _add_edge(self, edge: dict[str, Any]) -> None:
        edge_id = edge["id"]
        triple = (edge["type"], edge["source"], edge["target"])
        if edge_id in self._seen_edge_ids:
            # Same edge id collision is itself a duplicate triple
            self._duplicate_edges_removed += 1
            return
        if triple in self._seen_edge_triples:
            self._duplicate_edges_removed += 1
            return
        # Both endpoints must exist
        if edge["source"] not in self._seen_node_ids:
            return
        if edge["target"] not in self._seen_node_ids:
            return
        self._seen_edge_ids.add(edge_id)
        self._seen_edge_triples.add(triple)
        self._edges.append(edge)

    def _stats(self) -> dict[str, Any]:
        node_type_counts = dict(Counter(n["type"] for n in self._nodes))
        edge_type_counts = dict(Counter(e["type"] for e in self._edges))
        blocked_alias_topic_nodes = sum(
            1
            for node in self._nodes
            if node["type"] == NODE_TYPE_TOPIC
            and node["slug"] in BLOCKED_ALIAS_TOPIC_SLUGS
        )
        return {
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "node_type_counts": dict(sorted(node_type_counts.items())),
            "edge_type_counts": dict(sorted(edge_type_counts.items())),
            "blocked_alias_topic_nodes": blocked_alias_topic_nodes,
            "duplicate_edges_removed": self._duplicate_edges_removed,
        }


# -----------------------------------------------------------------------------
# Convenience functions
# -----------------------------------------------------------------------------

def build_graph(records: list[ResourceRecord], *, data_dir: Path | None = None) -> dict[str, Any]:
    """Build the graph in one call (thin wrapper around :class:`GraphBuilder`)."""
    return GraphBuilder(data_dir=data_dir).build(records)


# -----------------------------------------------------------------------------
# Local helpers
# -----------------------------------------------------------------------------

def _safe_read(path: Path) -> str:
    try:
        return Storage.read_text(path)
    except Exception:
        return ""


def _first_h1(content: str) -> str | None:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def _learn_resource_count(content: str) -> int:
    """Count resource link rows in a Learn chapter table.

    The chapter format produced by ``wiki/generate/learn.py`` has a
    final ``## Related resources`` table whose rows begin with
    ``| <date> | [title](/resources/...) | ...``. We count those
    rows.
    """
    count = 0
    in_table = False
    for line in content.splitlines():
        if line.startswith("## Related resources"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                if count:
                    break
                continue
            if "/resources/" in line:
                count += 1
    return count


def _load_records_from_registry() -> list[ResourceRecord]:
    """Load all resources from the registry. Used for text-match fallbacks."""
    # Imported lazily to avoid a hard import-time cycle through
    # wiki.cli. The registry is safe to import; cli is not.
    from wiki.registry import registry

    return list(registry.get_all())
