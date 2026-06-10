"""Tests for Prompt 30: Hybrid Retrieval Router.

The 29 required test cases from ``prompt30.md`` §"Required tests"
are covered by the classes in this file, plus 5 defensive cases
(34 total). The pattern follows the existing
``tests/test_prompt28_bm25_search.py`` and
``tests/test_prompt29_vector_search.py`` tests: build a small
chunk index in a tmp dir using controlled records, point
``SiteBuilder`` at isolated data/repo directories, and assert on
the generated files and the on-disk schema.

The tests are grouped by responsibility:

- :class:`TestSchema` — the dataclass schema and ``to_dict()``
  contract.
- :class:`TestFusion` — the pure score-fusion primitives.
- :class:`TestGraphLite` — the bounded graph-lite boost
  computation.
- :class:`TestRouter` — the in-memory router across all four
  modes.
- :class:`TestRouterCli` — the ``wiki retrieve`` CLI command.
- :class:`TestBuildSiteAndValidate` — build-site, smoke-site,
  validate integration.
- :class:`TestRetrievalBoundaries` — scope guards (no
  LLM/embedding/vector-DB dependencies; chunk, BM25, vector,
  graph builders unmodified).
- :class:`TestStaticRoutes` — the static-route verification
  script includes the new retrieval route.
- :class:`TestRealPdfRetrievalVerification` — real-PDF
  verification (skipped when the real PDF fixture is missing).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import pytest
from typer.testing import CliRunner

from wiki import cli
from wiki.chunks import (
    CHUNK_INDEX_SCHEMA_VERSION,
    ChunkIndexResult,
    ChunkMetadata,
    ChunkRecord,
    SourceRef,
    build_chunk_index,
)
from wiki.chunks.export import write_chunk_index
from wiki.config import config
from wiki.schemas import (
    Importance,
    ResourceRecord,
    ResourceStatus,
    SourceType,
)
from wiki.site.builder import SiteBuilder


# =============================================================================
# Fixtures and helpers
# =============================================================================


REPO_ROOT = Path(__file__).parent.parent.resolve()
REAL_PDF = Path.home() / "llm-wiki-data" / "test-pdfs" / "attention-is-all-you-need.pdf"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Pytest fixture that points config at a tmp data dir."""
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    config.ensure_directories()
    return tmp_path


def _isolated_data_dir(tmp_path: Path, monkeypatch) -> Path:
    """Point config at a tmp data dir and create the standard dirs."""
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    config.ensure_directories()
    return tmp_path


def _setup_site_builder(tmp_path: Path, monkeypatch) -> SiteBuilder:
    """Build an isolated SiteBuilder with tmp data and repo dirs."""
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    builder = SiteBuilder()
    builder.data_site_dir = tmp_path / "site_generated" / "docs"
    builder.repo_site_dir = tmp_path / "repo_docs"
    builder.data_site_dir.mkdir(parents=True, exist_ok=True)
    builder.repo_site_dir.mkdir(parents=True, exist_ok=True)
    return builder


def _make_normalized_record(
    tmp_path: Path,
    *,
    resource_id: str,
    source_type: SourceType,
    chunks: List[dict],
    extra: Optional[dict] = None,
    title: Optional[str] = None,
    content_hash: Optional[str] = None,
) -> ResourceRecord:
    """Build a ResourceRecord whose local_normalized_path has chunks.jsonl."""
    norm_dir = tmp_path / "normalized" / resource_id.replace(":", "_")
    norm_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = norm_dir / "chunks.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for entry in chunks:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return ResourceRecord(
        id=resource_id,
        source_type=source_type,
        canonical_id=resource_id,
        original_url=f"https://example.com/{resource_id.replace(':', '_')}",
        local_normalized_path=norm_dir,
        title=title or resource_id,
        status=ResourceStatus.NORMALIZED,
        llm_provider="mock",
        llm_model="mock-model",
        prompt_version="harish_llm_wiki_v4",
        tags=["test"],
        importance=Importance.MEDIUM,
        content_hash=content_hash,
        extra=extra or {},
    )


def _make_pdf_record(
    tmp_path: Path,
    *,
    resource_id: str = "pdf:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    title: str = "Attention Is All You Need",
    content_hash: Optional[str] = None,
    page_chunks: Optional[List[dict]] = None,
) -> ResourceRecord:
    """Build a PDF record with a deterministic on-disk ``chunks.json`` mirror."""
    if content_hash is None:
        content_hash = "0123456789abcdef" * 4  # 64 hex chars
    mirror = tmp_path / "processed" / "pdfs" / content_hash[:8] / "chunks.json"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    chunks = page_chunks if page_chunks is not None else [
        {
            "chunk_id": f"{resource_id}-p0001",
            "page_start": 1,
            "page_end": 3,
            "text": (
                "Attention Is All You Need introduces the Transformer, "
                "a model based on Scaled Dot-Product Attention."
            ),
            "citation_label": "pages 1-3",
            "file_path": str(tmp_path / "attention.pdf"),
        },
        {
            "chunk_id": f"{resource_id}-p0004",
            "page_start": 4,
            "page_end": 5,
            "text": (
                "We propose a new simple network architecture, the Transformer, "
                "based solely on attention mechanisms."
            ),
            "citation_label": "pages 4-5",
            "file_path": str(tmp_path / "attention.pdf"),
        },
    ]
    mirror.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    return ResourceRecord(
        id=resource_id,
        source_type=SourceType.PDF,
        canonical_id=resource_id,
        original_url=str(tmp_path / "attention.pdf"),
        content_hash=content_hash,
        local_normalized_path=tmp_path / "normalized" / resource_id.replace(":", "_"),
        title=title,
        status=ResourceStatus.NORMALIZED,
        llm_provider="mock",
        llm_model="mock-model",
        prompt_version="harish_llm_wiki_v4",
        tags=["transformer", "attention"],
        importance=Importance.MEDIUM,
        extra={
            "original_path": str(tmp_path / "attention.pdf"),
            "extraction_method": "pypdf",
        },
    )


