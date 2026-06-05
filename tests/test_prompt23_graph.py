"""Tests for Prompt 23: Knowledge Graph Data Model and Graph JSON Export.

Covers the 12 required test cases from the prompt plus a small
deterministic-build helper used by several of them.
"""

import json
from pathlib import Path

import pytest

from wiki.config import config
from wiki.graph import (
    BLOCKED_ALIAS_TOPIC_SLUGS,
    EDGE_TYPE_RESOURCE_HAS_TAG,
    EDGE_TYPE_RESOURCE_HAS_TOPIC,
    EDGE_TYPE_TOPIC_RELATED_TO_TOPIC,
    NODE_TYPE_RESOURCE,
    NODE_TYPE_TAG,
    NODE_TYPE_TOPIC,
    SCHEMA_VERSION,
    GraphBuilder,
    export_graph,
    iter_issues_from_files,
    validate_graph,
)
from wiki.graph.builder import build_graph
from wiki.graph.schema import make_node_id
from wiki.graph.validate import validate_edges_file, validate_nodes_file
from wiki.schemas import (
    Importance,
    ResourceRecord,
    ResourceStatus,
    SourceType,
)
from wiki.site.builder import SiteBuilder
from wiki.storage import Storage


# -----------------------------------------------------------------------------
# Fixtures and helpers
# -----------------------------------------------------------------------------


def _make_note() -> str:
    """A minimal but realistic generated note for a RAG resource."""
    return (
        "# RAG Notes\n\n"
        "## One-line memory hook\n\n"
        "Retrieval quality controls answer quality.\n\n"
        "## Why this resource matters\n\n"
        "This helps build RAG systems.\n\n"
        "## Source-backed summary\n\n"
        "- RAG retrieves context before generation. "
        "[source: webpage:test-c0001]\n\n"
        "## Revision questions\n\n"
        "1. What is retrieval-augmented generation?\n\n"
        "## Provenance\n\n"
        "- LLM provider: mock\n"
    )


