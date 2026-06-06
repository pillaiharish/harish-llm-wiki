"""Validation helpers for the chunk index (Prompt 27).

The validator is intentionally small and non-brittle. It runs against
the on-disk JSON / JSONL files and reports issues as 3-tuples of
``(severity, code, message)`` where ``severity`` is ``"error"`` or
``"warning"``. The set of checks is a subset of the issues the chunk
index *could* have; callers (``validate()`` in ``wiki/cli.py``) decide
what to do with the issues.

Issue codes
-----------

- ``chunks_json_invalid`` (warning): ``chunks.json`` is not valid JSON
- ``chunks_jsonl_invalid`` (warning): a line in ``chunks.jsonl`` is
  not valid JSON
- ``chunks_count_mismatch`` (warning): ``chunks.json`` and
  ``chunks.jsonl`` report different chunk counts
- ``duplicate_chunk_id`` (error): the same ``chunk_id`` appears more
  than once in the chunk list
- ``empty_chunk_text`` (warning): a chunk has empty text
- ``missing_citation_label`` (warning): a chunk has no
  ``citation_label``
- ``missing_resource_id`` (warning): a chunk has no ``resource_id``

The checks are the same as those enumerated in
``prompt27.md`` §"Validation requirement" and the
:class:`TestChunkIndexBuilder` test class.

The validator is **read-only**: it does not write to the index
files. It is also deliberately independent of Pydantic, so that a
malformed chunk file is reported as a warning rather than crashing
the validator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from wiki.chunks.schema import CHUNK_INDEX_SCHEMA_VERSION


# =============================================================================
# Public API
# =============================================================================


def iter_chunk_index_issues(
    *,
    chunks_jsonl_path: Path,
    chunks_json_path: Path,
    manifest_path: Path,
) -> Iterator[tuple[str, str, str]]:
    """Yield ``(severity, code, message)`` tuples for the chunk index.

    The function never raises. Malformed files are reported as
    warnings so that a partially-built index does not crash
    ``validate()`` or ``smoke-site``.

    Parameters
    ----------
    chunks_jsonl_path:
        Path to ``chunks.jsonl``.
    chunks_json_path:
        Path to ``chunks.json``.
    manifest_path:
        Path to ``manifest.json``.
    """
    jsonl_chunks, jsonl_error = _read_jsonl_chunks(chunks_jsonl_path)
    if jsonl_error:
        yield (
            "warning",
            "chunks_jsonl_invalid",
            f"chunks.jsonl could not be parsed at {chunks_jsonl_path}: {jsonl_error}",
        )

    json_chunks, json_error = _read_json_chunks(chunks_json_path)
    if json_error:
        yield (
            "warning",
            "chunks_json_invalid",
            f"chunks.json could not be parsed at {chunks_json_path}: {json_error}",
        )

    if jsonl_chunks is not None and json_chunks is not None:
        if len(jsonl_chunks) != len(json_chunks):
            yield (
                "warning",
                "chunks_count_mismatch",
                (
                    f"chunks.json has {len(json_chunks)} entries but "
                    f"chunks.jsonl has {len(jsonl_chunks)} entries"
                ),
            )

    # Run per-chunk checks on the most-trusted payload (the JSON list,
    # if it parsed; otherwise the JSONL).
    chunks_for_checks: list[dict[str, Any]] | None = json_chunks
    if chunks_for_checks is None:
        chunks_for_checks = jsonl_chunks
    if chunks_for_checks is None:
        return

    seen_chunk_ids: set[str] = set()
    for chunk in chunks_for_checks:
        if not isinstance(chunk, dict):
            yield (
                "warning",
                "chunks_invalid_entry",
                f"Chunk entry is not a dict: {chunk!r}",
            )
            continue
        chunk_id = str(chunk.get("chunk_id", "") or "")
        resource_id = str(chunk.get("resource_id", "") or "")
        text = str(chunk.get("text", "") or "")
        citation_label = str(chunk.get("citation_label", "") or "")

        if chunk_id:
            if chunk_id in seen_chunk_ids:
                yield (
                    "error",
                    "duplicate_chunk_id",
                    f"Duplicate chunk_id: {chunk_id!r}",
                )
            else:
                seen_chunk_ids.add(chunk_id)

        if not text:
            yield (
                "warning",
                "empty_chunk_text",
                f"Chunk {chunk_id!r} has empty text",
            )
        if not citation_label:
            yield (
                "warning",
                "missing_citation_label",
                f"Chunk {chunk_id!r} has no citation_label",
            )
        if not resource_id:
            yield (
                "warning",
                "missing_resource_id",
                f"Chunk {chunk_id!r} has no resource_id",
            )

    # Optional manifest shape check. A wrong schema_version is a warning.
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            yield (
                "warning",
                "manifest_invalid",
                f"manifest.json is not valid JSON: {exc}",
            )
        else:
            if isinstance(manifest, dict):
                schema_version = manifest.get("schema_version")
                if schema_version and schema_version != CHUNK_INDEX_SCHEMA_VERSION:
                    yield (
                        "warning",
                        "schema_version_mismatch",
                        (
                            f"manifest.json schema_version is {schema_version!r}, "
                            f"expected {CHUNK_INDEX_SCHEMA_VERSION!r}"
                        ),
                    )
                if "chunk_count" not in manifest:
                    yield (
                        "warning",
                        "manifest_missing_chunk_count",
                        "manifest.json is missing 'chunk_count' key",
                    )
                if "resource_count" not in manifest:
                    yield (
                        "warning",
                        "manifest_missing_resource_count",
                        "manifest.json is missing 'resource_count' key",
                    )
            else:
                yield (
                    "warning",
                    "manifest_not_dict",
                    f"manifest.json root is not a dict: {type(manifest).__name__}",
                )


# =============================================================================
# Local helpers
# =============================================================================


def _read_jsonl_chunks(
    path: Path,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Read a JSONL file. Returns ``(None, error_message)`` on failure."""
    if not path.exists():
        return None, f"file not found: {path}"
    try:
        items: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    return None, f"invalid JSONL line: {exc}"
                if isinstance(payload, dict):
                    items.append(payload)
        return items, None
    except OSError as exc:
        return None, str(exc)


def _read_json_chunks(
    path: Path,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Read a JSON file. Returns ``(None, error_message)`` on failure."""
    if not path.exists():
        return None, f"file not found: {path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(payload, list):
        return None, f"root is not a list: {type(payload).__name__}"
    return [item for item in payload if isinstance(item, dict)], None


__all__ = ["iter_chunk_index_issues"]
