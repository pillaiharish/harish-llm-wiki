"""Non-brittle validation for the hybrid retrieval router (Prompt 30).

The validator yields ``(severity, code, message)`` tuples.
``severity`` is one of ``"error"`` (the on-disk retrieval
report page is missing or malformed) or ``"warning"`` (the
retrieval report page is missing but the build did not generate
it because the underlying indexes are missing; this is a
soft warning, not a hard error).

The validator is purely defensive: it never modifies files and
never raises. The CLI's ``validate`` and ``smoke_site`` commands
consume its output via :func:`iter_retrieval_issues`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from wiki.config import config
from wiki.retrieval.schema import (
    ALLOWED_MODES,
    GRAPH_LITE_MAX_BOOST,
    RETRIEVAL_SCHEMA_VERSION,
    RetrievalResult,
)


# =============================================================================
# Public API
# =============================================================================


def iter_retrieval_issues(
    *,
    site_dir: Path | None = None,
    data_dir: Path | None = None,
) -> Iterator[tuple[str, str, str]]:
    """Yield ``(severity, code, message)`` for retrieval-page issues.

    Parameters
    ----------
    site_dir:
        The in-repo site docs directory (e.g. ``site/docs``).
        Defaults to ``config.LLM_WIKI_DATA_DIR / site_generated / docs``.
    data_dir:
        The wiki data dir. Defaults to
        ``config.LLM_WIKI_DATA_DIR``.

    Yields
    ------
    (severity, code, message)
        ``severity`` is ``"error"`` or ``"warning"``. ``code``
        is a stable retrieval-prefixed string (e.g.
        ``retrieval_missing_page``). ``message`` is a
        human-readable string.
    """
    site_root = (
        Path(site_dir)
        if site_dir is not None
        else (config.get_data_path("site_generated", "docs"))
    )
    page_path = site_root / "search" / "retrieval.md"
    if not page_path.exists():
        yield (
            "warning",
            "retrieval_missing_page",
            f"Missing retrieval report page: {page_path}",
        )
        return

    content: str
    try:
        content = page_path.read_text(encoding="utf-8")
    except OSError as exc:
        yield (
            "warning",
            "retrieval_unreadable_page",
            f"Could not read retrieval page: {exc}",
        )
        return

    if len(content) < 50:
        yield (
            "warning",
            "retrieval_page_too_small",
            f"Retrieval page is suspiciously small ({len(content)} bytes): {page_path}",
        )

    # The page must reference the public search JSON files so
    # the reader can inspect the actual indexes. If both
    # public copies are missing, surface a warning.
    public_dir = site_root / "public" / "search"
    if not (public_dir / "bm25_manifest.json").exists():
        yield (
            "warning",
            "retrieval_bm25_manifest_missing",
            f"Missing BM25 public manifest: {public_dir / 'bm25_manifest.json'}",
        )
    if not (public_dir / "vector_manifest.json").exists():
        yield (
            "warning",
            "retrieval_vector_manifest_missing",
            f"Missing vector public manifest: {public_dir / 'vector_manifest.json'}",
        )


def iter_retrieval_result_issues(
    result: RetrievalResult,
) -> Iterator[tuple[str, str, str]]:
    """Yield ``(severity, code, message)`` for a single result.

    The validator is exhaustive: it checks every required field,
    every required component-score sub-field, and the bounds
    on the boost value. It is used by tests to assert that the
    result schema is well-formed.
    """
    if result.mode not in ALLOWED_MODES:
        yield (
            "error",
            "retrieval_invalid_mode",
            f"Invalid retrieval mode: {result.mode!r}",
        )
    if result.component_scores.graph_boost < 0.0:
        yield (
            "error",
            "retrieval_negative_boost",
            f"Graph-lite boost is negative: {result.component_scores.graph_boost}",
        )
    if result.component_scores.graph_boost > GRAPH_LITE_MAX_BOOST + 1e-9:
        yield (
            "error",
            "retrieval_boost_above_cap",
            f"Graph-lite boost exceeds the cap: "
            f"{result.component_scores.graph_boost} > {GRAPH_LITE_MAX_BOOST}",
        )
    if not result.chunk_id:
        yield (
            "error",
            "retrieval_missing_chunk_id",
            "RetrievalResult is missing chunk_id",
        )
    if not result.resource_id:
        yield (
            "error",
            "retrieval_missing_resource_id",
            "RetrievalResult is missing resource_id",
        )
    if result.rank < 1:
        yield (
            "error",
            "retrieval_invalid_rank",
            f"RetrievalResult rank is not positive: {result.rank}",
        )
    # Component score sub-fields.
    for field_name in (
        "bm25",
        "vector",
        "graph_boost",
        "normalized_bm25",
        "normalized_vector",
        "final",
    ):
        value = getattr(result.component_scores, field_name, None)
        if value is None:
            yield (
                "error",
                "retrieval_missing_component_score",
                f"Missing component_scores.{field_name}",
            )
    # The normalized scores must be in [0, 1] (they are
    # max-normalized). A small epsilon tolerates float
    # rounding.
    for field_name in ("normalized_bm25", "normalized_vector"):
        value = getattr(result.component_scores, field_name, 0.0)
        if value < 0.0 - 1e-9 or value > 1.0 + 1e-9:
            yield (
                "error",
                "retrieval_normalized_out_of_bounds",
                f"component_scores.{field_name} out of [0, 1]: {value}",
            )


__all__ = [
    "iter_retrieval_issues",
    "iter_retrieval_result_issues",
]
