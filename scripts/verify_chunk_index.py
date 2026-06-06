#!/usr/bin/env python
"""Manual verification script for the chunk index (Prompt 27).

This is the real-PDF chunk verification flow described in
``prompt27.md`` §"Real PDF verification requirement".

It runs against an isolated data dir so the user's main wiki state
is untouched. The default PDF is
``~/llm-wiki-data/test-pdfs/attention-is-all-you-need.pdf`` (matches
``scripts/verify_pdf_import.py`` from Prompt 26).

Usage
-----

    # Use the local PDF if present
    .venv/bin/python scripts/verify_chunk_index.py

    # Download the PDF first (uses the same download helper as
    # ``scripts/verify_pdf_import.py``), then verify
    .venv/bin/python scripts/verify_chunk_index.py --download

The script prints a short summary and exits with status 0 on
success. It exits with status 1 if the PDF cannot be ingested or
the index does not contain the expected markers.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional

# Make the project importable when run as a script.
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from wiki import cli as wiki_cli  # noqa: E402
from wiki.chunks import build_chunk_index  # noqa: E402
from wiki.chunks.export import (  # noqa: E402
    chunk_index_output_paths,
    write_chunk_index,
)
from wiki.config import config  # noqa: E402
from wiki.ingest.pdf import pdf_ingestor  # noqa: E402
from wiki.normalize.pdf import pdf_normalizer  # noqa: E402
from wiki.registry import Registry  # noqa: E402
from wiki.schemas import SourceType  # noqa: E402


DEFAULT_PDF = Path.home() / "llm-wiki-data" / "test-pdfs" / "attention-is-all-you-need.pdf"
DEFAULT_PDF_URL = (
    "https://arxiv.org/pdf/1706.03762"
)
EXPECTED_MARKERS: tuple[str, ...] = (
    "Attention Is All You Need",
    "Transformer",
    "Scaled Dot-Product Attention",
)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdf",
        type=Path,
        default=DEFAULT_PDF,
        help="Path to a local PDF (default: %(default)s)",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the PDF with the same helper as verify_pdf_import.py",
    )
    parser.add_argument(
        "--keep-data-dir",
        action="store_true",
        help="Skip cleaning up the isolated data dir (useful for debugging)",
    )
    return parser.parse_args(argv)


def _maybe_download(pdf: Path) -> Path:
    """Download the PDF to the same path used by verify_pdf_import.py."""
    pdf.parent.mkdir(parents=True, exist_ok=True)
    if pdf.exists():
        return pdf
    import urllib.request

    print(f"Downloading {DEFAULT_PDF_URL} -> {pdf}")
    with urllib.request.urlopen(DEFAULT_PDF_URL) as response, pdf.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return pdf


def _print_summary(record, result, paths) -> None:
    print("OK: Chunk index built from real PDF")
    print(f"  PDF resource id:    {record.id}")
    print(f"  Chunks in index:    {len(result.chunks)}")
    print(f"  Resources indexed:  {len(result.chunk_count_by_resource)}")
    print(f"  By source type:     {result.manifest.get('by_source_type')}")
    print(f"  Output chunks.json: {paths['chunks_json']}")
    print(f"  Output manifest:    {paths['manifest']}")
    print(f"  Warnings:           {len(result.warnings)}")


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    pdf_path = args.pdf
    if args.download or not pdf_path.exists():
        try:
            pdf_path = _maybe_download(pdf_path)
        except Exception as exc:
            print(f"FAIL: could not download PDF: {exc}", file=sys.stderr)
            return 1
    if not pdf_path.exists():
        print(f"FAIL: PDF not found at {pdf_path}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="wiki-chunk-verify-") as tmp:
        tmp_data_dir = Path(tmp) / "data"
        tmp_data_dir.mkdir(parents=True, exist_ok=True)

        # Re-point the global config at the isolated data dir.
        original_data_dir = config.LLM_WIKI_DATA_DIR
        original_db_path = wiki_cli.registry.db_path
        try:
            config.LLM_WIKI_DATA_DIR = tmp_data_dir
            config.ensure_directories()
            new_registry = Registry()
            wiki_cli.registry = new_registry

            # Ingest + normalize the PDF.
            record = pdf_ingestor.build_record(pdf_path)
            existing = new_registry.get_by_canonical_id(record.canonical_id)
            if existing is None:
                from wiki.schemas import ResourceIdentity, ResourceStatus

                identity = ResourceIdentity(
                    source_type=SourceType.PDF,
                    canonical_id=record.canonical_id,
                    original_url=record.original_url,
                    normalized_url=record.normalized_url,
                    content_hash=record.content_hash,
                )
                inserted = new_registry.insert(identity, status=ResourceStatus.NEW)
                record.id = inserted.id
                record.first_seen_at = inserted.first_seen_at
                record.last_seen_at = inserted.last_seen_at
            else:
                record.id = existing.id
                record.first_seen_at = existing.first_seen_at

            record = pdf_normalizer.normalize(record)
            new_registry.update(record)

            # Build the chunk index.
            result = build_chunk_index(list(new_registry.get_all()))
            paths = write_chunk_index(result)

            # Sanity-check: at least one PDF chunk and all markers.
            pdf_chunks = [c for c in result.chunks if c.source_type == "pdf"]
            if not pdf_chunks:
                print("FAIL: chunk index contains no PDF chunks", file=sys.stderr)
                return 1
            joined_text = "\n".join(c.text for c in pdf_chunks)
            for marker in EXPECTED_MARKERS:
                if marker not in joined_text:
                    print(
                        f"FAIL: expected marker {marker!r} not found in chunk text",
                        file=sys.stderr,
                    )
                    return 1

            # Sanity-check: manifest reports the pdf source type.
            by_source = result.manifest.get("by_source_type", {}) or {}
            if by_source.get("pdf", 0) < 1:
                print(
                    f"FAIL: manifest does not report pdf source type (got {by_source})",
                    file=sys.stderr,
                )
                return 1

            _print_summary(record, result, paths)
        finally:
            # Restore the global config / registry. The temp dir is
            # cleaned up by the context manager unless --keep-data-dir
            # was passed.
            config.LLM_WIKI_DATA_DIR = original_data_dir
            wiki_cli.registry.db_path = original_db_path

    if args.keep_data_dir:
        kept = Path(tempfile.gettempdir()) / "wiki-chunk-verify-keep"
        print(f"--keep-data-dir set; tmp data dir may still exist at {kept}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
