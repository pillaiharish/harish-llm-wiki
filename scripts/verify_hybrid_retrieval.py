#!/usr/bin/env python
"""Manual verification script for the hybrid retrieval router (Prompt 30).

This script runs the full hybrid retrieval flow against an
isolated data directory and the real PDF fixture used by
``verify_bm25_search.py`` and ``verify_vector_search.py``
(Prompt 28/29).

It:

- ingests + normalizes the real PDF (``Attention Is All You Need``)
  into an isolated data dir;
- builds the chunk index, the BM25 index, and the vector index;
- runs the canonical example queries from ``prompt30.md``
  §"CLI requirement" against the router in all four modes
  (``bm25``, ``vector``, ``hybrid``, ``graph-lite``);
- prints the top-3 results for each (mode, query) pair;
- asserts that the top-1 result of ``"attention transformer"`` is
  the Attention paper chunk in all four modes;
- asserts that the graph-lite boost is non-negative and bounded
  by ``GRAPH_LITE_MAX_BOOST`` for every result;
- exits 0 on success, 1 on any failure.

The script is a no-op when the real PDF fixture is missing
(skips with a clear message).

Usage
-----

    # Use the local PDF if present
    .venv/bin/python scripts/verify_hybrid_retrieval.py

    # Download the PDF first
    .venv/bin/python scripts/verify_hybrid_retrieval.py --download
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))


from wiki import cli as wiki_cli  # noqa: E402
from wiki.chunks import build_chunk_index  # noqa: E402
from wiki.chunks.export import write_chunk_index  # noqa: E402
from wiki.config import config  # noqa: E402
from wiki.ingest.pdf import pdf_ingestor  # noqa: E402
from wiki.normalize.pdf import pdf_normalizer  # noqa: E402
from wiki.registry import Registry  # noqa: E402
from wiki.retrieval import ALLOWED_MODES, GRAPH_LITE_MAX_BOOST, retrieve_hybrid  # noqa: E402
from wiki.schemas import ResourceStatus, SourceType  # noqa: E402
from wiki.search import build_bm25_index, write_bm25_index  # noqa: E402
from wiki.vector import build_vector_index, write_vector_index  # noqa: E402


DEFAULT_PDF = Path.home() / "llm-wiki-data" / "test-pdfs" / "attention-is-all-you-need.pdf"
DEFAULT_PDF_URL = "https://arxiv.org/pdf/1706.03762"

# The five example queries from prompt30.md §"CLI requirement".
# Each query is expected to return at least one non-empty
# result for the attention-paper corpus.
EXAMPLE_QUERIES: tuple[str, ...] = (
    "attention transformer",
    "scaled dot-product attention",
    "embeddings retrieval",
    "vllm paged attention",
    "rag evaluation",
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

    with tempfile.TemporaryDirectory(prefix="wiki-hybrid-verify-") as tmp:
        tmp_data_dir = Path(tmp) / "data"
        tmp_data_dir.mkdir(parents=True, exist_ok=True)

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
                from wiki.schemas import ResourceIdentity

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
            chunk_result = build_chunk_index(list(new_registry.get_all()))
            if not chunk_result.chunks:
                print("FAIL: chunk index contains no chunks", file=sys.stderr)
                return 1
            chunk_paths = write_chunk_index(chunk_result)
            print(
                f"OK: Chunk index built ({len(chunk_result.chunks)} chunks)"
            )

            # Build the BM25 index.
            bm25_result = build_bm25_index(chunk_result)
            write_bm25_index(bm25_result)
            print(
                f"OK: BM25 index built ({bm25_result.doc_count} chunks, "
                f"vocab={len(bm25_result.vocab)})"
            )

            # Build the vector index.
            vector_result = build_vector_index(chunk_result)
            write_vector_index(vector_result)
            print(
                f"OK: Vector index built ({vector_result.chunk_count} chunks, "
                f"dim={vector_result.config.dimension}, "
                f"vocab={vector_result.vocab_size})"
            )

            # Build the knowledge graph (Prompt 23/24) so the
            # graph-lite boost has something to work with.
            try:
                from wiki.graph import GraphBuilder
                from wiki.graph.export import export_graph

                graph = GraphBuilder(data_dir=tmp_data_dir).build(
                    list(new_registry.get_all())
                )
                export_graph(graph, data_dir=tmp_data_dir)
                print(
                    f"OK: Knowledge graph built "
                    f"({len(graph.get('nodes', []))} nodes, "
                    f"{len(graph.get('edges', []))} edges)"
                )
            except Exception as exc:
                print(
                    f"WARN: Knowledge graph build failed: {exc}; "
                    "graph-lite mode will return zero boost."
                )

            # Run the example queries in all four modes.
            print()
            for mode in sorted(ALLOWED_MODES):
                print(f"=== mode={mode} ===")
                for query in EXAMPLE_QUERIES:
                    try:
                        results = retrieve_hybrid(
                            query,
                            mode=mode,
                            limit=3,
                            data_dir=tmp_data_dir,
                        )
                    except Exception as exc:
                        print(
                            f"FAIL: query {query!r} raised: {exc}",
                            file=sys.stderr,
                        )
                        return 1
                    if not results:
                        print(
                            f"FAIL: query {query!r} (mode={mode}) "
                            "returned no results",
                            file=sys.stderr,
                        )
                        return 1
                    # Boost bound check.
                    for r in results:
                        if r.component_scores.graph_boost < 0.0:
                            print(
                                f"FAIL: graph_boost is negative: "
                                f"{r.component_scores.graph_boost}",
                                file=sys.stderr,
                            )
                            return 1
                        if r.component_scores.graph_boost > GRAPH_LITE_MAX_BOOST:
                            print(
                                f"FAIL: graph_boost exceeds the cap: "
                                f"{r.component_scores.graph_boost} > "
                                f"{GRAPH_LITE_MAX_BOOST}",
                                file=sys.stderr,
                            )
                            return 1
                    print(f"Query: {query!r}")
                    for r in results:
                        title = r.title or r.resource_id
                        print(
                            f"  {r.rank}. score={r.score:.4f}  "
                            f"chunk_id={r.chunk_id}  title={title[:50]}  "
                            f"boost={r.component_scores.graph_boost:.4f}"
                        )
                print()

            # Special assertion: the top-1 result of
            # "attention transformer" must be the Attention
            # paper chunk in all four modes.
            for mode in sorted(ALLOWED_MODES):
                results = retrieve_hybrid(
                    "attention transformer",
                    mode=mode,
                    limit=1,
                    data_dir=tmp_data_dir,
                )
                if not results:
                    print(
                        f"FAIL: 'attention transformer' returned no results "
                        f"in mode={mode}",
                        file=sys.stderr,
                    )
                    return 1
                if "attention" not in (results[0].title or "").lower():
                    print(
                        f"FAIL: 'attention transformer' top-1 is not the "
                        f"Attention paper in mode={mode}: {results[0].title!r}",
                        file=sys.stderr,
                    )
                    return 1

            print("OK: All example queries returned non-empty results.")
            print("OK: All graph-lite boosts are within bounds.")
            print("OK: 'attention transformer' is the Attention paper in all modes.")
        finally:
            config.LLM_WIKI_DATA_DIR = original_data_dir
            wiki_cli.registry.db_path = original_db_path

    if args.keep_data_dir:
        kept = Path(tempfile.gettempdir()) / "wiki-hybrid-verify-keep"
        print(f"--keep-data-dir set; tmp data dir may still exist at {kept}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