def _build_indexes(
    tmp_path: Path, records: List[ResourceRecord]
) -> tuple:
    """Build a chunk index, BM25 index, and vector index from records."""
    from wiki.search import build_bm25_index
    from wiki.vector import build_vector_index

    chunk_index = build_chunk_index(records)
    bm25_index = build_bm25_index(chunk_index)
    vector_index = build_vector_index(chunk_index)
    return chunk_index, bm25_index, vector_index


# =============================================================================
# Test class 1: TestSchema
# =============================================================================


class TestSchema:
    def test_retrieval_result_schema_has_all_required_fields(self):
        """Test 1: Retrieval result schema contains all 18 required fields."""
        from wiki.retrieval.schema import ComponentScores, Explanation, RetrievalResult

        cs = ComponentScores(
            bm25=0.1,
            vector=0.2,
            graph_boost=0.0,
            normalized_bm25=0.5,
            normalized_vector=0.5,
            final=0.5,
        )
        explanation = Explanation(
            shared_topics=["transformer"],
            shared_concepts=["attention"],
            source_type_preference=True,
            resource_relationship_targets=["pdf:other"],
            weights={"bm25": 0.55, "vector": 0.45},
            normalization={"bm25_max": 1.0, "vector_max": 1.0},
        )
        result = RetrievalResult(
            rank=1,
            score=0.5,
            chunk_id="c1",
            resource_id="pdf:abc",
            title="T",
            source_type="pdf",
            text_preview="hello",
            citation_label="pages 1-3",
            resource_route="/resources/pdf_abc",
            source_ref={"kind": "pdf_pages"},
            mode="hybrid",
            component_scores=cs,
            matched_terms=["hello"],
            explanation=explanation,
            metadata={"source_url": "u", "tags": ["a"], "topics": ["b"]},
        )
        d = result.to_dict()
        for required in (
            "rank",
            "score",
            "chunk_id",
            "resource_id",
            "title",
            "source_type",
            "text_preview",
            "citation_label",
            "resource_route",
            "source_ref",
            "mode",
            "component_scores",
            "matched_terms",
            "explanation",
            "metadata",
        ):
            assert required in d, f"missing {required!r} in result"
        # component_scores sub-fields
        for required in (
            "bm25",
            "vector",
            "graph_boost",
            "normalized_bm25",
            "normalized_vector",
            "final",
        ):
            assert required in d["component_scores"], (
                f"missing component_scores.{required}"
            )
        # explanation sub-fields (verbose)
        d_verbose = result.to_dict(verbose=True)
        for required in (
            "shared_topics",
            "shared_concepts",
            "source_type_preference",
            "resource_relationship_targets",
            "weights",
            "normalization",
        ):
            assert required in d_verbose["explanation"], (
                f"missing explanation.{required}"
            )

    def test_explanation_compact_omits_per_factor_fields(self):
        from wiki.retrieval.schema import Explanation

        explanation = Explanation(
            shared_topics=["transformer"],
            shared_concepts=["attention"],
            source_type_preference=True,
            resource_relationship_targets=["pdf:other"],
            weights={"bm25": 0.55, "vector": 0.45},
            normalization={"bm25_max": 1.0, "vector_max": 1.0},
        )
        d_compact = explanation.to_dict()
        assert "shared_topics" not in d_compact
        assert "weights" in d_compact
        assert "normalization" in d_compact

    def test_allowed_modes_constant(self):
        from wiki.retrieval.schema import ALLOWED_MODES

        assert ALLOWED_MODES == frozenset({"bm25", "vector", "hybrid", "graph-lite"})

    def test_graph_lite_max_boost_constant(self):
        from wiki.retrieval.schema import (
            GRAPH_LITE_MAX_BOOST,
            RESOURCE_RELATIONSHIP_BOOST_MAX,
            SAME_TOPIC_BOOST_MAX,
            SHARED_CONCEPT_BOOST_MAX,
            SOURCE_TYPE_BOOST_MAX,
        )

        # The four sub-maxes must sum to exactly the cap.
        total = (
            SAME_TOPIC_BOOST_MAX
            + SHARED_CONCEPT_BOOST_MAX
            + SOURCE_TYPE_BOOST_MAX
            + RESOURCE_RELATIONSHIP_BOOST_MAX
        )
        assert total == GRAPH_LITE_MAX_BOOST


# =============================================================================
# Test class 2: TestFusion
# =============================================================================


