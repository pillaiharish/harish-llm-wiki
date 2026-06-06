"""Vector search runtime (Prompt 29).

Combines the on-disk vector index with the chunk-index text store
and the cosine-similarity scorer. Returns a list of
:class:`SearchResult` objects in stable order.

The search runtime is intentionally simple: load the in-memory
vector index from the data dir (or accept an in-memory
:class:`VectorIndexResult` directly), tokenize the query, score
against every chunk using cosine similarity, and project to a
:class:`SearchResult` list.

Filters
-------

- ``--source-type`` / ``source_types``: post-score filter, applied
  to ``meta.source_type``. The score is still computed over the
  full index to avoid re-normalization bugs.
- ``--resource-id`` / ``resource_id``: post-score filter on
  ``meta.resource_id``.

Text previews
-------------

The ``text_preview`` field is the first ``TEXT_PREVIEW_CHARS``
characters of the chunk text. The in-memory index already carries
a ``text_preview`` (truncated at build time). When
``include_text=True`` is passed, the search runtime falls back to
re-reading the chunk index on disk so the full chunk text is
available.

The text-lookup is performed by reading
``processed/chunk_index/chunks.json`` (the canonical list of all
chunks). The function is defensive: if the chunk text cannot be
found, ``text_preview`` is the empty string.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from wiki.config import config
from wiki.vector.index import (
    TEXT_PREVIEW_CHARS,
    VectorIndexResult,
)
from wiki.vector.tokenize import tokenize
from wiki.vector.vectorizer import HashingTfidfVectorizer


# =============================================================================
# Constants
# =============================================================================


#: Default number of results returned by :func:`search_vector`.
DEFAULT_LIMIT: int = 10

#: Hard cap on the number of results. The CLI rejects ``--limit`` > this.
MAX_LIMIT: int = 100


# =============================================================================
# Data classes
# =============================================================================


@dataclass
class SearchResult:
    """The public search-result schema (Prompt 29).

    The dataclass is the vector analog of the BM25 ``SearchResult``
    in :mod:`wiki.search.bm25`. The only field-name change is
    ``matched_terms`` -> ``query_terms`` in the public dict,
    because the vector backend scores by hashed-dot-product over
    the IDF-weighted terms, not by token presence.

    The field order is the canonical JSON serialization order,
    matching the schema required by ``prompt29.md`` §"Required
    search result schema".
    """

    rank: int
    score: float
    chunk_id: str
    resource_id: str
    title: str
    source_type: str
    text_preview: str
    citation_label: str
    resource_route: str
    source_ref: dict = field(default_factory=dict)
    query_terms: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Project to a dict in stable field order."""
        return {
            "rank": self.rank,
            "score": self.score,
            "chunk_id": self.chunk_id,
            "resource_id": self.resource_id,
            "title": self.title,
            "source_type": self.source_type,
            "text_preview": self.text_preview,
            "citation_label": self.citation_label,
            "resource_route": self.resource_route,
            "source_ref": self.source_ref,
            "query_terms": self.query_terms,
            "metadata": self.metadata,
        }


# =============================================================================
# Search runtime
# =============================================================================


def search_vector(
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
    source_types: Optional[Iterable[str]] = None,
    resource_id: Optional[str] = None,
    include_text: bool = False,
    index_dir: Path | None = None,
    data_dir: Path | None = None,
) -> list[SearchResult]:
    """Search the on-disk vector index for ``query``.

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
        schema is still complete (``text_preview`` is the
        truncated preview already in the index).
    index_dir:
        Optional override for the vector data dir. Defaults to
        ``processed/vector``.
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
        If the vector index files are missing.
    """
    if not query or not query.strip():
        raise ValueError("query is empty")

    limit = max(1, min(int(limit), MAX_LIMIT))

    base = data_dir or config.LLM_WIKI_DATA_DIR
    vector_dir = Path(index_dir) if index_dir is not None else (
        (base / "processed" / "vector")
    )
    index_path = vector_dir / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(
            f"Vector index not found: {index_path}. Run `wiki build-vector-index` first."
        )

    # Load the vector index into memory.
    from wiki.vector.index import load_vector_index  # local import to avoid cycle

    vector_index = load_vector_index(index_path)

    return search_vector_in_memory(
        query=query,
        vector_index=vector_index,
        limit=limit,
        source_types=source_types,
        resource_id=resource_id,
        include_text=include_text,
        data_dir=base,
    )


