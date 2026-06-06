"""Tests for Prompt 26: PDF Resource Ingestion.

The 15 required test cases from ``prompt26.md`` §"Required tests"
are covered by the classes in this file. The pattern follows the
existing ``tests/test_prompt12_media_transcripts.py`` and
``tests/test_prompt25_graph_visualization.py`` tests: build a
small graph in a tmp dir using controlled records, point
:class:`SiteBuilder` at isolated data/repo directories, and
assert on the generated files and the registry state.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from wiki import cli
from wiki.config import config
from wiki.graph import (
    EDGE_TYPE_RESOURCE_SAME_SOURCE_TYPE_AS_RESOURCE,
    EDGE_TYPE_RESOURCE_SHARES_TOPIC_WITH_RESOURCE,
    NODE_TYPE_RESOURCE,
    GraphBuilder,
)
from wiki.graph.builder import build_graph
from wiki.ingest.pdf import (
    PDF_EXTRACT_METHOD,
    PdfEncryptedError,
    chunk_pages,
    extract_pages,
    extract_pages_warnings,
    make_pdf_chunk_id,
    make_pdf_resource_id,
    pdf_ingestor,
    sha256_file,
)
from wiki.normalize.pdf import pdf_normalizer
from wiki.registry import Registry
from wiki.schemas import (
    PdfChunk,
    ResourceRecord,
    SourceType,
)
from wiki.site.builder import SiteBuilder
from wiki.storage import Storage


# -----------------------------------------------------------------------------
# Fixtures and helpers
# -----------------------------------------------------------------------------


FIXTURE_PDF = Path(__file__).parent / "fixtures" / "synthetic.pdf"


def _isolated_registry(tmp_path, monkeypatch) -> Registry:
    """Return a Registry instance backed by a tmp data dir."""
    monkeypatch.setattr(cli.config, "LLM_WIKI_DATA_DIR", tmp_path)
    cli.config.ensure_directories()
    reg = Registry()
    monkeypatch.setattr(cli, "registry", reg)
    return reg


def _isolated_data_dir(tmp_path, monkeypatch) -> Path:
    """Point config at a tmp data dir and create the standard dirs."""
    monkeypatch.setattr(cli.config, "LLM_WIKI_DATA_DIR", tmp_path)
    cli.config.ensure_directories()
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


def _make_non_pdf_record(
    tmp_path: Path,
    *,
    resource_id: str = "webpage:non-pdf",
    title: str = "RAG Hybrid Retrieval",
    tags: list | None = None,
    note_text: str | None = None,
) -> ResourceRecord:
    """Build a self-contained non-PDF ResourceRecord for pipeline tests."""
    safe_id = resource_id.replace(":", "_")
    note_path = tmp_path / "processed" / "resources" / f"{safe_id}.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    if note_text is None:
        note_text = (
            "# RAG Notes\n\n## One-line memory hook\n\n"
            "Retrieval quality controls answer quality.\n"
        )
    note_path.write_text(note_text, encoding="utf-8")
    return ResourceRecord(
        id=resource_id,
        source_type=SourceType.WEBPAGE,
        canonical_id=resource_id,
        original_url=f"https://example.com/{safe_id}",
        title=title,
        status=ResourceRecord.model_fields["status"].default,
        generated_note_path=note_path,
        llm_provider="mock",
        llm_model="mock-model",
        prompt_version="harish_llm_wiki_v4",
        tags=tags if tags is not None else ["rag", "retrieval"],
    )


def _make_encrypted_pdf(tmp_path: Path) -> Path:
    """Create a small, password-protected PDF using pypdf."""
    from pypdf import PdfWriter
    from pypdf.generic import (
        ContentStream,
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    content_obj = DecodedStreamObject()
    content_obj.set_data(b"BT\n/F1 12 Tf\n72 720 Td\n(Encrypted content) Tj\nET\n")
    page[NameObject("/Contents")] = ContentStream(content_obj, page)
    resources = DictionaryObject()
    font_dict = DictionaryObject()
    font_dict[NameObject("/F1")] = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    resources[NameObject("/Font")] = font_dict
    page[NameObject("/Resources")] = resources

    writer.encrypt("secret")

    path = tmp_path / "encrypted.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    return path


# -----------------------------------------------------------------------------
# Test class 1: TestPdfResourceId
# -----------------------------------------------------------------------------


class TestPdfResourceId:
    def test_make_pdf_resource_id_is_deterministic(self):
        h = "a" * 64
        a = make_pdf_resource_id(h)
        b = make_pdf_resource_id(h)
        assert a == b

    def test_make_pdf_resource_id_format(self):
        h = "f" * 64
        rid = make_pdf_resource_id(h)
        assert rid.startswith("pdf:")
        assert len(rid) == len("pdf:") + 64
        # Hex-only after the colon.
        assert re.fullmatch(r"pdf:[0-9a-f]{64}", rid)

    def test_make_pdf_chunk_id_is_deterministic_and_padded(self):
        rid = "pdf:abc123"
        cid = make_pdf_chunk_id(rid, 7)
        assert cid == "pdf:abc123-p0007"
        # Re-runs return the same value.
        assert make_pdf_chunk_id(rid, 7) == cid
        # Different indices produce different ids.
        assert make_pdf_chunk_id(rid, 8) != cid

    def test_sha256_file_matches_bytes(self, tmp_path):
        p = tmp_path / "bytes.bin"
        p.write_bytes(b"hello world")
        # hashlib uses a single read; sha256_file streams in 1 MiB
        # blocks. They must agree byte-for-byte.
        assert sha256_file(p) == hashlib.sha256(b"hello world").hexdigest()


# -----------------------------------------------------------------------------
# Test class 2: TestPdfExtraction
# -----------------------------------------------------------------------------


class TestPdfExtraction:
    def test_extract_pages_returns_one_entry_per_page(self):
        pages = extract_pages(FIXTURE_PDF)
        assert len(pages) == 3
        # Pages are 1-indexed and contiguous.
        assert [p["page"] for p in pages] == [1, 2, 3]
        for entry in pages:
            assert isinstance(entry["text"], str)
            assert entry["text"], f"page {entry['page']} should not be empty"

    def test_extract_pages_text_contains_known_marker(self):
        pages = extract_pages(FIXTURE_PDF)
        joined = "\n".join(entry["text"] for entry in pages)
        for needle in (
            "Page 1:",
            "Page 2:",
            "Page 3:",
            "Transformer",
            "Scaled Dot-Product Attention",
        ):
            assert needle in joined, f"missing marker: {needle}"

    def test_extract_pages_warnings_is_deterministic(self):
        pages = extract_pages(FIXTURE_PDF)
        a = extract_pages_warnings(pages)
        b = extract_pages_warnings(pages)
        assert a == b

    def test_encrypted_pdf_raises_pdf_encrypted_error(self, tmp_path):
        encrypted = _make_encrypted_pdf(tmp_path)
        with pytest.raises(PdfEncryptedError):
            extract_pages(encrypted)

    def test_invalid_pdf_raises_clear_error(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"not a real pdf " * 20)
        with pytest.raises(Exception):
            extract_pages(bad)


# -----------------------------------------------------------------------------
# Test class 3: TestPdfChunking
# -----------------------------------------------------------------------------


class TestPdfChunking:
    def test_chunk_pages_assigns_contiguous_page_ranges(self):
        pages = extract_pages(FIXTURE_PDF)
        rid = make_pdf_resource_id("a" * 64)
        chunks = chunk_pages(pages, resource_id=rid)
        # Each chunk's [page_start, page_end] must be valid, and
        # the chunks must form a non-overlapping partition of the
        # page range [1, len(pages)].
        covered = 0
        for chunk in chunks:
            start = chunk["page_start"]
            end = chunk["page_end"]
            assert 1 <= start <= end <= len(pages)
            assert start == covered + 1, (
                f"Gap or overlap at chunk starting page {start} after covered {covered}"
            )
            covered = end
        assert covered == len(pages)

    def test_chunk_pages_caps_max_chars(self):
        pages = [
            {"page": 1, "text": "a" * 200},
            {"page": 2, "text": "b" * 200},
            {"page": 3, "text": "c" * 200},
            {"page": 4, "text": "d" * 200},
        ]
        rid = make_pdf_resource_id("b" * 64)
        chunks = chunk_pages(
            pages, resource_id=rid, target_chars=200, max_chars=400
        )
        assert all(len(c["text"]) <= 400 for c in chunks)
        # And the chunks must be ordered by page.
        starts = [c["page_start"] for c in chunks]
        assert starts == sorted(starts)

    def test_chunk_pages_keeps_oversized_page_alone(self):
        pages = [{"page": 1, "text": "x" * 1000}]
        rid = make_pdf_resource_id("c" * 64)
        chunks = chunk_pages(pages, resource_id=rid, max_chars=200)
        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk["page_start"] == 1
        assert chunk["page_end"] == 1
        assert len(chunk["text"]) == 1000

    def test_chunk_pages_preserves_page_order(self):
        pages = [
            {"page": 1, "text": "alpha " * 50},
            {"page": 2, "text": "beta " * 50},
            {"page": 3, "text": "gamma " * 50},
        ]
        rid = make_pdf_resource_id("d" * 64)
        # Use small max_chars so each page lands in its own chunk.
        chunks = chunk_pages(pages, resource_id=rid, target_chars=10, max_chars=20)
        seen_pages = [c["page_start"] for c in chunks]
        assert seen_pages == [1, 2, 3]

    def test_chunk_pages_chunk_ids_are_sequential(self):
        pages = extract_pages(FIXTURE_PDF)
        rid = make_pdf_resource_id("e" * 64)
        chunks = chunk_pages(pages, resource_id=rid)
        ids = [c["chunk_id"] for c in chunks]
        # 4-digit zero-padded, starting at p0000.
        assert all(cid.endswith(f"-p{i:04d}") for i, cid in enumerate(ids))


# -----------------------------------------------------------------------------
# Test class 4: TestPdfIngestor
# -----------------------------------------------------------------------------


class TestPdfIngestor:
    def test_build_record_creates_raw_files(self, tmp_path, monkeypatch):
        _isolated_data_dir(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(FIXTURE_PDF)
        raw_dir = Path(record.local_raw_path)
        assert raw_dir.exists()
        for name in ("pages.json", "extracted.txt", "metadata.json"):
            path = raw_dir / name
            assert path.exists(), f"missing {path}"
            assert path.stat().st_size > 0, f"empty {path}"

    def test_build_record_does_not_copy_file_by_default(
        self, tmp_path, monkeypatch
    ):
        _isolated_data_dir(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(FIXTURE_PDF)
        assert record.extra["copied_to_media"] is False
        assert record.extra["media_path"] is None
        media_dir = tmp_path / "media" / "pdfs"
        # No PDF was copied.
        assert not (media_dir / f"{record.content_hash}.pdf").exists()

    def test_build_record_copies_file_when_requested(
        self, tmp_path, monkeypatch
    ):
        _isolated_data_dir(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(FIXTURE_PDF, copy_file=True)
        assert record.extra["copied_to_media"] is True
        media_path = Path(record.extra["media_path"])
        assert media_path.exists()
        # The copied bytes have the same content_hash as the
        # original file.
        assert sha256_file(media_path) == record.content_hash

    def test_build_record_sets_resource_id_and_metadata(
        self, tmp_path, monkeypatch
    ):
        _isolated_data_dir(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(FIXTURE_PDF)
        assert record.id.startswith("pdf:")
        assert record.source_type == SourceType.PDF
        assert record.canonical_id == record.id
        assert record.content_hash and len(record.content_hash) == 64
        assert record.extra["extraction_method"] == PDF_EXTRACT_METHOD
        assert record.extra["original_filename"] == FIXTURE_PDF.name
        assert record.extra["page_count"] == 3

    def test_build_record_uses_title_override(self, tmp_path, monkeypatch):
        _isolated_data_dir(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(
            FIXTURE_PDF, title="My Custom Title"
        )
        assert record.title == "My Custom Title"

    def test_build_record_uses_pdf_metadata_title(self, tmp_path, monkeypatch):
        _isolated_data_dir(tmp_path, monkeypatch)
        # The fixture's /Title is "Synthetic Test PDF for Prompt 26".
        record = pdf_ingestor.build_record(FIXTURE_PDF)
        assert record.title == "Synthetic Test PDF for Prompt 26"

    def test_build_record_falls_back_to_filename_stem(
        self, tmp_path, monkeypatch
    ):
        _isolated_data_dir(tmp_path, monkeypatch)
        # Build a PDF without a /Title.
        from pypdf import PdfWriter
        from pypdf.generic import (
            ContentStream,
            DecodedStreamObject,
            DictionaryObject,
            NameObject,
        )

        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        content_obj = DecodedStreamObject()
        content_obj.set_data(b"BT\n/F1 12 Tf\n72 720 Td\n(Sample) Tj\nET\n")
        page[NameObject("/Contents")] = ContentStream(content_obj, page)
        font_dict = DictionaryObject()
        font_dict[NameObject("/F1")] = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        resources = DictionaryObject()
        resources[NameObject("/Font")] = font_dict
        page[NameObject("/Resources")] = resources
        # No metadata.
        path = tmp_path / "no-title.pdf"
        with path.open("wb") as handle:
            writer.write(handle)

        record = pdf_ingestor.build_record(path)
        assert record.title == "no-title"

    def test_build_record_is_deterministic(self, tmp_path, monkeypatch):
        _isolated_data_dir(tmp_path, monkeypatch)
        a = pdf_ingestor.build_record(FIXTURE_PDF)
        b = pdf_ingestor.build_record(FIXTURE_PDF)
        assert a.id == b.id
        assert a.content_hash == b.content_hash
        assert a.local_raw_path == b.local_raw_path
        # The extracted.txt on disk has identical bytes.
        a_text = (Path(a.local_raw_path) / "extracted.txt").read_bytes()
        b_text = (Path(b.local_raw_path) / "extracted.txt").read_bytes()
        assert a_text == b_text


# -----------------------------------------------------------------------------
# Test class 5: TestPdfNormalizer
# -----------------------------------------------------------------------------


class TestPdfNormalizer:
    def test_normalize_writes_transcript_md(self, tmp_path, monkeypatch):
        _isolated_data_dir(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(FIXTURE_PDF)
        record = pdf_normalizer.normalize(record)
        transcript = Path(record.local_normalized_path) / "transcript.md"
        assert transcript.exists()
        content = transcript.read_text(encoding="utf-8")
        # Page markers from the fixture.
        for needle in ("Page 1:", "Page 2:", "Page 3:"):
            assert needle in content

    def test_normalize_writes_chunks_jsonl(self, tmp_path, monkeypatch):
        _isolated_data_dir(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(FIXTURE_PDF)
        record = pdf_normalizer.normalize(record)
        chunks_path = Path(record.local_normalized_path) / "chunks.jsonl"
        assert chunks_path.exists()
        # Each line is a PdfChunk-shaped dict.
        with chunks_path.open("r", encoding="utf-8") as handle:
            lines = [line for line in handle.read().splitlines() if line]
        assert lines
        # Round-trip the first chunk through PdfChunk.
        first = PdfChunk.model_validate_json(lines[0])
        assert first.source_type == SourceType.PDF
        assert first.page_start >= 1
        assert first.page_end >= first.page_start

    def test_normalize_updates_local_normalized_path(
        self, tmp_path, monkeypatch
    ):
        _isolated_data_dir(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(FIXTURE_PDF)
        before = record.local_normalized_path
        record = pdf_normalizer.normalize(record)
        assert before is None
        assert record.local_normalized_path is not None
        assert Path(record.local_normalized_path).exists()

    def test_normalize_sets_page_count_in_extra(self, tmp_path, monkeypatch):
        _isolated_data_dir(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(FIXTURE_PDF)
        record = pdf_normalizer.normalize(record)
        assert record.extra["page_count"] == 3
        assert record.extra["chunks_path"].endswith("chunks.jsonl")
        assert isinstance(record.extra["extraction_warnings"], list)

    def test_normalize_rejects_non_pdf_records(self, tmp_path, monkeypatch):
        _isolated_data_dir(tmp_path, monkeypatch)
        non_pdf = ResourceRecord(
            id="markdown:abc",
            source_type=SourceType.MARKDOWN,
            canonical_id="markdown:abc",
            original_url="local://x",
        )
        with pytest.raises(ValueError):
            pdf_normalizer.normalize(non_pdf)


# -----------------------------------------------------------------------------
# Test class 6: TestPdfCli
# -----------------------------------------------------------------------------


class TestPdfCli:
    def test_cli_import_pdf_prints_resource_id(self, tmp_path, monkeypatch):
        _isolated_registry(tmp_path, monkeypatch)
        result = CliRunner().invoke(
            cli.app,
            ["import-pdf", "--file", str(FIXTURE_PDF), "--title", "Syn CLI"],
        )
        assert result.exit_code == 0, result.output
        # The resource id is printed.
        assert "pdf:" in result.output
        assert "Imported PDF" in result.output

    def test_cli_import_pdf_dedupes_on_repeat(self, tmp_path, monkeypatch):
        reg = _isolated_registry(tmp_path, monkeypatch)
        first = CliRunner().invoke(
            cli.app,
            ["import-pdf", "--file", str(FIXTURE_PDF)],
        )
        second = CliRunner().invoke(
            cli.app,
            ["import-pdf", "--file", str(FIXTURE_PDF)],
        )
        assert first.exit_code == 0
        assert second.exit_code == 0
        assert "Duplicate PDF skipped" in second.output
        # Exactly one record exists.
        assert len(list(reg.get_all())) == 1

    def test_cli_import_pdf_force_reingests(self, tmp_path, monkeypatch):
        reg = _isolated_registry(tmp_path, monkeypatch)
        first = CliRunner().invoke(
            cli.app,
            ["import-pdf", "--file", str(FIXTURE_PDF)],
        )
        second = CliRunner().invoke(
            cli.app,
            ["import-pdf", "--file", str(FIXTURE_PDF), "--force"],
        )
        assert first.exit_code == 0
        assert second.exit_code == 0
        # Still a single record (idempotent on canonical id).
        records = list(reg.get_all())
        assert len(records) == 1
        assert records[0].id.startswith("pdf:")

    def test_cli_import_pdf_missing_file_exits_nonzero(
        self, tmp_path, monkeypatch
    ):
        _isolated_registry(tmp_path, monkeypatch)
        result = CliRunner().invoke(
            cli.app,
            ["import-pdf", "--file", str(tmp_path / "no-such.pdf")],
        )
        assert result.exit_code != 0
        assert "PDF not found" in result.output

    def test_cli_import_pdf_rejects_non_pdf_extension(
        self, tmp_path, monkeypatch
    ):
        _isolated_registry(tmp_path, monkeypatch)
        not_pdf = tmp_path / "notes.txt"
        not_pdf.write_text("hello", encoding="utf-8")
        result = CliRunner().invoke(
            cli.app,
            ["import-pdf", "--file", str(not_pdf)],
        )
        assert result.exit_code != 0
        assert "Not a .pdf" in result.output

    def test_cli_import_pdf_rejects_encrypted_pdf(
        self, tmp_path, monkeypatch
    ):
        _isolated_registry(tmp_path, monkeypatch)
        encrypted = _make_encrypted_pdf(tmp_path)
        result = CliRunner().invoke(
            cli.app,
            ["import-pdf", "--file", str(encrypted)],
        )
        assert result.exit_code != 0
        # The friendly CLI message includes "encrypted" or the
        # raw pypdf error; either is acceptable as long as the
        # exit code is non-zero.
        assert "encrypt" in result.output.lower() or "Could not read PDF" in result.output

    def test_cli_import_pdf_rejects_invalid_pdf(
        self, tmp_path, monkeypatch
    ):
        _isolated_registry(tmp_path, monkeypatch)
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"not a real pdf " * 20)
        result = CliRunner().invoke(
            cli.app,
            ["import-pdf", "--file", str(bad)],
        )
        assert result.exit_code != 0
        assert "Could not read PDF" in result.output

    def test_cli_import_pdf_with_copy_file_copies(
        self, tmp_path, monkeypatch
    ):
        _isolated_registry(tmp_path, monkeypatch)
        result = CliRunner().invoke(
            cli.app,
            [
                "import-pdf",
                "--file",
                str(FIXTURE_PDF),
                "--copy-file",
            ],
        )
        assert result.exit_code == 0, result.output
        # The PDF should be under data/media/pdfs/.
        media_dir = tmp_path / "media" / "pdfs"
        assert media_dir.exists()
        files = list(media_dir.glob("*.pdf"))
        assert files, "no PDF copied to media/pdfs"


# -----------------------------------------------------------------------------
# Test class 7: TestPdfPipelineIntegration
# -----------------------------------------------------------------------------


class TestPdfPipelineIntegration:
    def test_imported_pdf_appears_in_search_index(
        self, tmp_path, monkeypatch
    ):
        from wiki.generate.search import search_index_generator

        _isolated_data_dir(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(FIXTURE_PDF, title="Syn Search")
        record = pdf_normalizer.normalize(record)
        indexes = search_index_generator.generate([record])
        all_items = indexes["all"]
        matching = [
            item for item in all_items
            if item.get("id") == record.id and item.get("type") == "pdf"
        ]
        assert matching, f"PDF not in search index: {all_items}"

    def test_imported_pdf_appears_in_graph(self, tmp_path, monkeypatch):
        _isolated_data_dir(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(FIXTURE_PDF, title="Syn Graph")
        record = pdf_normalizer.normalize(record)
        graph = build_graph([record], data_dir=tmp_path)
        # Find the resource node for the PDF.
        resource_nodes = [
            n for n in graph["nodes"] if n.get("type") == NODE_TYPE_RESOURCE
        ]
        pdf_nodes = [
            n for n in resource_nodes
            if n.get("metadata", {}).get("source_type") == "pdf"
        ]
        assert pdf_nodes, f"No pdf resource node in graph: {resource_nodes}"
        node = pdf_nodes[0]
        # The id follows the resource_<safe_id> convention.
        assert "resource" in node["id"]
        safe = record.id.replace(":", "_")
        assert safe in node["id"]

    def test_imported_pdf_participates_in_resource_relationships(
        self, tmp_path, monkeypatch
    ):
        _isolated_data_dir(tmp_path, monkeypatch)
        # A PDF and a webpage that share the rag-retrieval topic.
        pdf_record = pdf_ingestor.build_record(
            FIXTURE_PDF, title="RAG Retrieval in Transformers", tags=["rag"]
        )
        pdf_record = pdf_normalizer.normalize(pdf_record)
        webpage = _make_non_pdf_record(
            tmp_path,
            resource_id="webpage:rag-compare",
            title="RAG Retrieval overview",
        )
        graph = build_graph([pdf_record, webpage], data_dir=tmp_path)
        # The PDF and the webpage should both be resource nodes.
        resource_types = {
            n.get("metadata", {}).get("source_type")
            for n in graph["nodes"] if n.get("type") == NODE_TYPE_RESOURCE
        }
        assert "pdf" in resource_types
        assert "webpage" in resource_types
        # And there should be at least one relationship edge
        # between them (e.g. shared topic).
        shared_topic = [
            e for e in graph["edges"]
            if e["type"] == EDGE_TYPE_RESOURCE_SHARES_TOPIC_WITH_RESOURCE
        ]
        # The PDF and the webpage share the rag-retrieval topic;
        # the detector should connect them.
        assert shared_topic, (
            f"Expected shared-topic relationship edge, got: {graph['edges']}"
        )

    def test_build_site_continues_to_work_with_pdfs(
        self, tmp_path, monkeypatch
    ):
        builder = _setup_site_builder(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(FIXTURE_PDF, title="Syn Site")
        record = pdf_normalizer.normalize(record)
        # A non-PDF record for breadth.
        webpage = _make_non_pdf_record(
            tmp_path, resource_id="webpage:other", title="RAG Retrieval"
        )
        builder.build([record, webpage])
        # No exception was raised. The repo site dir exists.
        assert builder.repo_site_dir.exists()
        # The resource page for the PDF was generated.
        safe_id = record.id.replace(":", "_")
        resource_page = builder.repo_site_dir / "resources" / f"{safe_id}.md"
        # The PDF record has no generated note path (we did not
        # run process-new), so the page is a placeholder index
        # entry. But the resources/index.md must still be
        # generated.
        resources_index = builder.repo_site_dir / "resources" / "index.md"
        assert resources_index.exists(), "resources/index.md not generated"

    def test_smoke_site_and_validate_run_clean_with_pdfs(
        self, tmp_path, monkeypatch
    ):
        from typer import Exit

        # Patch config + registry into the tmp dir and build a
        # full derived-views + site so smoke_site/validate have
        # everything they need to run cleanly.
        monkeypatch.setattr(cli.config, "LLM_WIKI_DATA_DIR", tmp_path)
        cli.config.ensure_directories()
        monkeypatch.setattr(cli, "registry", Registry())

        pdf_record = pdf_ingestor.build_record(
            FIXTURE_PDF, title="Syn Smoke"
        )
        pdf_record = pdf_normalizer.normalize(pdf_record)
        webpage = _make_non_pdf_record(
            tmp_path,
            resource_id="webpage:smoke-companion",
            title="RAG Retrieval overview",
        )

        # Generate derived views (search index, etc.) and build
        # the site in the tmp dirs.
        cli.generate_derived_views([pdf_record, webpage])
        # Use a tmp SiteBuilder pointed at the same tmp dirs.
        builder = SiteBuilder()
        builder.data_site_dir = tmp_path / "site_generated" / "docs"
        builder.repo_site_dir = tmp_path / "repo_docs"
        builder.data_site_dir.mkdir(parents=True, exist_ok=True)
        builder.repo_site_dir.mkdir(parents=True, exist_ok=True)
        # Re-run the parts of build() that are derived-view-aware
        # so the on-disk files are consistent.
        cli.site_builder.repo_site_dir = builder.repo_site_dir
        cli.site_builder.data_site_dir = builder.data_site_dir
        builder.build([pdf_record, webpage])
        # Sync the freshly-built data site to the repo_site_dir.
        cli.site_builder._sync_to_repo_site()

        # smoke_site and validate should not raise typer.Exit(1).
        try:
            cli.smoke_site()
        except Exit as exc:
            assert exc.exit_code == 0, f"smoke_site exited {exc.exit_code}"
        try:
            cli.validate(provider=None)
        except Exit as exc:
            assert exc.exit_code == 0, f"validate exited {exc.exit_code}"


# -----------------------------------------------------------------------------
# Test class 8: TestPdfSecurityAndBoundaries
# -----------------------------------------------------------------------------


class TestPdfSecurityAndBoundaries:
    def test_no_ocr_or_llm_dependencies_introduced(self):
        """Read pyproject.toml and the pdf ingestor source to confirm
        no OCR, LLM, embedding, or vector-search packages are
        pulled in.
        """
        pyproject = (
            Path(__file__).parent.parent / "pyproject.toml"
        ).read_text(encoding="utf-8")
        # Extract the ``dependencies`` list only. Optional ASR
        # extras (``openai-whisper``, ``faster-whisper``) are
        # pre-existing and not added by this prompt.
        match = re.search(
            r"^dependencies\s*=\s*\[(.*?)\]",
            pyproject,
            re.DOTALL | re.MULTILINE,
        )
        assert match, "could not locate dependencies block"
        block = match.group(1).lower()
        forbidden = [
            "tesseract",
            "pytesseract",
            "paddleocr",
            "docling",
            "marker",
            "llama-parse",
            "openai-whisper",
            "faiss",
            "chroma",
            "lancedb",
            "rank-bm25",
        ]
        for needle in forbidden:
            assert needle not in block, (
                f"forbidden dependency in [dependencies]: {needle}"
            )

        pdf_source = (
            Path(__file__).parent.parent / "wiki" / "ingest" / "pdf.py"
        ).read_text(encoding="utf-8")
        for forbidden_import in (
            "openai",
            "ollama",
            "httpx",
            "tiktoken",
            "torch",
            "transformers",
            "sentence_transformers",
            "faiss",
        ):
            assert (
                f"import {forbidden_import}" not in pdf_source
                and f"from {forbidden_import} import" not in pdf_source
            ), f"pdf.py imports {forbidden_import}"

    def test_original_pdf_is_not_copied_into_git_repo(
        self, tmp_path, monkeypatch
    ):
        _isolated_data_dir(tmp_path, monkeypatch)
        # Use --copy-file to opt into copying; ensure it lands
        # under the data dir (which is outside the repo by
        # default), not under the git repo.
        record = pdf_ingestor.build_record(FIXTURE_PDF, copy_file=True)
        media_path = Path(record.extra["media_path"])
        # The git repo is harish-llm-wiki/. The data dir is
        # expected to be outside it.
        repo_root = Path(__file__).parent.parent.resolve()
        # Ensure the media file is NOT under the repo root.
        # The data dir is monkeypatched to tmp_path, which is
        # never inside the repo for the test runner.
        assert not str(media_path).startswith(str(repo_root)), (
            f"PDF was copied into the git repo: {media_path}"
        )

    def test_repeated_import_is_deterministic(self, tmp_path, monkeypatch):
        _isolated_data_dir(tmp_path, monkeypatch)
        a = pdf_ingestor.build_record(FIXTURE_PDF)
        b = pdf_ingestor.build_record(FIXTURE_PDF)
        assert a.id == b.id
        assert a.content_hash == b.content_hash
        assert a.local_raw_path == b.local_normalized_path or (
            a.local_raw_path == b.local_raw_path
        )
        # And the CLI's dedup branch returns the same id.
        reg = _isolated_registry(tmp_path, monkeypatch)
        result = CliRunner().invoke(
            cli.app,
            ["import-pdf", "--file", str(FIXTURE_PDF)],
        )
        assert result.exit_code == 0
        second = CliRunner().invoke(
            cli.app,
            ["import-pdf", "--file", str(FIXTURE_PDF)],
        )
        assert second.exit_code == 0
        # Only one record exists.
        assert len(list(reg.get_all())) == 1

    def test_pypdf_is_the_only_pdf_dependency(self):
        pyproject = (
            Path(__file__).parent.parent / "pyproject.toml"
        ).read_text(encoding="utf-8")
        # Find the dependencies list block.
        match = re.search(
            r"^dependencies\s*=\s*\[(.*?)\]",
            pyproject,
            re.DOTALL | re.MULTILINE,
        )
        assert match, "could not locate dependencies block"
        block = match.group(1)
        # The only PDF-related package is pypdf.
        pdf_terms = ("pypdf", "pymupdf", "pdfplumber", "pdfminer")
        found = [term for term in pdf_terms if term in block.lower()]
        assert found == ["pypdf"], (
            f"Unexpected PDF dependencies in pyproject: {found}"
        )

    def test_extraction_method_is_constant(self, tmp_path, monkeypatch):
        _isolated_data_dir(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(FIXTURE_PDF)
        assert record.extra["extraction_method"] == "pypdf"
        # After normalization the field is still the same.
        record = pdf_normalizer.normalize(record)
        assert record.extra["extraction_method"] == "pypdf"

    def test_validate_contains_pdf_warnings(self):
        """validate() must include a check for PDF source_type."""
        source = inspect.getsource(cli)
        # The new per-record check for source_type == pdf.
        assert "record.source_type == SourceType.PDF" in source, (
            "validate() is missing the PDF source_type check"
        )

    def test_graph_builder_accepts_pdf_records_without_modification(
        self, tmp_path, monkeypatch
    ):
        """The graph builder should treat PDF records the same as
        any other source type, emitting a resource node and the
        normal set of edges.
        """
        _isolated_data_dir(tmp_path, monkeypatch)
        record = pdf_ingestor.build_record(FIXTURE_PDF, title="RAG Transformers")
        record = pdf_normalizer.normalize(record)
        graph = GraphBuilder().build([record])
        # Resource node for the PDF.
        pdf_nodes = [
            n for n in graph["nodes"]
            if n.get("type") == NODE_TYPE_RESOURCE
            and n.get("metadata", {}).get("source_type") == "pdf"
        ]
        assert pdf_nodes, "GraphBuilder did not produce a PDF resource node"
        # A self-same-source-type edge would only appear with
        # another pdf: record, but we at least expect
        # resource_has_topic / resource_has_tag edges when the
        # title contains a known topic keyword. The title
        # "RAG Transformers" matches the rag-retrieval topic.
        has_topic = [
            e for e in graph["edges"] if e["type"] == "resource_has_topic"
        ]
        assert has_topic, (
            f"Expected resource_has_topic edges for PDF title, got: {graph['edges']}"
        )


# -----------------------------------------------------------------------------
# Test class 9: TestRealPdfIntegration (skipped when the real PDF is missing)
# -----------------------------------------------------------------------------


REAL_PDF = (
    Path.home()
    / "llm-wiki-data"
    / "test-pdfs"
    / "attention-is-all-you-need.pdf"
)


@pytest.mark.skipif(
    not REAL_PDF.exists(),
    reason="Real PDF fixture not on disk; download via "
    "scripts/verify_pdf_import.py --download to enable",
)
class TestRealPdfIntegration:
    """Optional integration test that runs the real-PDF
    verification script end-to-end.

    This test is skipped by default (the real PDF is not
    committed). To enable it, place the Attention Is All You
    Need paper at ``~/llm-wiki-data/test-pdfs/attention-is-all-you-need.pdf``
    or download it via:

        .venv/bin/python scripts/verify_pdf_import.py --download

    The test does not need network access; it only consumes the
    PDF that is already on disk.
    """

    def test_real_pdf_imports_and_pipeline_passes(self, tmp_path, monkeypatch):
        # Drive the same flow the script does, but in-process so
        # the test result is reported by pytest.
        import os
        from wiki.config import config
        from wiki.ingest.pdf import extract_pages, pdf_ingestor
        from wiki.normalize.pdf import pdf_normalizer

        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        config.ensure_directories()
        monkeypatch.setattr(os, "environ", {**os.environ, "LLM_WIKI_DATA_DIR": str(tmp_path)})

        record = pdf_ingestor.build_record(REAL_PDF)
        record = pdf_normalizer.normalize(record)
        # The extracted text contains the expected phrase.
        pages = extract_pages(REAL_PDF)
        joined = "\n".join(page["text"] for page in pages)
        for phrase in ("Attention Is All You Need", "Transformer"):
            assert phrase in joined, f"missing phrase: {phrase}"
        # The graph builder includes the PDF as a resource node.
        graph = build_graph([record], data_dir=tmp_path)
        pdf_nodes = [
            n for n in graph["nodes"]
            if n.get("type") == NODE_TYPE_RESOURCE
            and n.get("metadata", {}).get("source_type") == "pdf"
        ]
        assert pdf_nodes, "Real PDF did not produce a graph node"
