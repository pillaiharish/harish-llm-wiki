"""Tests for Prompt 24: Resource Relationship Detection.

Covers the 12 required test cases from the prompt plus 3 defensive
tests for a total of 15 new test methods.

These tests follow the same pattern as
:mod:`tests.test_prompt23_graph`: build a small graph in a tmp dir
with controlled records, then assert on the resulting graph bundle,
on the on-disk JSON files, and on the validator.
"""

import json
from pathlib import Path

import pytest

from wiki.config import config
from wiki.graph import (
    EDGE_TYPE_RESOURCE_MAY_BE_PREREQUISITE_FOR_RESOURCE,
    EDGE_TYPE_RESOURCE_MAY_EXPAND_ON_RESOURCE,
    EDGE_TYPE_RESOURCE_SAME_SOURCE_TYPE_AS_RESOURCE,
    EDGE_TYPE_RESOURCE_SHARES_CONCEPT_WITH_RESOURCE,
    EDGE_TYPE_RESOURCE_SHARES_TOPIC_WITH_RESOURCE,
    EDGE_TYPE_RESOURCE_SIMILAR_TO_RESOURCE,
    NODE_TYPE_RESOURCE,
    RESOURCE_RELATIONSHIP_EDGE_TYPES,
    GraphBuilder,
    export_graph,
    validate_graph,
)
from wiki.graph.builder import build_graph
from wiki.graph.relationships import (
    build_resource_views,
    detect_resource_relationships,
)
from wiki.graph.schema import make_edge_id, make_node_id
from wiki.schemas import (
    Importance,
    ResourceRecord,
    ResourceStatus,
    SourceType,
)


# -----------------------------------------------------------------------------
# Fixtures and helpers
# -----------------------------------------------------------------------------


def _make_note() -> str:
    """A minimal but realistic generated note."""
    return (
        "# Test Notes\n\n"
        "## Source-backed summary\n\n"
        "- Test content. [source: webpage:test]\n"
    )


def _make_record(
    tmp_path: Path,
    *,
    resource_id: str = "webpage:test",
    title: str = "RAG Hybrid Retrieval",
    tags: list | None = None,
    source_type: SourceType = SourceType.WEBPAGE,
    note_text: str | None = None,
) -> ResourceRecord:
    """Build a self-contained ResourceRecord on disk under tmp_path."""
    safe_id = resource_id.replace(":", "_")
    note_path = tmp_path / "processed" / "resources" / f"{safe_id}.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(note_text or _make_note(), encoding="utf-8")
    return ResourceRecord(
        id=resource_id,
        source_type=source_type,
        canonical_id=resource_id,
        original_url=f"https://example.com/{safe_id}",
        title=title,
        status=ResourceStatus.PROCESSED,
        generated_note_path=note_path,
        llm_provider="mock",
        llm_model="mock-model",
        prompt_version="harish_llm_wiki_v4",
        tags=tags if tags is not None else ["rag", "retrieval"],
        importance=Importance.MEDIUM,
    )


def _build(tmp_path: Path, *, records: list[ResourceRecord] | None = None) -> dict:
    """Build a graph in a tmp dir and return the bundle."""
    if records is None:
        records = [_make_record(tmp_path)]
    return build_graph(records, data_dir=tmp_path)


def _ids_by_type(nodes: list[dict], node_type: str) -> list[str]:
    return sorted(n["id"] for n in nodes if n.get("type") == node_type)


def _edges_of_type(graph: dict, edge_type: str) -> list[dict]:
    return [e for e in graph["edges"] if e["type"] == edge_type]


# -----------------------------------------------------------------------------
# Test 1: similar resources get a relationship edge
# -----------------------------------------------------------------------------