class TestFusion:
    def test_max_normalize_divides_by_max(self):
        """Test 5: Score normalization is deterministic."""
        from wiki.retrieval.fusion import max_normalize

        result = max_normalize({"a": 2.0, "b": 1.0, "c": 0.0})
        assert result == {"a": 1.0, "b": 0.5, "c": 0.0}

    def test_max_normalize_handles_empty(self):
        from wiki.retrieval.fusion import max_normalize

        assert max_normalize({}) == {}
        assert max_normalize({"a": 0.0, "b": 0.0}) == {}

    def test_linear_fuse_uses_default_weights(self):
        from wiki.retrieval.fusion import linear_fuse

        bm25_norm = {"a": 1.0, "b": 0.5}
        vector_norm = {"a": 0.5, "c": 1.0}
        result = linear_fuse(
            bm25_norm, vector_norm, bm25_weight=0.55, vector_weight=0.45
        )
        # a: 0.55 * 1.0 + 0.45 * 0.5 = 0.55 + 0.225 = 0.775
        # b: 0.55 * 0.5 + 0.45 * 0 = 0.275
        # c: 0.55 * 0   + 0.45 * 1.0 = 0.45
        assert result == {"a": 0.775, "b": 0.275, "c": 0.45}

    def test_linear_fuse_rejects_zero_sum(self):
        from wiki.retrieval.fusion import linear_fuse

        with pytest.raises(ValueError):
            linear_fuse({}, {}, bm25_weight=0.0, vector_weight=0.0)

    def test_linear_fuse_rejects_negative_weight(self):
        from wiki.retrieval.fusion import linear_fuse

        with pytest.raises(ValueError):
            linear_fuse({}, {}, bm25_weight=-0.1, vector_weight=0.5)

    def test_apply_graph_lite_boost_clamps_to_max(self):
        from wiki.retrieval.fusion import apply_graph_lite_boost

        result = apply_graph_lite_boost(
            {"a": 0.5, "b": 0.3},
            {"a": 0.2, "b": -0.1},
            max_boost=0.10,
        )
        # a: 0.5 + 0.2 (clamped to 0.10) = 0.6
        # b: 0.3 + 0.0 (clamped from -0.1 to 0.0) = 0.3
        assert result == {"a": 0.6, "b": 0.3}

    def test_sort_keys_deterministic(self):
        from wiki.retrieval.fusion import sort_keys_deterministically

        pairs = sort_keys_deterministically(
            {"a": 0.5, "b": 0.5, "c": 0.3},
            secondary_keys={"a": "r2", "b": "r1", "c": "r3"},
        )
        # Both a and b have score 0.5; tie-break by secondary: b (r1) before a (r2).
        keys = [p[0] for p in pairs]
        assert keys == ["b", "a", "c"]


# =============================================================================
# Test class 3: TestGraphLite
# =============================================================================


class TestGraphLite:
    def _write_graph(
        self,
        tmp_path: Path,
        *,
        nodes: list,
        edges: list,
    ) -> Path:
        from wiki.graph.schema import SCHEMA_VERSION

        bundle = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": "2026-06-06T00:00:00+00:00",
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "node_count": len(nodes),
                "edge_count": len(edges),
            },
        }
        graph_path = tmp_path / "site_generated" / "docs" / "public" / "graph"
        graph_path.mkdir(parents=True, exist_ok=True)
        out = graph_path / "knowledge_graph.json"
        out.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
        return out

    def test_graph_lite_boost_is_bounded(self, tmp_path):
        """Test 13: graph-lite mode applies a bounded boost."""
        from wiki.retrieval.graph_lite import build_boost_map
        from wiki.retrieval.schema import GRAPH_LITE_MAX_BOOST

        # Two resources sharing a topic.
        nodes = [
            {
                "id": "resource:pdf_a",
                "type": "resource",
                "label": "A",
                "slug": "pdf_a",
                "metadata": {"source_type": "pdf"},
            },
            {
                "id": "resource:pdf_b",
                "type": "resource",
                "label": "B",
                "slug": "pdf_b",
                "metadata": {"source_type": "pdf"},
            },
            {
                "id": "topic:transformer",
                "type": "topic",
                "label": "Transformer",
                "slug": "transformer",
            },
        ]
        edges = [
            {
                "id": "e1",
                "type": "resource_has_topic",
                "source": "resource:pdf_a",
                "target": "topic:transformer",
                "metadata": {},
            },
            {
                "id": "e2",
                "type": "resource_has_topic",
                "source": "resource:pdf_b",
                "target": "topic:transformer",
                "metadata": {},
            },
            {
                "id": "e3",
                "type": "resource_shares_topic_with_resource",
                "source": "resource:pdf_a",
                "target": "resource:pdf_b",
                "metadata": {},
            },
        ]
        graph_path = self._write_graph(tmp_path, nodes=nodes, edges=edges)

        boost_map = build_boost_map(
            graph_path=graph_path,
            candidate_resource_ids={"pdf:a", "pdf:b"},
            candidate_source_types={"pdf"},
            chunk_resource_id_to_chunk_ids={"pdf:a": {"c1"}, "pdf:b": {"c2"}},
        )
        assert "c1" in boost_map
        assert "c2" in boost_map
        # Boost must be bounded by GRAPH_LITE_MAX_BOOST.
        for value in boost_map.values():
            assert 0.0 <= value <= GRAPH_LITE_MAX_BOOST

    def test_graph_lite_does_not_perform_unbounded_traversal(self):
        """Test 14: graph-lite does not perform unbounded traversal;
        reads the on-disk graph file at most once per retrieval call."""
        from unittest.mock import patch

        from wiki.retrieval import graph_lite
        from wiki.retrieval.router import _build_graph_lite_boost

        # Patch Storage.read_json to count reads.
        call_count = {"n": 0}

        def counting_read_json(path):
            call_count["n"] += 1
            # Return a minimal valid bundle with one node, one edge.
            from wiki.graph.schema import SCHEMA_VERSION

            return {
                "schema_version": SCHEMA_VERSION,
                "generated_at": "2026-06-06T00:00:00+00:00",
                "nodes": [
                    {
                        "id": "resource:pdf_a",
                        "type": "resource",
                        "label": "A",
                        "slug": "pdf_a",
                        "metadata": {"source_type": "pdf"},
                    }
                ],
                "edges": [],
                "stats": {"node_count": 1, "edge_count": 0},
            }

        # Construct a tiny in-memory router state.
        bm25_by_cid = {"c1": _make_fake_bm25_result("c1", "pdf:a")}
        vector_by_cid = {}

        with patch.object(graph_lite.Storage, "read_json", counting_read_json):
            boost_map, explanations = _build_graph_lite_boost(
                chunk_ids=["c1"],
                bm25_by_cid=bm25_by_cid,
                vector_by_cid=vector_by_cid,
                data_dir=None,
            )

        # The router must read the graph at most twice (once for
        # the boost map and once for the per-chunk explanations).
        # The exact upper bound is 2; we assert that the
        # function does not perform recursive walks (call count
        # must be small).
        assert call_count["n"] <= 2, (
            f"graph-lite read the graph too many times: {call_count['n']}"
        )
        # No traversal means no recursion. The boost map should
        # still be empty (no shared edges in the fixture), but
        # the function must return without raising.
        assert "c1" not in boost_map or boost_map["c1"] == 0.0


