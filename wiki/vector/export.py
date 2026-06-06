"""Deterministic on-disk export of the vector index (Prompt 29).

Writes three files into the data directory:

- ``processed/vector/index.json`` - sparse vectors, chunk meta,
  vectorizer parameters. No timestamps.
- ``processed/vector/manifest.json`` - deterministic summary (no
  timestamps). Used by ``validate`` and by the public copy.
- ``processed/vector/stats.json`` - aggregate counters and build
  metadata (timestamps, duration). The only file allowed to drift
  between runs.

The function also writes a small public copy under
``site_generated/docs/public/search/`` so the VitePress site can
expose the manifest at ``/public/search/vector_manifest.json``.

JSON output policy
------------------

The output is byte-stable across runs with the same input:

- ``index.json`` and ``manifest.json`` have no timestamps.
- Top-level keys are in stable insertion order (declared in the
  helper functions).
- ``idf`` keys are sorted alphabetically.
- ``vectors`` keys are sorted alphabetically by ``chunk_id``.
- The ``entries`` sub-dict of each vector is sorted by integer
  dimension, but the integer is written as a string key (JSON
  limitation); the reader converts back to int.
- ``json.dump(..., sort_keys=False)`` is intentional; we rely on
  Python 3.7+ dict insertion order.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from wiki.config import config
from wiki.storage import Storage
from wiki.vector.index import VectorIndexResult


# =============================================================================
# Constants
# =============================================================================


#: Schema version for the vector index files.
VECTOR_SCHEMA_VERSION: str = "vector_index_v1"


# =============================================================================
# Output paths
# =============================================================================


def vector_output_paths(*, data_dir: Path | None = None) -> dict[str, Path]:
    """Return the standard output paths for the vector index files.

    The data-dir layout is fixed by ``prompt29.md``:

    - ``data/processed/vector/index.json``
    - ``data/processed/vector/manifest.json``
    - ``data/processed/vector/stats.json``

    The site copy is:

    - ``data/site_generated/docs/public/search/vector_index.json``
    - ``data/site_generated/docs/public/search/vector_manifest.json``
    """
    base = (data_dir or config.LLM_WIKI_DATA_DIR) / "processed" / "vector"
    return {
        "index_json": base / "index.json",
        "manifest": base / "manifest.json",
        "stats": base / "stats.json",
        "directory": base,
    }


def public_vector_paths(*, data_dir: Path | None = None) -> dict[str, Path]:
    """Return the public site copy paths for the vector index."""
    base = (
        (data_dir or config.LLM_WIKI_DATA_DIR)
        / "site_generated"
        / "docs"
        / "public"
        / "search"
    )
    return {
        "vector_index_json": base / "vector_index.json",
        "vector_manifest": base / "vector_manifest.json",
        "directory": base,
    }


# =============================================================================
# Main writer
# =============================================================================


def write_vector_index(
    result: VectorIndexResult,
    *,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Write the deterministic vector index files.

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
        paths = vector_output_paths()
    paths["directory"].mkdir(parents=True, exist_ok=True)

    # Project the in-memory result to a plain dict. The on-disk
    # schema matches the plan in PROMPT29_PLAN.md.
    index_payload = _index_to_dict(result)
    Storage.write_json(index_payload, paths["index_json"])

    manifest_payload = _manifest_to_dict(result)
    Storage.write_json(manifest_payload, paths["manifest"])

    stats_payload = _stats_to_dict(result, paths)
    Storage.write_json(stats_payload, paths["stats"])

    return paths


def _index_to_dict(result: VectorIndexResult) -> dict[str, Any]:
    """Project :class:`VectorIndexResult` to the on-disk dict shape.

    Key order is the contract: callers (``validate``, the public
    copy, the search runtime) expect to read the same top-level
    keys in the same order.
    """
    idf_sorted: dict[str, float] = {}
    if result.state is not None:
        for term in sorted(result.state.idf.keys()):
            idf_sorted[term] = float(result.state.idf[term])

    vectors: dict[str, Any] = {}
    for cid in sorted(result.vectors.keys()):
        entry = result.vectors[cid]
        entries_sorted: dict[str, float] = {}
        for dim in sorted((entry.get("entries") or {}).keys()):
            entries_sorted[str(int(dim))] = float((entry["entries"])[dim])
        vectors[cid] = {
            "entries": entries_sorted,
            "norm": float(entry.get("norm", 0.0)),
            "resource_id": str(entry.get("resource_id", "")),
            "source_type": str(entry.get("source_type", "")),
            "title": str(entry.get("title", "")),
            "citation_label": str(entry.get("citation_label", "")),
            "resource_route": str(entry.get("resource_route", "")),
            "source_ref": dict(entry.get("source_ref") or {}),
            "text_preview": str(entry.get("text_preview", "")),
        }

    return {
        "schema_version": result.schema_version,
        "vectorizer": result.config.to_dict(),
        "chunk_count": int(result.chunk_count),
        "resource_count": int(result.resource_count),
        "vocab_size": int(result.vocab_size),
        "total_nnz": int(result.total_nnz),
        "idf": idf_sorted,
        "vectors": vectors,
    }


def _manifest_to_dict(result: VectorIndexResult) -> dict[str, Any]:
    """Build the deterministic ``manifest.json`` payload.

    The manifest has no timestamps; it is the canonical summary.
    """
    by_source_type: dict[str, int] = {}
    for cid, entry in result.vectors.items():
        st = str(entry.get("source_type", ""))
        if not st:
            continue
        by_source_type[st] = by_source_type.get(st, 0) + 1
    sorted_by_source_type = dict(sorted(by_source_type.items()))

    return {
        "schema_version": result.schema_version,
        "chunk_count": int(result.chunk_count),
        "resource_count": int(result.resource_count),
        "dimension": int(result.config.dimension),
        "vocab_size": int(result.vocab_size),
        "total_nnz": int(result.total_nnz),
        "vectorizer_name": str(result.config.name),
        "hash_family": str(result.config.hash_family),
        "norm": str(result.config.norm),
        "by_source_type": sorted_by_source_type,
    }


def _stats_to_dict(result: VectorIndexResult, paths: dict[str, Path]) -> dict[str, Any]:
    """Build the ``stats.json`` payload (the only file allowed timestamps)."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": result.schema_version,
        "build_started_at": now,
        "build_finished_at": now,
        "duration_seconds": 0.0,
        "chunk_count": int(result.chunk_count),
        "resource_count": int(result.resource_count),
        "dimension": int(result.config.dimension),
        "vocab_size": int(result.vocab_size),
        "total_nnz": int(result.total_nnz),
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
    """Write a small public copy of the vector index into the site dir.

    The public copy is intentionally smaller than the data-dir
    index: it carries the manifest plus a vocab summary
    (``{term: idf}``) but **no** full sparse vectors and **no**
    chunk meta. This keeps the public payload small and avoids
    exposing internal chunk metadata in the browser.

    The full index lives in the data dir; the CLI search uses
    the data-dir index for full retrieval. The public copy is
    for documentation and future client-side hints.
    """
    data_paths = vector_output_paths(data_dir=data_dir)
    if output_dir is not None:
        public_paths = {
            "vector_index_json": output_dir / "vector_index.json",
            "vector_manifest": output_dir / "vector_manifest.json",
            "directory": output_dir,
        }
    else:
        public_paths = public_vector_paths(data_dir=data_dir)
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

    # The public vector_index.json is a vocab summary (term -> idf),
    # not the full sparse vectors. If the data-dir index.json is
    # missing, emit an empty vocab summary.
    if data_paths["index_json"].exists():
        try:
            index_data = json.loads(
                data_paths["index_json"].read_text(encoding="utf-8")
            )
            idf = {
                str(term): float(weight)
                for term, weight in (index_data.get("idf") or {}).items()
            }
        except json.JSONDecodeError:
            idf = {}
    else:
        idf = {}

    public_index = {
        "schema_version": VECTOR_SCHEMA_VERSION,
        "manifest": manifest_data,
        "vocab_summary": idf,
        "note": (
            "Vocab summary (term -> IDF weight). Full sparse vectors and "
            "chunk meta live in the data dir; the CLI search command uses "
            "the data-dir index for full retrieval."
        ),
    }

    Storage.write_json(public_index, public_paths["vector_index_json"])
    Storage.write_json(manifest_data, public_paths["vector_manifest"])
    return public_paths


def _empty_manifest() -> dict[str, Any]:
    return {
        "schema_version": VECTOR_SCHEMA_VERSION,
        "chunk_count": 0,
        "resource_count": 0,
        "dimension": 0,
        "vocab_size": 0,
        "total_nnz": 0,
        "vectorizer_name": "hashing_tfidf",
        "hash_family": "blake2b_signed",
        "norm": "l2",
        "by_source_type": {},
    }


__all__ = [
    "VECTOR_SCHEMA_VERSION",
    "public_vector_paths",
    "vector_output_paths",
    "write_public_copy",
    "write_vector_index",
]
