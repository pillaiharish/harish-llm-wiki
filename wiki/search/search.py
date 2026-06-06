"""BM25 search runtime (Prompt 28).

Combines the on-disk BM25 index with the chunk-index text store
and the BM25 scorer. Returns a list of :class:`SearchResult`
objects in stable order.

The search runtime is intentionally simple: load the in-memory
BM25 index from the data dir (or accept an in-memory
:class:`BM25IndexResult` directly), tokenize the query, score,
and project to a :class:`SearchResult` list.

Filters
-------

- ``--source-type`` / ``source_types``: post-score filter,
  applied to ``meta.source_type``. The score is still computed
  over the full index to avoid re-normalization bugs.
- ``--resource-id`` / ``resource_id``: post-score filter on
  ``meta.resource_id``.

Text previews
-------------

The ``text_preview`` field is the first ``TEXT_PREVIEW_CHARS``
characters of the chunk text. The chunk text is loaded from the
chunk index on disk (re-looked up by ``chunk_id``), not from
``chunk_meta.text`` (which is only available in-memory at build
time). The on-disk chunk index is the canonical text store; this
keeps the BM25 index files smaller.

The text-lookup is performed by reading
``processed/chunk_index/chunks.json`` (the canonical list of all
chunks). The function is defensive: if the chunk text cannot be
found, ``text_preview`` is the empty string and a warning is
emitted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

from wiki.config import config
from wiki.search.bm25 import BM25Scorer, SearchResult
from wiki.search.export import bm25_output_paths
from wiki.search.index import BM25IndexResult, TEXT_PREVIEW_CHARS
from wiki.search.tokenize import tokenize


# =============================================================================
# Constants
# =============================================================================


#: Default number of results returned by :func:`search_bm25`.
DEFAULT_LIMIT: int = 10

#: Hard cap on the number of results. The CLI rejects ``--limit`` > this.
MAX_LIMIT: int = 100


# =============================================================================
# Search runtime
# =============================================================================


def search_bm25(
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
    source_types: Optional[Iterable[str]] = None,
    resource_id: Optional[str] = None,
    include_text: bool = False,
    index_dir: Path | None = None,
    data_dir: Path | None = None,
) -> list[SearchResult]:
    """Search the on-disk BM25 index for ``query``.

    Returns a list of :class:`SearchResult` objects, sorted by
    rank (descending score, then ``chunk_id`` asc).

    Parameters
    ----------
    query:
        The user query. Must be non-empty after stripping.
    limit:
        Maximum number of results. Default ``DEFAULT_LIMIT``
        (10). Hard-capped at ``MAX_LIMIT`` (100).
    source_types:
        Optional iterable of source types to filter by. Applied
        after scoring.
    resource_id:
        Optional single resource id to filter by. Applied after
        scoring.
    include_text:
        If ``True``, populate the ``text_preview`` field with the
        first 240 chars of the chunk text (read from the chunk
        index). When ``False`` (the CLI default), the result
        schema is still complete (``text_preview`` is empty).
    index_dir:
        Optional override for the BM25 data dir. Defaults to
        ``processed/bm25``.
    data_dir:
        Optional override for the wiki data dir. Defaults to
        ``config.LLM_WIKI_DATA_DIR``.

    Returns
    -------
    list[SearchResult]
        The ranked results. Empty if ``query`` is empty/whitespace
        or the index has no matching chunks.

    Raises
    ------
    ValueError
        If ``query`` is empty/whitespace.
    FileNotFoundError
        If the BM25 index files are missing.
    """
    if not query or not query.strip():
        raise ValueError("query is empty")

    limit = max(1, min(int(limit), MAX_LIMIT))

    base = data_dir or config.LLM_WIKI_DATA_DIR
    bm25_dir = Path(index_dir) if index_dir is not None else (
        (base / "processed" / "bm25")
    )
    index_path = bm25_dir / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(
            f"BM25 index not found: {index_path}. Run `wiki build-bm25-index` first."
        )

    # Load the BM25 index into memory.
    from wiki.search.index import load_bm25_index  # local import to avoid cycle

    bm25_index = load_bm25_index(index_path)

    return search_bm25_in_memory(
        query=query,
        bm25_index=bm25_index,
        limit=limit,
        source_types=source_types,
        resource_id=resource_id,
        include_text=include_text,
        data_dir=base,
    )


def search_bm25_in_memory(
    *,
    query: str,
    bm25_index: BM25IndexResult,
    limit: int = DEFAULT_LIMIT,
    source_types: Optional[Iterable[str]] = None,
    resource_id: Optional[str] = None,
    include_text: bool = False,
    data_dir: Path | None = None,
) -> list[SearchResult]:
    """Search an in-memory :class:`BM25IndexResult` for ``query``.

    Exposed for unit tests and for callers that already have the
    in-memory index in hand. The on-disk :func:`search_bm25` is
    the public entry point; this function is the pure search
    runtime.
    """
    if not query or not query.strip():
        raise ValueError("query is empty")

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    limit = max(1, min(int(limit), MAX_LIMIT))
    source_types_set = (
        {str(s).strip() for s in source_types if str(s).strip()}
        if source_types
        else None
    )

    # Strip the in-memory ``text`` field out of chunk_meta for the
    # scorer. The on-disk chunk_meta does not carry text, so this
    # is a no-op for the on-disk path; the in-memory build path
    # keeps ``text`` for the preview, but the scorer does not need it.
    scorer_meta: dict[str, dict] = {
        cid: {k: v for k, v in meta.items() if k != "text"}
        for cid, meta in bm25_index.chunk_meta.items()
    }
    matched_terms_per_chunk: dict[str, set] = {}
    scorer = BM25Scorer(k1=bm25_index.k1, b=bm25_index.b)
    scores = scorer.score_query(
        query_tokens,
        bm25_index.vocab,
        scorer_meta,
        matched_terms_out=matched_terms_per_chunk,
    )

    # Apply filters.
    if source_types_set is not None or resource_id is not None:
        filtered: list = []
        for s in scores:
            meta = bm25_index.chunk_meta.get(s.chunk_id) or {}
            if (
                source_types_set is not None
                and str(meta.get("source_type", "")) not in source_types_set
            ):
                continue
            if (
                resource_id is not None
                and str(meta.get("resource_id", "")) != resource_id
            ):
                continue
            filtered.append(s)
        scores = filtered

    # Truncate to limit.
    top = scores[:limit]

    # Compute matched_terms for each top result.
    matched_by_query = bm25_index.matched_terms(query_tokens)

    # Optionally load the chunk text for text_preview.
    chunk_text_by_id: dict[str, str] = {}
    if include_text:
        chunk_text_by_id = _load_chunk_text_map(data_dir=data_dir)

    results: list[SearchResult] = []
    for rank, score in enumerate(top, start=1):
        meta = bm25_index.chunk_meta.get(score.chunk_id) or {}
        # Prefer the matched-terms from the postings pass; fall
        # back to the text-blob scan if a chunk matched via a
        # field that did not contribute to tf (defensive).
        from_postings = sorted(matched_terms_per_chunk.get(score.chunk_id, set()))
        from_text = matched_by_query.get(score.chunk_id, [])
        if from_postings:
            matched_terms = from_postings
        else:
            matched_terms = from_text
        text_preview = ""
        if include_text:
            text_preview = _truncate_text(
                chunk_text_by_id.get(score.chunk_id)
                or str(meta.get("text", "") or "")
            )
        results.append(
            SearchResult(
                rank=rank,
                score=float(score.score),
                chunk_id=str(score.chunk_id),
                resource_id=str(meta.get("resource_id", "")),
                title=str(meta.get("title", "")),
                source_type=str(meta.get("source_type", "")),
                text_preview=text_preview,
                citation_label=str(meta.get("citation_label", "")),
                resource_route=str(meta.get("resource_route", "")),
                source_ref=dict(meta.get("source_ref") or {}),
                matched_terms=matched_terms,
                metadata=_build_metadata(meta),
            )
        )
    return results


# =============================================================================
# Local helpers
# =============================================================================


def _truncate_text(text: str) -> str:
    if not text:
        return ""
    if len(text) <= TEXT_PREVIEW_CHARS:
        return text
    return text[:TEXT_PREVIEW_CHARS]


def _build_metadata(meta: dict) -> dict:
    """Build the ``metadata`` block of a search result.

    Kept small: the URL, the tags, and the topics. The full
    ``extra`` bag is not included to keep the result compact
    and to avoid leaking per-chunk detail that the chunk
    index's own public copy already exposes.
    """
    return {
        "source_url": str(meta.get("source_url") or ""),
        "tags": list(meta.get("tags") or []),
        "topics": list(meta.get("topics") or []),
    }


def _load_chunk_text_map(*, data_dir: Path | None = None) -> dict[str, str]:
    """Read the chunk index ``chunks.json`` and return ``{chunk_id: text}``.

    The function is defensive: if the chunk index is missing or
    malformed, it returns an empty map. The on-disk chunk index
    is the canonical text store; the BM25 index does not embed
    the full text.
    """
    base = data_dir or config.LLM_WIKI_DATA_DIR
    chunks_path = base / "processed" / "chunk_index" / "chunks.json"
    if not chunks_path.exists():
        return {}
    try:
        payload = json.loads(chunks_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, list):
        return {}
    out: dict[str, str] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("chunk_id", "") or "")
        if not cid:
            continue
        out[cid] = str(entry.get("text", "") or "")
    return out


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "search_bm25",
    "search_bm25_in_memory",
]
