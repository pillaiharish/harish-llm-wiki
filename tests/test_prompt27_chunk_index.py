"""Tests for Prompt 27: Chunk Index Foundation.

The 18 required test cases from ``prompt27.md`` §"Required tests" are
covered by the classes in this file. The pattern follows the existing
``tests/test_prompt23_graph.py``, ``tests/test_prompt25_graph_visualization.py``,
and ``tests/test_prompt26_pdf_ingestion.py`` tests: build a small chunk
index in a tmp dir using controlled records, point ``SiteBuilder`` at
isolated data/repo directories, and assert on the generated files and
the on-disk schema.

The tests are grouped by responsibility:

- :class:`TestChunkSchema` – Pydantic schema shape and validation.
- :class:`TestChunkIndexBuilder` – builder behavior on synthetic records.
- :class:`TestChunkIndexDeterminism` – byte-stable, repeated builds.
- :class:`TestPdfChunkIndexing` – PDF source-specific metadata.
- :class:`TestTranscriptChunkIndexing` – YouTube + local transcript.
- :class:`TestWebpageAndMarkdownChunkIndexing` – webpage + markdown.
- :class:`TestChunkIndexFiles` – on-disk output files.
- :class:`TestChunkIndexCli` – ``wiki build-chunk-index`` CLI command.
- :class:`TestBuildSiteAndValidate` – build-site, smoke-site, validate
  integration.
- :class:`TestChunkIndexBoundaries` – scope guards (no BM25/vector/LLM).
- :class:`TestRealPdfChunkVerification` – real-PDF verification
  (skipped when the real PDF fixture is missing).
"""

from __future__ import annotations

import hashlib
import json
import re
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
    iter_chunk_index_issues,
)
from wiki.chunks.export import (
    write_chunk_index,
    write_public_copy,
)
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