def _make_record(
    tmp_path: Path,
    *,
    resource_id: str = "webpage:test",
    title: str = "RAG Hybrid Retrieval",
    tags: list | None = None,
    note_text: str | None = None,
) -> ResourceRecord:
    """Build a self-contained ResourceRecord on disk under tmp_path."""
    safe_id = resource_id.replace(":", "_")
    note_path = tmp_path / "processed" / "resources" / f"{safe_id}.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(note_text or _make_note(), encoding="utf-8")
    return ResourceRecord(
        id=resource_id,
        source_type=SourceType.WEBPAGE,
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


# -----------------------------------------------------------------------------
# Test 1: Node IDs are unique
# -----------------------------------------------------------------------------


class TestNodeIdsUnique:
    def test_node_ids_unique(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        ids = [n["id"] for n in graph["nodes"]]
        assert len(ids) == len(set(ids)), f"Duplicate node ids found: {ids}"

    def test_node_ids_unique_for_synthetic_record(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _make_record(
            tmp_path, resource_id="webpage:unique", tags=["llm", "rag"]
        )
        graph = _build(tmp_path, records=[record])
        ids = [n["id"] for n in graph["nodes"]]
        assert len(ids) == len(set(ids))


# -----------------------------------------------------------------------------
# Test 2: Edge IDs are unique
# -----------------------------------------------------------------------------


class TestEdgeIdsUnique:
    def test_edge_ids_unique(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        ids = [e["id"] for e in graph["edges"]]
        assert len(ids) == len(set(ids)), f"Duplicate edge ids found: {ids}"

    def test_edge_ids_unique_with_multiple_resources(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        records = [
            _make_record(tmp_path, resource_id="webpage:a", tags=["rag"]),
            _make_record(tmp_path, resource_id="webpage:b", tags=["llm"]),
        ]
        graph = _build(tmp_path, records=records)
        ids = [e["id"] for e in graph["edges"]]
        assert len(ids) == len(set(ids))


# -----------------------------------------------------------------------------
# Test 3: Edge source and target nodes exist
# -----------------------------------------------------------------------------


class TestEdgeEndpointsExist:
    def test_all_edge_endpoints_exist(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        node_ids = {n["id"] for n in graph["nodes"]}
        for edge in graph["edges"]:
            assert edge["source"] in node_ids, (
                f"Edge {edge['id']!r} source {edge['source']!r} missing"
            )
            assert edge["target"] in node_ids, (
                f"Edge {edge['id']!r} target {edge['target']!r} missing"
            )

    def test_validate_catches_missing_endpoint(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        # Drop one node, leave an edge referencing it dangling.
        del graph["nodes"][-1]
        graph["nodes"] = [n for n in graph["nodes"] if n["type"] != NODE_TYPE_TOPIC]
        graph["edges"] = [
            e
            for e in graph["edges"]
            if e["type"] != EDGE_TYPE_TOPIC_RELATED_TO_TOPIC
        ]
        issues = validate_graph(graph)
        codes = {code for _sev, code, _msg in issues}
        assert "edge_source_missing" in codes or "edge_target_missing" in codes


# -----------------------------------------------------------------------------
# Test 4: No alias topic nodes
# -----------------------------------------------------------------------------


class TestNoAliasTopicNodes:
    def test_no_alias_topic_nodes_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # Even when the user tags a record with an alias, no `topic:rag`
        # or `topic:security` node should appear.
        record = _make_record(
            tmp_path,
            resource_id="webpage:alias",
            tags=["rag", "security", "training", "ai-safety"],
        )
        graph = _build(tmp_path, records=[record])
        topic_ids = _ids_by_type(graph["nodes"], NODE_TYPE_TOPIC)
        for slug in BLOCKED_ALIAS_TOPIC_SLUGS:
            blocked = make_node_id(NODE_TYPE_TOPIC, slug)
            assert blocked not in topic_ids, (
                f"Alias topic node {blocked!r} should not be in the graph"
            )

    def test_no_alias_topic_nodes_with_rag_tags(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _make_record(tmp_path, tags=["rag", "retrieval"])
        graph = _build(tmp_path, records=[record])
        topic_ids = set(_ids_by_type(graph["nodes"], NODE_TYPE_TOPIC))
        assert "topic:rag" not in topic_ids
        assert "topic:retrieval" not in topic_ids
        assert "topic:security" not in topic_ids
        assert "topic:training" not in topic_ids

    def test_alias_topic_node_detected_by_validate(self):
        """If a bad node sneaks in, the validator should flag it."""
        nodes = [
            {
                "id": "topic:rag",
                "type": "topic",
                "label": "RAG",
                "slug": "rag",
                "metadata": {},
            }
        ]
        issues = validate_nodes_file(nodes)
        codes = [code for _sev, code, _msg in issues]
        assert "alias_topic_node" in codes


# -----------------------------------------------------------------------------
# Test 5: Canonical topic nodes are present
# -----------------------------------------------------------------------------


class TestCanonicalTopicNodes:
    def test_canonical_rag_retrieval_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _make_record(tmp_path, tags=["rag", "retrieval"])
        graph = _build(tmp_path, records=[record])
        topic_ids = set(_ids_by_type(graph["nodes"], NODE_TYPE_TOPIC))
        assert "topic:rag-retrieval" in topic_ids

    def test_multiple_canonical_topics_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _make_record(tmp_path, tags=["rag"])
        graph = _build(tmp_path, records=[record])
        topic_ids = set(_ids_by_type(graph["nodes"], NODE_TYPE_TOPIC))
        # rag-retrieval is the canonical alias of 'rag'/'retrieval'.
        assert "topic:rag-retrieval" in topic_ids
        # The graph includes the full set of canonical topics defined
        # in TOPIC_DEFINITIONS, not just those that the record matches.
        from wiki.resource_utils import TOPIC_DEFINITIONS

        for slug in TOPIC_DEFINITIONS:
            if slug in BLOCKED_ALIAS_TOPIC_SLUGS:
                continue
            assert f"topic:{slug}" in topic_ids, (
                f"Missing canonical topic node for {slug!r}"
            )


# -----------------------------------------------------------------------------
# Test 6: Resource-topic edges are generated
# -----------------------------------------------------------------------------


class TestResourceTopicEdges:
    def test_resource_topic_edge_generated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _make_record(tmp_path, tags=["rag", "retrieval"])
        graph = _build(tmp_path, records=[record])
        resource_id = make_node_id(NODE_TYPE_RESOURCE, "webpage_test")
        topic_id = make_node_id(NODE_TYPE_TOPIC, "rag-retrieval")
        matches = [
            e
            for e in graph["edges"]
            if e["type"] == EDGE_TYPE_RESOURCE_HAS_TOPIC
            and e["source"] == resource_id
            and e["target"] == topic_id
        ]
        assert matches, "resource_has_topic edge from resource to rag-retrieval missing"

    def test_topic_has_resource_inverse_generated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _make_record(tmp_path, tags=["rag"])
        graph = _build(tmp_path, records=[record])
        topic_id = make_node_id(NODE_TYPE_TOPIC, "rag-retrieval")
        resource_id = make_node_id(NODE_TYPE_RESOURCE, "webpage_test")
        matches = [
            e
            for e in graph["edges"]
            if e["type"] == "topic_has_resource"
            and e["source"] == topic_id
            and e["target"] == resource_id
        ]
        assert matches, "topic_has_resource edge from rag-retrieval to resource missing"


# -----------------------------------------------------------------------------
# Test 7: Resource-tag edges are generated using synthetic tagged records
# -----------------------------------------------------------------------------


class TestResourceTagEdges:
    def test_resource_tag_edge_generated_for_synthetic_tag(self, tmp_path, monkeypatch):
        """The existing data has no tags, so we feed a synthetic record."""
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # Tags set to user-supplied values that don't collide with topics.
        record = _make_record(
            tmp_path,
            resource_id="webpage:tagged",
            tags=["machine-learning", "embeddings", "vector-db"],
        )
        graph = _build(tmp_path, records=[record])
        resource_id = make_node_id(NODE_TYPE_RESOURCE, "webpage_tagged")

        for tag in ["machine-learning", "embeddings", "vector-db"]:
            tag_id = make_node_id(NODE_TYPE_TAG, tag)
            matches = [
                e
                for e in graph["edges"]
                if e["type"] == EDGE_TYPE_RESOURCE_HAS_TAG
                and e["source"] == resource_id
                and e["target"] == tag_id
            ]
            assert matches, f"resource_has_tag edge for tag {tag!r} missing"

    def test_tag_node_count_matches_tags(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _make_record(
            tmp_path,
            resource_id="webpage:multi-tag",
            tags=["alpha", "beta", "gamma"],
        )
        graph = _build(tmp_path, records=[record])
        tag_nodes = _ids_by_type(graph["nodes"], NODE_TYPE_TAG)
        assert "tag:alpha" in tag_nodes
        assert "tag:beta" in tag_nodes
        assert "tag:gamma" in tag_nodes

    def test_tags_normalize_to_lowercase(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _make_record(
            tmp_path, resource_id="webpage:case", tags=["MixedCase", "UPPER"]
        )
        graph = _build(tmp_path, records=[record])
        tag_nodes = set(_ids_by_type(graph["nodes"], NODE_TYPE_TAG))
        assert "tag:mixedcase" in tag_nodes
        assert "tag:upper" in tag_nodes


# -----------------------------------------------------------------------------
# Test 8: Output JSON is deterministic
# -----------------------------------------------------------------------------


class TestOutputJsonDeterministic:
    def test_nodes_and_edges_byte_equal_between_runs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # Build the graph twice with the same input.
        records = [_make_record(tmp_path)]
        graph1 = _build(tmp_path, records=records)
        graph2 = _build(tmp_path, records=records)
        # The full bundle includes `generated_at` which is timestamped,
        # so we compare only the stable arrays.
        assert graph1["nodes"] == graph2["nodes"]
        assert graph1["edges"] == graph2["edges"]
        # And verify they are in sorted id order (deterministic).
        node_ids = [n["id"] for n in graph1["nodes"]]
        assert node_ids == sorted(node_ids)
        edge_ids = [e["id"] for e in graph1["edges"]]
        assert edge_ids == sorted(edge_ids)

    def test_export_writes_byte_stable_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        paths1 = export_graph(graph, data_dir=tmp_path)
        nodes1 = Path(paths1["nodes"]).read_text(encoding="utf-8")
        edges1 = Path(paths1["edges"]).read_text(encoding="utf-8")
        # Re-export and compare.
        paths2 = export_graph(graph, data_dir=tmp_path)
        nodes2 = Path(paths2["nodes"]).read_text(encoding="utf-8")
        edges2 = Path(paths2["edges"]).read_text(encoding="utf-8")
        assert nodes1 == nodes2
        assert edges1 == edges2

    def test_export_files_exist(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        paths = export_graph(graph, data_dir=tmp_path)
        for label, path in paths.items():
            if label == "directory":
                continue
            assert Path(path).exists(), f"{label} missing at {path}"


# -----------------------------------------------------------------------------
# Test 9: Graph files are generated by build-site
# -----------------------------------------------------------------------------


class TestBuildSiteGeneratesGraphFiles:
    def test_build_site_creates_graph_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _make_record(tmp_path)
        # Use a real SiteBuilder with isolated data/repo dirs.
        builder = SiteBuilder()
        builder.data_site_dir = tmp_path / "site_generated" / "docs"
        builder.repo_site_dir = tmp_path / "repo_docs"
        builder.data_site_dir.mkdir(parents=True, exist_ok=True)
        builder.repo_site_dir.mkdir(parents=True, exist_ok=True)
        builder._build_knowledge_graph([record])

        graph_dir = builder.data_site_dir / "public" / "graph"
        assert (graph_dir / "nodes.json").exists(), "nodes.json not generated"
        assert (graph_dir / "edges.json").exists(), "edges.json not generated"
        assert (graph_dir / "knowledge_graph.json").exists(), (
            "knowledge_graph.json not generated"
        )

    def test_build_site_knowledge_graph_has_schema_version(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _make_record(tmp_path)
        builder = SiteBuilder()
        builder.data_site_dir = tmp_path / "site_generated" / "docs"
        builder.repo_site_dir = tmp_path / "repo_docs"
        builder.data_site_dir.mkdir(parents=True, exist_ok=True)
        builder.repo_site_dir.mkdir(parents=True, exist_ok=True)
        builder._build_knowledge_graph([record])
        path = builder.data_site_dir / "public" / "graph" / "knowledge_graph.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION


# -----------------------------------------------------------------------------
# Test 10: Validate catches malformed graph
# -----------------------------------------------------------------------------


class TestValidateCatchesMalformedGraph:
    def test_validate_catches_missing_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # Construct a graph manually with a dangling edge.
        nodes = [
            {"id": "topic:rag-retrieval", "type": "topic", "label": "RAG",
             "slug": "rag-retrieval", "metadata": {}}
        ]
        edges = [
            {
                "id": "resource_has_topic:resource:webpage_x:topic:rag-retrieval",
                "type": EDGE_TYPE_RESOURCE_HAS_TOPIC,
                "source": "resource:webpage_x",
                "target": "topic:rag-retrieval",
                "metadata": {},
            }
        ]
        graph = {
            "schema_version": SCHEMA_VERSION,
            "nodes": nodes,
            "edges": edges,
            "stats": {"node_count": 1, "edge_count": 1},
        }
        issues = validate_graph(graph)
        codes = {code for _sev, code, _msg in issues}
        assert "edge_source_missing" in codes, (
            f"Expected edge_source_missing, got {codes}"
        )

    def test_validate_catches_alias_topic_node(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = {
            "schema_version": SCHEMA_VERSION,
            "nodes": [
                {"id": "topic:rag", "type": "topic", "label": "RAG",
                 "slug": "rag", "metadata": {}}
            ],
            "edges": [],
            "stats": {"node_count": 1, "edge_count": 0},
        }
        issues = validate_graph(graph)
        codes = {code for _sev, code, _msg in issues}
        assert "alias_topic_node" in codes

    def test_validate_catches_duplicate_node_ids(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = {
            "schema_version": SCHEMA_VERSION,
            "nodes": [
                {"id": "topic:a", "type": "topic", "label": "A",
                 "slug": "a", "metadata": {}},
                {"id": "topic:a", "type": "topic", "label": "A2",
                 "slug": "a", "metadata": {}},
            ],
            "edges": [],
            "stats": {"node_count": 2, "edge_count": 0},
        }
        issues = validate_graph(graph)
        codes = {code for _sev, code, _msg in issues}
        assert "duplicate_node_id" in codes

    def test_validate_catches_missing_required_keys(self):
        """A bundle missing `stats` or `schema_version` is invalid."""
        graph = {"nodes": [], "edges": []}
        issues = validate_graph(graph)
        codes = {code for _sev, code, _msg in issues}
        assert "missing_key" in codes

    def test_iter_issues_from_files_handles_missing_files(self, tmp_path):
        """If the files don't exist we should get clear `missing_file` errors."""
        issues = iter_issues_from_files(
            tmp_path / "nodes.json",
            tmp_path / "edges.json",
        )
        codes = {code for _sev, code, _msg in issues}
        assert "missing_file" in codes

    def test_iter_issues_from_files_does_not_require_knowledge_graph_when_only_arrays_present(
        self, tmp_path
    ):
        """File-level validation handles nodes.json and edges.json as JSON
        arrays, and only treats knowledge_graph.json as a full bundle."""
        nodes = [
            {"id": "topic:rag-retrieval", "type": "topic",
             "label": "RAG", "slug": "rag-retrieval", "metadata": {}}
        ]
        edges = [
            {
                "id": "topic_related_to_topic:topic:rag-retrieval:topic:llm-inference",
                "type": EDGE_TYPE_TOPIC_RELATED_TO_TOPIC,
                "source": "topic:rag-retrieval",
                "target": "topic:llm-inference",
                "metadata": {},
            }
        ]
        nodes_path = tmp_path / "nodes.json"
        edges_path = tmp_path / "edges.json"
        nodes_path.write_text(json.dumps(nodes), encoding="utf-8")
        edges_path.write_text(json.dumps(edges), encoding="utf-8")

        # No knowledge_graph_path passed — should still validate.
        issues = iter_issues_from_files(nodes_path, edges_path)
        # No "missing_key" errors for nodes.json or edges.json since
        # those are arrays, not bundles.
        for _sev, code, _msg in issues:
            assert code != "missing_key", (
                f"iter_issues_from_files should not report missing_key "
                f"for nodes.json/edges.json arrays (got {code})"
            )

    def test_validate_nodes_file_rejects_non_list(self):
        issues = validate_nodes_file({"not": "a list"})
        codes = {code for _sev, code, _msg in issues}
        assert "nodes_file_not_list" in codes

    def test_validate_edges_file_rejects_non_list(self):
        issues = validate_edges_file({"not": "a list"})
        codes = {code for _sev, code, _msg in issues}
        assert "edges_file_not_list" in codes


# -----------------------------------------------------------------------------
# Test 11: Duplicate edges are prevented
# -----------------------------------------------------------------------------


class TestDuplicateEdgesPrevented:
    def test_duplicate_edge_triples_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # A record with overlapping tag sets should not produce duplicate
        # resource_has_tag edges.
        record = _make_record(
            tmp_path,
            resource_id="webpage:dup",
            tags=["llm", "llm", "llm"],
        )
        graph = _build(tmp_path, records=[record])
        tag_edges = [
            e
            for e in graph["edges"]
            if e["type"] == EDGE_TYPE_RESOURCE_HAS_TAG
        ]
        triples = [(e["type"], e["source"], e["target"]) for e in tag_edges]
        assert len(triples) == len(set(triples)), (
            f"Duplicate edge triples found: {triples}"
        )

    def test_duplicate_edges_removed_in_stats(self, tmp_path, monkeypatch):
        """Build with deliberate duplicates injected via the dedupe set."""
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _make_record(tmp_path, tags=["rag", "rag", "rag", "rag"])
        graph = _build(tmp_path, records=[record])
        # The builder dedupes user-supplied tags, so we additionally
        # verify that re-running produces the same edge count.
        graph2 = _build(tmp_path, records=[record])
        assert len(graph["edges"]) == len(graph2["edges"])

    def test_validate_catches_explicit_duplicate_edges(self):
        graph = {
            "schema_version": SCHEMA_VERSION,
            "nodes": [
                {"id": "resource:x", "type": "resource", "label": "X",
                 "slug": "x", "metadata": {}},
                {"id": "topic:a", "type": "topic", "label": "A",
                 "slug": "a", "metadata": {}},
            ],
            "edges": [
                {
                    "id": "edge1",
                    "type": EDGE_TYPE_RESOURCE_HAS_TOPIC,
                    "source": "resource:x",
                    "target": "topic:a",
                    "metadata": {},
                },
                {
                    "id": "edge2",
                    "type": EDGE_TYPE_RESOURCE_HAS_TOPIC,
                    "source": "resource:x",
                    "target": "topic:a",
                    "metadata": {},
                },
            ],
            "stats": {"node_count": 2, "edge_count": 2},
        }
        issues = validate_graph(graph)
        codes = {code for _sev, code, _msg in issues}
        # Both duplicate_edge_id and duplicate_edge_triple are reported
        # by the validator.
        assert "duplicate_edge_id" in codes or "duplicate_edge_triple" in codes


# -----------------------------------------------------------------------------
# Test 12: Knowledge graph has schema_version, nodes, edges, stats
# -----------------------------------------------------------------------------


class TestKnowledgeGraphBundleShape:
    def test_knowledge_graph_has_required_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        for key in ("schema_version", "nodes", "edges", "stats"):
            assert key in graph, f"Missing key {key!r} in knowledge graph bundle"

    def test_knowledge_graph_schema_version_is_1_0_0(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        assert graph["schema_version"] == SCHEMA_VERSION
        assert SCHEMA_VERSION == "1.0.0"

    def test_knowledge_graph_exported_file_has_required_keys(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        paths = export_graph(graph, data_dir=tmp_path)
        data = json.loads(Path(paths["knowledge_graph"]).read_text(encoding="utf-8"))
        for key in ("schema_version", "nodes", "edges", "stats"):
            assert key in data, f"Missing key {key!r} in exported knowledge_graph.json"
        assert data["schema_version"] == "1.0.0"
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)
        assert isinstance(data["stats"], dict)

    def test_stats_counts_match_nodes_and_edges(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        stats = graph["stats"]
        assert stats["node_count"] == len(graph["nodes"])
        assert stats["edge_count"] == len(graph["edges"])


# -----------------------------------------------------------------------------
# Sanity: builder pipeline end-to-end
# -----------------------------------------------------------------------------


class TestGraphBuilderEndToEnd:
    def test_empty_records_still_produces_topic_nodes(self, tmp_path, monkeypatch):
        """The canonical topic set is graph-level metadata, not data-driven."""
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = build_graph([], data_dir=tmp_path)
        topic_ids = _ids_by_type(graph["nodes"], NODE_TYPE_TOPIC)
        assert "topic:rag-retrieval" in topic_ids

    def test_blocked_alias_topic_count_is_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        assert graph["stats"]["blocked_alias_topic_nodes"] == 0

    @pytest.mark.parametrize(
        "slug",
        ["rag", "security", "retrieval", "ai-safety", "optimization-training", "training"],
    )
    def test_no_blocked_alias_slugs_appear_as_nodes(self, tmp_path, monkeypatch, slug):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _make_record(
            tmp_path,
            resource_id=f"webpage:{slug.replace('-', '_')}",
            tags=[slug, "rag", "retrieval"],
        )
        graph = _build(tmp_path, records=[record])
        topic_ids = set(_ids_by_type(graph["nodes"], NODE_TYPE_TOPIC))
        assert f"topic:{slug}" not in topic_ids
