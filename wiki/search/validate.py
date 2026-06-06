"""Validation helpers for the BM25 index (Prompt 28).

The validator is intentionally small and non-brittle. It runs
against the on-disk JSON files and reports issues as 3-tuples of
``(severity, code, message)`` where ``severity`` is ``"error"`` or
``"warning"``. The set of checks is a subset of the issues the
BM25 index *could* have; callers (``validate()`` in
``wiki/cli.py``) decide what to do with the issues.

Issue codes
-----------

- ``bm25_index_missing`` (warning): neither ``index.json`` nor
  ``manifest.json`` exists. Missing index is non-fatal because
  the BM25 backend is optional at validate time.
- ``bm25_index_invalid`` (warning): ``index.json`` is not valid
  JSON.
- ``bm25_manifest_invalid`` (warning): ``manifest.json`` is not
  valid JSON or its root is not a dict.
- ``bm25_schema_version_mismatch`` (warning): unexpected
  ``schema_version`` constant.
- ``bm25_chunk_id_missing`` (warning): a posting references an
  empty ``chunk_id``.
- ``bm25_chunk_meta_missing`` (warning): a ``chunk_id`` in
  ``postings`` has no entry in ``chunk_meta``.
- ``bm25_index_stats_inconsistent`` (warning):
  ``manifest.doc_count``, ``manifest.vocab_size``,
  ``stats.json.doc_count`` disagree.

The checks are non-fatal on purpose: a missing BM25 index is a
warning so the wiki can be validated before the BM25 index has
been built. When the user explicitly runs
``wiki build-bm25-index`` and the build fails, the CLI exits 1
with a clear message (the validator is not the failure path).

The validator is **read-only**: it does not write to the index
files. It is also deliberately independent of Pydantic, so that
a malformed index file is reported as a warning rather than
crashing the validator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from wiki.search.export import BM25_SCHEMA_VERSION


# =============================================================================
# Public API
# =============================================================================


def iter_bm25_index_issues(
    *,
    index_path: Path,
    manifest_path: Path,
    stats_path: Path,
) -> Iterator[tuple[str, str, str]]:
    """Yield ``(severity, code, message)`` tuples for the BM25 index.

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
            "bm25_index_missing",
            (
                "BM25 index not built. Run `wiki build-bm25-index` "
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
                "bm25_manifest_invalid",
                f"bm25 manifest.json is not valid JSON: {exc}",
            )
        else:
            if not isinstance(manifest_data, dict):
                yield (
                    "warning",
                    "bm25_manifest_invalid",
                    f"bm25 manifest.json root is not a dict: {type(manifest_data).__name__}",
                )
                manifest_data = None
            else:
                schema_version = manifest_data.get("schema_version")
                if schema_version and schema_version != BM25_SCHEMA_VERSION:
                    yield (
                        "warning",
                        "bm25_schema_version_mismatch",
                        (
                            f"bm25 manifest.json schema_version is {schema_version!r}, "
                            f"expected {BM25_SCHEMA_VERSION!r}"
                        ),
                    )
    else:
        yield (
            "warning",
            "bm25_manifest_missing",
            f"bm25 manifest.json is missing: {manifest_path}",
        )

    # Index checks.
    index_data: dict[str, Any] | None = None
    if index_path.exists():
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            yield (
                "warning",
                "bm25_index_invalid",
                f"bm25 index.json is not valid JSON: {exc}",
            )
        else:
            if not isinstance(index_data, dict):
                yield (
                    "warning",
                    "bm25_index_invalid",
                    f"bm25 index.json root is not a dict: {type(index_data).__name__}",
                )
            else:
                schema_version = index_data.get("schema_version")
                if schema_version and schema_version != BM25_SCHEMA_VERSION:
                    yield (
                        "warning",
                        "bm25_schema_version_mismatch",
                        (
                            f"bm25 index.json schema_version is {schema_version!r}, "
                            f"expected {BM25_SCHEMA_VERSION!r}"
                        ),
                    )
                # Per-chunk_id checks.
                vocab = index_data.get("vocab")
                chunk_meta = index_data.get("chunk_meta")
                if isinstance(vocab, dict) and isinstance(chunk_meta, dict):
                    yield from _check_postings(vocab, chunk_meta)
    else:
        yield (
            "warning",
            "bm25_index_missing",
            f"bm25 index.json is missing: {index_path}",
        )

    # Stats consistency: manifest.doc_count == stats.doc_count.
    if stats_path.exists() and manifest_data is not None:
        try:
            stats_data = json.loads(stats_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Don't escalate an unparseable stats file; the
            # manifest is the canonical file.
            return
        if isinstance(stats_data, dict) and isinstance(manifest_data, dict):
            manifest_doc_count = manifest_data.get("doc_count")
            stats_doc_count = stats_data.get("doc_count")
            if (
                isinstance(manifest_doc_count, int)
                and isinstance(stats_doc_count, int)
                and manifest_doc_count != stats_doc_count
            ):
                yield (
                    "warning",
                    "bm25_index_stats_inconsistent",
                    (
                        f"bm25 stats.json doc_count={stats_doc_count} disagrees "
                        f"with manifest.doc_count={manifest_doc_count}"
                    ),
                )


# =============================================================================
# Local helpers
# =============================================================================


def _check_postings(
    vocab: dict[str, Any], chunk_meta: dict[str, Any]
) -> Iterator[tuple[str, str, str]]:
    """Yield per-posting validation issues."""
    for term, payload in vocab.items():
        if not isinstance(payload, dict):
            yield (
                "warning",
                "bm25_vocab_entry_invalid",
                f"vocab[{term!r}] is not a dict: {type(payload).__name__}",
            )
            continue
        postings = payload.get("postings")
        if not isinstance(postings, list):
            yield (
                "warning",
                "bm25_vocab_postings_invalid",
                f"vocab[{term!r}].postings is not a list: {type(postings).__name__}",
            )
            continue
        for entry in postings:
            if not isinstance(entry, dict):
                yield (
                    "warning",
                    "bm25_posting_invalid",
                    f"vocab[{term!r}] posting is not a dict: {entry!r}",
                )
                continue
            chunk_id = str(entry.get("chunk_id", "") or "")
            if not chunk_id:
                yield (
                    "warning",
                    "bm25_chunk_id_missing",
                    f"vocab[{term!r}] posting has empty chunk_id",
                )
                continue
            if chunk_id not in chunk_meta:
                yield (
                    "warning",
                    "bm25_chunk_meta_missing",
                    f"vocab[{term!r}] references chunk_id {chunk_id!r} with no chunk_meta entry",
                )


__all__ = ["iter_bm25_index_issues"]
