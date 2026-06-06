"""Normalize local PDF ingestor output into citeable chunks.

The PDF ingestor writes a ``pages.json`` file under
``raw/pdf/<content_hash[:8]>/`` together with ``metadata.json``
and ``extracted.txt``. This module reads that raw output, builds
a human-readable ``transcript.md`` plus a deterministic
``chunks.jsonl``, and updates the record's
``local_normalized_path``.

This module mirrors the shape of
``wiki/normalize/transcript_media.py`` so the rest of the
pipeline (citation rendering, graph builder, future chunk index)
treats PDFs as a first-class source.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from wiki.config import config
from wiki.ingest.pdf import (
    chunk_pages,
    extract_pages_warnings,
)
from wiki.schemas import PdfChunk, ResourceRecord, SourceType
from wiki.storage import Storage


class PdfNormalizer:
    """Read PDF pages, build chunks, write the normalized files."""

    def normalize(self, record: ResourceRecord) -> ResourceRecord:
        if record.source_type != SourceType.PDF:
            raise ValueError("PdfNormalizer only handles PDF records")
        if not record.local_raw_path:
            raise ValueError(f"No raw path for resource {record.id}")
        raw_dir = Path(record.local_raw_path)
        pages_path = raw_dir / "pages.json"
        pages = self._load_pages(pages_path)
        content_hash = record.content_hash or record.id.split(":", 1)[-1]
        norm_dir = config.get_data_path("normalized", "pdf", content_hash[:8])
        norm_dir.mkdir(parents=True, exist_ok=True)

        # Render the human-readable transcript and write it.
        markdown = self._render_markdown(record, pages)
        Storage.write_text(markdown, norm_dir / "transcript.md")

        # Build the chunks via the same deterministic chunker
        # the ingestor uses for tests, then write them as JSONL
        # plus a full JSON list for the processed/ view.
        chunks = self.pages_to_chunks(record, pages)
        chunks_path = norm_dir / "chunks.jsonl"
        with chunks_path.open("w", encoding="utf-8") as handle:
            for chunk in chunks:
                handle.write(json.dumps(chunk.model_dump(), ensure_ascii=False) + "\n")

        # Mirror chunks into processed/pdfs/<hash[:8]>/chunks.json
        # so the per-prompt data layout lives next to the raw
        # files when an LLM/RAG step needs them.
        processed_dir = config.get_data_path("processed", "pdfs", content_hash[:8])
        processed_dir.mkdir(parents=True, exist_ok=True)
        chunks_json = processed_dir / "chunks.json"
        Storage.write_json(
            [chunk.model_dump() for chunk in chunks],
            chunks_json,
        )
        # Copy pages.json, extracted.txt, and metadata.json into
        # processed/ for downstream consumers (Prompt 27 chunk
        # index, etc.) to read from a single canonical location.
        for source_name in ("pages.json", "extracted.txt", "metadata.json"):
            source = raw_dir / source_name
            if source.exists():
                shutil.copy2(source, processed_dir / source_name)

        # Update the record.
        record.local_normalized_path = norm_dir
        record.extra["page_count"] = len(pages)
        record.extra["chunks_path"] = str(chunks_path)
        record.extra["extraction_warnings"] = extract_pages_warnings(pages)
        return record

    def _load_pages(self, pages_path: Path) -> list[dict[str, Any]]:
        if not pages_path.exists():
            raise FileNotFoundError(f"Missing pages.json: {pages_path}")
        data = Storage.read_json(pages_path)
        if not isinstance(data, list):
            raise ValueError(f"pages.json is not a list: {pages_path}")
        return data

    def _render_markdown(self, record: ResourceRecord, pages: list[dict[str, Any]]) -> str:
        title = record.title or record.id
        source_file = record.extra.get("original_path") or record.original_url
        lines = [
            f"# {title}",
            "",
            f"Source file: {source_file}",
            f"Pages: {len(pages)}",
            f"Extraction method: {record.extra.get('extraction_method', 'pypdf')}",
            "",
            "## Transcript",
            "",
        ]
        for entry in pages:
            lines.append(f"### Page {entry['page']}")
            lines.append("")
            text = str(entry.get("text") or "").rstrip()
            lines.append(text or "_(no extractable text)_")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def pages_to_chunks(
        self,
        record: ResourceRecord,
        pages: list[dict[str, Any]],
    ) -> list[PdfChunk]:
        """Build :class:`PdfChunk` instances from extracted pages.

        This is a thin wrapper over
        :func:`wiki.ingest.pdf.chunk_pages` that constructs
        pydantic models for type safety.
        """
        raw_chunks = chunk_pages(
            pages,
            resource_id=record.id,
            title=record.title,
            file_path=record.extra.get("original_path"),
        )
        return [PdfChunk(**chunk) for chunk in raw_chunks]


pdf_normalizer = PdfNormalizer()
