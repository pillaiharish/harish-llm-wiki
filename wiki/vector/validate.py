"""Validation helpers for the vector index (Prompt 29).

The validator is intentionally small and non-brittle. It runs
against the on-disk JSON files and reports issues as 3-tuples of
``(severity, code, message)`` where ``severity`` is ``"error"`` or
``"warning"``.

Issue codes
-----------

- ``vector_index_missing`` (warning): neither ``index.json`` nor
  ``manifest.json`` exists. Missing index is non-fatal because the
  vector backend is optional at validate time.
- ``vector_index_invalid`` (warning): ``index.json`` is not valid
  JSON.
- ``vector_manifest_invalid`` (warning): ``manifest.json`` is not
  valid JSON or its root is not a dict.
- ``vector_schema_version_mismatch`` (warning): unexpected
  ``schema_version`` constant.
- ``vector_dimension_invalid`` (warning): ``vectorizer.dimension``
  is not a positive integer.
- ``vector_chunk_id_missing`` (warning): a vector entry has an
  empty ``chunk_id``.
- ``vector_idf_invalid`` (warning): the ``idf`` table is not a
  dict, or a value is negative.
- ``vector_stats_inconsistent`` (warning):
  ``manifest.chunk_count`` and ``stats.json.chunk_count`` disagree.

The checks are non-fatal on purpose: a missing vector index is a
warning so the wiki can be validated before the vector index has
been built. When the user explicitly runs
``wiki build-vector-index`` and the build fails, the CLI exits 1
with a clear message (the validator is not the failure path).

The validator is **read-only**: it does not write to the index
files. It is also deliberately independent of Pydantic, so that a
malformed index file is reported as a warning rather than
crashing the validator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from wiki.vector.export import VECTOR_SCHEMA_VERSION


# =============================================================================
# Public API
# =============================================================================


def iter_vector_index_issues(
    *,
    index_path: Path,
    manifest_path: Path,
    stats_path: Path,
) -> Iterator[tuple[str, str, str]]:
    """Yield ``(severity, code, message)`` tuples for the vector index.

    The function never raises. Malformed files are reported as
    warnings so that a partially-built index does not crash
    ``validate()`` or ``smoke-site``.

    Parameters
    ----------
    index_path:
        Path to ``index.json``.
    manifest_path:
        Path to ``manifest.json``.
    stats_path:
        Path to ``stats.json``.
    """
    if not index_path.exists() and not manifest_path.exists():
        yield (
            "warning",
            "vector_index_missing",
            (
                "Vector index not built. Run `wiki build-vector-index` "
                "(or `wiki build-site --refresh`) to create it."
            ),
        )
        return

    # Manifest checks (the manifest is the smaller, more reliable
    # summary).
    manifest_data: dict[str, Any] | None = None
    if manifest_path.exists():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            yield (
                "warning",
                "vector_manifest_invalid",
                f"vector manifest.json is not valid JSON: {exc}",
            )
        else:
            if not isinstance(manifest_data, dict):
                yield (
                    "warning",
                    "vector_manifest_invalid",
                    f"vector manifest.json root is not a dict: {type(manifest_data).__name__}",
                )
                manifest_data = None
            else:
                schema_version = manifest_data.get("schema_version")
                if schema_version and schema_version != VECTOR_SCHEMA_VERSION:
                    yield (
                        "warning",
                        "vector_schema_version_mismatch",
                        (
                            f"vector manifest.json schema_version is {schema_version!r}, "
                            f"expected {VECTOR_SCHEMA_VERSION!r}"
                        ),
                    )
    else:
        yield (
            "warning",
            "vector_manifest_missing",
            f"vector manifest.json is missing: {manifest_path}",
        )

    # Index checks.
    index_data: dict[str, Any] | None = None
    if index_path.exists():
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            yield (
                "warning",
                "vector_index_invalid",
                f"vector index.json is not valid JSON: {exc}",
            )
        else:
            if not isinstance(index_data, dict):
                yield (
                    "warning",
                    "vector_index_invalid",
                    f"vector index.json root is not a dict: {type(index_data).__name__}",
                )
            else:
                schema_version = index_data.get("schema_version")
                if schema_version and schema_version != VECTOR_SCHEMA_VERSION:
                    yield (
                        "warning",
                        "vector_schema_version_mismatch",
                        (
                            f"vector index.json schema_version is {schema_version!r}, "
                            f"expected {VECTOR_SCHEMA_VERSION!r}"
                        ),
                    )
                # Vectorizer config checks.
                vectorizer = index_data.get("vectorizer")
                if isinstance(vectorizer, dict):
                    dimension = vectorizer.get("dimension")
                    if not isinstance(dimension, int) or dimension <= 0:
                        yield (
                            "warning",
                            "vector_dimension_invalid",
                            (
                                f"vector index.json vectorizer.dimension is "
                                f"not a positive integer: {dimension!r}"
                            ),
                        )
                # IDF checks.
                idf = index_data.get("idf")
                if idf is not None:
                    if not isinstance(idf, dict):
                        yield (
                            "warning",
                            "vector_idf_invalid",
                            f"vector index.json idf is not a dict: {type(idf).__name__}",
                        )
                    else:
                        for term, weight in idf.items():
                            if not isinstance(weight, (int, float)):
                                yield (
                                    "warning",
                                    "vector_idf_invalid",
                                    (
                                        f"vector index.json idf[{term!r}] is not a number: "
                                        f"{type(weight).__name__}"
                                    ),
                                )
                                continue
                            if float(weight) < 0.0:
                                yield (
                                    "warning",
                                    "vector_idf_invalid",
                                    (
                                        f"vector index.json idf[{term!r}] is negative: "
                                        f"{weight}"
                                    ),
                                )
                # Per-chunk_id checks.
                vectors = index_data.get("vectors")
                if isinstance(vectors, dict):
                    yield from _check_vectors(vectors)
    else:
        yield (
            "warning",
            "vector_index_missing",
            f"vector index.json is missing: {index_path}",
        )

    # Stats consistency: manifest.chunk_count == stats.chunk_count.
    if stats_path.exists() and manifest_data is not None:
        try:
            stats_data = json.loads(stats_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Don't escalate an unparseable stats file; the
            # manifest is the canonical file.
            return
        if isinstance(stats_data, dict) and isinstance(manifest_data, dict):
            manifest_doc_count = manifest_data.get("chunk_count")
            stats_doc_count = stats_data.get("chunk_count")
            if (
                isinstance(manifest_doc_count, int)
                and isinstance(stats_doc_count, int)
                and manifest_doc_count != stats_doc_count
            ):
                yield (
                    "warning",
                    "vector_stats_inconsistent",
                    (
                        f"vector stats.json chunk_count={stats_doc_count} disagrees "
                        f"with manifest.chunk_count={manifest_doc_count}"
                    ),
                )


# =============================================================================
# Local helpers
# =============================================================================


def _check_vectors(vectors: dict[str, Any]) -> Iterator[tuple[str, str, str]]:
    """Yield per-chunk vector validation issues."""
    for cid, entry in vectors.items():
        if not isinstance(entry, dict):
            yield (
                "warning",
                "vector_entry_invalid",
                f"vectors[{cid!r}] is not a dict: {type(entry).__name__}",
            )
            continue
        if not str(cid):
            yield (
                "warning",
                "vector_chunk_id_missing",
                "vector index has an empty chunk_id",
            )
        entries = entry.get("entries")
        if entries is not None and not isinstance(entries, dict):
            yield (
                "warning",
                "vector_entries_invalid",
                f"vectors[{cid!r}].entries is not a dict: {type(entries).__name__}",
            )


__all__ = ["iter_vector_index_issues"]