class TestSimilarResources:
    def test_similar_resources_get_a_relationship_edge(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # Two resources sharing a topic (rag-retrieval) and a concept
        # (hybrid-search). Both titles contain "rag" and "retrieval"
        # so the keyword signal also fires.
        record_a = _make_record(
            tmp_path,
            resource_id="webpage:a",
            title="Intro to RAG Retrieval",
            tags=["rag", "retrieval"],
        )
        record_b = _make_record(
            tmp_path,
            resource_id="webpage:b",
            title="Advanced RAG with Hybrid Retrieval",
            tags=["rag"],
        )
        graph = _build(tmp_path, records=[record_a, record_b])

        similar = _edges_of_type(graph, EDGE_TYPE_RESOURCE_SIMILAR_TO_RESOURCE)
        assert similar, "Expected a resource_similar_to_resource edge"
        # The catch-all is symmetric: source is the id-sorted smaller id.
        edge = similar[0]
        assert edge["source"] == make_node_id(NODE_TYPE_RESOURCE, "webpage_a")
        assert edge["target"] == make_node_id(NODE_TYPE_RESOURCE, "webpage_b")
        meta = edge["metadata"]
        assert meta["score"] > 0
        assert isinstance(meta["reasons"], list)
        # At least one of the signals fired.
        assert any(
            r in meta["reasons"]
            for r in ("shared_topics", "shared_concepts", "shared_keywords")
        )


# -----------------------------------------------------------------------------
# Test 2: unrelated resources do not get a high-confidence relationship
# -----------------------------------------------------------------------------


class TestUnrelatedResources:
    def test_unrelated_resources_do_not_get_a_high_confidence_relationship(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # Two resources that share nothing: different source types,
        # disjoint topics, disjoint concepts, disjoint keyword substrings,
        # and neutral depth terms.
        record_a = _make_record(
            tmp_path,
            resource_id="webpage:alpha",
            title="Quarterly Earnings Report",
            tags=["finance", "earnings"],
            source_type=SourceType.WEBPAGE,
        )
        record_b = _make_record(
            tmp_path,
            resource_id="youtube:beta",
            title="Mountain Biking Trail Guide",
            tags=["outdoor", "biking"],
            source_type=SourceType.YOUTUBE,
        )
        graph = _build(tmp_path, records=[record_a, record_b])

        similar = _edges_of_type(graph, EDGE_TYPE_RESOURCE_SIMILAR_TO_RESOURCE)
        assert similar == [], (
            f"Expected no resource_similar_to_resource edges, got {similar}"
        )
        prereq = _edges_of_type(
            graph, EDGE_TYPE_RESOURCE_MAY_BE_PREREQUISITE_FOR_RESOURCE
        )
        expand = _edges_of_type(
            graph, EDGE_TYPE_RESOURCE_MAY_EXPAND_ON_RESOURCE
        )
        assert prereq == [], f"Expected no prerequisite edges, got {prereq}"
        assert expand == [], f"Expected no expand edges, got {expand}"


# -----------------------------------------------------------------------------
# Test 3: shared topic relationship is generated
# -----------------------------------------------------------------------------


class TestSharedTopicEdge:
    def test_shared_topic_relationship_is_generated(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # Two resources that share exactly the rag-retrieval topic.
        record_a = _make_record(
            tmp_path,
            resource_id="webpage:share-a",
            title="RAG Overview",
            tags=["rag"],
        )
        record_b = _make_record(
            tmp_path,
            resource_id="webpage:share-b",
            title="Retrieval Deep Dive",
            tags=["retrieval"],
        )
        graph = _build(tmp_path, records=[record_a, record_b])

        shared_topic = _edges_of_type(
            graph, EDGE_TYPE_RESOURCE_SHARES_TOPIC_WITH_RESOURCE
        )
        assert shared_topic, "Expected a resource_shares_topic_with_resource edge"
        edge = shared_topic[0]
        assert edge["metadata"]["shared_topics"] == ["rag-retrieval"]
        assert edge["source"] == make_node_id(NODE_TYPE_RESOURCE, "webpage_share-a")
        assert edge["target"] == make_node_id(NODE_TYPE_RESOURCE, "webpage_share-b")


# -----------------------------------------------------------------------------
# Test 4: shared concept relationship is generated
# -----------------------------------------------------------------------------


class TestSharedConceptEdge:
    def test_shared_concept_relationship_is_generated(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # Two resources that share a concept slug, even if no topic match.
        # We seed the graph's concept caches indirectly by writing a
        # concept JSON that references both resources.
        concepts_dir = tmp_path / "processed" / "concepts"
        concepts_dir.mkdir(parents=True, exist_ok=True)
        concept_payload = {
            "slug": "hybrid-search",
            "resources": [
                {"resource_id": "webpage:conc-a"},
                {"resource_id": "webpage:conc-b"},
            ],
        }
        (concepts_dir / "hybrid-search.json").write_text(
            json.dumps(concept_payload), encoding="utf-8"
        )
        # Also create the markdown so the concept node exists.
        (concepts_dir / "hybrid-search.md").write_text(
            "# Hybrid Search\n\nContent.\n", encoding="utf-8"
        )
        record_a = _make_record(
            tmp_path,
            resource_id="webpage:conc-a",
            title="RAG Overview",
            tags=["rag"],
        )
        record_b = _make_record(
            tmp_path,
            resource_id="webpage:conc-b",
            title="Retrieval Deep Dive",
            tags=["retrieval"],
        )
        graph = _build(tmp_path, records=[record_a, record_b])

        shared_concept = _edges_of_type(
            graph, EDGE_TYPE_RESOURCE_SHARES_CONCEPT_WITH_RESOURCE
        )
        assert shared_concept, "Expected a resource_shares_concept_with_resource edge"
        edge = shared_concept[0]
        assert edge["metadata"]["shared_concepts"] == ["hybrid-search"]


# -----------------------------------------------------------------------------
# Test 5: relationship edges are deterministic
# -----------------------------------------------------------------------------


class TestDeterminism:
    def test_relationship_edges_are_deterministic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        records = [
            _make_record(
                tmp_path,
                resource_id="webpage:det-a",
                title="RAG Intro",
                tags=["rag"],
            ),
            _make_record(
                tmp_path,
                resource_id="webpage:det-b",
                title="RAG Advanced",
                tags=["rag", "retrieval"],
            ),
            _make_record(
                tmp_path,
                resource_id="youtube:det-c",
                title="RAG Hybrid Search",
                tags=["rag"],
                source_type=SourceType.YOUTUBE,
            ),
        ]
        graph1 = _build(tmp_path, records=records)
        graph2 = _build(tmp_path, records=records)

        # Full bundle equality for nodes and edges (excluding
        # ``generated_at`` which is timestamped).
        assert graph1["nodes"] == graph2["nodes"]
        assert graph1["edges"] == graph2["edges"]

        # On-disk JSON is byte-stable.
        paths1 = export_graph(graph1, data_dir=tmp_path)
        edges1 = Path(paths1["edges"]).read_text(encoding="utf-8")
        paths2 = export_graph(graph2, data_dir=tmp_path)
        edges2 = Path(paths2["edges"]).read_text(encoding="utf-8")
        assert edges1 == edges2

    def test_relationship_edges_have_sorted_metadata(
        self, tmp_path, monkeypatch
    ):
        """``reasons`` and ``shared_*`` lists are sorted in the output."""
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        records = [
            _make_record(
                tmp_path,
                resource_id="webpage:sort-a",
                title="RAG with Vectors and FAISS",
                tags=["rag"],
            ),
            _make_record(
                tmp_path,
                resource_id="webpage:sort-b",
                title="RAG with Vectors and FAISS deep dive",
                tags=["rag"],
            ),
        ]
        graph = _build(tmp_path, records=records)
        rel_edges = [
            e for e in graph["edges"]
            if e["type"] in RESOURCE_RELATIONSHIP_EDGE_TYPES
        ]
        assert rel_edges, "Expected at least one relationship edge"
        for edge in rel_edges:
            meta = edge["metadata"]
            reasons = meta.get("reasons", [])
            assert reasons == sorted(reasons), (
                f"reasons not sorted: {reasons}"
            )
            for key in ("shared_topics", "shared_concepts", "shared_keywords"):
                value = meta.get(key, [])
                assert value == sorted(value), (
                    f"{key} not sorted: {value}"
                )


# -----------------------------------------------------------------------------
# Test 6: no duplicate relationship edges
# -----------------------------------------------------------------------------


class TestNoDuplicateEdges:
    def test_no_duplicate_relationship_edges(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # Two resources that share both a topic and a concept. The
        # detector must still emit exactly one of each relationship
        # edge type, not multiple.
        concepts_dir = tmp_path / "processed" / "concepts"
        concepts_dir.mkdir(parents=True, exist_ok=True)
        (concepts_dir / "hybrid-search.json").write_text(
            json.dumps(
                {
                    "slug": "hybrid-search",
                    "resources": [
                        {"resource_id": "webpage:dup-a"},
                        {"resource_id": "webpage:dup-b"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (concepts_dir / "hybrid-search.md").write_text(
            "# Hybrid Search\n\nContent.\n", encoding="utf-8"
        )
        record_a = _make_record(
            tmp_path,
            resource_id="webpage:dup-a",
            title="RAG with FAISS",
            tags=["rag"],
        )
        record_b = _make_record(
            tmp_path,
            resource_id="webpage:dup-b",
            title="RAG with FAISS",
            tags=["rag"],
        )
        graph = _build(tmp_path, records=[record_a, record_b])
        # Filter to the relationship edges between the two resources.
        rel_edges = [
            e for e in graph["edges"]
            if e["type"] in RESOURCE_RELATIONSHIP_EDGE_TYPES
            and e["source"] == make_node_id(NODE_TYPE_RESOURCE, "webpage_dup-a")
            and e["target"] == make_node_id(NODE_TYPE_RESOURCE, "webpage_dup-b")
        ]
        types = [e["type"] for e in rel_edges]
        # No duplicate types (each (type, source, target) is unique).
        assert len(types) == len(set(types)), (
            f"Duplicate relationship edge types: {types}"
        )
        # And no duplicate edge ids.
        ids = [e["id"] for e in rel_edges]
        assert len(ids) == len(set(ids)), f"Duplicate edge ids: {ids}"


# -----------------------------------------------------------------------------
# Test 7: no self-relationship edges
# -----------------------------------------------------------------------------


class TestNoSelfRelationshipEdges:
    def test_no_self_relationship_edges(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # A single resource must not produce any relationship edge
        # from itself to itself.
        record = _make_record(
            tmp_path,
            resource_id="webpage:solo",
            title="RAG Overview",
            tags=["rag"],
        )
        graph = _build(tmp_path, records=[record])
        for edge in graph["edges"]:
            if edge["type"] not in RESOURCE_RELATIONSHIP_EDGE_TYPES:
                continue
            assert edge["source"] != edge["target"], (
                f"Self-relationship edge found: {edge['id']}"
            )
        # And validator should also accept it without erroring.
        issues = validate_graph(graph)
        bad_codes = [
            code for _sev, code, _msg in issues
            if code == "self_relationship_edge"
        ]
        assert bad_codes == [], (
            f"Validator should not report self_relationship_edge: {issues}"
        )


# -----------------------------------------------------------------------------
# Test 8: relationship edge endpoints exist
# -----------------------------------------------------------------------------


class TestRelationshipEndpointsExist:
    def test_relationship_edge_endpoints_exist(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        records = [
            _make_record(
                tmp_path,
                resource_id="webpage:ep-a",
                title="RAG intro",
                tags=["rag"],
            ),
            _make_record(
                tmp_path,
                resource_id="webpage:ep-b",
                title="RAG advanced",
                tags=["rag"],
            ),
        ]
        graph = _build(tmp_path, records=records)
        node_ids = {n["id"] for n in graph["nodes"]}
        resource_ids = {
            n["id"] for n in graph["nodes"] if n["type"] == NODE_TYPE_RESOURCE
        }
        for edge in graph["edges"]:
            if edge["type"] not in RESOURCE_RELATIONSHIP_EDGE_TYPES:
                continue
            assert edge["source"] in node_ids, (
                f"Source {edge['source']!r} missing"
            )
            assert edge["target"] in node_ids, (
                f"Target {edge['target']!r} missing"
            )
            assert edge["source"] in resource_ids, (
                f"Source {edge['source']!r} is not a resource node"
            )
            assert edge["target"] in resource_ids, (
                f"Target {edge['target']!r} is not a resource node"
            )


# -----------------------------------------------------------------------------
# Test 9: relationship metadata includes reasons and score
# -----------------------------------------------------------------------------


class TestRelationshipMetadata:
    def test_relationship_metadata_includes_reasons_and_score(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        records = [
            _make_record(
                tmp_path,
                resource_id="webpage:meta-a",
                title="RAG intro with FAISS",
                tags=["rag"],
            ),
            _make_record(
                tmp_path,
                resource_id="webpage:meta-b",
                title="RAG advanced with FAISS",
                tags=["rag"],
            ),
        ]
        graph = _build(tmp_path, records=records)
        rel_edges = [
            e for e in graph["edges"]
            if e["type"] in RESOURCE_RELATIONSHIP_EDGE_TYPES
        ]
        assert rel_edges, "Expected at least one relationship edge"
        for edge in rel_edges:
            meta = edge["metadata"]
            assert "score" in meta, f"Missing score: {meta}"
            assert isinstance(meta["score"], (int, float))
            assert meta["score"] >= 0.0
            assert "reasons" in meta, f"Missing reasons: {meta}"
            assert isinstance(meta["reasons"], list)
            assert "shared_topics" in meta
            assert "shared_concepts" in meta
            assert "shared_keywords" in meta
            assert "source_resource_title" in meta
            assert "target_resource_title" in meta
            assert isinstance(meta["source_resource_title"], str)
            assert isinstance(meta["target_resource_title"], str)
            # If score is non-zero, reasons must be non-empty.
            if meta["score"] > 0:
                assert meta["reasons"], (
                    f"Non-zero score {meta['score']} but empty reasons"
                )


# -----------------------------------------------------------------------------
# Test 10: graph stats include relationship edge types
# -----------------------------------------------------------------------------


class TestStatsIncludeRelationshipEdgeTypes:
    def test_graph_stats_include_relationship_edge_types(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        records = [
            _make_record(
                tmp_path,
                resource_id="webpage:st-a",
                title="RAG overview",
                tags=["rag"],
            ),
            _make_record(
                tmp_path,
                resource_id="webpage:st-b",
                title="RAG advanced",
                tags=["rag"],
            ),
        ]
        graph = _build(tmp_path, records=records)
        edge_type_counts = graph["stats"]["edge_type_counts"]
        # At least one of the new relationship edge types is present.
        relationship_present = [
            et for et in edge_type_counts
            if et in RESOURCE_RELATIONSHIP_EDGE_TYPES
            and edge_type_counts[et] >= 1
        ]
        assert relationship_present, (
            f"Expected at least one relationship edge type in stats, "
            f"got {edge_type_counts}"
        )
        # The total edge count is consistent.
        assert graph["stats"]["edge_count"] == len(graph["edges"])


# -----------------------------------------------------------------------------
# Test 11: generated graph JSON includes relationship edges
# -----------------------------------------------------------------------------


class TestJsonIncludesRelationshipEdges:
    def test_generated_graph_json_includes_relationship_edges(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        records = [
            _make_record(
                tmp_path,
                resource_id="webpage:json-a",
                title="RAG intro",
                tags=["rag"],
            ),
            _make_record(
                tmp_path,
                resource_id="webpage:json-b",
                title="RAG advanced with FAISS",
                tags=["rag"],
            ),
        ]
        graph = _build(tmp_path, records=records)
        paths = export_graph(graph, data_dir=tmp_path)
        edges_data = json.loads(Path(paths["edges"]).read_text(encoding="utf-8"))
        bundle_data = json.loads(
            Path(paths["knowledge_graph"]).read_text(encoding="utf-8")
        )
        rel_in_edges = [
            e for e in edges_data if e["type"] in RESOURCE_RELATIONSHIP_EDGE_TYPES
        ]
        rel_in_bundle = [
            e for e in bundle_data["edges"]
            if e["type"] in RESOURCE_RELATIONSHIP_EDGE_TYPES
        ]
        assert rel_in_edges, (
            f"Expected relationship edges in edges.json, got: {edges_data}"
        )
        assert rel_in_bundle, (
            f"Expected relationship edges in knowledge_graph.json"
        )
        # Edges in the file are sorted by id.
        ids = [e["id"] for e in edges_data]
        assert ids == sorted(ids), "edges.json is not in sorted id order"


# -----------------------------------------------------------------------------
# Test 12: validator catches malformed relationship edges
# -----------------------------------------------------------------------------


class TestValidatorCatchesMalformedRelationshipEdges:
    def test_validator_catches_malformed_relationship_edges(self):
        # (a) relationship edge whose source is a topic node
        # (b) relationship edge with source == target (self-loop)
        graph = {
            "schema_version": "1.0.0",
            "nodes": [
                {"id": "resource:x", "type": "resource", "label": "X",
                 "slug": "x", "metadata": {}},
                {"id": "resource:y", "type": "resource", "label": "Y",
                 "slug": "y", "metadata": {}},
                {"id": "topic:t", "type": "topic", "label": "T",
                 "slug": "t", "metadata": {}},
            ],
            "edges": [
                # Wrong: source is a topic, not a resource.
                {
                    "id": make_edge_id(
                        EDGE_TYPE_RESOURCE_SIMILAR_TO_RESOURCE,
                        "topic:t",
                        "resource:x",
                    ),
                    "type": EDGE_TYPE_RESOURCE_SIMILAR_TO_RESOURCE,
                    "source": "topic:t",
                    "target": "resource:x",
                    "metadata": {"score": 1.0, "reasons": ["shared_topics"]},
                },
                # Wrong: self-loop on a relationship edge.
                {
                    "id": make_edge_id(
                        EDGE_TYPE_RESOURCE_SHARES_TOPIC_WITH_RESOURCE,
                        "resource:x",
                        "resource:x",
                    ),
                    "type": EDGE_TYPE_RESOURCE_SHARES_TOPIC_WITH_RESOURCE,
                    "source": "resource:x",
                    "target": "resource:x",
                    "metadata": {"score": 2.0, "reasons": ["shared_topics"]},
                },
            ],
            "stats": {"node_count": 3, "edge_count": 2},
        }
        issues = validate_graph(graph)
        codes = [code for _sev, code, _msg in issues]
        assert "relationship_endpoint_not_resource" in codes, (
            f"Expected relationship_endpoint_not_resource, got {codes}"
        )
        assert "self_relationship_edge" in codes, (
            f"Expected self_relationship_edge, got {codes}"
        )

    def test_validator_existing_endpoint_checks_cover_relationship_edges(self):
        # A relationship edge whose endpoint is missing entirely
        # should still be caught by the existing edge_source_missing
        # and edge_target_missing checks.
        graph = {
            "schema_version": "1.0.0",
            "nodes": [
                {"id": "resource:x", "type": "resource", "label": "X",
                 "slug": "x", "metadata": {}},
            ],
            "edges": [
                {
                    "id": make_edge_id(
                        EDGE_TYPE_RESOURCE_SIMILAR_TO_RESOURCE,
                        "resource:x",
                        "resource:missing",
                    ),
                    "type": EDGE_TYPE_RESOURCE_SIMILAR_TO_RESOURCE,
                    "source": "resource:x",
                    "target": "resource:missing",
                    "metadata": {"score": 1.0, "reasons": ["shared_topics"]},
                },
            ],
            "stats": {"node_count": 1, "edge_count": 1},
        }
        issues = validate_graph(graph)
        codes = [code for _sev, code, _msg in issues]
        assert "edge_target_missing" in codes, (
            f"Expected edge_target_missing, got {codes}"
        )


# -----------------------------------------------------------------------------
# Defensive tests
# -----------------------------------------------------------------------------


class TestRelationshipDetectionNoRegression:
    def test_relationship_detection_does_not_regress_prompt23_edges(
        self, tmp_path, monkeypatch
    ):
        """Adding the relationship builder must not change the
        Prompt 23 resource-topic / resource-concept / topic-topic edge
        counts.
        """
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        records = [
            _make_record(
                tmp_path,
                resource_id="webpage:nr-a",
                title="RAG intro",
                tags=["rag"],
            ),
            _make_record(
                tmp_path,
                resource_id="webpage:nr-b",
                title="RAG advanced",
                tags=["rag"],
            ),
        ]
        graph = _build(tmp_path, records=records)
        edge_type_counts = graph["stats"]["edge_type_counts"]
        # Prompt 23 edge types are still present.
        assert "resource_has_topic" in edge_type_counts
        assert "topic_has_resource" in edge_type_counts
        assert "topic_related_to_topic" in edge_type_counts
        # Both resources connect to rag-retrieval, so there should
        # be at least 2 of each direction edge.
        assert edge_type_counts["resource_has_topic"] >= 2

    def test_no_relationship_edges_for_resources_with_no_signal(
        self, tmp_path, monkeypatch
    ):
        """A resource with no topics, no concepts, no title, and no
        source type must not produce any relationship edge.
        """
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # Build records and then use model_copy to override the
        # ``extra`` dict to drop the source_type (the resource
        # node builder reads it from the registry, so we just
        # check the detector directly here).
        from wiki.graph.relationships import build_resource_views

        views = build_resource_views(
            resources=[
                {
                    "id": "resource:webpage_ns-a",
                    "type": "resource",
                    "slug": "webpage_ns-a",
                    "label": "",
                    "metadata": {"source_type": ""},
                },
                {
                    "id": "resource:webpage_ns-b",
                    "type": "resource",
                    "slug": "webpage_ns-b",
                    "label": "",
                    "metadata": {"source_type": ""},
                },
            ],
            resource_topics={},
            resource_concepts={},
        )
        edges = detect_resource_relationships(views)
        # No topic/concept/keyword overlap, no source-type match,
        # and depth is 0 for empty labels. No relationship edges.
        assert edges == [], (
            f"Expected no relationship edges, got {edges}"
        )


class TestDetectorUnitTests:
    def test_detector_returns_empty_for_no_resources(self):
        edges = detect_resource_relationships([])
        assert edges == []

    def test_detector_returns_empty_for_single_resource(self):
        view = {
            "id": "webpage:solo",
            "slug": "webpage_solo",
            "label": "RAG",
            "source_type": "webpage",
            "topics": {"rag-retrieval"},
            "concepts": set(),
            "tags": set(),
        }
        assert detect_resource_relationships([view]) == []

    def test_detector_handles_asymmetric_depth_edges(self):
        """Shallower resource points to deeper resource for prerequisite."""
        view_a = {
            "id": "webpage:a",
            "slug": "webpage_a",
            "label": "Intro to RAG",
            "source_type": "webpage",
            "topics": {"rag-retrieval"},
            "concepts": set(),
            "tags": set(),
        }
        view_b = {
            "id": "webpage:b",
            "slug": "webpage_b",
            "label": "Deep Dive on RAG",
            "source_type": "webpage",
            "topics": {"rag-retrieval"},
            "concepts": set(),
            "tags": set(),
        }
        edges = detect_resource_relationships([view_a, view_b])
        prereq = [
            e for e in edges
            if e["type"] == EDGE_TYPE_RESOURCE_MAY_BE_PREREQUISITE_FOR_RESOURCE
        ]
        expand = [
            e for e in edges
            if e["type"] == EDGE_TYPE_RESOURCE_MAY_EXPAND_ON_RESOURCE
        ]
        assert prereq, "Expected a prerequisite edge"
        assert expand, "Expected an expand edge"
        # The shallower resource (Intro) is the source of the
        # prerequisite edge; the deeper resource (Deep Dive) is the
        # source of the expand edge.
        prereq_source_id = prereq[0]["source"]
        expand_source_id = expand[0]["source"]
        # Map ids to slugs.
        assert prereq_source_id.endswith("webpage_a")  # shallower -> deeper
        assert expand_source_id.endswith("webpage_b")  # deeper -> shallower

    def test_build_resource_views_uses_source_type_from_metadata(self):
        """``build_resource_views`` should reverse the slug -> id mapping
        using the metadata.source_type hint.
        """
        nodes = [
            {
                "id": "resource:webpage_alpha",
                "type": "resource",
                "slug": "webpage_alpha",
                "label": "Alpha",
                "metadata": {"source_type": "webpage"},
            },
        ]
        topics = {"webpage:alpha": {"rag-retrieval"}}
        views = build_resource_views(
            resources=nodes, resource_topics=topics, resource_concepts={}
        )
        assert len(views) == 1
        assert views[0]["id"] == "webpage:alpha"
        assert views[0]["source_type"] == "webpage"
        assert views[0]["topics"] == {"rag-retrieval"}


# -----------------------------------------------------------------------------
# Smoke: builder pipeline emits valid graph
# -----------------------------------------------------------------------------


class TestBuildPipelineAcceptsRelationshipEdges:
    def test_build_pipeline_produces_valid_graph(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        records = [
            _make_record(
                tmp_path,
                resource_id="webpage:sm-a",
                title="RAG intro",
                tags=["rag"],
            ),
            _make_record(
                tmp_path,
                resource_id="webpage:sm-b",
                title="RAG advanced with FAISS",
                tags=["rag"],
            ),
        ]
        graph = _build(tmp_path, records=records)
        issues = validate_graph(graph)
        # No relationship-edge-specific errors.
        bad_codes = [
            code for _sev, code, _msg in issues
            if code in {
                "relationship_endpoint_not_resource",
                "self_relationship_edge",
            }
        ]
        assert bad_codes == [], (
            f"Unexpected relationship-edge validator issues: "
            f"{[(s, c, m) for s, c, m in issues if c in {'relationship_endpoint_not_resource', 'self_relationship_edge'}]}"
        )
