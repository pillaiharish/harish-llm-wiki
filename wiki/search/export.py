"""Deterministic on-disk export of the BM25 index (Prompt 28).

Writes three files into the data directory:

- ``processed/bm25/index.json`` – the inverted index (terms +
  postings + chunk_meta + BM25 parameters). No timestamps.
- ``processed/bm25/manifest.json`` – deterministic summary
  (no timestamps). Used by validate and by the public copy.
- ``processed/bm25/stats.json`` – aggregate counters and build
  metadata (timestamps, duration). The only file allowed to
  drift between runs.

The function also writes a small public copy under
``site_generated/docs/public/search/`` so the VitePress site can
expose the manifest at ``/public/search/bm25_manifest.json``.

JSON output policy
------------------

The output is byte-stable across runs with the same input:

- ``index.json`` keys are sorted (the builder already sorts
  ``vocab`` and ``chunk_meta`` keys).
- ``manifest.json`` is a flat dict with stable key order.
- ``stats.json`` carries the only timestamps allowed in the
  BM25 index family (``build_started_at`` /
  ``build_finished_at``).
- ``json.dump(..., sort_keys=False)`` is intentional; we rely
  on Python 3.7+ dict insertion order. Insertion order is
  declared in the helper functions below.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from wiki.config import config
from wiki.search.index import BM25IndexResult
from wiki.storage import Storage


# =============================================================================
# Constants
# =============================================================================


#: Schema version for the BM25 index files.
BM25_SCHEMA_VERSION: str = "bm25_index_v1"


# =============================================================================
# Output paths
# =============================================================================


def bm25_output_paths(*, data_dir: Path | None = None) -> dict[str, Path]:
    """Return the standard output paths for the BM25 index files.

    Layout:

    - ``data/processed/bm25/index.json``
    - ``data/processed/bm25/manifest.json``
    - ``data/processed/bm25/stats.json``

    The site copy is:

    - ``data/site_generated/docs/public/search/bm25_index.json``
    - ``data/site_generated/docs/public/search/bm25_manifest.json``
    """
    base = (data_dir or config.LLM_WIKI_DATA_DIR) / "processed" / "bm25"
    return {
        "index_json": base / "index.json",
        "manifest": base / "manifest.json",
        "stats": base / "stats.json",
        "directory": base,
    }


def public_bm25_paths(*, data_dir: Path | None = None) -> dict[str, Path]:
    """Return the public site copy paths for the BM25 index."""
    base = (
        (data_dir or config.LLM_WIKI_DATA_DIR)
        / "site_generated"
        / "docs"
        / "public"
        / "search"
    )
    return {
        "bm25_index_json": base / "bm25_index.json",
        "bm25_manifest": base / "bm25_manifest.json",
        "directory": base,
    }


# =============================================================================
# Main writer
# =============================================================================


def write_bm25_index(
    result: BM25IndexResult,
    *,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Write the deterministic BM25 index files.

    Returns a dict of output paths. The output is byte-stable
    across runs with the same input (only ``stats.json`` carries
    timestamps).
    """
    if output_dir is not None:
        paths = {
            "index_json": output_dir / "index.json",
            "manifest": output_dir / "manifest.json",
            "stats": output_dir / "stats.json",
            "directory": output_dir,
        }
    else:
        paths = bm25_output_paths()
    paths["directory"].mkdir(parents=True, exist_ok=True)

    # Project the in-memory result to a plain dict. The on-disk
    # schema matches the plan in PROMPT28_PLAN.md.
    index_payload = _index_to_dict(result)
    Storage.write_json(index_payload, paths["index_json"])

    manifest_payload = _manifest_to_dict(result)
    Storage.write_json(manifest_payload, paths["manifest"])

    stats_payload = _stats_to_dict(result, paths)
    Storage.write_json(stats_payload, paths["stats"])

    return paths


def _index_to_dict(result: BM25IndexResult) -> dict[str, Any]:
    """Project :class:`BM25IndexResult` to the on-disk dict shape.

    Key order is the contract: callers (``validate``, the public
    copy, the search runtime) expect to read the same top-level
    keys in the same order.
    """
    return {
        "schema_version": result.schema_version,
        "k1": result.k1,
        "b": result.b,
        "field_weights": dict(result.field_weights),
        "avg_doc_length": result.avg_doc_length,
        "doc_count": result.doc_count,
        "vocab": {
            term: {
                "df": int(payload.get("df", 0)),
                "postings": [
                    {"chunk_id": str(p["chunk_id"]), "tf": int(p["tf"])}
                    for p in payload.get("postings", [])
                ],
            }
            for term, payload in result.vocab.items()
        },
        "chunk_meta": {
            cid: _project_chunk_meta(meta) for cid, meta in result.chunk_meta.items()
        },
    }


