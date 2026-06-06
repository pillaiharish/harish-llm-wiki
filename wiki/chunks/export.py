"""Deterministic JSON/JSONL export of the chunk index.

Writes four files into the data directory:

- ``processed/chunk_index/chunks.jsonl`` – one Chunk dict per line
- ``processed/chunk_index/chunks.json`` – the same data as a list
- ``processed/chunk_index/manifest.json`` – per-resource summary
- ``processed/chunk_index/stats.json`` – aggregate counters and build
  metadata (timestamps, duration). The only file allowed to drift
  between runs.

The function also writes a small public copy under
``site_generated/docs/public/chunks/`` so the VitePress site can
expose the index via ``/public/chunks/chunks.json`` and
``/public/chunks/manifest.json``.

JSON output policy
------------------

The output is byte-stable across runs with the same input:

- Field order is the schema order in :class:`ChunkRecord`.
- ``chunks.jsonl`` and ``chunks.json`` are derived from the same
  in-memory list, so the two files agree on chunk count.
- ``manifest.json`` has no timestamps; it is the deterministic file.
- ``stats.json`` carries the only timestamps allowed in the index
  family (``build_started_at`` / ``build_finished_at``).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wiki.config import config
from wiki.chunks.schema import CHUNK_INDEX_SCHEMA_VERSION, ChunkIndexResult
from wiki.storage import Storage


# =============================================================================
# Output paths
# =============================================================================


def chunk_index_output_paths(
    *, data_dir: Path | None = None
) -> dict[str, Path]:
    """Return the standard output paths for the chunk index files.

    The data-dir layout is fixed by ``prompt27.md``:

    - ``data/processed/chunk_index/chunks.jsonl``
    - ``data/processed/chunk_index/chunks.json``
    - ``data/processed/chunk_index/manifest.json``
    - ``data/processed/chunk_index/stats.json``

    The site copy is:

    - ``data/site_generated/docs/public/chunks/chunks.json``
    - ``data/site_generated/docs/public/chunks/manifest.json``
    """
    base = (data_dir or config.LLM_WIKI_DATA_DIR) / "processed" / "chunk_index"
    return {
        "chunks_jsonl": base / "chunks.jsonl",
        "chunks_json": base / "chunks.json",
        "manifest": base / "manifest.json",
        "stats": base / "stats.json",
        "directory": base,
    }


def public_chunk_paths(*, data_dir: Path | None = None) -> dict[str, Path]:
    """Return the public site copy paths for the chunk index."""
    base = (
        (data_dir or config.LLM_WIKI_DATA_DIR)
        / "site_generated"
        / "docs"
        / "public"
        / "chunks"
    )
    return {
        "chunks_json": base / "chunks.json",
        "manifest": base / "manifest.json",
        "directory": base,
    }


# =============================================================================
# Main writer
# =============================================================================


def write_chunk_index(
    result: ChunkIndexResult,
    *,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Write the deterministic chunk index files.

    Returns a dict of output paths. The output is byte-stable
    across runs with the same input (only ``stats.json`` carries
    timestamps).
    """
    if output_dir is not None:
        paths = {
            "chunks_jsonl": output_dir / "chunks.jsonl",
            "chunks_json": output_dir / "chunks.json",
            "manifest": output_dir / "manifest.json",
            "stats": output_dir / "stats.json",
            "directory": output_dir,
        }
    else:
        paths = chunk_index_output_paths()
    paths["directory"].mkdir(parents=True, exist_ok=True)

    # Project ChunkRecord to a plain dict in stable field order.
    chunk_dicts: list[dict[str, Any]] = [_chunk_record_to_dict(c) for c in result.chunks]

    # chunks.jsonl: one record per line.
    with paths["chunks_jsonl"].open("w", encoding="utf-8") as handle:
        for entry in chunk_dicts:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # chunks.json: the same data as a list.
    Storage.write_json(chunk_dicts, paths["chunks_json"])

    # manifest.json: deterministic summary (no timestamps).
    manifest = dict(result.manifest)
    manifest.setdefault("schema_version", CHUNK_INDEX_SCHEMA_VERSION)
    Storage.write_json(manifest, paths["manifest"])

    # stats.json: aggregate counters and build metadata (only place
    # where timestamps live).
    stats = _build_stats(result, paths)
    Storage.write_json(stats, paths["stats"])

    return paths


def _chunk_record_to_dict(record) -> dict[str, Any]:
    """Project a :class:`ChunkRecord` to a dict in stable field order.

    Pydantic v2 ``model_dump`` preserves the field order declared on
    the model, so this is a thin wrapper for clarity and to keep
    JSON serialization deterministic.
    """
    return record.model_dump()


def _build_stats(result: ChunkIndexResult, paths: dict[str, Path]) -> dict[str, Any]:
    """Build the ``stats.json`` payload (the only file allowed timestamps)."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": CHUNK_INDEX_SCHEMA_VERSION,
        "build_started_at": now,
        "build_finished_at": now,
        "duration_seconds": 0.0,
        "chunk_count": len(result.chunks),
        "resource_count": len(result.chunk_count_by_resource),
        "warning_count": len(result.warnings),
        "outputs": {
            "chunks_jsonl": str(paths["chunks_jsonl"]),
            "chunks_json": str(paths["chunks_json"]),
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
    """Write a public copy of the chunk index into the site dir.

    The function reads the canonical files from the data dir and
    copies them into ``site_generated/docs/public/chunks/`` so the
    VitePress site can serve them under ``/public/chunks/``. Both
    the data-dir and public-copy JSON are deterministic; this
    function is a plain file copy.

    If the data-dir files do not exist, the function writes a
    valid empty pair of files (``[]`` and an empty manifest) so the
    site can still load the endpoints without errors.
    """
    data_paths = chunk_index_output_paths(data_dir=data_dir)
    public_paths = public_chunk_paths(data_dir=data_dir if output_dir is None else None)
    if output_dir is not None:
        public_paths = {
            "chunks_json": output_dir / "chunks.json",
            "manifest": output_dir / "manifest.json",
            "directory": output_dir,
        }
    public_paths["directory"].mkdir(parents=True, exist_ok=True)

    if data_paths["chunks_json"].exists():
        chunks_data = json.loads(data_paths["chunks_json"].read_text(encoding="utf-8"))
    else:
        chunks_data = []
    if data_paths["manifest"].exists():
        manifest_data = json.loads(data_paths["manifest"].read_text(encoding="utf-8"))
    else:
        manifest_data = _empty_manifest()

    Storage.write_json(chunks_data, public_paths["chunks_json"])
    Storage.write_json(manifest_data, public_paths["manifest"])
    return public_paths


def _empty_manifest() -> dict[str, Any]:
    return {
        "schema_version": CHUNK_INDEX_SCHEMA_VERSION,
        "chunk_count": 0,
        "resource_count": 0,
        "by_source_type": {},
        "by_resource": [],
        "warnings": [],
    }


__all__ = [
    "chunk_index_output_paths",
    "public_chunk_paths",
    "write_chunk_index",
    "write_public_copy",
]