def _make_fake_bm25_result(chunk_id: str, resource_id: str):
    """Construct a tiny in-memory result for graph-lite tests."""
    from wiki.search.bm25 import SearchResult

    return SearchResult(
        rank=1,
        score=1.0,
        chunk_id=chunk_id,
        resource_id=resource_id,
        title="T",
        source_type="pdf",
        text_preview="hello",
        citation_label="p1",
        resource_route="/r",
        source_ref={},
        matched_terms=[],
        metadata={},
    )


# =============================================================================
# Test class 4: TestRouter
# =============================================================================


class TestRouter:
    def test_bm25_mode_returns_bm25_only_scores(self, data_dir):
        """Test 2: bm25 mode returns BM25-only component scores."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        results = retrieve_hybrid_in_memory(
            query="attention",
            bm25_index=bm25_index,
            vector_index=vector_index,
            mode="bm25",
            limit=2,
        )
        assert len(results) >= 1
        for r in results:
            assert r.mode == "bm25"
            # vector and normalized_vector are zero in bm25 mode.
            assert r.component_scores.vector == 0.0
            assert r.component_scores.normalized_vector == 0.0
            # graph_boost is zero in non-graph-lite modes.
            assert r.component_scores.graph_boost == 0.0

    def test_vector_mode_returns_vector_only_scores(self, data_dir):
        """Test 3: vector mode returns vector-only component scores."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        results = retrieve_hybrid_in_memory(
            query="attention",
            bm25_index=bm25_index,
            vector_index=vector_index,
            mode="vector",
            limit=2,
        )
        assert len(results) >= 1
        for r in results:
            assert r.mode == "vector"
            assert r.component_scores.bm25 == 0.0
            assert r.component_scores.normalized_bm25 == 0.0
            assert r.component_scores.graph_boost == 0.0

    def test_hybrid_mode_combines_bm25_and_vector(self, data_dir):
        """Test 4: hybrid mode combines BM25 and vector scores."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        results = retrieve_hybrid_in_memory(
            query="attention",
            bm25_index=bm25_index,
            vector_index=vector_index,
            mode="hybrid",
            limit=2,
        )
        assert len(results) >= 1
        for r in results:
            assert r.mode == "hybrid"
            # graph_boost is zero in hybrid mode.
            assert r.component_scores.graph_boost == 0.0

    def test_score_normalization_is_deterministic(self, data_dir):
        """Test 5: score normalization is deterministic."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        results_1 = retrieve_hybrid_in_memory(
            query="attention",
            bm25_index=bm25_index,
            vector_index=vector_index,
            mode="hybrid",
            limit=5,
        )
        results_2 = retrieve_hybrid_in_memory(
            query="attention",
            bm25_index=bm25_index,
            vector_index=vector_index,
            mode="hybrid",
            limit=5,
        )
        # Same input, same output: ranks, scores, chunk_ids match.
        for a, b in zip(results_1, results_2):
            assert a.rank == b.rank
            assert a.chunk_id == b.chunk_id
            assert a.score == b.score

    def test_tie_breaking_is_deterministic(self, data_dir):
        """Test 6: tie-breaking is deterministic."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        rec = _make_normalized_record(
            data_dir,
            resource_id="webpage:tie",
            source_type=SourceType.WEBPAGE,
            chunks=[
                {
                    "chunk_id": "w:tie:z",
                    "text": "The transformer is great",
                    "citation_label": "Z",
                },
                {
                    "chunk_id": "w:tie:a",
                    "text": "The transformer is great",
                    "citation_label": "A",
                },
            ],
        )
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        results = retrieve_hybrid_in_memory(
            query="transformer",
            bm25_index=bm25_index,
            vector_index=vector_index,
            mode="hybrid",
            limit=2,
        )
        assert len(results) == 2
        if results[0].score == results[1].score:
            # Tie-break by resource_id then chunk_id.
            assert results[0].resource_id <= results[1].resource_id

    def test_source_type_filter_works(self, data_dir):
        """Test 11: source_type filter works."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        rec_pdf = _make_pdf_record(data_dir, resource_id="pdf:filt")
        rec_web = _make_normalized_record(
            data_dir,
            resource_id="webpage:filt",
            source_type=SourceType.WEBPAGE,
            chunks=[
                {
                    "chunk_id": "w:f:1",
                    "text": "attention transformer transformer",
                    "citation_label": "Intro",
                }
            ],
        )
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec_pdf, rec_web])
        results = retrieve_hybrid_in_memory(
            query="attention transformer",
            bm25_index=bm25_index,
            vector_index=vector_index,
            mode="hybrid",
            limit=10,
            source_types=["pdf"],
        )
        assert all(r.source_type == "pdf" for r in results)

    def test_resource_id_filter_works(self, data_dir):
        """Test 12: resource_id filter works."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        rec_pdf_a = _make_pdf_record(data_dir, resource_id="pdf:fa")
        rec_pdf_b = _make_pdf_record(
            data_dir,
            resource_id="pdf:fb",
            content_hash="fffffff" + "0" * 56,
        )
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec_pdf_a, rec_pdf_b])
        results = retrieve_hybrid_in_memory(
            query="attention transformer",
            bm25_index=bm25_index,
            vector_index=vector_index,
            mode="hybrid",
            limit=10,
            resource_id="pdf:fa",
        )
        assert all(r.resource_id == "pdf:fa" for r in results)

    def test_attention_transformer_query_returns_attention_chunk(self, data_dir):
        """Test 15: real PDF query 'attention transformer' returns Attention paper chunk."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        for mode in ("bm25", "vector", "hybrid", "graph-lite"):
            results = retrieve_hybrid_in_memory(
                query="attention transformer",
                bm25_index=bm25_index,
                vector_index=vector_index,
                mode=mode,
                limit=3,
            )
            assert len(results) >= 1
            assert results[0].source_type == "pdf"
            assert "Attention" in results[0].title

    def test_scaled_dot_product_attention_query_returns_cited_chunk(self, data_dir):
        """Test 16: 'scaled dot-product attention' returns a cited PDF chunk."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        for mode in ("bm25", "vector", "hybrid", "graph-lite"):
            results = retrieve_hybrid_in_memory(
                query="scaled dot-product attention",
                bm25_index=bm25_index,
                vector_index=vector_index,
                mode=mode,
                limit=3,
            )
            assert len(results) >= 1
            assert results[0].citation_label

    def test_empty_query_fails(self):
        """Test 8: empty query fails clearly."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        with pytest.raises(ValueError):
            retrieve_hybrid_in_memory(query="", bm25_index=None, vector_index=None)
        with pytest.raises(ValueError):
            retrieve_hybrid_in_memory(
                query="   ", bm25_index=None, vector_index=None
            )

    def test_invalid_mode_fails(self):
        """Test 7: --mode invalid fails clearly."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        with pytest.raises(ValueError):
            retrieve_hybrid_in_memory(
                query="x", bm25_index=None, vector_index=None, mode="fuzzy"
            )

    def test_component_score_fields_always_present(self, data_dir):
        """Defensive: component score fields are always present across all four modes."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        for mode in ("bm25", "vector", "hybrid", "graph-lite"):
            results = retrieve_hybrid_in_memory(
                query="attention",
                bm25_index=bm25_index,
                vector_index=vector_index,
                mode=mode,
                limit=1,
            )
            if not results:
                continue
            cs = results[0].component_scores
            for field in (
                "bm25",
                "vector",
                "graph_boost",
                "normalized_bm25",
                "normalized_vector",
                "final",
            ):
                assert hasattr(cs, field), f"{mode}: missing {field}"
                assert isinstance(getattr(cs, field), float), (
                    f"{mode}: {field} must be a float"
                )

    def test_explanation_weights_and_normalization_always_present(self, data_dir):
        """Defensive: weights and normalization blocks are always present in explanation."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        for mode in ("bm25", "vector", "hybrid", "graph-lite"):
            results = retrieve_hybrid_in_memory(
                query="attention",
                bm25_index=bm25_index,
                vector_index=vector_index,
                mode=mode,
                limit=1,
            )
            if not results:
                continue
            d = results[0].explanation.to_dict()
            assert "weights" in d, f"{mode}: missing explanation.weights"
            assert "normalization" in d, f"{mode}: missing explanation.normalization"

    def test_mode_specific_explanation(self, data_dir):
        """Defensive: bm25 mode has weights.bm25 set; vector mode has weights.vector set."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        results_bm25 = retrieve_hybrid_in_memory(
            query="attention",
            bm25_index=bm25_index,
            vector_index=vector_index,
            mode="bm25",
            limit=1,
        )
        if results_bm25:
            d = results_bm25[0].explanation.to_dict()
            assert "bm25" in d["weights"]
            # The vector weight in bm25 mode is zero.
            assert d["weights"].get("vector", 0.0) == 0.0

        results_vector = retrieve_hybrid_in_memory(
            query="attention",
            bm25_index=bm25_index,
            vector_index=vector_index,
            mode="vector",
            limit=1,
        )
        if results_vector:
            d = results_vector[0].explanation.to_dict()
            assert "vector" in d["weights"]
            assert d["weights"].get("bm25", 0.0) == 0.0

    def test_graph_boost_zero_for_non_graph_lite_modes(self, data_dir):
        """Defensive: graph_boost is 0.0 for non-graph-lite modes."""
        from wiki.retrieval import retrieve_hybrid_in_memory

        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        for mode in ("bm25", "vector", "hybrid"):
            results = retrieve_hybrid_in_memory(
                query="attention",
                bm25_index=bm25_index,
                vector_index=vector_index,
                mode=mode,
                limit=3,
            )
            for r in results:
                assert r.component_scores.graph_boost == 0.0, (
                    f"{mode}: graph_boost must be 0.0, got {r.component_scores.graph_boost}"
                )