def _project_chunk_meta(meta: dict) -> dict[str, Any]:
    """Project a single chunk_meta entry to the on-disk shape."""
    return {
        "resource_id": str(meta.get("resource_id", "")),
        "source_type": str(meta.get("source_type", "")),
        "title": str(meta.get("title", "")),
        "citation_label": str(meta.get("citation_label", "")),
        "resource_route": str(meta.get("resource_route", "")),
        "source_ref": dict(meta.get("source_ref") or {}),
        "doc_length": int(meta.get("doc_length", 0)),
        "word_count": int(meta.get("word_count", 0)),
    }


def _manifest_to_dict(result: BM25IndexResult) -> dict[str, Any]:
    """Build the deterministic ``manifest.json`` payload.

    The manifest has no timestamps; it is the canonical summary.
    """
    by_source_type: dict[str, int] = {}
    for cid, meta in result.chunk_meta.items():
        st = str(meta.get("source_type", ""))
        if not st:
            continue
        by_source_type[st] = by_source_type.get(st, 0) + 1
    sorted_by_source_type = dict(sorted(by_source_type.items()))

    # resource_count is the number of distinct resource_ids.
    resource_ids: set[str] = set()
    for meta in result.chunk_meta.values():
        rid = str(meta.get("resource_id", ""))
        if rid:
            resource_ids.add(rid)

    # total_postings is the sum of df.
    total_postings = sum(
        int(payload.get("df", 0)) for payload in result.vocab.values()
    )

    return {
        "schema_version": result.schema_version,
        "doc_count": result.doc_count,
        "resource_count": len(resource_ids),
        "vocab_size": len(result.vocab),
        "total_postings": total_postings,
        "avg_doc_length": result.avg_doc_length,
        "by_source_type": sorted_by_source_type,
    }


def _stats_to_dict(result: BM25IndexResult, paths: dict[str, Path]) -> dict[str, Any]:
    """Build the ``stats.json`` payload (the only file allowed timestamps)."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": result.schema_version,
        "build_started_at": now,
        "build_finished_at": now,
        "duration_seconds": 0.0,
        "doc_count": result.doc_count,
        "vocab_size": len(result.vocab),
        "total_postings": sum(
            int(payload.get("df", 0)) for payload in result.vocab.values()
        ),
        "outputs": {
            "index_json": str(paths["index_json"]),
            "manifest": str(paths["manifest"]),
            "stats": str(paths["stats"]),
        },
    }


# =============================================================================
# Public copy
# =============================================================================


def write_public_copy(
    *,
    data_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Write a small public copy of the BM25 index into the site dir.

    The public copy is intentionally smaller than the data-dir
    index: it carries the manifest plus a vocab summary
    (``{term: {"df": int}}``) but **no** full postings and **no**
    ``chunk_meta``. This keeps the public payload small and
    avoids exposing internal chunk metadata in the browser.

    The full index lives in the data dir; the CLI search uses
    the data-dir index for full retrieval. The public copy is
    for documentation and future client-side hints.
    """
    data_paths = bm25_output_paths(data_dir=data_dir)
    if output_dir is not None:
        public_paths = {
            "bm25_index_json": output_dir / "bm25_index.json",
            "bm25_manifest": output_dir / "bm25_manifest.json",
            "directory": output_dir,
        }
    else:
        public_paths = public_bm25_paths(data_dir=data_dir)
    public_paths["directory"].mkdir(parents=True, exist_ok=True)

    if data_paths["manifest"].exists():
        try:
            manifest_data = json.loads(
                data_paths["manifest"].read_text(encoding="utf-8")
            )
        except json.JSONDecodeError:
            manifest_data = _empty_manifest()
    else:
        manifest_data = _empty_manifest()

    # The public bm25_index.json is a vocab summary (term -> df),
    # not the full postings. If the data-dir index.json is
    # missing, emit an empty vocab summary.
    if data_paths["index_json"].exists():
        try:
            index_data = json.loads(
                data_paths["index_json"].read_text(encoding="utf-8")
            )
            vocab = {
                term: {"df": int(payload.get("df", 0))}
                for term, payload in (index_data.get("vocab") or {}).items()
            }
        except json.JSONDecodeError:
            vocab = {}
    else:
        vocab = {}

    public_index = {
        "schema_version": BM25_SCHEMA_VERSION,
        "manifest": manifest_data,
        "vocab": vocab,
        "note": (
            "Vocab summary (term -> document frequency). Full postings and "
            "chunk meta live in the data dir; the CLI search command uses "
            "the data-dir index for full retrieval."
        ),
    }

    Storage.write_json(public_index, public_paths["bm25_index_json"])
    Storage.write_json(manifest_data, public_paths["bm25_manifest"])
    return public_paths


def _empty_manifest() -> dict[str, Any]:
    return {
        "schema_version": BM25_SCHEMA_VERSION,
        "doc_count": 0,
        "resource_count": 0,
        "vocab_size": 0,
        "total_postings": 0,
        "avg_doc_length": 0.0,
        "by_source_type": {},
    }


__all__ = [
    "BM25_SCHEMA_VERSION",
    "bm25_output_paths",
    "public_bm25_paths",
    "write_bm25_index",
    "write_public_copy",
]