def search_vector_in_memory(
    *,
    query: str,
    vector_index: VectorIndexResult,
    limit: int = DEFAULT_LIMIT,
    source_types: Optional[Iterable[str]] = None,
    resource_id: Optional[str] = None,
    include_text: bool = False,
    data_dir: Path | None = None,
) -> list[SearchResult]:
    """Search an in-memory :class:`VectorIndexResult` for ``query``.

    Exposed for unit tests and for callers that already have the
    in-memory index in hand. The on-disk :func:`search_vector` is
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

    state = vector_index.state
    if state is None:
        # The in-memory index is missing the state (it was not
        # saved in older builds). Rebuild a minimal state from the
        # config so the search runtime still works.
        from wiki.vector.vectorizer import VectorizerState

        state = VectorizerState(
            dimension=vector_index.config.dimension,
            idf={},
            field_weights=dict(vector_index.config.field_weights),
        )

    vectorizer = HashingTfidfVectorizer(config=vector_index.config)
    query_vec = vectorizer.transform_query(query_tokens, state)

    if not query_vec:
        return []

    # Score every chunk.
    scored: list[tuple[float, str]] = []
    for cid, entry in vector_index.vectors.items():
        entries = entry.get("entries") or {}
        if not entries:
            continue
        score = vectorizer.cosine(query_vec, entries)
        # Cosine of L2-normalized vectors is in [-1, 1]; we clamp
        # to [0, 1] for human-readable results (the IDF is
        # never-negative so the dot product is in fact >= 0 here).
        if score < 0.0:
            score = 0.0
        scored.append((score, cid))
    # Sort by (-score, chunk_id asc).
    scored.sort(key=lambda pair: (-pair[0], pair[1]))

    # Apply filters.
    if source_types_set is not None or resource_id is not None:
        filtered: list[tuple[float, str]] = []
        for score, cid in scored:
            entry = vector_index.vectors.get(cid) or {}
            if (
                source_types_set is not None
                and str(entry.get("source_type", "")) not in source_types_set
            ):
                continue
            if (
                resource_id is not None
                and str(entry.get("resource_id", "")) != resource_id
            ):
                continue
            filtered.append((score, cid))
        scored = filtered

    # Truncate to limit.
    top = scored[:limit]

    # Optionally load the chunk text for text_preview.
    chunk_text_by_id: dict[str, str] = {}
    if include_text:
        chunk_text_by_id = _load_chunk_text_map(data_dir=data_dir)

    results: list[SearchResult] = []
    for rank, (score, cid) in enumerate(top, start=1):
        entry = vector_index.vectors.get(cid) or {}
        text_preview = ""
        if include_text:
            text_preview = _truncate_text(
                chunk_text_by_id.get(cid)
                or str(entry.get("text_preview", "") or "")
            )
        else:
            text_preview = str(entry.get("text_preview", "") or "")
        results.append(
            SearchResult(
                rank=rank,
                score=float(score),
                chunk_id=str(cid),
                resource_id=str(entry.get("resource_id", "")),
                title=str(entry.get("title", "")),
                source_type=str(entry.get("source_type", "")),
                text_preview=text_preview,
                citation_label=str(entry.get("citation_label", "")),
                resource_route=str(entry.get("resource_route", "")),
                source_ref=dict(entry.get("source_ref") or {}),
                query_terms=list(query_tokens),
                metadata=_build_metadata(entry),
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


def _build_metadata(entry: dict) -> dict:
    """Build the ``metadata`` block of a search result.

    Kept small: the URL, the tags, and the topics (extracted from
    ``source_ref`` if available). The BM25 backend uses
    ``chunk_meta`` for this; the vector backend stores per-chunk
    meta inside each vector entry's ``source_ref`` so we look
    there.
    """
    source_ref = dict(entry.get("source_ref") or {})
    return {
        "source_url": str(source_ref.get("source_url") or source_ref.get("url") or ""),
        "tags": list(source_ref.get("tags") or []),
        "topics": list(source_ref.get("topics") or []),
    }


def _load_chunk_text_map(*, data_dir: Path | None = None) -> dict[str, str]:
    """Read the chunk index ``chunks.json`` and return ``{chunk_id: text}``.

    The function is defensive: if the chunk index is missing or
    malformed, it returns an empty map. The on-disk chunk index
    is the canonical text store; the vector index does not embed
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
    "SearchResult",
    "search_vector",
    "search_vector_in_memory",
]
