"""Tests for Prompt 31: Retrieval Eval Suite Foundation.

The 30+ test cases from ``prompt31.md`` §"Required tests" are
covered by the classes in this file. The pattern follows the
existing ``tests/test_prompt30_hybrid_retrieval.py`` tests:
build a small chunk index in a tmp dir using controlled
records, point ``SiteBuilder`` at isolated data/repo
directories, and assert on the eval-case schema, the metric
functions, the runner, and the CLI.

The tests are grouped by responsibility:

- :class:`TestEvalCaseSchema` — the dataclass schema and
  the ``parse_cases`` validator.
- :class:`TestRetrievalEvalMetrics` — the pure metric
  functions: recall@k, precision@k, hit@k, MRR,
  expected-term coverage.
- :class:`TestRetrievalEvalRunner` — the in-memory eval
  runner across all four modes.
- :class:`TestRetrievalEvalOutput` — the readable and JSON
  output formatters.
- :class:`TestRetrievalEvalCli` — the ``wiki eval-retrieval``
  CLI command (readable, JSON, --mode hybrid --k 3,
  invalid mode, no Prompt 32 files, no boundary files).
- :class:`TestPrompt31Boundaries` — scope guards (no
  LLM/embedding/vector-DB imports; no Prompt 32 files;
  BM25, vector, chunk internals unmodified).
"""

from __future__ import annotations

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
    ChunkIndexResult,
    build_chunk_index,
)
from wiki.config import config
from wiki.retrieval_eval import (
    DEFAULT_FIXTURE_PATH,
    DEFAULT_K_VALUES,
    DEFAULT_MODES,
    EVAL_SCHEMA_VERSION,
    EvalCase,
    EvalCaseError,
    EvalCaseResult,
    EvalMetric,
    EvalReport,
    aggregate_metrics,
    compute_metric,
    format_json,
    format_readable,
    load_cases,
    parse_cases,
    run_eval,
    run_eval_in_memory,
)
from wiki.retrieval_eval.schema import (
    MAX_EXPECTED_ITEMS,
    MAX_K,
    MAX_K_VALUES,
)
from wiki.retrieval.schema import (
    ALLOWED_MODES,
    ComponentScores,
    Explanation,
    RetrievalResult,
)
from wiki.schemas import (
    Importance,
    ResourceRecord,
    ResourceStatus,
    SourceType,
)


# =============================================================================
# Fixtures and helpers
# =============================================================================


