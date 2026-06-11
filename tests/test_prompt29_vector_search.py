"""Tests for Prompt 29: Vector Search Backend.

The 26 required test cases from ``prompt29.md`` §"Required tests"
are covered by the classes in this file. The pattern follows the
existing ``tests/test_prompt28_bm25_search.py`` and
``tests/test_prompt27_chunk_index.py`` tests: build a small
chunk index in a tmp dir using controlled records, point
``SiteBuilder`` at isolated data/repo directories, and assert on
the generated files and the on-disk schema.

The tests are grouped by responsibility:

- :class:`TestVectorTokenizer` - tokenization determinism,
  lowercasing, punctuation handling, stopwords.
- :class:`TestTokenizerConsistency` - vector tokenizer matches
  the BM25 tokenizer byte-for-byte.
- :class:`TestVectorizer` - hashing determinism, sign
  distribution, IDF never-negative, L2 normalization, cosine
  symmetry / bounds.
- :class:`TestVectorIndex` - building the index from chunk
  records, including empty-input handling.
- :class:`TestVectorIndexDeterminism` - byte-stable, repeated
  builds.
- :class:`TestVectorSearch` - search behavior, ranking, schema,
  tie-breaking, empty query, source-type / resource-id filters.
- :class:`TestVectorFiles` - on-disk output files.
- :class:`TestVectorCli` - ``wiki build-vector-index`` and
  ``wiki search-vector`` CLI commands.
- :class:`TestBuildSiteAndValidate` - build-site, smoke-site,
  validate integration.
- :class:`TestVectorBoundaries` - scope guards (no
  vector/embedding/LLM dependencies; chunk index, BM25, graph
  builder unmodified).
- :class:`TestVectorRouteVerification` - the static route
  verification script supports the vector routes.
- :class:`TestRealPdfVectorVerification` - real-PDF verification
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
# Test class 1: TestVectorTokenizer
# =============================================================================


class TestVectorTokenizer:
    def test_tokenizer_lowercases_text(self):
        from wiki.vector.tokenize import tokenize

        tokens = tokenize("Attention is All You Need")
        # "is", "all", "you" are stopwords; "Attention" -> "attention"
        # "Need" -> "need".
        assert tokens == ["attention", "need"]

    def test_tokenizer_strips_punctuation(self):
        from wiki.vector.tokenize import tokenize

        tokens = tokenize("paged-attention; vLLM!")
        # Hyphens and semicolons are stripped; "vLLM" -> "vllm".
        assert tokens == ["paged", "attention", "vllm"]

    def test_tokenizer_filters_stopwords(self):
        from wiki.vector.tokenize import tokenize

        tokens = tokenize("the quick brown fox is on the table")
        # "the", "is", "on" are stopwords.
        assert tokens == ["quick", "brown", "fox", "table"]

    def test_tokenizer_is_deterministic(self):
        from wiki.vector.tokenize import tokenize

        text = "The transformer uses Scaled Dot-Product Attention"
        # Same input -> same list.
        assert tokenize(text) == tokenize(text)
        # Tokenize a list of strings and concatenate results to make
        # sure order matters and no global state is shared.
        out1 = tokenize(" ".join(["alpha", "beta", "gamma"]))
        out2 = tokenize("alpha beta gamma")
        assert out1 == out2

    def test_tokenizer_keeps_numeric_tokens(self):
        from wiki.vector.tokenize import tokenize

        # Multi-digit numeric tokens are kept by default; "vllm" too.
        tokens = tokenize("vllm 2024 release notes")
        assert "vllm" in tokens
        assert "2024" in tokens

    def test_tokenizer_handles_empty_and_whitespace(self):
        from wiki.vector.tokenize import tokenize

        assert tokenize("") == []
        assert tokenize("   ") == []
        assert tokenize("\n\t  \n") == []


# =============================================================================
# Test class 1b: TestTokenizerConsistency
# =============================================================================


class TestTokenizerConsistency:
    def test_vector_tokenizer_matches_bm25_tokenizer(self):
        """The vector tokenizer must produce the same tokens as the BM25 tokenizer.

        This guards the "shared contract" promise from
        ``PROMPT29_PLAN.md`` §"Tokenizer contract" - the two
        backends must be lexically aligned even though they
        physically live in different modules.
        """
        from wiki.search.tokenize import tokenize as bm25_tokenize
        from wiki.vector.tokenize import STOPWORDS, tokenize as vector_tokenize

        # Stopword lists must be byte-identical.
        from wiki.search.tokenize import STOPWORDS as BM25_STOPWORDS
        assert sorted(STOPWORDS) == sorted(BM25_STOPWORDS)

        samples = [
            "Attention is All You Need",
            "Scaled Dot-Product Attention",
            "vLLM uses paged-attention",
            "Embeddings and retrieval for RAG",
            "The quick brown fox is on the table",
            "vllm 0.6 release notes",
            "paged-attention; vLLM!",
            "   whitespace   tokens   ",
            "Unicode: café résumé naïve",
            "",
        ]
        for sample in samples:
            assert vector_tokenize(sample) == bm25_tokenize(sample), (
                f"vector/BM25 tokenize disagree on {sample!r}: "
                f"vector={vector_tokenize(sample)!r} bm25={bm25_tokenize(sample)!r}"
            )


# =============================================================================
# Test class 2: TestVectorizer
# =============================================================================


class TestVectorizer:
    def test_hash_token_is_deterministic(self):
        from wiki.vector.vectorizer import HashingTfidfVectorizer

        vec = HashingTfidfVectorizer()
        for token in ("attention", "transformer", "vllm", "rag"):
            d1, s1 = vec.hash_token(token)
            d2, s2 = vec.hash_token(token)
            assert d1 == d2
            assert s1 == s2
            assert 0 <= d1 < vec.config.dimension
            assert s1 in (-1, 1)

    def test_hash_token_distributes_over_dimension(self):
        from wiki.vector.vectorizer import HashingTfidfVectorizer

        vec = HashingTfidfVectorizer()
        # 2000 random-ish tokens should hit at least 50% of
        # the dimension range (uniform distribution).
        tokens = [f"token_{i:04d}" for i in range(2000)]
        seen = {vec.hash_token(t)[0] for t in tokens}
        assert len(seen) > vec.config.dimension * 0.5

    def test_idf_is_never_negative(self):
        from wiki.vector.vectorizer import HashingTfidfVectorizer

        vec = HashingTfidfVectorizer()
        # Two fake chunk counters.
        from collections import Counter
        per_chunk = [Counter({"a": 1}), Counter({"a": 1, "b": 1})]
        idf = vec.fit_idf(per_chunk)
        for term, weight in idf.items():
            assert weight >= 0.0

    def test_idf_is_higher_for_rare_terms(self):
        from collections import Counter

        from wiki.vector.vectorizer import HashingTfidfVectorizer

        vec = HashingTfidfVectorizer()
        # "rare" appears in 1/5 chunks, "common" in 4/5.
        per_chunk = [
            Counter({"rare": 1, "common": 1}),
            Counter({"common": 1}),
            Counter({"common": 1}),
            Counter({"common": 1}),
            Counter({"common": 1}),
        ]
        idf = vec.fit_idf(per_chunk)
        assert idf["rare"] > idf["common"]

    def test_l2_normalize_produces_unit_length(self):
        from wiki.vector.vectorizer import HashingTfidfVectorizer

        vec = HashingTfidfVectorizer()
        import math

        v = {1: 0.6, 7: 0.8}
        normed = vec._l2_normalize(v)
        length = math.sqrt(sum(w * w for w in normed.values()))
        assert abs(length - 1.0) < 1e-9

    def test_l2_normalize_empty_returns_empty(self):
        from wiki.vector.vectorizer import HashingTfidfVectorizer

        vec = HashingTfidfVectorizer()
        assert vec._l2_normalize({}) == {}

    def test_cosine_is_symmetric(self):
        from wiki.vector.vectorizer import HashingTfidfVectorizer

        vec = HashingTfidfVectorizer()
        a = {1: 0.5, 2: 0.5, 3: 0.5}
        b = {1: 0.7, 4: 0.3}
        assert abs(vec.cosine(a, b) - vec.cosine(b, a)) < 1e-12

    def test_cosine_of_empty_is_zero(self):
        from wiki.vector.vectorizer import HashingTfidfVectorizer

        vec = HashingTfidfVectorizer()
        assert vec.cosine({}, {1: 1.0}) == 0.0
        assert vec.cosine({1: 1.0}, {}) == 0.0
        assert vec.cosine({}, {}) == 0.0

    def test_cosine_of_unit_vectors_bounded(self):
        import math

        from wiki.vector.vectorizer import HashingTfidfVectorizer

        vec = HashingTfidfVectorizer()
        a = {1: 1.0 / math.sqrt(2), 2: 1.0 / math.sqrt(2)}
        b = {1: 1.0 / math.sqrt(2), 3: 1.0 / math.sqrt(2)}
        c = vec.cosine(a, b)
        assert -1.0 <= c <= 1.0


# =============================================================================
# Test class 3: TestVectorIndex
# =============================================================================


class TestVectorIndex:
    def test_index_builds_from_chunks(self, data_dir):
        from wiki.vector import build_vector_index

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])
        result = build_vector_index(chunk_index)
        # The index is non-empty.
        assert result.chunk_count >= 1
        assert result.vocab_size > 0
        # The IDF table contains terms.
        assert len(result.state.idf) > 0

    def test_index_handles_completely_empty_chunk_index(self, tmp_path):
        from wiki.vector import build_vector_index

        result = build_vector_index(ChunkIndexResult(chunks=[]))
        assert result.chunk_count == 0
        assert result.vocab_size == 0
        assert result.total_nnz == 0
        assert result.vectors == {}

    def test_index_vocab_idf_is_non_negative(self, data_dir):
        from wiki.vector import build_vector_index

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])
        result = build_vector_index(chunk_index)
        for term, weight in result.state.idf.items():
            assert weight >= 0.0


# =============================================================================
# Test class 4: TestVectorIndexDeterminism
# =============================================================================


class TestVectorIndexDeterminism:
    def test_repeated_builds_are_byte_identical(self, data_dir):
        from wiki.vector import build_vector_index, write_vector_index

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])

        out1 = data_dir / "out1"
        out2 = data_dir / "out2"
        out1.mkdir()
        out2.mkdir()

        r1 = build_vector_index(chunk_index)
        write_vector_index(r1, output_dir=out1)
        r2 = build_vector_index(chunk_index)
        write_vector_index(r2, output_dir=out2)

        for filename in ("index.json", "manifest.json"):
            text1 = (out1 / filename).read_text(encoding="utf-8")
            text2 = (out2 / filename).read_text(encoding="utf-8")
            assert text1 == text2, f"{filename} differs between runs"

    def test_no_timestamps_in_deterministic_files(self, data_dir):
        from wiki.vector import build_vector_index, write_vector_index

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])
        out = data_dir / "out"
        out.mkdir()
        write_vector_index(build_vector_index(chunk_index), output_dir=out)
        for filename in ("index.json", "manifest.json"):
            text = (out / filename).read_text(encoding="utf-8")
            assert "generated_at" not in text
            assert "build_started_at" not in text
            assert "build_finished_at" not in text
        # stats.json is allowed to contain timestamps.
        stats_text = (out / "stats.json").read_text(encoding="utf-8")
        assert "build_started_at" in stats_text


# =============================================================================
# Test class 5: TestVectorSearch
# =============================================================================


class TestVectorSearch:
    def test_search_attention_transformer(self, data_dir):
        from wiki.vector import (
            build_vector_index,
            search_vector_in_memory,
        )

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])
        vector_index = build_vector_index(chunk_index)
        results = search_vector_in_memory(
            query="attention transformer",
            vector_index=vector_index,
            limit=3,
        )
        assert len(results) >= 1
        # The top result should be a PDF chunk from the attention paper.
        assert results[0].source_type == "pdf"
        assert "Attention" in results[0].title

    def test_search_scaled_dot_product_attention(self, data_dir):
        from wiki.vector import (
            build_vector_index,
            search_vector_in_memory,
        )

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])
        vector_index = build_vector_index(chunk_index)
        results = search_vector_in_memory(
            query="scaled dot-product attention",
            vector_index=vector_index,
            limit=3,
        )
        assert len(results) >= 1
        # The top result should be the chunk containing
        # "Scaled Dot-Product Attention".
        assert results[0].source_type == "pdf"
        assert "Attention" in results[0].title

    def test_search_result_schema(self, data_dir):
        from wiki.vector import (
            build_vector_index,
            search_vector_in_memory,
        )

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])
        vector_index = build_vector_index(chunk_index)
        results = search_vector_in_memory(
            query="attention",
            vector_index=vector_index,
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
                "query_terms",
                "metadata",
            ):
                assert required in d, f"missing {required!r} in result"
            # citation_label and resource_id are non-empty.
            assert d["citation_label"]
            assert d["resource_id"]

    def test_search_tie_breaking_is_deterministic(self, data_dir):
        """Two chunks with identical cosine scores sort by chunk_id asc."""
        from wiki.vector import (
            build_vector_index,
            search_vector_in_memory,
        )

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
        vector_index = build_vector_index(chunk_index)
        results = search_vector_in_memory(
            query="transformer",
            vector_index=vector_index,
            limit=2,
        )
        assert len(results) == 2
        if results[0].score == results[1].score:
            assert results[0].chunk_id < results[1].chunk_id

    def test_search_empty_query_fails(self, data_dir):
        from wiki.vector import search_vector_in_memory

        vector_index = None
        with pytest.raises(ValueError):
            search_vector_in_memory(query="", vector_index=vector_index)
        with pytest.raises(ValueError):
            search_vector_in_memory(query="   ", vector_index=vector_index)

    def test_search_filters_by_source_type(self, data_dir):
        from wiki.vector import (
            build_vector_index,
            search_vector_in_memory,
        )

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
        vector_index = build_vector_index(chunk_index)
        results = search_vector_in_memory(
            query="attention transformer",
            vector_index=vector_index,
            limit=10,
            source_types=["pdf"],
        )
        assert all(r.source_type == "pdf" for r in results)

    def test_search_filters_by_resource_id(self, data_dir):
        from wiki.vector import (
            build_vector_index,
            search_vector_in_memory,
        )

        rec_pdf = _make_pdf_record(data_dir, resource_id="pdf:fa")
        rec_other = _make_pdf_record(
            data_dir,
            resource_id="pdf:fb",
            content_hash="fffffff" + "0" * 56,
        )
        chunk_index = build_chunk_index([rec_pdf, rec_other])
        vector_index = build_vector_index(chunk_index)
        results = search_vector_in_memory(
            query="attention transformer",
            vector_index=vector_index,
            limit=10,
            resource_id="pdf:fa",
        )
        assert all(r.resource_id == "pdf:fa" for r in results)

    def test_search_includes_text_when_requested(self, data_dir):
        from wiki.vector import (
            build_vector_index,
            search_vector_in_memory,
        )

        rec = _make_pdf_record(data_dir)
        chunk_index = build_chunk_index([rec])
        vector_index = build_vector_index(chunk_index)
        # Without include_text, text_preview is the truncated
        # preview already in the index (still non-empty here
        # because the chunks have text).
        results_no_text = search_vector_in_memory(
            query="attention",
            vector_index=vector_index,
            limit=1,
        )
        assert results_no_text[0].text_preview != ""
        # With include_text, text_preview is loaded from the
        # chunk index on disk. Point the runtime at our tmp
        # data dir so the on-disk chunk index lookup works.
        from wiki.config import config
        original = config.LLM_WIKI_DATA_DIR
        config.LLM_WIKI_DATA_DIR = data_dir
        try:
            results_with_text = search_vector_in_memory(
                query="attention",
                vector_index=vector_index,
                limit=1,
                include_text=True,
            )
        finally:
            config.LLM_WIKI_DATA_DIR = original
        # Both should have non-empty previews; the include_text
        # version may simply be the full first 240 chars.
        assert results_with_text[0].text_preview != ""


# =============================================================================
# Test class 6: TestVectorFiles
# =============================================================================


class TestVectorFiles:
    def test_vector_index_files_are_written(self, tmp_path):
        from wiki.vector import (
            build_vector_index,
            vector_output_paths,
            write_vector_index,
        )

        rec = _make_pdf_record(tmp_path)
        chunk_index = build_chunk_index([rec])
        result = build_vector_index(chunk_index)
        out = tmp_path / "out"
        out.mkdir()
        paths = write_vector_index(result, output_dir=out)
        # All three files exist.
        assert paths["index_json"].exists()
        assert paths["manifest"].exists()
        assert paths["stats"].exists()
        # And the index parses as JSON.
        index_data = json.loads(paths["index_json"].read_text(encoding="utf-8"))
        assert index_data["chunk_count"] == result.chunk_count
        manifest_data = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        assert manifest_data["schema_version"] == "vector_index_v1"

    def test_validate_catches_malformed_index(self, tmp_path):
        from wiki.vector import iter_vector_index_issues
        from wiki.vector.export import vector_output_paths

        vector_dir = tmp_path / "processed" / "vector"
        vector_dir.mkdir(parents=True, exist_ok=True)
        (vector_dir / "index.json").write_text("THIS IS NOT JSON\n", encoding="utf-8")
        (vector_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "vector_index_v1",
                    "chunk_count": 0,
                    "resource_count": 0,
                    "dimension": 1024,
                    "vocab_size": 0,
                    "total_nnz": 0,
                    "vectorizer_name": "hashing_tfidf",
                }
            ),
            encoding="utf-8",
        )
        issues = list(
            iter_vector_index_issues(
                index_path=vector_dir / "index.json",
                manifest_path=vector_dir / "manifest.json",
                stats_path=vector_dir / "stats.json",
            )
        )
        codes = [code for _sev, code, _msg in issues]
        assert "vector_index_invalid" in codes

    def test_validate_warns_on_missing_index(self, tmp_path):
        from wiki.vector import iter_vector_index_issues

        empty = tmp_path / "empty"
        empty.mkdir()
        issues = list(
            iter_vector_index_issues(
                index_path=empty / "index.json",
                manifest_path=empty / "manifest.json",
                stats_path=empty / "stats.json",
            )
        )
        # All warnings, no errors.
        for severity, _code, _msg in issues:
            assert severity == "warning"
        codes = [code for _sev, code, _msg in issues]
        assert "vector_index_missing" in codes

    def test_vector_public_copy_is_written(self, tmp_path):
        from wiki.vector import (
            build_vector_index,
            write_public_copy,
            write_vector_index,
        )

        rec = _make_pdf_record(tmp_path)
        chunk_index = build_chunk_index([rec])
        result = build_vector_index(chunk_index)
        out = tmp_path / "out"
        out.mkdir()
        write_vector_index(result, output_dir=out)
        public_paths = write_public_copy(
            data_dir=tmp_path,
            output_dir=tmp_path / "public_search",
        )
        assert (tmp_path / "public_search" / "vector_index.json").exists()
        assert (tmp_path / "public_search" / "vector_manifest.json").exists()
        # Both parse as valid JSON.
        json.loads((tmp_path / "public_search" / "vector_index.json").read_text(encoding="utf-8"))
        json.loads((tmp_path / "public_search" / "vector_manifest.json").read_text(encoding="utf-8"))


# =============================================================================
# Test class 7: TestVectorCli
# =============================================================================


class TestVectorCli:
    def test_cli_build_vector_index_prints_stats(self, data_dir, monkeypatch):
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

        result = CliRunner().invoke(cli.app, ["build-vector-index"])
        assert result.exit_code == 0, f"build-vector-index exited {result.exit_code}: {result.output}"
        assert "Chunks indexed" in result.output
        assert "Dimension" in result.output
        assert "Vocab size" in result.output
        assert "Total NNZ" in result.output
        assert "Duration" in result.output

    def test_cli_search_vector_readable_output(self, data_dir, monkeypatch):
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

        build = CliRunner().invoke(cli.app, ["build-vector-index"])
        assert build.exit_code == 0
        result = CliRunner().invoke(
            cli.app, ["search-vector", "attention transformer"]
        )
        assert result.exit_code == 0
        # Readable output has the table columns.
        assert "Rank" in result.output
        assert "Score" in result.output
        assert "Chunk" in result.output

    def test_cli_search_vector_json_output(self, data_dir, monkeypatch):
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

        CliRunner().invoke(cli.app, ["build-vector-index"])
        result = CliRunner().invoke(
            cli.app, ["search-vector", "attention", "--json"]
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
            "query_terms",
            "metadata",
        ):
            assert required in first

    def test_cli_search_vector_empty_query_fails(self, data_dir, monkeypatch):
        result = CliRunner().invoke(cli.app, ["search-vector", ""])
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

    def test_smoke_site_passes_after_vector_added(self, tmp_path, monkeypatch):
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

    def test_validate_passes_after_vector_added(self, tmp_path, monkeypatch):
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
# Test class 9: TestVectorBoundaries
# =============================================================================


class TestVectorBoundaries:
    def test_no_vector_embedding_llm_dependencies(self):
        """Read pyproject.toml and the wiki/vector/*.py files to
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

        vector_dir = REPO_ROOT / "wiki" / "vector"
        for py_file in vector_dir.glob("*.py"):
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

    def test_no_llm_calls(self):
        """wiki/vector/*.py must not import LLM client libraries."""
        vector_dir = REPO_ROOT / "wiki" / "vector"
        for py_file in vector_dir.glob("*.py"):
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

    def test_bm25_unmodified(self):
        """The BM25 code (Prompt 28) must not be modified by Prompt 29."""
        bm25_file = REPO_ROOT / "wiki" / "search" / "bm25.py"
        text = bm25_file.read_text(encoding="utf-8")
        # No import of wiki.vector in the BM25 module.
        for needle in ("wiki.vector", "from wiki.vector"):
            assert needle not in text, (
                f"wiki/search/bm25.py contains Prompt 29 import: {needle!r}"
            )

    def test_chunk_index_unmodified(self):
        """wiki/chunks/*.py must not import wiki.vector (vector backend
        is a consumer of the chunk index, not a modifier)."""
        chunks_dir = REPO_ROOT / "wiki" / "chunks"
        for py_file in chunks_dir.glob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            for needle in ("wiki.vector", "from wiki.vector"):
                assert needle not in text, (
                    f"{py_file.name} imports Prompt 29 module: {needle!r}"
                )

    def test_graph_builder_unmodified(self):
        """wiki/graph/builder.py must not import wiki.vector."""
        graph_builder = REPO_ROOT / "wiki" / "graph" / "builder.py"
        text = graph_builder.read_text(encoding="utf-8")
        for needle in ("wiki.vector", "from wiki.vector"):
            assert needle not in text, (
                f"graph builder imports Prompt 29 module: {needle!r}"
            )

    def test_vector_package_does_not_import_bm25(self):
        """wiki/vector/*.py must not import wiki.search (the BM25 package)."""
        vector_dir = REPO_ROOT / "wiki" / "vector"
        for py_file in vector_dir.glob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            # We allow docstring/comment references to wiki.search
            # but not actual import statements. Look for the
            # canonical import forms only.
            for needle in (
                "import wiki.search",
                "from wiki.search",
            ):
                assert needle not in text, (
                    f"{py_file.name} imports BM25 module: {needle!r}"
                )

    def test_static_route_verification_script_works(self, tmp_path):
        """Run scripts/verify_site_static_routes.py in a tmp dir;
        exits 0 with the expected list of routes (including the
        new vector routes)."""
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
        # the new vector routes) and confirm the script exits 0.
        for sub in ("graph", "chunks", "search", "public", "ingest", "operations", "control", "settings"):
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
        (tmp_path / "operations").joinpath("index.md").write_text("# Operations\n", encoding="utf-8")
        (tmp_path / "control").joinpath("index.md").write_text(
            "# Control\n", encoding="utf-8"
        )
        (tmp_path / "settings").joinpath("index.md").write_text(
            "# Settings\n", encoding="utf-8"
        )
        (tmp_path / "chunks").joinpath("index.md").write_text("# Chunks\n", encoding="utf-8")
        (tmp_path / "search").joinpath("bm25.md").write_text("# BM25\n", encoding="utf-8")
        (tmp_path / "public").joinpath("site-branding.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "runtime_identity_v1",
                    "defaultOwnerName": "Harish",
                    "defaultSiteTitle": "Harish LLM Wiki",
                    "allowBrowserOverride": True,
                }
            ),
            encoding="utf-8",
        )
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
        # Vector routes
        (tmp_path / "search").joinpath("vector.md").write_text("# Vector\n", encoding="utf-8")
        (tmp_path / "public" / "search").joinpath("vector_index.json").write_text(
            json.dumps({"schema_version": "vector_index_v1", "vocab_summary": {}, "manifest": {}}),
            encoding="utf-8",
        )
        (tmp_path / "public" / "search").joinpath("vector_manifest.json").write_text(
            json.dumps({"schema_version": "vector_index_v1", "chunk_count": 0, "resource_count": 0}),
            encoding="utf-8",
        )

        # Prompt 30: hybrid retrieval report page.
        (tmp_path / "search").joinpath("retrieval.md").write_text("# Retrieval\n", encoding="utf-8")

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
# Test class 10: TestRealPdfVectorVerification
# =============================================================================


class TestRealPdfVectorVerification:
    """Run the verify_vector_search.py flow when the real PDF is on disk.

    These tests are skipped if the real PDF fixture is not present so
    the test suite does not require network access.
    """

    def _real_pdf_present(self) -> bool:
        return REAL_PDF.exists()

    def test_real_pdf_vector_search(self, tmp_path, monkeypatch):
        if not self._real_pdf_present():
            pytest.skip(f"Real PDF fixture not present at {REAL_PDF}")
        from wiki.ingest.pdf import pdf_ingestor
        from wiki.normalize.pdf import pdf_normalizer
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity, ResourceStatus
        from wiki.vector import (
            build_vector_index,
            search_vector_in_memory,
        )

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
        vector_index = build_vector_index(chunk_index)
        assert vector_index.chunk_count > 0

        for query in (
            "attention transformer",
            "scaled dot-product attention",
            "embeddings retrieval",
            "vllm paged attention",
            "rag evaluation",
        ):
            results = search_vector_in_memory(
                query=query, vector_index=vector_index, limit=3
            )
            for r in results:
                assert r.chunk_id
                assert r.citation_label
                assert r.resource_route