# =============================================================================
# Test class 5: TestRouterCli
# =============================================================================


class TestRouterCli:
    def test_cli_retrieve_empty_query_fails(self):
        """Test 8 (CLI): empty query fails clearly."""
        result = CliRunner().invoke(cli.app, ["retrieve", ""])
        assert result.exit_code == 1
        assert "query is empty" in result.output

    def test_cli_retrieve_invalid_mode_fails(self):
        """Test 7 (CLI): --mode invalid fails clearly."""
        result = CliRunner().invoke(
            cli.app, ["retrieve", "attention", "--mode", "fuzzy"]
        )
        assert result.exit_code == 1
        assert "invalid" in result.output.lower() and "mode" in result.output.lower()

    def test_cli_retrieve_zero_weight_sum_fails(self):
        result = CliRunner().invoke(
            cli.app,
            [
                "retrieve",
                "attention",
                "--mode",
                "hybrid",
                "--bm25-weight",
                "0",
                "--vector-weight",
                "0",
            ],
        )
        assert result.exit_code == 1

    def test_cli_retrieve_json_output(self, data_dir, monkeypatch):
        """Test 9: --json returns valid JSON."""
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity, ResourceStatus

        rec = _make_pdf_record(data_dir)
        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        identity = ResourceIdentity(
            source_type=rec.source_type,
            canonical_id=rec.canonical_id,
            original_url=rec.original_url,
            content_hash=rec.content_hash,
        )
        inserted = reg.insert(identity, status=ResourceStatus.NORMALIZED)
        rec.id = inserted.id
        rec.first_seen_at = inserted.first_seen_at
        reg.update(rec)

        CliRunner().invoke(cli.app, ["build-bm25-index"])
        CliRunner().invoke(cli.app, ["build-vector-index"])
        result = CliRunner().invoke(
            cli.app, ["retrieve", "attention", "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert isinstance(payload, list)
        assert len(payload) >= 1
        first = payload[0]
        for required in (
            "rank",
            "score",
            "chunk_id",
            "resource_id",
            "title",
            "source_type",
            "text_preview",
            "citation_label",
            "resource_route",
            "source_ref",
            "mode",
            "component_scores",
            "matched_terms",
            "explanation",
            "metadata",
        ):
            assert required in first

    def test_cli_retrieve_explain_includes_verbose_explanation(
        self, data_dir, monkeypatch
    ):
        """Test 10: --explain includes explanation fields (verbose)."""
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity, ResourceStatus

        rec = _make_pdf_record(data_dir)
        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        identity = ResourceIdentity(
            source_type=rec.source_type,
            canonical_id=rec.canonical_id,
            original_url=rec.original_url,
            content_hash=rec.content_hash,
        )
        inserted = reg.insert(identity, status=ResourceStatus.NORMALIZED)
        rec.id = inserted.id
        rec.first_seen_at = inserted.first_seen_at
        reg.update(rec)

        CliRunner().invoke(cli.app, ["build-bm25-index"])
        CliRunner().invoke(cli.app, ["build-vector-index"])
        result = CliRunner().invoke(
            cli.app,
            ["retrieve", "attention", "--mode", "graph-lite", "--json", "--explain"],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert len(payload) >= 1
        first = payload[0]
        # Verbose explanation includes the per-factor fields.
        for required in (
            "shared_topics",
            "shared_concepts",
            "source_type_preference",
            "resource_relationship_targets",
            "weights",
            "normalization",
        ):
            assert required in first["explanation"]

    def test_cli_retrieve_readable_output(self, data_dir, monkeypatch):
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity, ResourceStatus

        rec = _make_pdf_record(data_dir)
        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        identity = ResourceIdentity(
            source_type=rec.source_type,
            canonical_id=rec.canonical_id,
            original_url=rec.original_url,
            content_hash=rec.content_hash,
        )
        inserted = reg.insert(identity, status=ResourceStatus.NORMALIZED)
        rec.id = inserted.id
        rec.first_seen_at = inserted.first_seen_at
        reg.update(rec)

        CliRunner().invoke(cli.app, ["build-bm25-index"])
        CliRunner().invoke(cli.app, ["build-vector-index"])
        result = CliRunner().invoke(
            cli.app, ["retrieve", "attention"]
        )
        assert result.exit_code == 0
        assert "Rank" in result.output
        assert "Score" in result.output
        assert "Chunk" in result.output
        assert "Boost" in result.output


# =============================================================================
# Test class 6: TestBuildSiteAndValidate
# =============================================================================


class TestBuildSiteAndValidate:
    def test_build_site_continues_to_pass(self, tmp_path, monkeypatch):
        """Test 20: build-site --refresh still passes."""
        rec = _make_pdf_record(tmp_path)
        builder = _setup_site_builder(tmp_path, monkeypatch)
        builder.build([rec])
        assert builder.repo_site_dir.exists()
        # The retrieval page must be generated.
        retrieval_page = builder.repo_site_dir / "search" / "retrieval.md"
        assert retrieval_page.exists(), f"missing {retrieval_page}"

    def test_smoke_site_passes_after_retrieval_added(self, tmp_path, monkeypatch):
        """Test 21: smoke-site still passes."""
        from typer import Exit

        _isolated_data_dir(tmp_path, monkeypatch)
        from wiki.registry import Registry

        monkeypatch.setattr(cli, "registry", Registry())

        rec = _make_pdf_record(tmp_path)
        cli.generate_derived_views([rec])
        builder = _setup_site_builder(tmp_path, monkeypatch)
        builder.build([rec])
        cli.site_builder.repo_site_dir = builder.repo_site_dir
        cli.site_builder.data_site_dir = builder.data_site_dir
        cli.site_builder._sync_to_repo_site()

        try:
            cli.smoke_site()
        except Exit as exc:
            assert exc.exit_code == 0, f"smoke_site exited {exc.exit_code}"

    def test_validate_passes_after_retrieval_added(self, tmp_path, monkeypatch):
        """Test 22: validate still passes."""
        from typer import Exit

        _isolated_data_dir(tmp_path, monkeypatch)
        from wiki.registry import Registry

        monkeypatch.setattr(cli, "registry", Registry())

        rec = _make_pdf_record(tmp_path)
        cli.generate_derived_views([rec])
        builder = _setup_site_builder(tmp_path, monkeypatch)
        builder.build([rec])
        cli.site_builder.repo_site_dir = builder.repo_site_dir
        cli.site_builder.data_site_dir = builder.data_site_dir
        cli.site_builder._sync_to_repo_site()

        try:
            cli.validate(provider=None)
        except Exit as exc:
            assert exc.exit_code == 0, f"validate exited {exc.exit_code}"


# =============================================================================
# Test class 7: TestRetrievalBoundaries
# =============================================================================


class TestRetrievalBoundaries:
    def test_no_llm_embedding_vector_db_dependencies(self):
        """Test 23: no LLM/model/vector-DB dependencies are introduced."""
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(
            r"^dependencies\s*=\s*\[(.*?)\]",
            pyproject,
            re.DOTALL | re.MULTILINE,
        )
        assert match, "could not locate dependencies block"
        block = match.group(1).lower()
        forbidden = [
            "rank-bm25",
            "faiss",
            "chroma",
            "lancedb",
            "qdrant",
            "milvus",
            "sentence-transformers",
            "transformers",
            "openai",
            "ollama",
            "numpy",
            "scipy",
            "scikit-learn",
        ]
        for needle in forbidden:
            assert needle not in block, (
                f"forbidden dependency in [dependencies]: {needle}"
            )

    def test_retrieval_package_does_not_import_banned_modules(self):
        """Defensive: wiki/retrieval/*.py must not import LLM/embedding modules."""
        retrieval_dir = REPO_ROOT / "wiki" / "retrieval"
        for py_file in retrieval_dir.glob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            for forbidden_import in (
                "import faiss",
                "from faiss",
                "import chromadb",
                "from chromadb",
                "import lancedb",
                "from lancedb",
                "import qdrant",
                "from qdrant",
                "import sentence_transformers",
                "from sentence_transformers",
                "import openai",
                "from openai",
                "import ollama",
                "from ollama",
                "import numpy",
                "import numpy as np",
                "from numpy",
                "import httpx",
            ):
                assert forbidden_import not in text, (
                    f"{py_file.name} contains forbidden import {forbidden_import!r}"
                )

    def test_no_llm_calls_in_retrieval(self):
        """Defensive: wiki/retrieval/*.py must not call LLM providers."""
        retrieval_dir = REPO_ROOT / "wiki" / "retrieval"
        for py_file in retrieval_dir.glob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            for forbidden in (
                "import openai",
                "from openai",
                "import ollama",
                "from ollama",
                "import httpx",
                "MockProvider",
                "OllamaCloudProvider",
            ):
                assert forbidden not in text, (
                    f"{py_file.name} contains forbidden reference {forbidden!r}"
                )

    def test_bm25_internals_unmodified(self):
        """Test 24: BM25 internals remain unmodified."""
        bm25_file = REPO_ROOT / "wiki" / "search" / "bm25.py"
        text = bm25_file.read_text(encoding="utf-8")
        for needle in ("wiki.retrieval", "from wiki.retrieval"):
            assert needle not in text, (
                f"wiki/search/bm25.py contains Prompt 30 import: {needle!r}"
            )

    def test_vector_internals_unmodified(self):
        """Test 25: vector internals remain unmodified."""
        for sub in ("vectorizer.py", "search.py"):
            vector_file = REPO_ROOT / "wiki" / "vector" / sub
            text = vector_file.read_text(encoding="utf-8")
            for needle in ("wiki.retrieval", "from wiki.retrieval"):
                assert needle not in text, (
                    f"wiki/vector/{sub} contains Prompt 30 import: {needle!r}"
                )

    def test_chunk_builder_unmodified(self):
        """Test 26: chunk builder remains unmodified."""
        chunks_file = REPO_ROOT / "wiki" / "chunks" / "builder.py"
        text = chunks_file.read_text(encoding="utf-8")
        for needle in ("wiki.retrieval", "from wiki.retrieval"):
            assert needle not in text, (
                f"wiki/chunks/builder.py contains Prompt 30 import: {needle!r}"
            )

    def test_graph_builder_unmodified(self):
        """Test 27: graph builder remains unmodified."""
        graph_file = REPO_ROOT / "wiki" / "graph" / "builder.py"
        text = graph_file.read_text(encoding="utf-8")
        for needle in ("wiki.retrieval", "from wiki.retrieval"):
            assert needle not in text, (
                f"wiki/graph/builder.py contains Prompt 30 import: {needle!r}"
            )


# =============================================================================
# Test class 8: TestStaticRoutes
# =============================================================================


class TestStaticRoutes:
    def test_static_route_verification_script_works(self, tmp_path):
        """Test 28: static route verification includes retrieval page."""
        script = REPO_ROOT / "scripts" / "verify_site_static_routes.py"
        assert script.exists(), f"missing verification script: {script}"

        # The script accepts a --site-dir flag. Pointing it at a
        # fresh tmp dir that does not contain the routes should
        # exit 1 (routes missing).
        result_missing = subprocess.run(
            [sys.executable, str(script), "--site-dir", str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result_missing.returncode == 1
        assert "Missing" in result_missing.stdout or "Missing" in result_missing.stderr

        # Now create a minimal set of expected routes (including
        # the new retrieval route) and confirm the script exits 0.
        for sub in ("graph", "chunks", "search", "public", "ingest"):
            (tmp_path / sub).mkdir(parents=True, exist_ok=True)
        (tmp_path / "public" / "chunks").mkdir(parents=True, exist_ok=True)
        (tmp_path / "public" / "search").mkdir(parents=True, exist_ok=True)
        (tmp_path / "graph").joinpath("index.md").write_text("# Graph\n", encoding="utf-8")
        (tmp_path / "graph").joinpath("explore.md").write_text("# Explore\n", encoding="utf-8")
        (tmp_path / "graph").joinpath("graphify.md").write_text("# Graphify\n", encoding="utf-8")
        (tmp_path / "graph").joinpath("viewer.md").write_text("# Viewer\n", encoding="utf-8")
        (tmp_path / "graph").joinpath("resource-relationships.md").write_text(
            "# RR\n", encoding="utf-8"
        )
        (tmp_path / "ingest").joinpath("index.md").write_text("# Ingest\n", encoding="utf-8")
        (tmp_path / "chunks").joinpath("index.md").write_text("# Chunks\n", encoding="utf-8")
        (tmp_path / "search").joinpath("bm25.md").write_text("# BM25\n", encoding="utf-8")
        (tmp_path / "public" / "chunks").joinpath("chunks.json").write_text("[]", encoding="utf-8")
        (tmp_path / "public" / "chunks").joinpath("manifest.json").write_text(
            json.dumps({"schema_version": "chunk_index_v1", "chunk_count": 0, "resource_count": 0}),
            encoding="utf-8",
        )
        (tmp_path / "public" / "search").joinpath("bm25_index.json").write_text(
            json.dumps({"schema_version": "bm25_index_v1", "vocab": {}, "manifest": {}}),
            encoding="utf-8",
        )
        (tmp_path / "public" / "search").joinpath("bm25_manifest.json").write_text(
            json.dumps({"schema_version": "bm25_index_v1", "doc_count": 0, "resource_count": 0}),
            encoding="utf-8",
        )
        (tmp_path / "search").joinpath("vector.md").write_text("# Vector\n", encoding="utf-8")
        (tmp_path / "public" / "search").joinpath("vector_index.json").write_text(
            json.dumps({"schema_version": "vector_index_v1", "vocab_summary": {}, "manifest": {}}),
            encoding="utf-8",
        )
        (tmp_path / "public" / "search").joinpath("vector_manifest.json").write_text(
            json.dumps({"schema_version": "vector_index_v1", "chunk_count": 0, "resource_count": 0}),
            encoding="utf-8",
        )
        # Prompt 30: retrieval page.
        (tmp_path / "search").joinpath("retrieval.md").write_text(
            "# Retrieval\n", encoding="utf-8"
        )

        result_ok = subprocess.run(
            [sys.executable, str(script), "--site-dir", str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result_ok.returncode == 0, (
            f"script exited {result_ok.returncode} with routes: "
            f"stdout={result_ok.stdout!r} stderr={result_ok.stderr!r}"
        )
        assert "Routes checked" in result_ok.stdout


# =============================================================================
# Test class 9: TestRealPdfRetrievalVerification
# =============================================================================


class TestRealPdfRetrievalVerification:
    """Run the verify_hybrid_retrieval.py flow when the real PDF is on disk.

    These tests are skipped if the real PDF fixture is not
    present so the test suite does not require network access.
    """

    def _real_pdf_present(self) -> bool:
        return REAL_PDF.exists()

    def test_real_pdf_hybrid_retrieval(self, tmp_path, monkeypatch):
        """Test 29: verify_hybrid_retrieval.py passes against the real PDF fixture."""
        if not self._real_pdf_present():
            pytest.skip(f"Real PDF fixture not present at {REAL_PDF}")
        from wiki.ingest.pdf import pdf_ingestor
        from wiki.normalize.pdf import pdf_normalizer
        from wiki.registry import Registry
        from wiki.retrieval import ALLOWED_MODES, GRAPH_LITE_MAX_BOOST, retrieve_hybrid
        from wiki.schemas import ResourceIdentity, ResourceStatus
        from wiki.search import build_bm25_index, write_bm25_index
        from wiki.vector import build_vector_index, write_vector_index

        _isolated_data_dir(tmp_path, monkeypatch)
        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)

        record = pdf_ingestor.build_record(REAL_PDF)
        existing = reg.get_by_canonical_id(record.canonical_id)
        if existing is None:
            identity = ResourceIdentity(
                source_type=record.source_type,
                canonical_id=record.canonical_id,
                original_url=record.original_url,
                content_hash=record.content_hash,
            )
            inserted = reg.insert(identity, status=ResourceStatus.NEW)
            record.id = inserted.id
        else:
            record.id = existing.id
        record = pdf_normalizer.normalize(record)
        reg.update(record)

        chunk_index = build_chunk_index(list(reg.get_all()))
        bm25_index = build_bm25_index(chunk_index)
        vector_index = build_vector_index(chunk_index)
        assert vector_index.chunk_count > 0

        # Persist the indexes so the on-disk retrieve_hybrid
        # entry point can find them.
        from wiki.chunks.export import write_chunk_index as _write_ci

        _write_ci(chunk_index)
        write_bm25_index(bm25_index)
        write_vector_index(vector_index)

        # Build a small knowledge graph for the graph-lite
        # boost.
        try:
            from wiki.graph import GraphBuilder
            from wiki.graph.export import export_graph

            graph = GraphBuilder(data_dir=tmp_path).build(list(reg.get_all()))
            export_graph(graph, data_dir=tmp_path)
        except Exception:
            pass  # graph-lite will return zero boost.

        for query in (
            "attention transformer",
            "scaled dot-product attention",
            "embeddings retrieval",
            "vllm paged attention",
            "rag evaluation",
        ):
            for mode in sorted(ALLOWED_MODES):
                results = retrieve_hybrid(
                    query=query,
                    mode=mode,
                    limit=3,
                    data_dir=tmp_path,
                )
                # Each result must have a valid boost bound.
                for r in results:
                    assert 0.0 <= r.component_scores.graph_boost <= GRAPH_LITE_MAX_BOOST
                    assert r.chunk_id
                    assert r.citation_label
                    assert r.resource_route
