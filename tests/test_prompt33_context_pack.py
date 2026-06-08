"""Tests for Prompt 33: Context-Pack Builder.

The 20+ test cases from ``prompt33.md`` §"Testing requirements"
are covered by the classes in this file. The pattern follows
the existing ``tests/test_prompt30_hybrid_retrieval.py``,
``tests/test_prompt31_retrieval_eval.py``, and
``tests/test_prompt32_retrieval_eval_report.py`` tests: build
a small chunk index in a tmp dir using controlled records,
point the SiteBuilder at isolated data/repo directories, and
assert on the deterministic context-pack output.

The tests are grouped by responsibility:

- :class:`TestContextPackSchema` — the dataclass schema and
  ``to_dict()`` contract for ``ContextChunk``,
  ``ContextSource``, and ``ContextPack``.
- :class:`TestContextPackBuilder` — the in-memory builder
  across all four retrieval modes.
- :class:`TestContextPackOutput` — the readable (Markdown)
  and JSON output formatters.
- :class:`TestContextPackCli` — the ``wiki build-context``
  CLI command (readable, JSON, --max-chars, graph-lite mode).
- :class:`TestContextPackBoundaries` — scope guards (no
  LLM/embedding/vector-DB imports; no retrieval scoring
  changes; no Prompt 34 files; no answer generation; no
  prompt template package).
- :class:`TestContextPackFullSuite` — full-suite
  compatibility: the new tests don't break the existing
  Prompt 30 / 31 / 32 boundaries.
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
from wiki.chunks import build_chunk_index
from wiki.config import config
from wiki.context_pack import (
    CONTEXT_PACK_SCHEMA_VERSION,
    DEFAULT_LIMIT,
    DEFAULT_MAX_CHARS,
    DEFAULT_MODE,
    MAX_LIMIT,
    ContextChunk,
    ContextPack,
    ContextSource,
    build_context_pack_in_memory,
    make_citation_label,
)
from wiki.retrieval.schema import (
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
# Constants and helpers
# =============================================================================


REPO_ROOT = Path(__file__).parent.parent.resolve()


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


def _make_pdf_record(
    tmp_path: Path,
    *,
    resource_id: str = "pdf:033456789abcdef033456789abcdef033456789abcdef033456789abcdef",
    title: str = "Attention Is All You Need",
    content_hash: Optional[str] = None,
    page_chunks: Optional[List[dict]] = None,
) -> ResourceRecord:
    """Build a PDF record with a deterministic on-disk ``chunks.json`` mirror."""
    if content_hash is None:
        content_hash = "033456789abcdef0" * 4  # 64 hex chars
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
                "based solely on attention mechanisms, dispensing with recurrence "
                "and convolutions entirely."
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


def _write_chunk_index(
    chunk_index, *, data_dir: Path
) -> None:
    """Persist the chunk index to ``processed/chunk_index/chunks.json``."""
    from wiki.chunks.export import write_chunk_index

    write_chunk_index(chunk_index)


def _build_indexes(tmp_path: Path, records: List[ResourceRecord]) -> tuple:
    """Build a chunk index, BM25 index, and vector index from records."""
    from wiki.search import build_bm25_index, write_bm25_index
    from wiki.vector import build_vector_index, write_vector_index

    chunk_index = build_chunk_index(records)
    bm25_index = build_bm25_index(chunk_index)
    vector_index = build_vector_index(chunk_index)
    _write_chunk_index(chunk_index, data_dir=tmp_path)
    write_bm25_index(bm25_index)
    write_vector_index(vector_index)
    return chunk_index, bm25_index, vector_index


def _make_retrieval_result(
    *,
    chunk_id: str,
    resource_id: str = "pdf:abc",
    title: str = "Sample",
    source_type: str = "pdf",
    rank: int = 1,
    score: float = 1.0,
    text_preview: str = "preview",
    citation_label: str = "pages 1-3",
    resource_route: str = "/resources/pdf_abc",
    source_ref: Optional[dict] = None,
    mode: str = "hybrid",
) -> RetrievalResult:
    """Build a :class:`RetrievalResult` for unit tests."""
    return RetrievalResult(
        rank=rank,
        score=float(score),
        chunk_id=str(chunk_id),
        resource_id=str(resource_id),
        title=str(title),
        source_type=str(source_type),
        text_preview=str(text_preview),
        citation_label=str(citation_label),
        resource_route=str(resource_route),
        source_ref=source_ref or {"kind": "pdf_pages"},
        mode=str(mode),
        component_scores=ComponentScores(
            bm25=0.0,
            vector=0.0,
            graph_boost=0.0,
            normalized_bm25=0.0,
            normalized_vector=0.0,
            final=float(score),
        ),
        matched_terms=[],
        explanation=Explanation(),
        metadata={},
    )


def _write_chunk_index_payload(
    tmp_path: Path, *, payload: list
) -> Path:
    """Write a synthetic ``chunks.json`` payload to the chunk index dir."""
    out_path = tmp_path / "processed" / "chunk_index" / "chunks.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return out_path


# =============================================================================
# Test class 1: TestContextPackSchema
# =============================================================================


class TestContextPackSchema:
    """The dataclass schema and ``to_dict()`` contract."""

    def test_schema_fields(self):
        """Test 1: schema fields are present and typed."""
        chunk = ContextChunk(
            rank=1,
            citation_label="[cite:1]",
            resource_id="pdf:abc",
            chunk_id="pdf:abc-p0001",
            title="Sample",
            source_type="pdf",
            score=0.5,
            text="hello world",
            truncated=False,
        )
        d = chunk.to_dict()
        for required in (
            "rank",
            "citation_label",
            "resource_id",
            "chunk_id",
            "title",
            "source_type",
            "score",
            "text",
            "truncated",
        ):
            assert required in d, f"missing {required!r} in ContextChunk.to_dict()"
        assert d["rank"] == 1
        assert d["citation_label"] == "[cite:1]"
        assert d["score"] == 0.5
        assert d["truncated"] is False

    def test_context_source_schema_fields(self):
        """Test 2: ContextSource schema fields are present."""
        source = ContextSource(
            citation_label="[cite:1]",
            resource_id="pdf:abc",
            title="Sample",
            source_type="pdf",
            chunk_ids=["pdf:abc-p0001", "pdf:abc-p0002"],
        )
        d = source.to_dict()
        for required in (
            "citation_label",
            "resource_id",
            "title",
            "source_type",
            "chunk_ids",
        ):
            assert required in d, f"missing {required!r} in ContextSource.to_dict()"
        assert d["chunk_ids"] == ["pdf:abc-p0001", "pdf:abc-p0002"]

    def test_context_pack_schema_fields(self):
        """Test 3: ContextPack schema fields are present in stable order."""
        pack = ContextPack(
            schema_version=CONTEXT_PACK_SCHEMA_VERSION,
            query="attention transformer",
            mode="hybrid",
            limit=10,
            max_chars=0,
            used_chars=0,
            total_chunks=0,
            chunks=[],
            sources=[],
        )
        d = pack.to_dict()
        for required in (
            "schema_version",
            "query",
            "mode",
            "limit",
            "max_chars",
            "used_chars",
            "total_chunks",
            "chunks",
            "sources",
        ):
            assert required in d, f"missing {required!r} in ContextPack.to_dict()"
        # Top-level key order is stable: schema_version is the first key.
        keys = list(d.keys())
        assert keys[0] == "schema_version", (
            f"schema_version must be the first key, got {keys[0]!r}"
        )
        # The expected stable order:
        assert keys == [
            "schema_version",
            "query",
            "mode",
            "limit",
            "max_chars",
            "used_chars",
            "total_chunks",
            "chunks",
            "sources",
        ]

    def test_make_citation_label_format(self):
        """Test 4: make_citation_label returns ``[cite:N]``."""
        assert make_citation_label(1) == "[cite:1]"
        assert make_citation_label(2) == "[cite:2]"
        assert make_citation_label(42) == "[cite:42]"


# =============================================================================
# Test class 2: TestContextPackBuilder
# =============================================================================


class TestContextPackBuilder:
    """The in-memory builder across all four retrieval modes."""

    def test_deterministic_ordering(self, tmp_path):
        """Test 5: same input -> same output (stable ordering)."""
        r1 = _make_retrieval_result(chunk_id="c1", rank=1, score=0.9)
        r2 = _make_retrieval_result(chunk_id="c2", rank=2, score=0.5)
        r3 = _make_retrieval_result(chunk_id="c3", rank=3, score=0.1)
        pack1 = build_context_pack_in_memory(
            query="q", results=[r1, r2, r3], data_dir=tmp_path
        )
        pack2 = build_context_pack_in_memory(
            query="q", results=[r1, r2, r3], data_dir=tmp_path
        )
        assert pack1.to_dict() == pack2.to_dict()
        # Ranks are 1, 2, 3 in input order.
        assert [c.rank for c in pack1.chunks] == [1, 2, 3]
        assert [c.chunk_id for c in pack1.chunks] == ["c1", "c2", "c3"]

    def test_stable_citation_labels(self, tmp_path):
        """Test 6: citation labels are stable and match the rank."""
        results = [
            _make_retrieval_result(chunk_id=f"c{i}", rank=i, score=1.0 - i * 0.1)
            for i in range(1, 6)
        ]
        pack = build_context_pack_in_memory(
            query="q", results=results, data_dir=tmp_path
        )
        for chunk in pack.chunks:
            assert chunk.citation_label == f"[cite:{chunk.rank}]"

    def test_duplicate_chunk_dedup_first_seen(self, tmp_path):
        """Test 7: duplicate chunk_ids are removed; first-seen wins."""
        r1 = _make_retrieval_result(chunk_id="c1", rank=1, score=0.9)
        r1_dup = _make_retrieval_result(chunk_id="c1", rank=99, score=0.001)
        r2 = _make_retrieval_result(chunk_id="c2", rank=2, score=0.5)
        pack = build_context_pack_in_memory(
            query="q", results=[r1, r1_dup, r2], data_dir=tmp_path
        )
        # c1 is kept once; c2 follows.
        assert [c.chunk_id for c in pack.chunks] == ["c1", "c2"]
        assert [c.rank for c in pack.chunks] == [1, 2]
        assert pack.total_chunks == 2

    def test_duplicate_source_dedup(self, tmp_path):
        """Test 8: duplicate resource_ids collapse into one source entry."""
        r1 = _make_retrieval_result(
            chunk_id="c1", resource_id="pdf:abc", rank=1
        )
        r2 = _make_retrieval_result(
            chunk_id="c2", resource_id="pdf:abc", rank=2
        )
        r3 = _make_retrieval_result(
            chunk_id="c3", resource_id="pdf:xyz", rank=3
        )
        pack = build_context_pack_in_memory(
            query="q", results=[r1, r2, r3], data_dir=tmp_path
        )
        # Two sources: pdf:abc first, pdf:xyz second.
        assert [s.resource_id for s in pack.sources] == ["pdf:abc", "pdf:xyz"]
        # pdf:abc lists both chunk_ids in citation order.
        assert pack.sources[0].chunk_ids == ["c1", "c2"]
        assert pack.sources[0].citation_label == "[cite:1]"
        # pdf:xyz has the third chunk.
        assert pack.sources[1].chunk_ids == ["c3"]

    def test_max_chars_trims_text(self, tmp_path):
        """Test 9: max_chars trims per-chunk text at a stable boundary."""
        long_text = "the quick brown fox jumps over the lazy dog " * 10
        _write_chunk_index_payload(
            tmp_path,
            payload=[
                {
                    "chunk_id": "c1",
                    "resource_id": "pdf:abc",
                    "title": "Sample",
                    "source_type": "pdf",
                    "text": long_text,
                    "citation_label": "pages 1-3",
                    "source_ref": {"kind": "pdf_pages"},
                    "resource_route": "/resources/pdf_abc",
                    "char_count": len(long_text),
                    "word_count": len(long_text.split()),
                    "token_estimate": len(long_text) // 4,
                    "chunk_index": 0,
                    "content_hash": "h",
                    "metadata": {"source_url": "", "tags": [], "topics": [], "extra": {}},
                }
            ],
        )
        r1 = _make_retrieval_result(chunk_id="c1", rank=1, score=1.0)
        pack = build_context_pack_in_memory(
            query="q", results=[r1], max_chars=80, data_dir=tmp_path
        )
        # The trimmed text ends with an ellipsis.
        assert pack.chunks[0].truncated is True
        assert pack.chunks[0].text.endswith("...")
        assert len(pack.chunks[0].text) <= 80

    def test_tiny_max_chars(self, tmp_path):
        """Test 10: tiny max_chars (e.g. 2) produces a stable, well-defined output."""
        long_text = "abcdefghijklmnopqrstuvwxyz"
        _write_chunk_index_payload(
            tmp_path,
            payload=[
                {
                    "chunk_id": "c1",
                    "resource_id": "pdf:abc",
                    "title": "Sample",
                    "source_type": "pdf",
                    "text": long_text,
                    "citation_label": "pages 1-3",
                    "source_ref": {"kind": "pdf_pages"},
                    "resource_route": "/resources/pdf_abc",
                    "char_count": len(long_text),
                    "word_count": len(long_text.split()),
                    "token_estimate": len(long_text) // 4,
                    "chunk_index": 0,
                    "content_hash": "h",
                    "metadata": {"source_url": "", "tags": [], "topics": [], "extra": {}},
                }
            ],
        )
        r1 = _make_retrieval_result(chunk_id="c1", rank=1, score=1.0)
        pack = build_context_pack_in_memory(
            query="q", results=[r1], max_chars=2, data_dir=tmp_path
        )
        # max_chars <= 3 produces a string of exactly max_chars dots.
        assert pack.chunks[0].truncated is True
        assert pack.chunks[0].text == ".."

    def test_empty_retrieval(self, tmp_path):
        """Test 11: empty result list produces a valid empty pack."""
        pack = build_context_pack_in_memory(
            query="q", results=[], data_dir=tmp_path
        )
        assert pack.total_chunks == 0
        assert pack.used_chars == 0
        assert pack.chunks == []
        assert pack.sources == []
        # Still a well-formed JSON document.
        d = pack.to_dict()
        assert d["total_chunks"] == 0
        assert d["chunks"] == []
        assert d["sources"] == []

    def test_chunks_preserve_text_from_chunk_index(self, tmp_path):
        """Test 12: chunk text is looked up from the chunk index, not the preview."""
        full_text = "The Transformer is a new model architecture."
        _write_chunk_index_payload(
            tmp_path,
            payload=[
                {
                    "chunk_id": "c1",
                    "resource_id": "pdf:abc",
                    "title": "Sample",
                    "source_type": "pdf",
                    "text": full_text,
                    "citation_label": "pages 1-3",
                    "source_ref": {"kind": "pdf_pages"},
                    "resource_route": "/resources/pdf_abc",
                    "char_count": len(full_text),
                    "word_count": len(full_text.split()),
                    "token_estimate": len(full_text) // 4,
                    "chunk_index": 0,
                    "content_hash": "h",
                    "metadata": {"source_url": "", "tags": [], "topics": [], "extra": {}},
                }
            ],
        )
        r1 = _make_retrieval_result(
            chunk_id="c1", rank=1, text_preview="TRUNCATED PREVIEW"
        )
        pack = build_context_pack_in_memory(
            query="q", results=[r1], data_dir=tmp_path
        )
        # Full text wins over the preview.
        assert pack.chunks[0].text == full_text
        assert pack.used_chars == len(full_text)

    def test_used_chars_sums_per_chunk_text(self, tmp_path):
        """Test 13: used_chars is the sum of per-chunk text lengths."""
        texts = {
            "c1": "short text one",
            "c2": "a slightly longer text two",
            "c3": "x",
        }
        _write_chunk_index_payload(
            tmp_path,
            payload=[
                {
                    "chunk_id": cid,
                    "resource_id": "pdf:abc" if cid != "c2" else "pdf:xyz",
                    "title": "Sample",
                    "source_type": "pdf",
                    "text": text,
                    "citation_label": "pages 1-3",
                    "source_ref": {"kind": "pdf_pages"},
                    "resource_route": "/resources/pdf_abc",
                    "char_count": len(text),
                    "word_count": len(text.split()),
                    "token_estimate": len(text) // 4,
                    "chunk_index": i,
                    "content_hash": "h",
                    "metadata": {"source_url": "", "tags": [], "topics": [], "extra": {}},
                }
                for i, (cid, text) in enumerate(texts.items())
            ],
        )
        results = [
            _make_retrieval_result(
                chunk_id=cid, rank=i + 1, resource_id="pdf:abc" if cid != "c2" else "pdf:xyz"
            )
            for i, cid in enumerate(texts)
        ]
        pack = build_context_pack_in_memory(
            query="q", results=results, data_dir=tmp_path
        )
        expected_used = sum(len(t) for t in texts.values())
        assert pack.used_chars == expected_used
        assert pack.total_chunks == 3

    def test_invalid_query_rejected(self, tmp_path):
        """Test 14: empty query is rejected."""
        with pytest.raises(ValueError):
            build_context_pack_in_memory(query="", results=[], data_dir=tmp_path)
        with pytest.raises(ValueError):
            build_context_pack_in_memory(query="   ", results=[], data_dir=tmp_path)

    def test_invalid_mode_rejected(self, tmp_path):
        """Test 15: invalid mode is rejected."""
        with pytest.raises(ValueError):
            build_context_pack_in_memory(
                query="q", results=[], mode="fuzzy", data_dir=tmp_path
            )

    def test_invalid_max_chars_rejected(self, tmp_path):
        """Test 16: negative max_chars is rejected."""
        with pytest.raises(ValueError):
            build_context_pack_in_memory(
                query="q", results=[], max_chars=-1, data_dir=tmp_path
            )

    def test_default_constants(self):
        """Test 17: default constants match the spec."""
        assert DEFAULT_MODE == "hybrid"
        assert DEFAULT_LIMIT == 10
        assert DEFAULT_MAX_CHARS == 0
        assert MAX_LIMIT == 100


# =============================================================================
# Test class 3: TestContextPackOutput
# =============================================================================


class TestContextPackOutput:
    """The readable (Markdown) and JSON output formatters."""

    def test_readable_output_includes_required_sections(self, tmp_path):
        """Test 18: readable output has Context Pack, query, mode, max chars, chunks, sources."""
        from wiki.context_pack.output import format_readable

        results = [
            _make_retrieval_result(chunk_id="c1", rank=1, resource_id="pdf:abc"),
            _make_retrieval_result(chunk_id="c2", rank=2, resource_id="pdf:abc"),
        ]
        pack = build_context_pack_in_memory(
            query="attention transformer",
            results=results,
            mode="hybrid",
            max_chars=4000,
            data_dir=tmp_path,
        )
        text = format_readable(pack)
        for marker in (
            "# Context Pack",
            "attention transformer",
            "`hybrid`",
            "Max chars (per chunk): 4000",
            "## Chunks",
            "## Sources",
            "[cite:1]",
            "[cite:2]",
        ):
            assert marker in text, f"missing marker: {marker!r}"

    def test_json_output_has_required_fields(self, tmp_path):
        """Test 19: JSON output includes schema_version, query, mode, limit, max_chars, used_chars, chunks, sources."""
        from wiki.context_pack.output import format_json

        results = [
            _make_retrieval_result(chunk_id="c1", rank=1, resource_id="pdf:abc"),
        ]
        pack = build_context_pack_in_memory(
            query="q", results=results, data_dir=tmp_path
        )
        out = format_json(pack)
        payload = json.loads(out)
        for required in (
            "schema_version",
            "query",
            "mode",
            "limit",
            "max_chars",
            "used_chars",
            "chunks",
            "sources",
        ):
            assert required in payload, f"missing field: {required!r}"
        assert payload["schema_version"] == CONTEXT_PACK_SCHEMA_VERSION
        assert payload["query"] == "q"
        assert isinstance(payload["chunks"], list)
        assert isinstance(payload["sources"], list)
        assert payload["chunks"][0]["citation_label"] == "[cite:1]"

    def test_json_output_is_deterministic(self, tmp_path):
        """Test 20: two builds with the same input produce identical JSON."""
        from wiki.context_pack.output import format_json

        results = [
            _make_retrieval_result(chunk_id="c1", rank=1, resource_id="pdf:abc"),
            _make_retrieval_result(chunk_id="c2", rank=2, resource_id="pdf:xyz"),
        ]
        pack_a = build_context_pack_in_memory(
            query="q", results=results, data_dir=tmp_path
        )
        pack_b = build_context_pack_in_memory(
            query="q", results=results, data_dir=tmp_path
        )
        assert format_json(pack_a) == format_json(pack_b)


# =============================================================================
# Test class 4: TestContextPackCli
# =============================================================================


class TestContextPackCli:
    """The ``wiki build-context`` CLI command."""

    def test_cli_empty_query_fails(self):
        result = CliRunner().invoke(cli.app, ["build-context", ""])
        assert result.exit_code == 1
        assert "query is empty" in result.output

    def test_cli_invalid_mode_fails(self):
        result = CliRunner().invoke(
            cli.app, ["build-context", "attention", "--mode", "fuzzy"]
        )
        assert result.exit_code == 1
        assert "mode" in result.output.lower()

    def test_cli_invalid_max_chars_fails(self):
        result = CliRunner().invoke(
            cli.app, ["build-context", "attention", "--max-chars", "-5"]
        )
        assert result.exit_code == 1
        assert "max-chars" in result.output

    def test_cli_readable_output(self, data_dir, monkeypatch):
        """Test 21: CLI readable output (Markdown) on a real index."""
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity

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
            cli.app, ["build-context", "attention"]
        )
        assert result.exit_code == 0, result.output
        for marker in (
            "# Context Pack",
            "## Chunks",
            "## Sources",
        ):
            assert marker in result.output, f"missing marker: {marker!r}"

    def test_cli_json_output(self, data_dir, monkeypatch):
        """Test 22: CLI --json output is a valid JSON document."""
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity

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
            cli.app, ["build-context", "attention", "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["schema_version"] == CONTEXT_PACK_SCHEMA_VERSION
        assert payload["query"] == "attention"
        assert isinstance(payload["chunks"], list)
        assert isinstance(payload["sources"], list)

    def test_cli_graph_lite_with_max_chars(self, data_dir, monkeypatch):
        """Test 23: CLI graph-lite + max-chars produces a trimmed pack."""
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity

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
            [
                "build-context",
                "attention",
                "--mode",
                "graph-lite",
                "--max-chars",
                "60",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["mode"] == "graph-lite"
        assert payload["max_chars"] == 60
        if payload["chunks"]:
            for chunk in payload["chunks"]:
                # The text is either empty or trimmed to <= 60.
                if chunk["truncated"]:
                    assert len(chunk["text"]) <= 60


# =============================================================================
# Test class 5: TestContextPackBoundaries
# =============================================================================


class TestContextPackBoundaries:
    """Scope guards for Prompt 33."""

    def test_no_llm_provider_imports(self):
        """No LLM, provider, OpenAI, Ollama, Gemini, or vector-DB imports."""
        for sub in ("__init__.py", "schema.py", "builder.py", "output.py"):
            text = (REPO_ROOT / "wiki" / "context_pack" / sub).read_text(
                encoding="utf-8"
            )
            for needle in (
                "openai",
                "ollama",
                "gemini",
                "langchain",
                "llama_index",
                "llamaindex",
                "faiss",
                "chroma",
                "qdrant",
                "lancedb",
                "milvus",
                "sentence_transformers",
                "transformers",
            ):
                assert needle not in text.lower(), (
                    f"context_pack/{sub} imports forbidden module {needle!r}"
                )

    def test_no_prompt_template_package(self):
        """No prompt builder or answer generation package."""
        for rel in (
            "wiki/prompt_builder.py",
            "wiki/answer_generator.py",
            "wiki/grounded_answer.py",
        ):
            assert not (REPO_ROOT / rel).exists(), (
                f"Prompt 33 boundary violation: {rel} must not exist"
            )
        for pkg in ("prompt_builder", "answer_generator", "grounded_answer"):
            assert not (REPO_ROOT / "wiki" / pkg).exists(), (
                f"Prompt 33 boundary violation: wiki/{pkg} package must not exist"
            )

    def test_no_answer_generation_in_context_pack(self):
        """No answer generation functions in the context_pack package."""
        for sub in ("__init__.py", "schema.py", "builder.py", "output.py"):
            text = (REPO_ROOT / "wiki" / "context_pack" / sub).read_text(
                encoding="utf-8"
            )
            for needle in (
                "generate_answer",
                "answer_generator",
                "ask_llm",
                "MockProvider",
                "OllamaLocalProvider",
                "OllamaCloudProvider",
                "OpenAICompatibleProvider",
                "completion",
            ):
                assert needle not in text, (
                    f"context_pack/{sub} contains answer-generation symbol {needle!r}"
                )

    def test_no_retrieval_scoring_changes(self):
        """The BM25, vector, fusion, and router files are unmodified."""
        for rel in (
            "wiki/search/bm25.py",
            "wiki/search/search.py",
            "wiki/vector/search.py",
            "wiki/vector/vectorizer.py",
            "wiki/retrieval/fusion.py",
            "wiki/retrieval/router.py",
            "wiki/retrieval/graph_lite.py",
        ):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            for needle in ("wiki.context_pack",):
                assert needle not in text, (
                    f"{rel} imports Prompt 33 module: {needle!r}"
                )

    def test_no_prompt34_files(self):
        """No Prompt 34 files exist in the repo yet."""
        for rel in (
            "tests/test_prompt34_chat_ui.py",
            "tests/test_prompt34_grounded_answer.py",
            "wiki/chat_ui.py",
            "wiki/answer_api.py",
            "scripts/verify_grounded_answer.py",
        ):
            assert not (REPO_ROOT / rel).exists(), (
                f"Prompt 34 file already present: {rel}"
            )

    def test_no_search_context_page(self):
        """Prompt 34 has landed: /search/context is now allowed.

        Prompt 33 still must not add duplicate context pages in unsupported
        locations.
        """
        for rel in (
            "site/docs/context.md",
            "site/docs/context/index.md",
            "site/docs/search/context/index.md",
            "site_generated/docs/context.md",
            "site_generated/docs/context/index.md",
            "site_generated/docs/search/context/index.md",
        ):
            assert not (REPO_ROOT / rel).exists(), (
                f"Unsupported duplicate context page exists: {rel}"
            )

    def test_pyproject_dependencies_unchanged(self):
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(
            r"^dependencies\s*=\s*\[(.*?)\]",
            pyproject,
            re.DOTALL | re.MULTILINE,
        )
        assert m, "could not locate dependencies block"
        block = m.group(1).lower()
        for needle in (
            "openai",
            "ollama",
            "faiss",
            "chroma",
            "lancedb",
            "qdrant",
            "milvus",
            "sentence-transformers",
            "transformers",
            "langchain",
            "llama-index",
        ):
            assert needle not in block, (
                f"Prompt 33 added forbidden dependency: {needle}"
            )

    def test_chunk_builder_unmodified(self):
        """The chunk builder was not modified by Prompt 33."""
        text = (REPO_ROOT / "wiki" / "chunks" / "builder.py").read_text(
            encoding="utf-8"
        )
        for needle in ("wiki.context_pack",):
            assert needle not in text, (
                f"wiki/chunks/builder.py imports Prompt 33 module: {needle!r}"
            )

    def test_site_builder_unmodified(self):
        """Prompt 34 has landed: site builder may call context_pack for static pages.

        It still must not call real model/provider integrations.
        """
        text = (REPO_ROOT / "wiki" / "site" / "builder.py").read_text(
            encoding="utf-8"
        )
        for needle in (
            "OpenAICompatibleProvider",
            "OllamaLocalProvider",
            "OllamaCloudProvider",
            "ask_llm",
            "chat.completions",
            "client.chat",
        ):
            assert needle not in text, (
                f"wiki/site/builder.py contains provider/runtime symbol: {needle!r}"
            )

# =============================================================================
# Test class 6: TestContextPackFullSuite
# =============================================================================


class TestContextPackFullSuite:
    """Full-suite compatibility: the new tests don't break prior boundaries."""

    def test_prompt32_boundaries_still_hold(self):
        """Prompt 32's boundary guards still pass under Prompt 33."""
        # These mirror test_prompt32_retrieval_eval_report.py's
        # boundary checks. We re-state them here to ensure
        # Prompt 33's new files do not violate the prior
        # prompts' invariants.
        for rel in (
            "wiki/context_pack.py",
            "tests/test_prompt33_chat_ui.py",
            "tests/test_prompt33_grounded_answer_api.py",
            "scripts/verify_grounded_answer.py",
        ):
            assert not (REPO_ROOT / rel).exists(), (
                f"Prior-prompt boundary violation: {rel} must not exist"
            )