def _isolated_data_dir(tmp_path: Path, monkeypatch) -> Path:
    """Point config at a tmp data dir and create the standard dirs."""
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    config.ensure_directories()
    return tmp_path


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Pytest fixture that points config at a tmp data dir.

    Tests that use this fixture get an isolated ``config.LLM_WIKI_DATA_DIR``
    set to ``tmp_path`` for the duration of the test, so the chunk index
    builder and other data-dir-aware code paths read from the tmp dir.
    """
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
    """Build a ResourceRecord whose local_normalized_path has chunks.jsonl.

    The helper writes ``chunks`` to a deterministic on-disk location and
    returns a fully-formed :class:`ResourceRecord`. Each entry in
    ``chunks`` is a dict that the per-source reader will project into a
    uniform :class:`ChunkRecord`.
    """
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
# Test class 1: TestChunkSchema
# =============================================================================


class TestChunkSchema:
    def test_chunk_schema_version_constant(self):
        assert CHUNK_INDEX_SCHEMA_VERSION == "chunk_index_v1"

    def test_chunk_schema_has_required_fields(self):
        rec = ChunkRecord(
            chunk_id="test:1",
            resource_id="pdf:abc",
            source_type="pdf",
            title="Test",
            text="Hello world",
            citation_label="page 1",
            source_ref=SourceRef(kind="pdf_pages", page_start=1, page_end=1),
            char_count=11,
            word_count=2,
            token_estimate=3,
            chunk_index=0,
            content_hash=hashlib.sha256(b"Hello world").hexdigest(),
            metadata=ChunkMetadata(),
        )
        assert rec.chunk_id == "test:1"
        assert rec.resource_id == "pdf:abc"
        assert rec.source_type == "pdf"
        assert rec.text == "Hello world"
        assert rec.citation_label == "page 1"
        assert rec.char_count == 11
        assert rec.word_count == 2
        assert rec.token_estimate == 3
        assert rec.chunk_index == 0
        assert rec.content_hash == hashlib.sha256(b"Hello world").hexdigest()
        assert rec.metadata is not None
        # Round-trip through Pydantic preserves the fields.
        payload = rec.model_dump()
        for key in (
            "chunk_id",
            "resource_id",
            "source_type",
            "title",
            "text",
            "citation_label",
            "source_ref",
            "resource_route",
            "char_count",
            "word_count",
            "token_estimate",
            "chunk_index",
            "content_hash",
            "metadata",
        ):
            assert key in payload, f"missing required field {key!r} in dict payload"

    def test_chunk_record_rejects_empty_text(self):
        with pytest.raises(Exception):
            ChunkRecord(
                chunk_id="test:1",
                resource_id="pdf:abc",
                source_type="pdf",
                title="Test",
                text="",
                citation_label="page 1",
                source_ref=SourceRef(kind="pdf_pages", page_start=1, page_end=1),
                char_count=0,
                word_count=0,
                token_estimate=0,
                chunk_index=0,
                content_hash="x" * 64,
                metadata=ChunkMetadata(),
            )

    def test_chunk_record_rejects_empty_citation_label(self):
        with pytest.raises(Exception):
            ChunkRecord(
                chunk_id="test:1",
                resource_id="pdf:abc",
                source_type="pdf",
                title="Test",
                text="non-empty",
                citation_label="",
                source_ref=SourceRef(kind="pdf_pages", page_start=1, page_end=1),
                char_count=8,
                word_count=1,
                token_estimate=2,
                chunk_index=0,
                content_hash="x" * 64,
                metadata=ChunkMetadata(),
            )

    def test_source_ref_kinds_match_source_type(self):
        for kind, kwargs in {
            "pdf_pages": {"page_start": 1, "page_end": 2},
            "youtube_time": {"start_seconds": 0.0, "end_seconds": 60.0},
            "local_time": {"start_seconds": 0.0, "end_seconds": 60.0},
            "webpage_section": {"section_title": "Intro", "paragraph_index": 1},
            "markdown_section": {"section_title": "Intro", "paragraph_index": 1},
        }.items():
            ref = SourceRef(kind=kind, **kwargs)
            assert ref.kind == kind
            payload = ref.model_dump()
            assert payload["kind"] == kind

    def test_source_ref_rejects_unknown_kind(self):
        with pytest.raises(Exception):
            SourceRef(kind="bogus_kind")


# =============================================================================
# Test class 2: TestChunkIndexBuilder
# =============================================================================


class TestChunkIndexBuilder:
    def test_builder_returns_sorted_chunks(self, tmp_path):
        rec_z = _make_normalized_record(
            tmp_path,
            resource_id="webpage:z",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "w:z:1", "text": "Z text", "citation_label": "Z"}],
        )
        rec_a = _make_normalized_record(
            tmp_path,
            resource_id="webpage:a",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "w:a:1", "text": "A text", "citation_label": "A"}],
        )
        rec_m = _make_normalized_record(
            tmp_path,
            resource_id="webpage:m",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "w:m:1", "text": "M text", "citation_label": "M"}],
        )
        result = build_chunk_index([rec_z, rec_a, rec_m])
        ids = [c.resource_id for c in result.chunks]
        assert ids == ["webpage:a", "webpage:m", "webpage:z"]

    def test_builder_skips_records_with_no_chunks_file(self, tmp_path):
        """A record with local_normalized_path missing or non-existent
        does not raise; it emits a warning and contributes zero chunks.
        """
        # local_normalized_path points to a non-existent dir.
        rec = ResourceRecord(
            id="webpage:empty",
            source_type=SourceType.WEBPAGE,
            canonical_id="webpage:empty",
            original_url="https://example.com/empty",
            local_normalized_path=tmp_path / "does_not_exist",
            title="Empty",
            status=ResourceStatus.NEW,
        )
        result = build_chunk_index([rec])
        assert result.chunks == []
        assert any(w["code"] == "missing_chunks_file" for w in result.warnings)

    def test_builder_emits_warning_for_missing_chunks_file(self, tmp_path):
        """A record with local_normalized_path set but no chunks.jsonl
        on disk is skipped with a warning.
        """
        norm_dir = tmp_path / "normalized" / "ghost"
        norm_dir.mkdir(parents=True, exist_ok=True)
        rec = ResourceRecord(
            id="webpage:ghost",
            source_type=SourceType.WEBPAGE,
            canonical_id="webpage:ghost",
            original_url="https://example.com/ghost",
            local_normalized_path=norm_dir,
            title="Ghost",
            status=ResourceStatus.NORMALIZED,
        )
        result = build_chunk_index([rec])
        assert result.chunks == []
        warnings = [w for w in result.warnings if w["code"] == "missing_chunks_file"]
        assert len(warnings) >= 1
        assert warnings[0]["resource_id"] == "webpage:ghost"

    def test_builder_respects_include_source_type_filter(self, data_dir):
        rec_pdf = _make_pdf_record(data_dir)
        rec_web = _make_normalized_record(
            data_dir,
            resource_id="webpage:filtered",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "w:f:1", "text": "Web text", "citation_label": "Intro"}],
        )
        result = build_chunk_index(
            [rec_pdf, rec_web], include_source_types=["pdf"]
        )
        assert all(c.source_type == "pdf" for c in result.chunks)
        assert len(result.chunks) >= 1
        assert "webpage:filtered" not in {c.resource_id for c in result.chunks}

    def test_builder_respects_resource_id_filter(self, data_dir):
        rec_pdf = _make_pdf_record(data_dir)
        rec_web = _make_normalized_record(
            data_dir,
            resource_id="webpage:only",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "w:o:1", "text": "Only web", "citation_label": "Intro"}],
        )
        result = build_chunk_index([rec_pdf, rec_web], resource_id="webpage:only")
        assert len(result.chunks) == 1
        assert result.chunks[0].resource_id == "webpage:only"

    def test_builder_respects_limit(self, tmp_path):
        rec_a = _make_normalized_record(
            tmp_path,
            resource_id="webpage:limit-a",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "w:la:1", "text": "A", "citation_label": "A"}],
        )
        rec_b = _make_normalized_record(
            tmp_path,
            resource_id="webpage:limit-b",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "w:lb:1", "text": "B", "citation_label": "B"}],
        )
        rec_c = _make_normalized_record(
            tmp_path,
            resource_id="webpage:limit-c",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "w:lc:1", "text": "C", "citation_label": "C"}],
        )
        result = build_chunk_index([rec_a, rec_b, rec_c], limit=2)
        # Only the first two (alphabetical) resources are kept.
        ids = {c.resource_id for c in result.chunks}
        assert ids == {"webpage:limit-a", "webpage:limit-b"}
        assert "webpage:limit-c" not in ids

    def test_builder_emits_empty_index_for_empty_registry(self, tmp_path):
        result = build_chunk_index([])
        assert result.chunks == []
        assert result.warnings == []
        assert result.manifest["chunk_count"] == 0
        assert result.manifest["resource_count"] == 0
        assert result.manifest["by_source_type"] == {}
        assert result.manifest["by_resource"] == []

    def test_builder_dedupes_duplicate_chunk_ids(self, tmp_path):
        # Two records with the same chunk_id. The builder keeps the
        # first-seen and emits a warning.
        rec_a = _make_normalized_record(
            tmp_path,
            resource_id="webpage:dup-a",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "shared-id", "text": "first", "citation_label": "Intro"}],
        )
        rec_b = _make_normalized_record(
            tmp_path,
            resource_id="webpage:dup-b",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "shared-id", "text": "second", "citation_label": "Intro"}],
        )
        result = build_chunk_index([rec_a, rec_b])
        assert len(result.chunks) == 1
        assert result.chunks[0].chunk_id == "shared-id"
        assert result.chunks[0].text == "first"
        # And a duplicate-chunk-id warning was emitted.
        warnings = [w for w in result.warnings if w["code"] == "duplicate_chunk_id"]
        assert len(warnings) >= 1

    def test_chunk_index_result_envelope_shape(self, data_dir):
        rec = _make_pdf_record(data_dir)
        result = build_chunk_index([rec])
        assert isinstance(result, ChunkIndexResult)
        assert isinstance(result.chunks, list)
        assert isinstance(result.manifest, dict)
        assert isinstance(result.warnings, list)
        assert isinstance(result.chunk_count_by_resource, dict)
        # by_resource is a {resource_id: chunk_count} map.
        assert all(isinstance(v, int) for v in result.chunk_count_by_resource.values())


# =============================================================================
# Test class 3: TestChunkIndexDeterminism
# =============================================================================


class TestChunkIndexDeterminism:
    def test_repeated_builds_are_byte_identical(self, data_dir):
        rec_pdf = _make_pdf_record(data_dir)
        rec_web = _make_normalized_record(
            data_dir,
            resource_id="webpage:det",
            source_type=SourceType.WEBPAGE,
            chunks=[
                {
                    "chunk_id": "w:det:1",
                    "text": "Determinism test text",
                    "citation_label": "Intro",
                    "section_heading": "Intro",
                    "paragraph_index": 1,
                }
            ],
        )

        out1 = data_dir / "out1"
        out2 = data_dir / "out2"
        out1.mkdir()
        out2.mkdir()

        r1 = build_chunk_index([rec_pdf, rec_web])
        write_chunk_index(r1, output_dir=out1)
        r2 = build_chunk_index([rec_pdf, rec_web])
        write_chunk_index(r2, output_dir=out2)

        for filename in ("chunks.jsonl", "chunks.json", "manifest.json"):
            text1 = (out1 / filename).read_text(encoding="utf-8")
            text2 = (out2 / filename).read_text(encoding="utf-8")
            assert text1 == text2, f"{filename} differs between runs"

    def test_chunk_order_is_stable_across_runs(self, tmp_path):
        rec_a = _make_normalized_record(
            tmp_path,
            resource_id="webpage:stable-a",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "w:sa:1", "text": "A", "citation_label": "A"}],
        )
        rec_b = _make_normalized_record(
            tmp_path,
            resource_id="webpage:stable-b",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "w:sb:1", "text": "B", "citation_label": "B"}],
        )
        r1 = build_chunk_index([rec_b, rec_a])
        r2 = build_chunk_index([rec_a, rec_b])
        ids1 = [c.chunk_id for c in r1.chunks]
        ids2 = [c.chunk_id for c in r2.chunks]
        assert ids1 == ids2

    def test_content_hash_is_deterministic(self, tmp_path):
        rec = _make_normalized_record(
            tmp_path,
            resource_id="webpage:hash",
            source_type=SourceType.WEBPAGE,
            chunks=[
                {"chunk_id": "w:h:1", "text": "hello", "citation_label": "Intro"},
                {"chunk_id": "w:h:2", "text": "hello", "citation_label": "Intro2"},
            ],
        )
        result = build_chunk_index([rec])
        for chunk in result.chunks:
            expected = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
            assert chunk.content_hash == expected

    def test_no_timestamps_in_deterministic_files(self, data_dir):
        rec = _make_pdf_record(data_dir)
        out = data_dir / "out"
        out.mkdir()
        result = build_chunk_index([rec])
        write_chunk_index(result, output_dir=out)
        for filename in ("chunks.json", "manifest.json", "chunks.jsonl"):
            text = (out / filename).read_text(encoding="utf-8")
            assert "generated_at" not in text
            assert "build_started_at" not in text
            assert "build_finished_at" not in text
        # stats.json is allowed to contain timestamps.
        stats_text = (out / "stats.json").read_text(encoding="utf-8")
        assert "build_started_at" in stats_text

    def test_resource_order_is_alphabetical(self, tmp_path):
        ids = ["webpage:z", "webpage:a", "webpage:m"]
        records = [
            _make_normalized_record(
                tmp_path,
                resource_id=rid,
                source_type=SourceType.WEBPAGE,
                chunks=[{"chunk_id": f"c:{rid}", "text": rid, "citation_label": "X"}],
            )
            for rid in ids
        ]
        result = build_chunk_index(records)
        out_ids = [c.resource_id for c in result.chunks]
        assert out_ids == sorted(ids)

    def test_chunks_json_uses_schema_field_order(self, data_dir):
        rec = _make_pdf_record(data_dir)
        out = data_dir / "out"
        out.mkdir()
        result = build_chunk_index([rec])
        write_chunk_index(result, output_dir=out)
        payload = json.loads((out / "chunks.json").read_text(encoding="utf-8"))
        first = payload[0]
        # The order of keys in the dumped object should match the
        # declaration order on the Pydantic model.
        keys = list(first.keys())
        expected_first_fields = ["chunk_id", "resource_id", "source_type", "title", "text"]
        assert keys[:5] == expected_first_fields, (
            f"Expected first 5 fields {expected_first_fields}, got {keys[:5]}"
        )


# =============================================================================
# Test class 4: TestPdfChunkIndexing
# =============================================================================


class TestPdfChunkIndexing:
    def test_pdf_chunks_include_page_start_page_end(self, data_dir):
        rec = _make_pdf_record(data_dir)
        result = build_chunk_index([rec])
        assert len(result.chunks) >= 1
        for chunk in result.chunks:
            assert chunk.source_type == "pdf"
            assert chunk.source_ref.kind == "pdf_pages"
            assert isinstance(chunk.source_ref.page_start, int)
            assert isinstance(chunk.source_ref.page_end, int)
            assert chunk.source_ref.page_start <= chunk.source_ref.page_end

    def test_pdf_citation_labels_include_page_numbers(self, data_dir):
        rec = _make_pdf_record(data_dir)
        result = build_chunk_index([rec])
        for chunk in result.chunks:
            assert chunk.citation_label, "PDF chunk has no citation_label"
            assert re.search(r"pages?\s+\d+", chunk.citation_label), (
                f"PDF citation_label {chunk.citation_label!r} missing page numbers"
            )

    def test_pdf_chunks_link_to_resource_route(self, data_dir):
        rec = _make_pdf_record(data_dir)
        result = build_chunk_index([rec])
        for chunk in result.chunks:
            assert chunk.resource_route, "PDF chunk has no resource_route"
            assert chunk.resource_route.startswith("/resources/")

    def test_pdf_source_ref_preserves_file_path(self, data_dir):
        rec = _make_pdf_record(data_dir)
        result = build_chunk_index([rec])
        file_paths = {chunk.source_ref.file_path for chunk in result.chunks}
        # At least one chunk has a file_path; it should match the
        # configured PDF path.
        assert any(p and "attention.pdf" in p for p in file_paths), (
            f"Expected file_path containing 'attention.pdf', got {file_paths}"
        )

    def test_pdf_chunk_text_contains_known_markers(self, data_dir):
        rec = _make_pdf_record(data_dir)
        result = build_chunk_index([rec])
        joined = "\n".join(c.text for c in result.chunks)
        assert "Attention Is All You Need" in joined
        assert "Transformer" in joined
        assert "Scaled Dot-Product Attention" in joined


# =============================================================================
# Test class 5: TestTranscriptChunkIndexing
# =============================================================================


class TestTranscriptChunkIndexing:
    def test_local_transcript_chunks_have_timestamps(self, tmp_path):
        rec = _make_normalized_record(
            tmp_path,
            resource_id="local_transcript:abc",
            source_type=SourceType.LOCAL_TRANSCRIPT,
            chunks=[
                {
                    "chunk_id": "lt:1",
                    "text": "Local transcript text",
                    "citation_label": "00:00-00:10",
                    "start_time": 0.0,
                    "end_time": 10.0,
                },
                {
                    "chunk_id": "lt:2",
                    "text": "More transcript text",
                    "citation_label": "00:10-00:20",
                    "start_time": 10.0,
                    "end_time": 20.0,
                },
            ],
        )
        result = build_chunk_index([rec])
        assert len(result.chunks) == 2
        for chunk in result.chunks:
            assert chunk.source_ref.kind == "local_time"
            assert isinstance(chunk.source_ref.start_seconds, float)
            assert isinstance(chunk.source_ref.end_seconds, float)

    def test_youtube_chunks_have_timestamps(self, tmp_path):
        rec = _make_normalized_record(
            tmp_path,
            resource_id="youtube:vid-1",
            source_type=SourceType.YOUTUBE,
            chunks=[
                {
                    "chunk_id": "yt:1",
                    "text": "Hello world",
                    "citation_label": "00:00-00:30",
                    "start_time": 0.0,
                    "end_time": 30.0,
                    "url": "https://youtu.be/vid-1",
                }
            ],
        )
        result = build_chunk_index([rec])
        assert len(result.chunks) == 1
        chunk = result.chunks[0]
        assert chunk.source_ref.kind == "youtube_time"
        assert chunk.source_ref.start_seconds == 0.0
        assert chunk.source_ref.end_seconds == 30.0

    def test_youtube_chunks_have_url_in_source_ref(self, tmp_path):
        rec = _make_normalized_record(
            tmp_path,
            resource_id="youtube:vid-2",
            source_type=SourceType.YOUTUBE,
            chunks=[
                {
                    "chunk_id": "yt:2",
                    "text": "Hello",
                    "citation_label": "00:00-00:10",
                    "start_time": 0.0,
                    "end_time": 10.0,
                    "url": "https://youtu.be/vid-2",
                }
            ],
        )
        result = build_chunk_index([rec])
        assert result.chunks[0].source_ref.url == "https://youtu.be/vid-2"

    def test_transcript_citation_label_is_timestamp_range(self, tmp_path):
        rec = _make_normalized_record(
            tmp_path,
            resource_id="local_transcript:ts",
            source_type=SourceType.LOCAL_TRANSCRIPT,
            chunks=[
                {
                    "chunk_id": "lt:ts",
                    "text": "Range",
                    "citation_label": "00:00-01:30",
                    "start_time": 0.0,
                    "end_time": 90.0,
                }
            ],
        )
        result = build_chunk_index([rec])
        # The label may come from the source (preferred) or be
        # generated by the builder; either way, it must look like
        # a timestamp range.
        label = result.chunks[0].citation_label
        assert re.match(r"^\d{2}:\d{2}-\d{2}:\d{2}$", label), (
            f"Citation label {label!r} is not a timestamp range"
        )


# =============================================================================
# Test class 6: TestWebpageAndMarkdownChunkIndexing
# =============================================================================


class TestWebpageAndMarkdownChunkIndexing:
    def test_webpage_chunks_have_section_heading(self, tmp_path):
        rec = _make_normalized_record(
            tmp_path,
            resource_id="webpage:section",
            source_type=SourceType.WEBPAGE,
            chunks=[
                {
                    "chunk_id": "w:s:1",
                    "text": "Webpage section text",
                    "citation_label": "Intro, paragraph 1",
                    "section_heading": "Intro",
                    "paragraph_index": 1,
                }
            ],
        )
        result = build_chunk_index([rec])
        chunk = result.chunks[0]
        assert chunk.source_ref.kind == "webpage_section"
        assert chunk.source_ref.section_title == "Intro"
        assert chunk.source_ref.paragraph_index == 1

    def test_markdown_chunks_have_file_path(self, tmp_path):
        rec = _make_normalized_record(
            tmp_path,
            resource_id="markdown:doc",
            source_type=SourceType.MARKDOWN,
            chunks=[
                {
                    "chunk_id": "m:1",
                    "text": "Markdown body",
                    "citation_label": "Section, paragraph 1",
                    "section_heading": "Section",
                    "paragraph_index": 1,
                    "file_path": "/tmp/example.md",
                }
            ],
        )
        result = build_chunk_index([rec])
        chunk = result.chunks[0]
        assert chunk.source_ref.kind == "markdown_section"
        assert chunk.source_ref.file_path == "/tmp/example.md"

    def test_webpage_source_url_preserved_in_metadata(self, tmp_path):
        rec = _make_normalized_record(
            tmp_path,
            resource_id="webpage:url",
            source_type=SourceType.WEBPAGE,
            chunks=[
                {
                    "chunk_id": "w:u:1",
                    "text": "Has URL",
                    "citation_label": "Intro",
                    "section_heading": "Intro",
                    "paragraph_index": 1,
                }
            ],
        )
        result = build_chunk_index([rec])
        assert result.chunks[0].metadata.source_url == rec.original_url

    def test_markdown_chunks_use_markdown_section_kind(self, tmp_path):
        rec = _make_normalized_record(
            tmp_path,
            resource_id="markdown:kind",
            source_type=SourceType.MARKDOWN,
            chunks=[
                {
                    "chunk_id": "m:k:1",
                    "text": "Kind test",
                    "citation_label": "Section",
                    "section_heading": "Section",
                    "paragraph_index": 1,
                }
            ],
        )
        result = build_chunk_index([rec])
        assert result.chunks[0].source_ref.kind == "markdown_section"

    def test_webpage_chunks_use_webpage_section_kind(self, tmp_path):
        rec = _make_normalized_record(
            tmp_path,
            resource_id="webpage:kind",
            source_type=SourceType.WEBPAGE,
            chunks=[
                {
                    "chunk_id": "w:k:1",
                    "text": "Webpage kind test",
                    "citation_label": "Section",
                    "section_heading": "Section",
                    "paragraph_index": 1,
                }
            ],
        )
        result = build_chunk_index([rec])
        assert result.chunks[0].source_ref.kind == "webpage_section"


# =============================================================================
# Test class 7: TestChunkIndexFiles
# =============================================================================


class TestChunkIndexFiles:
    def test_chunks_jsonl_is_written(self, data_dir):
        rec = _make_pdf_record(data_dir)
        out = data_dir / "out"
        out.mkdir()
        result = build_chunk_index([rec])
        paths = write_chunk_index(result, output_dir=out)
        assert paths["chunks_jsonl"].exists()
        # Every line is valid JSON.
        with paths["chunks_jsonl"].open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                json.loads(line)  # raises on malformed

    def test_chunks_json_is_written(self, data_dir):
        rec = _make_pdf_record(data_dir)
        out = data_dir / "out"
        out.mkdir()
        result = build_chunk_index([rec])
        paths = write_chunk_index(result, output_dir=out)
        assert paths["chunks_json"].exists()
        payload = json.loads(paths["chunks_json"].read_text(encoding="utf-8"))
        assert isinstance(payload, list)
        assert len(payload) == len(result.chunks)

    def test_manifest_json_is_written(self, data_dir):
        rec = _make_pdf_record(data_dir)
        out = data_dir / "out"
        out.mkdir()
        result = build_chunk_index([rec])
        paths = write_chunk_index(result, output_dir=out)
        assert paths["manifest"].exists()
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        for key in ("chunk_count", "resource_count", "by_source_type", "by_resource"):
            assert key in manifest, f"manifest missing {key!r}"
        assert manifest["chunk_count"] == len(result.chunks)

    def test_stats_json_is_written(self, data_dir):
        rec = _make_pdf_record(data_dir)
        out = data_dir / "out"
        out.mkdir()
        result = build_chunk_index([rec])
        paths = write_chunk_index(result, output_dir=out)
        assert paths["stats"].exists()
        stats = json.loads(paths["stats"].read_text(encoding="utf-8"))
        assert "chunk_count" in stats
        assert "resource_count" in stats

    def test_public_chunks_json_is_written(self, data_dir, monkeypatch):
        rec = _make_pdf_record(data_dir)
        out = data_dir / "out"
        out.mkdir()
        result = build_chunk_index([rec])
        write_chunk_index(result, output_dir=out)
        public_dir = data_dir / "public"
        public = write_public_copy(
            data_dir=data_dir,
            output_dir=public_dir / "chunks",
        )
        assert (public_dir / "chunks" / "chunks.json").exists()
        assert (public_dir / "chunks" / "manifest.json").exists()
        # And both parse as valid JSON.
        json.loads((public_dir / "chunks" / "chunks.json").read_text(encoding="utf-8"))
        json.loads((public_dir / "chunks" / "manifest.json").read_text(encoding="utf-8"))

    def test_public_manifest_json_is_written(self, data_dir, monkeypatch):
        rec = _make_pdf_record(data_dir)
        out = data_dir / "out"
        out.mkdir()
        result = build_chunk_index([rec])
        write_chunk_index(result, output_dir=out)
        public = write_public_copy(
            data_dir=data_dir,
            output_dir=data_dir / "public_chunks",
        )
        manifest = json.loads(public["manifest"].read_text(encoding="utf-8"))
        assert manifest["schema_version"] == CHUNK_INDEX_SCHEMA_VERSION

    def test_chunks_index_page_is_written(self, data_dir, monkeypatch):
        rec = _make_pdf_record(data_dir)
        out = data_dir / "out"
        out.mkdir()
        result = build_chunk_index([rec])
        write_chunk_index(result, output_dir=out)
        builder = _setup_site_builder(data_dir, monkeypatch)
        # Need to write the public copy to the SiteBuilder's data_site_dir
        # so the chunks index page can read the manifest.
        write_public_copy(
            data_dir=data_dir,
            output_dir=builder.data_site_dir / "public" / "chunks",
        )
        builder._build_chunks_index_page()
        index_page = builder.data_site_dir / "chunks" / "index.md"
        assert index_page.exists()
        content = index_page.read_text(encoding="utf-8")
        assert "Chunk Index" in content
        assert "public/chunks/chunks.json" in content


# =============================================================================
# Test class 8: TestChunkIndexCli
# =============================================================================


class TestChunkIndexCli:
    def test_build_chunk_index_prints_stats(self, data_dir, monkeypatch):
        rec = _make_pdf_record(data_dir)
        _isolated_data_dir(data_dir, monkeypatch)
        # Insert the record into the registry so the CLI sees it.
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity, ResourceStatus

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

        result = CliRunner().invoke(cli.app, ["build-chunk-index"])
        assert result.exit_code == 0, f"build-chunk-index exited {result.exit_code}: {result.output}"
        assert "Total chunks" in result.output
        assert "Total resources indexed" in result.output
        assert "Output chunks.jsonl" in result.output
        assert "Output chunks.json" in result.output
        assert "Warnings" in result.output

    def test_build_chunk_index_with_filter(self, data_dir, monkeypatch):
        rec_pdf = _make_pdf_record(data_dir)
        rec_web = _make_normalized_record(
            data_dir,
            resource_id="webpage:cli-filter",
            source_type=SourceType.WEBPAGE,
            chunks=[
                {
                    "chunk_id": "w:cf:1",
                    "text": "Filter me out",
                    "citation_label": "Intro",
                    "section_heading": "Intro",
                    "paragraph_index": 1,
                }
            ],
        )
        _isolated_data_dir(data_dir, monkeypatch)
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity, ResourceStatus

        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        for rec in (rec_pdf, rec_web):
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

        result = CliRunner().invoke(
            cli.app,
            ["build-chunk-index", "--include-source-type", "pdf"],
        )
        assert result.exit_code == 0
        # Only PDF chunks in the output index.
        out_chunks = json.loads(
            (data_dir / "processed" / "chunk_index" / "chunks.json").read_text(
                encoding="utf-8"
            )
        )
        assert all(c["source_type"] == "pdf" for c in out_chunks)
        assert len(out_chunks) >= 1

    def test_build_chunk_index_with_resource_id(self, data_dir, monkeypatch):
        rec_pdf = _make_pdf_record(data_dir, resource_id="pdf:cli-only-a")
        rec_other = _make_pdf_record(
            data_dir,
            resource_id="pdf:cli-only-b",
            content_hash="fffffff" + "0" * 56,
        )
        _isolated_data_dir(data_dir, monkeypatch)
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity, ResourceStatus

        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        for rec in (rec_pdf, rec_other):
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

        result = CliRunner().invoke(
            cli.app,
            ["build-chunk-index", "--resource-id", rec_pdf.id],
        )
        assert result.exit_code == 0
        out_chunks = json.loads(
            (data_dir / "processed" / "chunk_index" / "chunks.json").read_text(
                encoding="utf-8"
            )
        )
        assert all(c["resource_id"] == rec_pdf.id for c in out_chunks)

    def test_build_chunk_index_with_limit(self, tmp_path, monkeypatch):
        rec_a = _make_normalized_record(
            tmp_path,
            resource_id="webpage:limit-cli-a",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "w:lca:1", "text": "A", "citation_label": "X"}],
        )
        rec_b = _make_normalized_record(
            tmp_path,
            resource_id="webpage:limit-cli-b",
            source_type=SourceType.WEBPAGE,
            chunks=[{"chunk_id": "w:lcb:1", "text": "B", "citation_label": "X"}],
        )
        _isolated_data_dir(tmp_path, monkeypatch)
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity, ResourceStatus

        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        for rec in (rec_a, rec_b):
            identity = ResourceIdentity(
                source_type=rec.source_type,
                canonical_id=rec.canonical_id,
                original_url=rec.original_url,
            )
            inserted = reg.insert(identity, status=ResourceStatus.NORMALIZED)
            rec.id = inserted.id
            rec.first_seen_at = inserted.first_seen_at
            reg.update(rec)

        result = CliRunner().invoke(cli.app, ["build-chunk-index", "--limit", "1"])
        assert result.exit_code == 0
        out_manifest = json.loads(
            (tmp_path / "processed" / "chunk_index" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert out_manifest["resource_count"] == 1

    def test_build_chunk_index_empty_registry(self, tmp_path, monkeypatch):
        _isolated_data_dir(tmp_path, monkeypatch)
        from wiki.registry import Registry

        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        result = CliRunner().invoke(cli.app, ["build-chunk-index"])
        assert result.exit_code == 0
        # Empty index files exist and are valid.
        chunks_json = tmp_path / "processed" / "chunk_index" / "chunks.json"
        manifest_json = tmp_path / "processed" / "chunk_index" / "manifest.json"
        assert chunks_json.exists()
        assert manifest_json.exists()
        payload = json.loads(chunks_json.read_text(encoding="utf-8"))
        assert payload == []
        manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
        assert manifest["chunk_count"] == 0
        assert manifest["resource_count"] == 0

    def test_build_chunk_index_refresh_rebuilds(self, data_dir, monkeypatch):
        rec = _make_pdf_record(data_dir)
        _isolated_data_dir(data_dir, monkeypatch)
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity, ResourceStatus

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

        first = CliRunner().invoke(cli.app, ["build-chunk-index"])
        assert first.exit_code == 0
        first_chunks = json.loads(
            (data_dir / "processed" / "chunk_index" / "chunks.json").read_text(
                encoding="utf-8"
            )
        )
        second = CliRunner().invoke(cli.app, ["build-chunk-index", "--refresh"])
        assert second.exit_code == 0
        second_chunks = json.loads(
            (data_dir / "processed" / "chunk_index" / "chunks.json").read_text(
                encoding="utf-8"
            )
        )
        # Excluding stats.json, the deterministic files are byte-stable.
        assert first_chunks == second_chunks


# =============================================================================
# Test class 9: TestBuildSiteAndValidate
# =============================================================================


class TestBuildSiteAndValidate:
    def test_build_site_continues_to_pass(self, data_dir, monkeypatch):
        rec = _make_pdf_record(data_dir)
        builder = _setup_site_builder(data_dir, monkeypatch)
        # Build the site with this record.
        builder.build([rec])
        # The site build did not raise. The repo site dir exists.
        assert builder.repo_site_dir.exists()

    def test_smoke_site_passes_after_chunk_index_added(self, tmp_path, monkeypatch):
        from typer import Exit

        # Patch config + registry to point at the tmp dir.
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

    def test_validate_passes_after_chunk_index_added(self, tmp_path, monkeypatch):
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

    def test_validate_catches_malformed_chunk_index(self, tmp_path, monkeypatch):
        _isolated_data_dir(tmp_path, monkeypatch)
        from wiki.registry import Registry

        monkeypatch.setattr(cli, "registry", Registry())

        # Build a valid index, then corrupt chunks.jsonl.
        rec = _make_pdf_record(tmp_path)
        cli.generate_derived_views([rec])
        chunk_dir = tmp_path / "processed" / "chunk_index"
        jsonl = chunk_dir / "chunks.jsonl"
        jsonl.write_text("THIS IS NOT JSON\n", encoding="utf-8")

        # We can call iter_chunk_index_issues directly to confirm a warning.
        issues = list(
            iter_chunk_index_issues(
                chunks_jsonl_path=jsonl,
                chunks_json_path=chunk_dir / "chunks.json",
                manifest_path=chunk_dir / "manifest.json",
            )
        )
        codes = [code for _sev, code, _msg in issues]
        assert "chunks_jsonl_invalid" in codes

    def test_validate_warns_on_duplicate_chunk_id(self, tmp_path, monkeypatch):
        chunk_dir = tmp_path / "processed" / "chunk_index"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        duplicated_chunk = {
            "chunk_id": "duplicated-id",
            "resource_id": "webpage:foo",
            "source_type": "webpage",
            "title": "Foo",
            "text": "Hello",
            "citation_label": "Intro",
            "source_ref": {"kind": "webpage_section"},
            "char_count": 5,
            "word_count": 1,
            "token_estimate": 1,
            "chunk_index": 0,
            "content_hash": hashlib.sha256(b"Hello").hexdigest(),
            "metadata": {},
        }
        (chunk_dir / "chunks.json").write_text(
            json.dumps([duplicated_chunk, duplicated_chunk]), encoding="utf-8"
        )
        (chunk_dir / "chunks.jsonl").write_text(
            json.dumps(duplicated_chunk) + "\n" + json.dumps(duplicated_chunk) + "\n",
            encoding="utf-8",
        )
        (chunk_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": CHUNK_INDEX_SCHEMA_VERSION,
                    "chunk_count": 2,
                    "resource_count": 1,
                    "by_source_type": {"webpage": 2},
                    "by_resource": [],
                    "warnings": [],
                }
            ),
            encoding="utf-8",
        )
        issues = list(
            iter_chunk_index_issues(
                chunks_jsonl_path=chunk_dir / "chunks.jsonl",
                chunks_json_path=chunk_dir / "chunks.json",
                manifest_path=chunk_dir / "manifest.json",
            )
        )
        codes = [code for _sev, code, _msg in issues]
        assert "duplicate_chunk_id" in codes


# =============================================================================
# Test class 10: TestChunkIndexBoundaries
# =============================================================================


class TestChunkIndexBoundaries:
    def test_no_bm25_or_embedding_dependencies(self):
        """Read pyproject.toml and the wiki/chunks/*.py files to
        confirm no BM25, FAISS, Chroma, LanceDB, OpenAI, transformers,
        or sentence-transformers is pulled in.
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
        ]
        for needle in forbidden:
            assert needle not in block, (
                f"forbidden dependency in [dependencies]: {needle}"
            )

        chunks_dir = REPO_ROOT / "wiki" / "chunks"
        for py_file in chunks_dir.glob("*.py"):
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
                "import httpx",
            ):
                assert forbidden_import not in text, (
                    f"{py_file.name} contains forbidden import {forbidden_import!r}"
                )

    def test_no_llm_calls(self):
        """wiki/chunks/*.py must not import LLM client libraries."""
        chunks_dir = REPO_ROOT / "wiki" / "chunks"
        for py_file in chunks_dir.glob("*.py"):
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

    def test_no_graph_builder_modification(self, tmp_path):
        """The graph builder must not be modified by Prompt 27."""
        graph_builder = REPO_ROOT / "wiki" / "graph" / "builder.py"
        text = graph_builder.read_text(encoding="utf-8")
        # No Prompt 27 modules may be imported.
        for needle in ("wiki.chunks", "from wiki.chunks"):
            assert needle not in text, (
                f"graph builder imports Prompt 27 module: {needle!r}"
            )

    def test_no_pdf_extraction_changes(self):
        """The PDF ingestor must not be modified by Prompt 27."""
        pdf_ingest = REPO_ROOT / "wiki" / "ingest" / "pdf.py"
        text = pdf_ingest.read_text(encoding="utf-8")
        for needle in ("wiki.chunks", "from wiki.chunks"):
            assert needle not in text, (
                f"pdf ingestor imports Prompt 27 module: {needle!r}"
            )


# =============================================================================
# Test class 11: TestRealPdfChunkVerification
# =============================================================================


class TestRealPdfChunkVerification:
    """Run the verify_chunk_index.py flow when the real PDF is on disk.

    These tests are skipped if the real PDF fixture is not present so
    the test suite does not require network access.
    """

    def _real_pdf_present(self) -> bool:
        return REAL_PDF.exists()

    def test_real_pdf_index_contains_markers(self, tmp_path, monkeypatch):
        if not self._real_pdf_present():
            pytest.skip(f"Real PDF fixture not present at {REAL_PDF}")
        from wiki.ingest.pdf import pdf_ingestor
        from wiki.normalize.pdf import pdf_normalizer
        from wiki.registry import Registry
        from wiki.schemas import ResourceIdentity, ResourceStatus

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

        result = build_chunk_index(list(reg.get_all()))
        assert len(result.chunks) > 0
        joined = "\n".join(c.text for c in result.chunks)
        assert "Attention Is All You Need" in joined
        assert "Transformer" in joined
        assert "Scaled Dot-Product Attention" in joined
        assert result.manifest["by_source_type"].get("pdf", 0) >= 1