REPO_ROOT = Path(__file__).parent.parent.resolve()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Pytest fixture that points config at a tmp data dir."""
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    config.ensure_directories()
    return tmp_path


def _make_normalized_record(
    tmp_path: Path,
    *,
    resource_id: str,
    source_type: SourceType,
    chunks: List[dict],
    extra: Optional[dict] = None,
    title: Optional[str] = None,
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
        extra=extra or {},
    )


def _make_pdf_record(
    tmp_path: Path,
    *,
    resource_id: str = "pdf:0111111111111111111111111111111111111111111111111111111111111111",
    title: str = "Attention Is All You Need",
    content_hash: Optional[str] = None,
) -> ResourceRecord:
    """Build a PDF record with a deterministic on-disk ``chunks.json`` mirror."""
    if content_hash is None:
        content_hash = "01111111" * 8  # 64 hex chars
    mirror = tmp_path / "processed" / "pdfs" / content_hash[:8] / "chunks.json"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    chunks = [
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


def _make_fake_result(
    *,
    rank: int,
    chunk_id: str,
    resource_id: str = "pdf:test",
    matched_terms: Optional[list] = None,
    text_preview: str = "",
) -> RetrievalResult:
    """Build a minimal ``RetrievalResult`` for unit tests."""
    return RetrievalResult(
        rank=rank,
        score=0.5,
        chunk_id=chunk_id,
        resource_id=resource_id,
        title="T",
        source_type="pdf",
        text_preview=text_preview,
        citation_label="p1",
        resource_route="/r",
        source_ref={},
        mode="bm25",
        component_scores=ComponentScores(
            bm25=0.5,
            vector=0.0,
            graph_boost=0.0,
            normalized_bm25=0.5,
            normalized_vector=0.0,
            final=0.5,
        ),
        matched_terms=matched_terms or [],
        explanation=Explanation(),
        metadata={},
    )


# =============================================================================
# Test class 1: TestEvalCaseSchema
# =============================================================================


class TestEvalCaseSchema:
    def test_eval_case_has_all_required_fields(self):
        case = EvalCase(
            id="case-1",
            query="hello world",
            expected_resource_ids=["pdf:a"],
            expected_chunk_ids=[],
            expected_terms=[],
            modes=["bm25"],
            k_values=[1, 3],
            notes="",
        )
        d = case.to_dict()
        for field in (
            "id",
            "query",
            "expected_resource_ids",
            "expected_chunk_ids",
            "expected_terms",
            "modes",
            "k_values",
            "notes",
        ):
            assert field in d, f"missing {field!r}"
        assert d["id"] == "case-1"
        assert d["query"] == "hello world"
        assert d["expected_resource_ids"] == ["pdf:a"]
        assert d["expected_chunk_ids"] == []
        assert d["expected_terms"] == []
        assert d["modes"] == ["bm25"]
        assert d["k_values"] == [1, 3]

    def test_parse_cases_valid_payload(self):
        raw = {
            "schema_version": "retrieval_eval_v1",
            "cases": [
                {
                    "id": "ok",
                    "query": "transformer attention",
                    "expected_resource_ids": ["pdf:a"],
                    "expected_chunk_ids": [],
                    "expected_terms": ["attention"],
                    "modes": ["bm25"],
                    "k_values": [1, 3],
                    "notes": "ok",
                }
            ],
        }
        cases = parse_cases(raw)
        assert len(cases) == 1
        assert cases[0].id == "ok"
        assert cases[0].query == "transformer attention"
        assert cases[0].modes == ["bm25"]
        assert cases[0].k_values == [1, 3]

    def test_parse_cases_bare_list(self):
        raw = [
            {
                "id": "ok",
                "query": "x",
                "expected_terms": ["a"],
                "modes": ["bm25"],
                "k_values": [1],
            }
        ]
        cases = parse_cases(raw)
        assert len(cases) == 1
        assert cases[0].id == "ok"

    def test_empty_id_rejected(self):
        raw = [
            {
                "id": "",
                "query": "x",
                "expected_terms": ["a"],
            }
        ]
        with pytest.raises(EvalCaseError, match="id"):
            parse_cases(raw)

    def test_empty_query_rejected(self):
        raw = [
            {
                "id": "ok",
                "query": "",
                "expected_terms": ["a"],
            }
        ]
        with pytest.raises(EvalCaseError, match="query"):
            parse_cases(raw)

    def test_invalid_mode_rejected(self):
        raw = [
            {
                "id": "ok",
                "query": "x",
                "expected_terms": ["a"],
                "modes": ["fuzzy"],
            }
        ]
        with pytest.raises(EvalCaseError, match="mode"):
            parse_cases(raw)

    def test_invalid_k_rejected(self):
        raw = [
            {
                "id": "ok",
                "query": "x",
                "expected_terms": ["a"],
                "k_values": [0],
            }
        ]
        with pytest.raises(EvalCaseError, match="k_values"):
            parse_cases(raw)

    def test_non_integer_k_rejected(self):
        raw = [
            {
                "id": "ok",
                "query": "x",
                "expected_terms": ["a"],
                "k_values": ["three"],
            }
        ]
        with pytest.raises(EvalCaseError, match="k_values"):
            parse_cases(raw)

    def test_missing_expectations_rejected(self):
        raw = [
            {
                "id": "ok",
                "query": "x",
            }
        ]
        with pytest.raises(EvalCaseError, match="at least one of"):
            parse_cases(raw)

    def test_duplicate_case_ids_rejected(self):
        raw = [
            {
                "id": "dupe",
                "query": "x",
                "expected_terms": ["a"],
            },
            {
                "id": "dupe",
                "query": "y",
                "expected_terms": ["b"],
            },
        ]
        with pytest.raises(EvalCaseError, match="duplicate"):
            parse_cases(raw)

    def test_k_too_large_rejected(self):
        raw = [
            {
                "id": "ok",
                "query": "x",
                "expected_terms": ["a"],
                "k_values": [MAX_K + 1],
            }
        ]
        with pytest.raises(EvalCaseError, match="exceeds MAX_K"):
            parse_cases(raw)

    def test_too_many_k_values_rejected(self):
        raw = [
            {
                "id": "ok",
                "query": "x",
                "expected_terms": ["a"],
                "k_values": list(range(1, MAX_K_VALUES + 2)),
            }
        ]
        with pytest.raises(EvalCaseError, match="too many"):
            parse_cases(raw)

    def test_load_cases_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_cases(tmp_path / "does_not_exist.json")

    def test_default_fixture_loads(self):
        cases = load_cases()
        assert len(cases) >= 1
        for c in cases:
            assert c.id
            assert c.query
            assert c.modes
            assert c.k_values

    def test_default_modes_constant(self):
        assert DEFAULT_MODES == ("bm25", "vector", "hybrid", "graph-lite")

    def test_default_k_values_constant(self):
        assert DEFAULT_K_VALUES == (1, 3, 5)

    def test_schema_version_constant(self):
        assert EVAL_SCHEMA_VERSION == "retrieval_eval_v1"

    def test_too_many_expected_items_rejected(self):
        raw = [
            {
                "id": "ok",
                "query": "x",
                "expected_terms": [f"t{i}" for i in range(MAX_EXPECTED_ITEMS + 1)],
            }
        ]
        with pytest.raises(EvalCaseError, match="too many"):
            parse_cases(raw)


# =============================================================================
# Test class 2: TestRetrievalEvalMetrics
# =============================================================================


class TestRetrievalEvalMetrics:
    def test_recall_at_k_correctness(self):
        results = [
            _make_fake_result(rank=1, chunk_id="c1", resource_id="r1"),
            _make_fake_result(rank=2, chunk_id="c2", resource_id="r2"),
            _make_fake_result(rank=3, chunk_id="c3", resource_id="r3"),
        ]
        m = compute_metric(
            results=results,
            mode="bm25",
            k=3,
            expected_resource_ids=["r1", "r2"],
        )
        # 2 expected items, both in top-3 → recall = 2/2 = 1.0
        assert m.recall == 1.0
        assert m.matched_count == 2
        assert m.result_count == 3
        assert m.first_match_rank == 1

    def test_precision_at_k_correctness(self):
        results = [
            _make_fake_result(rank=1, chunk_id="c1", resource_id="r1"),
            _make_fake_result(rank=2, chunk_id="c2", resource_id="r_other"),
            _make_fake_result(rank=3, chunk_id="c3", resource_id="r3"),
        ]
        m = compute_metric(
            results=results,
            mode="bm25",
            k=3,
            expected_resource_ids=["r1", "r3"],
        )
        # 2 of 3 in top-3 (r1 and r3) → precision = 2/3
        assert m.precision == pytest.approx(2.0 / 3.0)
        assert m.matched_count == 2
        assert m.first_match_rank == 1

    def test_hit_at_k_correctness(self):
        results = [
            _make_fake_result(rank=1, chunk_id="c1", resource_id="r_other"),
            _make_fake_result(rank=2, chunk_id="c2", resource_id="r1"),
        ]
        m = compute_metric(
            results=results,
            mode="bm25",
            k=2,
            expected_resource_ids=["r1"],
        )
        assert m.hit == 1.0
        assert m.first_match_rank == 2

    def test_hit_at_k_zero_when_no_match(self):
        results = [
            _make_fake_result(rank=1, chunk_id="c1", resource_id="r_other"),
            _make_fake_result(rank=2, chunk_id="c2", resource_id="r_other2"),
        ]
        m = compute_metric(
            results=results,
            mode="bm25",
            k=2,
            expected_resource_ids=["r1"],
        )
        assert m.hit == 0.0
        assert m.first_match_rank == 0
        assert m.matched_count == 0
        assert m.mrr == 0.0

    def test_mrr_correctness(self):
        results = [
            _make_fake_result(rank=1, chunk_id="c1", resource_id="r_other"),
            _make_fake_result(rank=2, chunk_id="c2", resource_id="r1"),
            _make_fake_result(rank=3, chunk_id="c3", resource_id="r_other2"),
        ]
        m = compute_metric(
            results=results,
            mode="bm25",
            k=3,
            expected_resource_ids=["r1"],
        )
        assert m.mrr == pytest.approx(1.0 / 2.0)

    def test_mrr_zero_when_no_match(self):
        results = [
            _make_fake_result(rank=1, chunk_id="c1", resource_id="r_other"),
        ]
        m = compute_metric(
            results=results,
            mode="bm25",
            k=1,
            expected_resource_ids=["r1"],
        )
        assert m.mrr == 0.0

    def test_expected_term_coverage_correctness(self):
        results = [
            _make_fake_result(
                rank=1,
                chunk_id="c1",
                resource_id="r1",
                matched_terms=["transformer", "attention"],
                text_preview="the Transformer is great",
            ),
        ]
        m = compute_metric(
            results=results,
            mode="bm25",
            k=1,
            expected_terms=["transformer", "attention", "missing"],
        )
        # 2 of 3 expected terms are present.
        assert m.expected_term_coverage == pytest.approx(2.0 / 3.0)

    def test_expected_term_coverage_zero_when_no_terms(self):
        results = [
            _make_fake_result(
                rank=1,
                chunk_id="c1",
                resource_id="r1",
                matched_terms=["a"],
            ),
        ]
        m = compute_metric(
            results=results,
            mode="bm25",
            k=1,
            expected_terms=[],
        )
        assert m.expected_term_coverage == 0.0

    def test_empty_results_return_zero_metrics(self):
        m = compute_metric(
            results=[],
            mode="bm25",
            k=3,
            expected_resource_ids=["r1"],
            expected_terms=["t1"],
        )
        assert m.recall == 0.0
        assert m.precision == 0.0
        assert m.hit == 0.0
        assert m.mrr == 0.0
        assert m.expected_term_coverage == 0.0
        assert m.matched_count == 0
        assert m.result_count == 0
        assert m.first_match_rank == 0

    def test_chunk_id_priority_over_resource_id(self):
        # When both expected lists are non-empty, chunk_id wins.
        results = [
            _make_fake_result(rank=1, chunk_id="c1", resource_id="r1"),
            _make_fake_result(rank=2, chunk_id="c2", resource_id="r2"),
        ]
        m = compute_metric(
            results=results,
            mode="bm25",
            k=2,
            expected_resource_ids=["r1"],
            expected_chunk_ids=["c2"],
        )
        # chunk_id "c2" is in top-2 → 1 of 1 expected → hit=1
        assert m.hit == 1.0
        assert m.first_match_rank == 2

    def test_k_larger_than_results(self):
        results = [
            _make_fake_result(rank=1, chunk_id="c1", resource_id="r1"),
        ]
        m = compute_metric(
            results=results,
            mode="bm25",
            k=5,
            expected_resource_ids=["r1"],
        )
        assert m.result_count == 1
        assert m.matched_count == 1
        assert m.hit == 1.0
        assert m.precision == 1.0  # 1 of 1

    def test_aggregate_metrics_averages_over_cases(self):
        m1 = _make_fake_result(rank=1, chunk_id="c1", resource_id="r1")
        m2 = _make_fake_result(rank=1, chunk_id="c2", resource_id="r2")
        metric1 = compute_metric(
            results=[m1],
            mode="bm25",
            k=1,
            expected_resource_ids=["r1"],
        )
        metric2 = compute_metric(
            results=[m2],
            mode="bm25",
            k=1,
            expected_resource_ids=["r1"],
        )
        agg = aggregate_metrics([metric1, metric2])
        assert "bm25" in agg
        assert "1" in agg["bm25"]
        assert agg["bm25"]["1"]["case_count"] == 2
        # mean recall: 1.0 (matched) and 0.0 (miss) → 0.5
        assert agg["bm25"]["1"]["recall"] == pytest.approx(0.5)
        assert agg["bm25"]["1"]["hit"] == pytest.approx(0.5)


# =============================================================================
# Test class 3: TestRetrievalEvalRunner
# =============================================================================


class TestRetrievalEvalRunner:
    def test_all_modes_supported(self, data_dir):
        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        cases = [
            EvalCase(
                id="all-modes",
                query="attention",
                expected_resource_ids=[rec.id],
                modes=["bm25", "vector", "hybrid", "graph-lite"],
                k_values=[1],
            )
        ]
        report = run_eval_in_memory(
            cases,
            bm25_index=bm25_index,
            vector_index=vector_index,
        )
        assert sorted(report.modes) == ["bm25", "graph-lite", "hybrid", "vector"]
        assert report.k_values == [1]
        # 4 modes × 1 k → 4 metrics
        assert len(report.aggregate_metrics["bm25"]["1"]) > 0
        assert len(report.aggregate_metrics["vector"]["1"]) > 0
        assert len(report.aggregate_metrics["hybrid"]["1"]) > 0
        assert len(report.aggregate_metrics["graph-lite"]["1"]) > 0

    def test_mode_filter_works(self, data_dir):
        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        cases = [
            EvalCase(
                id="hybrid-only",
                query="attention",
                expected_resource_ids=[rec.id],
                modes=["bm25", "vector", "hybrid", "graph-lite"],
                k_values=[1],
            )
        ]
        report = run_eval_in_memory(
            cases,
            mode_filter="hybrid",
            bm25_index=bm25_index,
            vector_index=vector_index,
        )
        assert report.modes == ["hybrid"]

    def test_k_filter_works(self, data_dir):
        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        cases = [
            EvalCase(
                id="k-1-only",
                query="attention",
                expected_resource_ids=[rec.id],
                modes=["bm25"],
                k_values=[1, 3, 5],
            )
        ]
        report = run_eval_in_memory(
            cases,
            k_filter=1,
            bm25_index=bm25_index,
            vector_index=vector_index,
        )
        assert report.k_values == [1]

    def test_deterministic_ordering(self, data_dir):
        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        cases = parse_cases(
            [
                {
                    "id": "a",
                    "query": "attention",
                    "expected_resource_ids": [rec.id],
                    "modes": ["bm25"],
                    "k_values": [1],
                },
                {
                    "id": "b",
                    "query": "transformer",
                    "expected_resource_ids": [rec.id],
                    "modes": ["bm25"],
                    "k_values": [1],
                },
            ]
        )
        report_1 = run_eval_in_memory(
            cases,
            bm25_index=bm25_index,
            vector_index=vector_index,
        )
        report_2 = run_eval_in_memory(
            list(reversed(cases)),
            bm25_index=bm25_index,
            vector_index=vector_index,
        )
        # Both reports have the same set of modes/k values.
        assert report_1.modes == report_2.modes
        assert report_1.k_values == report_2.k_values
        # The metrics in aggregate_metrics are identical (the
        # aggregate does not depend on the input order).
        for mode in report_1.modes:
            for k in report_1.k_values:
                assert (
                    report_1.aggregate_metrics[mode][str(k)]
                    == report_2.aggregate_metrics[mode][str(k)]
                )

    def test_no_hit_case_handled(self, data_dir):
        rec = _make_pdf_record(data_dir)
        _, bm25_index, vector_index = _build_indexes(data_dir, [rec])
        cases = [
            EvalCase(
                id="no-hit",
                query="zzznonexistent",
                expected_resource_ids=["pdf:does-not-exist"],
                modes=["bm25"],
                k_values=[1, 3],
            )
        ]
        report = run_eval_in_memory(
            cases,
            bm25_index=bm25_index,
            vector_index=vector_index,
        )
        # All metrics for this case are zero.
        for metric in report.case_results[0].metrics:
            assert metric.recall == 0.0
            assert metric.precision == 0.0
            assert metric.hit == 0.0
            assert metric.mrr == 0.0
        assert report.failures == []

    def test_empty_case_list(self, data_dir):
        _, bm25_index, vector_index = _build_indexes(data_dir, [])
        report = run_eval_in_memory([], bm25_index=bm25_index, vector_index=vector_index)
        assert report.total_cases == 0
        assert report.modes == []
        assert report.k_values == []
        assert report.aggregate_metrics == {}
        assert report.case_results == []
        assert report.failures == []

    def test_missing_bm25_index_marks_failure(self, data_dir):
        # No indexes: hybrid and bm25 should fail; vector is fine with no index
        # (it just returns no results). The runner should record failures
        # and not raise.
        rec = _make_pdf_record(data_dir)
        cases = [
            EvalCase(
                id="needs-bm25",
                query="attention",
                expected_resource_ids=[rec.id],
                modes=["bm25"],
                k_values=[1],
            )
        ]
        report = run_eval_in_memory(
            cases,
            bm25_index=None,
            vector_index=None,
        )
        # The case has a failure recorded.
        assert report.failures
        assert "BM25" in report.failures[0].failure or "bm25" in report.failures[0].failure

    def test_run_eval_validates_mode_filter(self):
        with pytest.raises(ValueError):
            run_eval([], mode_filter="fuzzy")

    def test_run_eval_validates_k_filter(self):
        with pytest.raises(ValueError):
            run_eval([], k_filter=0)


# =============================================================================
# Test class 4: TestRetrievalEvalOutput
# =============================================================================


class TestRetrievalEvalOutput:
    def _make_report(self) -> EvalReport:
        return EvalReport(
            schema_version=EVAL_SCHEMA_VERSION,
            total_cases=1,
            modes=["bm25"],
            k_values=[1],
            aggregate_metrics={
                "bm25": {
                    "1": {
                        "recall": 1.0,
                        "precision": 1.0,
                        "hit": 1.0,
                        "mrr": 1.0,
                        "expected_term_coverage": 0.5,
                        "case_count": 1,
                    }
                }
            },
            case_results=[
                EvalCaseResult(
                    case_id="ok",
                    query="x",
                    metrics=[
                        EvalMetric(
                            mode="bm25",
                            k=1,
                            recall=1.0,
                            precision=1.0,
                            hit=1.0,
                            mrr=1.0,
                            expected_term_coverage=0.5,
                            result_count=1,
                            matched_count=1,
                            first_match_rank=1,
                        )
                    ],
                )
            ],
            failures=[],
        )

    def test_format_readable_contains_key_fields(self):
        report = self._make_report()
        text = format_readable(report)
        assert "Retrieval Evaluation Report" in text
        assert EVAL_SCHEMA_VERSION in text
        assert "bm25" in text
        assert "recall" in text
        assert "Total cases: 1" in text

    def test_format_readable_handles_empty(self):
        report = EvalReport(
            schema_version=EVAL_SCHEMA_VERSION,
            total_cases=0,
            modes=[],
            k_values=[],
            aggregate_metrics={},
            case_results=[],
            failures=[],
        )
        text = format_readable(report)
        assert "No eval cases." in text
        assert "Total cases: 0" in text

    def test_format_readable_includes_failures(self):
        report = EvalReport(
            schema_version=EVAL_SCHEMA_VERSION,
            total_cases=1,
            modes=["bm25"],
            k_values=[1],
            aggregate_metrics={},
            case_results=[
                EvalCaseResult(
                    case_id="bad",
                    query="x",
                    metrics=[],
                    failure="BM25 index missing for mode='bm25'",
                )
            ],
            failures=[
                EvalCaseResult(
                    case_id="bad",
                    query="x",
                    metrics=[],
                    failure="BM25 index missing for mode='bm25'",
                )
            ],
        )
        text = format_readable(report)
        assert "Failures (1):" in text
        assert "BM25 index missing" in text

    def test_format_json_has_stable_field_order(self):
        report = self._make_report()
        out = format_json(report)
        data = json.loads(out)
        assert data["schema_version"] == EVAL_SCHEMA_VERSION
        assert data["total_cases"] == 1
        assert data["modes"] == ["bm25"]
        assert data["k_values"] == [1]
        assert "aggregate_metrics" in data
        assert "case_results" in data
        assert "failures" in data
        # The JSON document must start with '{' on the first line.
        assert out.lstrip().startswith("{")
        # Check ordering of top-level keys.
        top_level_keys: list[str] = []
        for line in out.splitlines():
            stripped = line.rstrip()
            if not stripped:
                continue
            leading = len(stripped) - len(stripped.lstrip(" "))
            content = stripped.lstrip(" ")
            if leading == 2 and content.startswith('"'):
                top_level_keys.append(content.split('":', 1)[0].strip('"'))
        assert top_level_keys[0] == "schema_version"
        assert top_level_keys == [
            "schema_version",
            "total_cases",
            "modes",
            "k_values",
            "aggregate_metrics",
            "case_results",
            "failures",
        ]

    def test_format_json_handles_empty(self):
        report = EvalReport(
            schema_version=EVAL_SCHEMA_VERSION,
            total_cases=0,
            modes=[],
            k_values=[],
            aggregate_metrics={},
            case_results=[],
            failures=[],
        )
        out = format_json(report)
        data = json.loads(out)
        assert data["total_cases"] == 0


# =============================================================================
# Test class 5: TestRetrievalEvalCli
# =============================================================================


class TestRetrievalEvalCli:
    def _persist_indexes(
        self, data_dir: Path, records: List[ResourceRecord]
    ) -> None:
        """Build BM25 and vector indexes in memory and write them to disk.

        The CLI loads the indexes from disk, so the tests must
        persist the indexes that ``_build_indexes`` produces.
        """
        from wiki.search import write_bm25_index
        from wiki.vector import write_vector_index
        from wiki.search.export import bm25_output_paths
        from wiki.vector.export import vector_output_paths

        _, bm25_index, vector_index = _build_indexes(data_dir, records)
        bm25_dir = bm25_output_paths(data_dir=data_dir)["directory"]
        vector_dir = vector_output_paths(data_dir=data_dir)["directory"]
        write_bm25_index(bm25_index, output_dir=bm25_dir)
        write_vector_index(vector_index, output_dir=vector_dir)

    def test_eval_retrieval_readable_runs(self, data_dir):
        rec = _make_pdf_record(data_dir)
        self._persist_indexes(data_dir, [rec])
        # Write a tiny cases file in tmp and point the CLI at it.
        cases_path = data_dir / "cases.json"
        cases_path.write_text(
            json.dumps(
                {
                    "schema_version": EVAL_SCHEMA_VERSION,
                    "cases": [
                        {
                            "id": "cli-bm25",
                            "query": "attention",
                            "expected_resource_ids": [rec.id],
                            "modes": ["bm25"],
                            "k_values": [1, 3],
                        }
                    ],
                }
            )
        )
        runner = CliRunner()
        result = runner.invoke(
            cli.app,
            ["eval-retrieval", "--cases-path", str(cases_path)],
        )
        assert result.exit_code == 0, result.output
        assert "Retrieval Evaluation Report" in result.output
        assert EVAL_SCHEMA_VERSION in result.output
        assert "Total cases: 1" in result.output

    def test_eval_retrieval_json_runs(self, data_dir):
        rec = _make_pdf_record(data_dir)
        self._persist_indexes(data_dir, [rec])
        cases_path = data_dir / "cases.json"
        cases_path.write_text(
            json.dumps(
                {
                    "schema_version": EVAL_SCHEMA_VERSION,
                    "cases": [
                        {
                            "id": "cli-json",
                            "query": "attention",
                            "expected_resource_ids": [rec.id],
                            "modes": ["bm25"],
                            "k_values": [1],
                        }
                    ],
                }
            )
        )
        runner = CliRunner()
        result = runner.invoke(
            cli.app,
            ["eval-retrieval", "--json", "--cases-path", str(cases_path)],
        )
        assert result.exit_code == 0, result.output
        # The output should be valid JSON.
        data = json.loads(result.output)
        assert data["schema_version"] == EVAL_SCHEMA_VERSION
        assert data["total_cases"] == 1
        assert "bm25" in data["aggregate_metrics"]

    def test_eval_retrieval_hybrid_k3(self, data_dir):
        rec = _make_pdf_record(data_dir)
        self._persist_indexes(data_dir, [rec])
        cases_path = data_dir / "cases.json"
        cases_path.write_text(
            json.dumps(
                {
                    "schema_version": EVAL_SCHEMA_VERSION,
                    "cases": [
                        {
                            "id": "cli-hybrid",
                            "query": "attention",
                            "expected_resource_ids": [rec.id],
                            "modes": ["bm25", "vector", "hybrid", "graph-lite"],
                            "k_values": [1, 3],
                        }
                    ],
                }
            )
        )
        runner = CliRunner()
        result = runner.invoke(
            cli.app,
            [
                "eval-retrieval",
                "--mode",
                "hybrid",
                "--k",
                "3",
                "--cases-path",
                str(cases_path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Evaluated modes: hybrid" in result.output
        assert "Evaluated k values: 3" in result.output

    def test_eval_retrieval_invalid_mode_fails(self, data_dir):
        runner = CliRunner()
        result = runner.invoke(cli.app, ["eval-retrieval", "--mode", "fuzzy"])
        assert result.exit_code != 0
        assert "invalid --mode" in result.output

    def test_eval_retrieval_invalid_k_fails(self, data_dir):
        runner = CliRunner()
        result = runner.invoke(cli.app, ["eval-retrieval", "--k", "0"])
        assert result.exit_code != 0
        assert "--k must be >= 1" in result.output

    def test_eval_retrieval_missing_cases_file_fails(self, data_dir):
        runner = CliRunner()
        result = runner.invoke(
            cli.app,
            [
                "eval-retrieval",
                "--cases-path",
                str(data_dir / "missing.json"),
            ],
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_eval_retrieval_invalid_case_fails(self, data_dir):
        cases_path = data_dir / "bad.json"
        cases_path.write_text(
            json.dumps(
                {
                    "schema_version": EVAL_SCHEMA_VERSION,
                    "cases": [
                        {
                            "id": "",
                            "query": "x",
                            "expected_terms": ["a"],
                        }
                    ],
                }
            )
        )
        runner = CliRunner()
        result = runner.invoke(
            cli.app,
            ["eval-retrieval", "--cases-path", str(cases_path)],
        )
        assert result.exit_code != 0
        assert "id" in result.output

    def test_eval_retrieval_subprocess_works(self, data_dir, monkeypatch):
        """Run the actual CLI via subprocess with the venv python.

        This guards against import-time regressions in the
        eval-retrieval command.
        """
        rec = _make_pdf_record(data_dir)
        self._persist_indexes(data_dir, [rec])
        cases_path = data_dir / "cases.json"
        cases_path.write_text(
            json.dumps(
                {
                    "schema_version": EVAL_SCHEMA_VERSION,
                    "cases": [
                        {
                            "id": "sub",
                            "query": "attention",
                            "expected_resource_ids": [rec.id],
                            "modes": ["bm25"],
                            "k_values": [1],
                        }
                    ],
                }
            )
        )
        env = {
            "PYTHONPATH": str(REPO_ROOT),
        }
        result = subprocess.run(
            [
                str(REPO_ROOT / ".venv" / "bin" / "python"),
                "-m",
                "wiki",
                "eval-retrieval",
                "--cases-path",
                str(cases_path),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert "Retrieval Evaluation Report" in result.stdout


# =============================================================================
# Test class 6: TestPrompt31Boundaries
# =============================================================================


class TestPrompt31Boundaries:
    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def test_no_openai_imports(self):
        for path in (REPO_ROOT / "wiki" / "retrieval_eval").rglob("*.py"):
            text = self._read_text(path)
            assert "openai" not in text.lower(), (
                f"openai import found in {path}"
            )

    def test_no_ollama_imports(self):
        for path in (REPO_ROOT / "wiki" / "retrieval_eval").rglob("*.py"):
            text = self._read_text(path)
            assert "ollama" not in text.lower(), (
                f"ollama import found in {path}"
            )

    def test_no_gemini_imports(self):
        for path in (REPO_ROOT / "wiki" / "retrieval_eval").rglob("*.py"):
            text = self._read_text(path)
            assert "gemini" not in text.lower(), (
                f"gemini import found in {path}"
            )

    def test_no_langchain_imports(self):
        for path in (REPO_ROOT / "wiki" / "retrieval_eval").rglob("*.py"):
            text = self._read_text(path)
            assert "langchain" not in text.lower(), (
                f"langchain import found in {path}"
            )

    def test_no_llama_index_imports(self):
        for path in (REPO_ROOT / "wiki" / "retrieval_eval").rglob("*.py"):
            text = self._read_text(path)
            assert "llama_index" not in text.lower() and "llamaindex" not in text.lower(), (
                f"llama-index import found in {path}"
            )

    def test_no_faiss_chroma_qdrant_lancedb_milvus_imports(self):
        forbidden = ["faiss", "chroma", "qdrant", "lancedb", "milvus"]
        for path in (REPO_ROOT / "wiki" / "retrieval_eval").rglob("*.py"):
            text = self._read_text(path).lower()
            for module in forbidden:
                assert module not in text, (
                    f"{module} import found in {path}"
                )

    def test_no_sentence_transformers_or_transformers_imports(self):
        forbidden = ["sentence_transformers", "transformers"]
        for path in (REPO_ROOT / "wiki" / "retrieval_eval").rglob("*.py"):
            text = self._read_text(path).lower()
            for module in forbidden:
                assert module not in text, (
                    f"{module} import found in {path}"
                )

    def test_no_prompt32_files_added(self):
        # Prompt 32 has landed: the verify script and the
        # test file now exist. This test now asserts that
        # Prompt 31 did not also accidentally add a duplicate
        # eval-report module in a different runtime location.
        prompt31_forbidden = [
            "wiki/retrieval_eval_report.py",
            "wiki/site/eval_report.py",
            "wiki/retrieval/report.py",
        ]
        for rel in prompt31_forbidden:
            assert not (REPO_ROOT / rel).exists(), (
                f"Prompt 31 accidentally added a duplicate eval report module: {rel}"
            )

    def test_no_static_search_eval_page_added(self):
        # Prompt 32 has landed: site/docs/search/eval.md is
        # now the expected static report page. This test now
        # asserts that Prompt 31 did not add duplicate eval
        # report pages in unsupported locations.
        prompt31_forbidden = [
            REPO_ROOT / "site" / "docs" / "eval.md",
            REPO_ROOT / "site" / "docs" / "eval" / "index.md",
            REPO_ROOT / "site" / "docs" / "retrieval-eval.md",
            REPO_ROOT / "site_generated" / "docs" / "eval.md",
            REPO_ROOT / "site_generated" / "docs" / "eval" / "index.md",
            REPO_ROOT / "site_generated" / "docs" / "retrieval-eval.md",
        ]
        for path in prompt31_forbidden:
            assert not path.exists(), (
                f"Prompt 31 added an out-of-scope eval report page: {path}"
            )

    def test_no_bm25_internals_changed(self):
        # The BM25 search module should not have any of the
        # eval-suite-specific imports.
        for path in (REPO_ROOT / "wiki" / "search").rglob("*.py"):
            text = self._read_text(path)
            assert "retrieval_eval" not in text, (
                f"BM25 module imports retrieval_eval: {path}"
            )

    def test_no_vector_internals_changed(self):
        for path in (REPO_ROOT / "wiki" / "vector").rglob("*.py"):
            text = self._read_text(path)
            assert "retrieval_eval" not in text, (
                f"Vector module imports retrieval_eval: {path}"
            )

    def test_no_chunk_builder_internals_changed(self):
        for path in (REPO_ROOT / "wiki" / "chunks").rglob("*.py"):
            text = self._read_text(path)
            assert "retrieval_eval" not in text, (
                f"Chunk module imports retrieval_eval: {path}"
            )

    def test_cli_docstring_mentions_no_llm(self):
        text = self._read_text(REPO_ROOT / "wiki" / "retrieval_eval" / "runner.py")
        # The runner docstring or schema docstring should
        # not advertise LLM calls.
        assert "LLM" not in text or "no LLM" in text or "not call any LLM" in text

    def test_eval_retrieval_command_does_not_call_llm(self):
        # The CLI command must not import any LLM module.
        cli_text = self._read_text(REPO_ROOT / "wiki" / "cli.py")
        # The eval-retrieval command body should not call any
        # LLM provider. We assert by checking the local
        # imports inside the function body.
        m = re.search(
            r"def eval_retrieval\([\s\S]+?\) -> None:[\s\S]+?(?=\n@app\.command|\ndef [A-Za-z_])",
            cli_text,
        )
        assert m is not None, "eval_retrieval function not found in cli.py"
        body = m.group(0)
        for module in (
            "openai",
            "ollama",
            "gemini",
            "MockProvider",
            "OllamaCloudProvider",
            "OllamaLocalProvider",
            "OpenAICompatibleProvider",
        ):
            assert module not in body, (
                f"eval_retrieval body imports LLM module: {module}"
            )
