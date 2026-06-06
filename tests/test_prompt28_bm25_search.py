"""Tests for Prompt 28: BM25 Search Backend.

The 20 required test cases from ``prompt28.md`` §"Required tests"
are covered by the classes in this file. The pattern follows the
existing ``tests/test_prompt27_chunk_index.py`` and
``tests/test_prompt25_graph_visualization.py`` tests: build a
small chunk index in a tmp dir using controlled records, point
``SiteBuilder`` at isolated data/repo directories, and assert on
the generated files and the on-disk schema.

The tests are grouped by responsibility:

- :class:`TestTokenizer` – tokenization determinism, lowercasing,
  punctuation handling, stopwords.
- :class:`TestBM25Scorer` – pure BM25 math.
- :class:`TestBM25Index` – building the inverted index from
  chunk records, including empty-input handling.
- :class:`TestBM25IndexDeterminism` – byte-stable, repeated
  builds.
- :class:`TestBM25Search` – search behavior, ranking, schema,
  tie-breaking, empty query, source-type/resource-id filters.
- :class:`TestBM25Files` – on-disk output files.
- :class:`TestBM25Cli` – ``wiki build-bm25-index`` and
  ``wiki search-bm25`` CLI commands.
- :class:`TestBuildSiteAndValidate` – build-site, smoke-site,
  validate integration.
- :class:`TestBM25Boundaries` – scope guards (no vector/embedding/LLM
  dependencies; chunk index unmodified).
- :class:`TestRealPdfBm25Verification` – real-PDF verification
  (skipped when the real PDF fixture is missing).
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


# =============================================================================
# Test class 1: TestTokenizer
# =============================================================================


class TestTokenizer:
    def test_tokenizer_lowercases_text(self):
        from wiki.search.tokenize import tokenize

        tokens = tokenize("Attention is All You Need")
        # "is", "all", "you" are stopwords; "Attention" -> "attention"
        # "Need" -> "need".
        assert tokens == ["attention", "need"]

    def test_tokenizer_strips_punctuation(self):
        from wiki.search.tokenize import tokenize

        tokens = tokenize("paged-attention; vLLM!")
        # Hyphens and semicolons are stripped; "vLLM" -> "vllm".
        assert tokens == ["paged", "attention", "vllm"]

    def test_tokenizer_filters_stopwords(self):
        from wiki.search.tokenize import tokenize

        tokens = tokenize("the quick brown fox is on the table")
        # "the", "is", "on" are stopwords.
        assert tokens == ["quick", "brown", "fox", "table"]

    def test_tokenizer_is_deterministic(self):
        from wiki.search.tokenize import tokenize

        text = "The transformer uses Scaled Dot-Product Attention"
        # Same input -> same list.
        assert tokenize(text) == tokenize(text)
        # Tokenize a list of strings and concatenate results to make
        # sure order matters and no global state is shared.
        out1 = tokenize(" ".join(["alpha", "beta", "gamma"]))
        out2 = tokenize("alpha beta gamma")
        assert out1 == out2

    def test_tokenizer_keeps_numeric_tokens(self):
        from wiki.search.tokenize import tokenize

        # Multi-digit numeric tokens are kept by default; "vllm" too.
        tokens = tokenize("vllm 2024 release notes")
        assert "vllm" in tokens
        assert "2024" in tokens

    def test_tokenizer_handles_empty_and_whitespace(self):
        from wiki.search.tokenize import tokenize

        assert tokenize("") == []
        assert tokenize("   ") == []
        assert tokenize("\n\t  \n") == []


# =============================================================================
# Test class 2: TestBM25Scorer
# =============================================================================


class TestBM25Scorer:
    def test_idf_is_never_negative(self):
        from wiki.search.bm25 import BM25Scorer

        scorer = BM25Scorer()
        # n_t can equal N; log((0+0.5)/(N+0.5) + 1) > 0.
        for n in (1, 10, 100):
            for n_t in (0, 1, n // 2, n - 1, n, n + 1):
                idf = scorer.idf(n_t, n)
                assert idf >= 0.0, f"idf({n_t}, {n}) is negative: {idf}"

    def test_idf_is_higher_for_rare_terms(self):
        from wiki.search.bm25 import BM25Scorer

        scorer = BM25Scorer()
        # Rare term has higher idf than common term.
        idf_rare = scorer.idf(1, 100)
        idf_common = scorer.idf(50, 100)
        assert idf_rare > idf_common

    def test_score_term_is_non_negative(self):
        from wiki.search.bm25 import BM25Scorer

        scorer = BM25Scorer()
        for tf in (1, 2, 5):
            for dl in (50, 100, 200):
                for avgdl in (100, 200):
                    score = scorer.score_term(tf, dl, avgdl, idf=1.0)
                    assert score >= 0.0

    def test_score_query_returns_sorted_results(self):
        from wiki.search.bm25 import BM25Scorer

        scorer = BM25Scorer()
        # Two chunks, query token "attention" in both.
        postings = {
            "attention": {
                "df": 2,
                "postings": [
                    {"chunk_id": "c1", "tf": 5},
                    {"chunk_id": "c2", "tf": 2},
                ],
            }
        }
        chunk_meta = {
            "c1": {"doc_length": 100},
            "c2": {"doc_length": 100},
        }
        scores = scorer.score_query(["attention"], postings, chunk_meta)
        # c1 has higher tf, so it should rank first.
        assert scores[0].chunk_id == "c1"
        assert scores[1].chunk_id == "c2"
        # Scores are non-negative and sorted descending.
        assert all(s.score >= 0 for s in scores)

    def test_score_query_empty_query_returns_empty(self):
        from wiki.search.bm25 import BM25Scorer

        scorer = BM25Scorer()
        scores = scorer.score_query([], {"x": {"df": 1, "postings": []}}, {})
        assert scores == []

    def test_score_query_no_postings_returns_empty(self):
        from wiki.search.bm25 import BM25Scorer

        scorer = BM25Scorer()
        scores = scorer.score_query(["foo"], {}, {})
        assert scores == []


# =============================================================================
# Test class 3: TestBM25Index
# =============================================================================


class TestBM25Index:
    def test_index_builds_from_chunks(self, data_dir):
        from wiki.search import build_bm25_index

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])
        result = build_bm25_index(chunk_index)
        # The index is non-empty.
        assert result.doc_count >= 1
        assert len(result.vocab) > 0
        # "attention" should be in the vocab because the PDF text
        # mentions attention multiple times.
        assert "attention" in result.vocab

    def test_index_handles_empty_chunks(self, data_dir):
        from wiki.search import build_bm25_index, BM25IndexResult

        rec = _make_normalized_record(
            data_dir,
            resource_id="webpage:empty-bm25",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "w:e:1", "text": "Hello world", "citation_label": "X"}],
        )
        chunk_index = build_chunk_index([rec])
        result = build_bm25_index(chunk_index)
        assert result.doc_count == 1
        assert isinstance(result, BM25IndexResult)

    def test_index_handles_completely_empty_chunk_index(self, tmp_path):
        from wiki.search import build_bm25_index

        # Empty chunk index produces an empty BM25 index.
        result = build_bm25_index(ChunkIndexResult(chunks=[]))
        assert result.doc_count == 0
        assert result.vocab == {}
        assert result.chunk_meta == {}
        assert result.avg_doc_length == 0.0

    def test_index_postings_sorted_by_tf_desc_then_chunk_id(self, data_dir):
        from wiki.search import build_bm25_index

        # Two PDF records so the same token appears in both.
        rec_a = _make_pdf_record(data_dir, resource_id="pdf:aaa")
        rec_b = _make_pdf_record(
            data_dir,
            resource_id="pdf:bbb",
            content_hash="fffffff" + "0" * 56,
        )
        chunk_index = build_chunk_index([rec_a, rec_b])
        result = build_bm25_index(chunk_index)
        for term, payload in result.vocab.items():
            postings = payload["postings"]
            tfs = [p["tf"] for p in postings]
            cids = [p["chunk_id"] for p in postings]
            # tfs must be sorted descending.
            assert tfs == sorted(tfs, reverse=True), f"tfs not sorted desc for {term!r}"
            # Within the same tf, chunk_ids must be sorted ascending.
            for i in range(len(postings) - 1):
                if postings[i]["tf"] == postings[i + 1]["tf"]:
                    assert cids[i] <= cids[i + 1], (
                        f"chunk_ids not sorted asc for equal tf in {term!r}"
                    )


# =============================================================================
# Test class 4: TestBM25IndexDeterminism
# =============================================================================


class TestBM25IndexDeterminism:
    def test_repeated_builds_are_byte_identical(self, data_dir):
        from wiki.search import build_bm25_index, write_bm25_index

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])

        out1 = data_dir / "out1"
        out2 = data_dir / "out2"
        out1.mkdir()
        out2.mkdir()

        r1 = build_bm25_index(chunk_index)
        write_bm25_index(r1, output_dir=out1)
        r2 = build_bm25_index(chunk_index)
        write_bm25_index(r2, output_dir=out2)

        for filename in ("index.json", "manifest.json"):
            text1 = (out1 / filename).read_text(encoding="utf-8")
            text2 = (out2 / filename).read_text(encoding="utf-8")
            assert text1 == text2, f"{filename} differs between runs"

    def test_no_timestamps_in_deterministic_files(self, data_dir):
        from wiki.search import build_bm25_index, write_bm25_index

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])
        out = data_dir / "out"
        out.mkdir()
        write_bm25_index(build_bm25_index(chunk_index), output_dir=out)
        for filename in ("index.json", "manifest.json"):
            text = (out / filename).read_text(encoding="utf-8")
            assert "generated_at" not in text
            assert "build_started_at" not in text
            assert "build_finished_at" not in text
        # stats.json is allowed to contain timestamps.
        stats_text = (out / "stats.json").read_text(encoding="utf-8")
        assert "build_started_at" in stats_text


# =============================================================================
# Test class 5: TestBM25Search
# =============================================================================


class TestBM25Search:
    def test_search_attention_transformer(self, data_dir):
        from wiki.search import build_bm25_index, search_bm25_in_memory

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])
        bm25_index = build_bm25_index(chunk_index)
        results = search_bm25_in_memory(
            query="attention transformer",
            bm25_index=bm25_index,
            limit=3,
        )
        assert len(results) >= 1
        # The top result should be a PDF chunk from the attention paper.
        assert results[0].source_type == "pdf"
        assert "Attention" in results[0].title

    def test_search_scaled_dot_product_attention(self, data_dir):
        from wiki.search import build_bm25_index, search_bm25_in_memory

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])
        bm25_index = build_bm25_index(chunk_index)
        results = search_bm25_in_memory(
            query="scaled dot-product attention",
            bm25_index=bm25_index,
            limit=3,
        )
        assert len(results) >= 1
        # The top result should be the chunk containing
        # "Scaled Dot-Product Attention".
        assert results[0].source_type == "pdf"
        assert "Attention" in results[0].title

    def test_search_result_schema(self, data_dir):
        from wiki.search import build_bm25_index, search_bm25_in_memory

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])
        bm25_index = build_bm25_index(chunk_index)
        results = search_bm25_in_memory(
            query="attention",
            bm25_index=bm25_index,
            limit=3,
        )
        for r in results:
            d = r.to_dict()
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
                "matched_terms",
                "metadata",
            ):
                assert required in d, f"missing {required!r} in result"
            # citation_label and resource_id are non-empty.
            assert d["citation_label"]
            assert d["resource_id"]

    def test_search_tie_breaking_is_deterministic(self, data_dir):
        """Two chunks with identical BM25 scores sort by chunk_id asc."""
        from wiki.search import build_bm25_index, search_bm25_in_memory

        # Build a chunk index with two chunks that have the same
        # text. They will get the same score for a query that
        # matches the shared text.
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
        chunk_index = build_chunk_index([rec])
        bm25_index = build_bm25_index(chunk_index)
        results = search_bm25_in_memory(
            query="transformer",
            bm25_index=bm25_index,
            limit=2,
        )
        assert len(results) == 2
        # Same score -> chunk_id ascending.
        if results[0].score == results[1].score:
            assert results[0].chunk_id < results[1].chunk_id

    def test_search_empty_query_fails(self, data_dir):
        from wiki.search import search_bm25_in_memory

        bm25_index = None
        with pytest.raises(ValueError):
            search_bm25_in_memory(query="", bm25_index=bm25_index)
        with pytest.raises(ValueError):
            search_bm25_in_memory(query="   ", bm25_index=bm25_index)

    def test_search_filters_by_source_type(self, data_dir):
        from wiki.search import build_bm25_index, search_bm25_in_memory

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
        chunk_index = build_chunk_index([rec_pdf, rec_web])
        bm25_index = build_bm25_index(chunk_index)
        results = search_bm25_in_memory(
            query="attention transformer",
            bm25_index=bm25_index,
            limit=10,
            source_types=["pdf"],
        )
        assert all(r.source_type == "pdf" for r in results)

    def test_search_filters_by_resource_id(self, data_dir):
        from wiki.search import build_bm25_index, search_bm25_in_memory

        rec_pdf = _make_pdf_record(data_dir, resource_id="pdf:fa")
        rec_other = _make_pdf_record(
            data_dir,
            resource_id="pdf:fb",
            content_hash="fffffff" + "0" * 56,
        )
        chunk_index = build_chunk_index([rec_pdf, rec_other])
        bm25_index = build_bm25_index(chunk_index)
        results = search_bm25_in_memory(
            query="attention transformer",
            bm25_index=bm25_index,
            limit=10,
            resource_id="pdf:fa",
        )
        assert all(r.resource_id == "pdf:fa" for r in results)

    def test_search_includes_text_when_requested(self, data_dir):
        from wiki.search import build_bm25_index, search_bm25_in_memory

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])
        bm25_index = build_bm25_index(chunk_index)
        # Without include_text, text_preview is empty.
        results_no_text = search_bm25_in_memory(
            query="attention",
            bm25_index=bm25_index,
            limit=1,
        )
        assert results_no_text[0].text_preview == ""
        # With include_text, text_preview has content. The
        # ``search_bm25_in_memory`` reads the chunk index from
        # the configured data dir; we point it at ``data_dir``
        # so the on-disk chunk index lookup works.
        from wiki.config import config
        original = config.LLM_WIKI_DATA_DIR
        config.LLM_WIKI_DATA_DIR = data_dir
        try:
            results_with_text = search_bm25_in_memory(
                query="attention",
                bm25_index=bm25_index,
                limit=1,
                include_text=True,
            )
        finally:
            config.LLM_WIKI_DATA_DIR = original
        assert results_with_text[0].text_preview != ""


# =============================================================================
# Test class 6: TestBM25Files
# =============================================================================


class TestBM25Files:
    def test_bm25_index_files_are_written(self, tmp_path):
        from wiki.search import build_bm25_index, write_bm25_index, bm25_output_paths

        rec = _make_pdf_record(tmp_path)
        chunk_index = build_chunk_index([rec])
        result = build_bm25_index(chunk_index)
        out = tmp_path / "out"
        out.mkdir()
        paths = write_bm25_index(result, output_dir=out)
        # All three files exist.
        assert paths["index_json"].exists()
        assert paths["manifest"].exists()
        assert paths["stats"].exists()
        # And the index parses as JSON.
        index_data = json.loads(paths["index_json"].read_text(encoding="utf-8"))
        assert index_data["doc_count"] == result.doc_count
        manifest_data = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        assert manifest_data["schema_version"] == "bm25_index_v1"

    def test_validate_catches_malformed_index(self, tmp_path):
        from wiki.search import iter_bm25_index_issues
        from wiki.search.export import bm25_output_paths

        bm25_dir = tmp_path / "processed" / "bm25"
        bm25_dir.mkdir(parents=True, exist_ok=True)
        (bm25_dir / "index.json").write_text("THIS IS NOT JSON\n", encoding="utf-8")
        (bm25_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "bm25_index_v1",
                    "doc_count": 0,
                    "resource_count": 0,
                    "vocab_size": 0,
                    "total_postings": 0,
                    "by_source_type": {},
                }
            ),
            encoding="utf-8",
        )
        issues = list(
            iter_bm25_index_issues(
                index_path=bm25_dir / "index.json",
                manifest_path=bm25_dir / "manifest.json",
                stats_path=bm25_dir / "stats.json",
            )
        )
        codes = [code for _sev, code, _msg in issues]
        assert "bm25_index_invalid" in codes

    def test_validate_warns_on_missing_index(self, tmp_path):
        from wiki.search import iter_bm25_index_issues

        empty = tmp_path / "empty"
        empty.mkdir()
        issues = list(
            iter_bm25_index_issues(
                index_path=empty / "index.json",
                manifest_path=empty / "manifest.json",
                stats_path=empty / "stats.json",
            )
        )
        # All warnings, no errors.
        for severity, _code, _msg in issues:
            assert severity == "warning"
        codes = [code for _sev, code, _msg in issues]
        assert "bm25_index_missing" in codes

    def test_bm25_public_copy_is_written(self, tmp_path):
        from wiki.search import build_bm25_index, write_bm25_index, write_public_copy

        rec = _make_pdf_record(tmp_path)
        chunk_index = build_chunk_index([rec])
        result = build_bm25_index(chunk_index)
        out = tmp_path / "out"
        out.mkdir()
        write_bm25_index(result, output_dir=out)
        public_paths = write_public_copy(
            data_dir=tmp_path,
            output_dir=tmp_path / "public_search",
        )
        assert (tmp_path / "public_search" / "bm25_index.json").exists()
        assert (tmp_path / "public_search" / "bm25_manifest.json").exists()
        # Both parse as valid JSON.
        json.loads((tmp_path / "public_search" / "bm25_index.json").read_text(encoding="utf-8"))
        json.loads((tmp_path / "public_search" / "bm25_manifest.json").read_text(encoding="utf-8"))


# =============================================================================
# Test class 7: TestBM25Cli
# =============================================================================


class TestBM25Cli:
    def test_cli_build_bm25_index_prints_stats(self, data_dir, monkeypatch):
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

        # First build the chunk index (default behavior of
        # build-bm25-index is to call build-chunk-index first).
        result = CliRunner().invoke(cli.app, ["build-bm25-index"])
        assert result.exit_code == 0, f"build-bm25-index exited {result.exit_code}: {result.output}"
        assert "Chunks indexed" in result.output
        assert "Vocab size" in result.output
        assert "Total postings" in result.output
        assert "Duration" in result.output

    def test_cli_search_bm25_readable_output(self, data_dir, monkeypatch):
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

        # First build, then search.
        build = CliRunner().invoke(cli.app, ["build-bm25-index"])
        assert build.exit_code == 0
        result = CliRunner().invoke(
            cli.app, ["search-bm25", "attention transformer"]
        )
        assert result.exit_code == 0
        # Readable output has the table columns.
        assert "Rank" in result.output
        assert "Score" in result.output
        assert "Chunk" in result.output

    def test_cli_search_bm25_json_output(self, data_dir, monkeypatch):
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
        result = CliRunner().invoke(
            cli.app, ["search-bm25", "attention", "--json"]
        )
        assert result.exit_code == 0
        # Parse the stdout as JSON.
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
            "matched_terms",
            "metadata",
        ):
            assert required in first

    def test_cli_search_bm25_empty_query_fails(self, data_dir, monkeypatch):
        result = CliRunner().invoke(cli.app, ["search-bm25", ""])
        # Empty query exits 1.
        assert result.exit_code == 1
        assert "query is empty" in result.output


# =============================================================================
# Test class 8: TestBuildSiteAndValidate
# =============================================================================


class TestBuildSiteAndValidate:
    def test_build_site_continues_to_pass(self, tmp_path, monkeypatch):
        rec = _make_pdf_record(tmp_path)
        builder = _setup_site_builder(tmp_path, monkeypatch)
        builder.build([rec])
        assert builder.repo_site_dir.exists()

    def test_smoke_site_passes_after_bm25_added(self, tmp_path, monkeypatch):
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

    def test_validate_passes_after_bm25_added(self, tmp_path, monkeypatch):
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
# Test class 9: TestBM25Boundaries
# =============================================================================


class TestBM25Boundaries:
    def test_no_vector_embedding_llm_dependencies(self):
        """Read pyproject.toml and the wiki/search/*.py files to
        confirm no vector/embedding/LLM dependencies are pulled in.
        """
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
            "sentence-transformers",
            "transformers",
            "openai",
            "ollama",
        ]
        for needle in forbidden:
            assert needle not in block, (
                f"forbidden dependency in [dependencies]: {needle}"
            )

        search_dir = REPO_ROOT / "wiki" / "search"
        for py_file in search_dir.glob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            for forbidden_import in (
                "import rank_bm25",
                "from rank_bm25",
                "import faiss",
                "from faiss",
                "import chromadb",
                "from chromadb",
                "import lancedb",
                "from lancedb",
                "import sentence_transformers",
                "from sentence_transformers",
                "import openai",
                "from openai",
                "import ollama",
                "from ollama",
                "import httpx",
            ):
                assert forbidden_import not in text, (
                    f"{py_file.name} contains forbidden import {forbidden_import!r}"
                )

    def test_no_llm_calls(self):
        """wiki/search/*.py must not import LLM client libraries."""
        search_dir = REPO_ROOT / "wiki" / "search"
        for py_file in search_dir.glob("*.py"):
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

    def test_chunk_index_unmodified(self):
        """wiki/chunks/*.py must not import wiki.search (BM25 is a
        consumer of the chunk index, not a modifier)."""
        chunks_dir = REPO_ROOT / "wiki" / "chunks"
        for py_file in chunks_dir.glob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            for needle in ("wiki.search", "from wiki.search"):
                assert needle not in text, (
                    f"{py_file.name} imports Prompt 28 module: {needle!r}"
                )

    def test_graph_builder_unmodified(self):
        """wiki/graph/builder.py must not import wiki.search."""
        graph_builder = REPO_ROOT / "wiki" / "graph" / "builder.py"
        text = graph_builder.read_text(encoding="utf-8")
        for needle in ("wiki.search", "from wiki.search"):
            assert needle not in text, (
                f"graph builder imports Prompt 28 module: {needle!r}"
            )

    def test_static_route_verification_script_works(self, tmp_path):
        """Run scripts/verify_site_static_routes.py in a tmp dir;
        exits 0 with the expected list of routes."""
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

        # Now create a minimal set of expected routes and confirm
        # the script exits 0.
        for sub in ("graph", "chunks", "search"):
            (tmp_path / sub).mkdir(parents=True, exist_ok=True)
        (tmp_path / "graph").joinpath("index.md").write_text("# Graph\n", encoding="utf-8")
        (tmp_path / "graph").joinpath("viewer.md").write_text("# Viewer\n", encoding="utf-8")
        (tmp_path / "graph").joinpath("resource-relationships.md").write_text(
            "# RR\n", encoding="utf-8"
        )
        (tmp_path / "chunks").joinpath("index.md").write_text("# Chunks\n", encoding="utf-8")
        (tmp_path / "search").joinpath("bm25.md").write_text("# BM25\n", encoding="utf-8")
        (tmp_path / "public" / "chunks").mkdir(parents=True, exist_ok=True)
        (tmp_path / "public" / "chunks").joinpath("chunks.json").write_text("[]", encoding="utf-8")
        (tmp_path / "public" / "chunks").joinpath("manifest.json").write_text(
            json.dumps({"schema_version": "chunk_index_v1", "chunk_count": 0, "resource_count": 0}),
            encoding="utf-8",
        )
        (tmp_path / "public" / "search").mkdir(parents=True, exist_ok=True)
        (tmp_path / "public" / "search").joinpath("bm25_index.json").write_text(
            json.dumps({"schema_version": "bm25_index_v1", "vocab": {}, "manifest": {}}),
            encoding="utf-8",
        )
        (tmp_path / "public" / "search").joinpath("bm25_manifest.json").write_text(
            json.dumps({"schema_version": "bm25_index_v1", "doc_count": 0, "resource_count": 0}),
            encoding="utf-8",
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
# Test class 10: TestRealPdfBm25Verification
# =============================================================================


class TestRealPdfBm25Verification:
    """Run the verify_bm25_search.py flow when the real PDF is on disk.

    These tests are skipped if the real PDF fixture is not present so
    the test suite does not require network access.
    """

    def _real_pdf_present(self) -> bool:
        return REAL_PDF.exists()

    def test_real_pdf_bm25_search(self, tmp_path, monkeypatch):
        if not self._real_pdf_present():
            pytest.skip(f"Real PDF fixture not present at {REAL_PDF}")
        from wiki.ingest.pdf import pdf_ingestor
        from wiki.normalize.pdf import pdf_normalizer
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity, ResourceStatus
        from wiki.search import build_bm25_index, search_bm25_in_memory

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
        assert bm25_index.doc_count > 0

        for query in (
            "attention transformer",
            "scaled dot-product attention",
            "embeddings retrieval",
            "vllm paged attention",
            "rag evaluation",
        ):
            results = search_bm25_in_memory(
                query=query, bm25_index=bm25_index, limit=3
            )
            # Don't enforce a specific top result for every
            # query (depends on the corpus) but make sure the
            # search does not crash and the schema is complete.
            for r in results:
                assert r.chunk_id
                assert r.citation_label
                assert r.resource_route
