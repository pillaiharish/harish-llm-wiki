"""Context-pack builder (Prompt 33).

This module converts a list of
:class:`wiki.retrieval.schema.RetrievalResult` objects into a
:class:`wiki.context_pack.schema.ContextPack`. The pack is
deterministic, no-LLM, and pure-Python; it is consumed by the
``wiki build-context`` CLI and the context-pack tests.

The builder is a thin layer over the existing hybrid
retrieval router (Prompt 30). It does **not** reimplement
retrieval scoring and it does **not** modify the chunk
index, the BM25 index, the vector index, or the graph
backend. It reuses :func:`wiki.retrieval.retrieve_hybrid`
to fetch the ranked result list and looks up the full chunk
text from the on-disk chunk index
(``processed/chunk_index/chunks.json``).

Determinism rules
-----------------

1. The input result list is treated as already ranked (the
   upstream router is the single source of truth for
   ranking). The builder only re-ranks to apply the
   cross-chunk dedup policy.
2. Duplicate chunks (same ``chunk_id``) are removed
   deterministically. First-seen wins. The remaining chunks
   keep their original upstream order.
3. Duplicate sources (same ``resource_id``) are removed
   from the source list. The first-seen source wins and the
   subsequent ``chunk_ids`` are appended to it.
4. Citation labels are assigned in the final chunk order.
   The first chunk gets ``[cite:1]``, the second ``[cite:2]``,
   etc. A source's ``citation_label`` matches the label of
   the first chunk that cited it.
5. The per-chunk char budget (``max_chars``) is applied
   *per chunk*, not across the whole pack. A non-positive
   ``max_chars`` disables trimming. The trim is at stable
   word boundaries; the ``truncated`` flag records whether a
   chunk was trimmed.
6. The output JSON field order is stable (see
   :meth:`ContextPack.to_dict`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

from wiki.config import config
from wiki.context_pack.schema import (
    CONTEXT_PACK_SCHEMA_VERSION,
    ContextChunk,
    ContextPack,
    ContextSource,
    DEFAULT_LIMIT,
    DEFAULT_MAX_CHARS,
    DEFAULT_MODE,
    EMPTY_STRING,
    MAX_LIMIT,
    make_citation_label,
)
from wiki.retrieval.schema import (
    ALLOWED_MODES,
    DEFAULT_BM25_WEIGHT,
    DEFAULT_VECTOR_WEIGHT,
    RetrievalResult,
)


# =============================================================================
# On-disk entry point
# =============================================================================


def build_context_pack(
    query: str,
    *,
    mode: str = DEFAULT_MODE,
    limit: int = DEFAULT_LIMIT,
    max_chars: int = DEFAULT_MAX_CHARS,
    source_types: Optional[Iterable[str]] = None,
    resource_id: Optional[str] = None,
    include_text: bool = True,
    bm25_weight: float = DEFAULT_BM25_WEIGHT,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    explain: bool = False,
    index_dir: Path | None = None,
    data_dir: Path | None = None,
) -> ContextPack:
    """Build a context pack for ``query`` over the on-disk indexes.

    This is the on-disk entry point used by the CLI. It loads
    the BM25 and vector indexes from the data dir, calls the
    upstream hybrid router, and packages the result list into
    a :class:`ContextPack`.

    Parameters
    ----------
    query:
        The user query. Must be non-empty after stripping.
    mode:
        One of ``bm25``, ``vector``, ``hybrid``, ``graph-lite``.
    limit:
        Maximum number of retrieval results. Hard-capped at
        ``MAX_LIMIT`` (100).
    max_chars:
        Per-chunk char budget. ``0`` (or any non-positive
        value) means "no per-chunk char budget".
    source_types:
        Optional iterable of source types to filter by.
        Applied after scoring.
    resource_id:
        Optional single resource id to filter by.
    include_text:
        If ``True`` (the default for this entry point), the
        router populates each result's ``text_preview`` from
        the chunk index. The builder reads the same chunk
        index to populate the full chunk text in the pack.
    bm25_weight:
        Weight on the BM25 contribution (forwarded to the
        router).
    vector_weight:
        Weight on the vector contribution (forwarded to the
        router).
    explain:
        If ``True``, the router's ``--explain`` flag is set.
        The pack itself does not surface the per-factor
        graph-lite details; the flag exists for symmetry with
        ``wiki retrieve``.
    index_dir:
        Optional override for the BM25/vector index dir.
    data_dir:
        Optional override for the wiki data dir.

    Returns
    -------
    ContextPack
        The deterministic context pack.

    Raises
    ------
    ValueError
        If ``query`` is empty/whitespace, if ``mode`` is not
        in :data:`ALLOWED_MODES`, or if the weights are
        invalid.
    FileNotFoundError
        If the BM25 or vector index is missing for a mode
        that requires it.
    """
    base = Path(data_dir) if data_dir is not None else config.LLM_WIKI_DATA_DIR

    # Local imports to avoid an import cycle with the router
    # when the package is imported during tests.
    from wiki.retrieval import retrieve_hybrid

    # The router has its own limit cap. We mirror it here so
    # the validation is in one place; the router will clamp
    # again.
    effective_limit = max(1, min(int(limit), MAX_LIMIT))

    results = retrieve_hybrid(
        query,
        mode=mode,
        limit=effective_limit,
        source_types=source_types,
        resource_id=resource_id,
        include_text=include_text,
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
        explain=explain,
        index_dir=index_dir,
        data_dir=base,
    )

    return build_context_pack_from_results(
        query=query,
        mode=mode,
        limit=effective_limit,
        max_chars=max_chars,
        results=results,
        data_dir=base,
    )


# =============================================================================
# In-memory entry point
# =============================================================================


def build_context_pack_in_memory(
    *,
    query: str,
    results: list[RetrievalResult],
    mode: str = DEFAULT_MODE,
    limit: int = DEFAULT_LIMIT,
    max_chars: int = DEFAULT_MAX_CHARS,
    data_dir: Path | None = None,
) -> ContextPack:
    """Build a context pack from a pre-computed result list.

    The in-memory entry point used by tests and by callers
    that already have the upstream :class:`RetrievalResult`
    list. The function is pure: it does not call the router
    and does not import the BM25/vector indexes. It only
    reads the on-disk chunk index to look up the full chunk
    text.

    Parameters
    ----------
    query:
        The user query. Stored verbatim in the pack.
    results:
        The ranked :class:`RetrievalResult` list. Order is
        preserved (modulo the cross-chunk dedup).
    mode:
        The retrieval mode label. Stored in the pack.
    limit:
        The original ``limit`` argument. Stored in the
        pack; the function does not re-truncate the result
        list.
    max_chars:
        Per-chunk char budget. ``0`` (or any non-positive
        value) means "no per-chunk char budget".
    data_dir:
        Optional override for the wiki data dir. The chunk
        index is read from
        ``<data_dir>/processed/chunk_index/chunks.json``.

    Returns
    -------
    ContextPack
        The deterministic context pack.
    """
    base = Path(data_dir) if data_dir is not None else config.LLM_WIKI_DATA_DIR
    return build_context_pack_from_results(
        query=query,
        mode=mode,
        limit=limit,
        max_chars=max_chars,
        results=results,
        data_dir=base,
    )


# =============================================================================
# Core builder
# =============================================================================


def build_context_pack_from_results(
    *,
    query: str,
    mode: str,
    limit: int,
    max_chars: int,
    results: list[RetrievalResult],
    data_dir: Path,
) -> ContextPack:
    """Build a context pack from a pre-computed result list.

    This is the deterministic core used by both the on-disk
    and the in-memory entry points. The function does not
    call the router, does not re-rank, and does not import
    the BM25/vector indexes.

    The function performs the following steps in order:

    1. Validate the request (``query``, ``mode``, ``limit``,
       ``max_chars``).
    2. Load the chunk text map from the on-disk chunk index.
    3. Deduplicate chunks by ``chunk_id`` (first-seen wins).
    4. Assign stable citation labels in the final chunk
       order.
    5. Trim each chunk's text to respect ``max_chars`` and
       set the ``truncated`` flag.
    6. Build the deduplicated source list in first-cited
       order.
    7. Compute ``used_chars`` and ``total_chunks``.
    8. Project to a :class:`ContextPack` with stable field
       order.
    """
    if not query or not str(query).strip():
        raise ValueError("query is empty")
    if mode not in ALLOWED_MODES:
        raise ValueError(
            f"invalid mode: {mode!r} (allowed: {sorted(ALLOWED_MODES)})"
        )
    if int(limit) < 1:
        raise ValueError(f"limit must be >= 1 (got {limit})")
    if int(max_chars) < 0:
        raise ValueError(f"max_chars must be >= 0 (got {max_chars})")

    chunk_text_map = _load_chunk_text_map(data_dir=data_dir)

    # 1. Deduplicate chunks by chunk_id. The upstream router
    # is the single source of truth for ranking; first-seen
    # wins.
    seen_chunk_ids: set[str] = set()
    deduped: list[RetrievalResult] = []
    for r in results:
        cid = str(r.chunk_id or "")
        if not cid:
            continue
        if cid in seen_chunk_ids:
            continue
        seen_chunk_ids.add(cid)
        deduped.append(r)

    # 2. Build the chunk list with stable citation labels.
    chunks: list[ContextChunk] = []
    used_chars = 0
    for rank, r in enumerate(deduped, start=1):
        cid = str(r.chunk_id)
        text = chunk_text_map.get(cid) or _resolve_text_from_result(r)
        trimmed_text, truncated = _trim_text(text, max_chars=max_chars)
        used_chars += len(trimmed_text)
        chunks.append(
            ContextChunk(
                rank=rank,
                citation_label=make_citation_label(rank),
                resource_id=str(r.resource_id or EMPTY_STRING),
                chunk_id=cid,
                title=str(r.title or EMPTY_STRING),
                source_type=str(r.source_type or EMPTY_STRING),
                score=float(r.score or 0.0),
                text=trimmed_text,
                truncated=bool(truncated),
            )
        )

    # 3. Build the deduplicated source list in first-cited
    # order. Two passes: first assign each chunk's
    # resource_id a citation label (taken from the chunk's
    # own citation_label), then build the list.
    sources: list[ContextSource] = []
    source_by_rid: dict[str, ContextSource] = {}
    for chunk in chunks:
        rid = chunk.resource_id
        if not rid:
            continue
        existing = source_by_rid.get(rid)
        if existing is None:
            existing = ContextSource(
                citation_label=chunk.citation_label,
                resource_id=rid,
                title=chunk.title,
                source_type=chunk.source_type,
                chunk_ids=[chunk.chunk_id],
            )
            source_by_rid[rid] = existing
            sources.append(existing)
        else:
            # Append in a way that preserves immutability:
            # build a new source with the appended list and
            # replace the cached entry and the in-place list
            # reference in the sources list.
            new_chunk_ids = list(existing.chunk_ids) + [chunk.chunk_id]
            new_source = ContextSource(
                citation_label=existing.citation_label,
                resource_id=existing.resource_id,
                title=existing.title,
                source_type=existing.source_type,
                chunk_ids=new_chunk_ids,
            )
            source_by_rid[rid] = new_source
            for i, s in enumerate(sources):
                if s.resource_id == rid:
                    sources[i] = new_source
                    break

    return ContextPack(
        schema_version=CONTEXT_PACK_SCHEMA_VERSION,
        query=str(query),
        mode=str(mode),
        limit=int(limit),
        max_chars=int(max_chars),
        used_chars=int(used_chars),
        total_chunks=len(chunks),
        chunks=chunks,
        sources=sources,
    )


# =============================================================================
# Local helpers
# =============================================================================


def _trim_text(text: str, *, max_chars: int) -> tuple[str, bool]:
    """Trim ``text`` to ``max_chars`` characters at a stable boundary.

    The function trims at the nearest whitespace boundary that
    is at or below ``max_chars``, with a hard cap at
    ``max_chars`` if no whitespace is found. The trim
    always appends an ellipsis (``...``) to make the trim
    visible to downstream consumers. A non-positive
    ``max_chars`` disables trimming.

    The function is deterministic: same text + same
    ``max_chars`` always produce the same output.
    """
    if not text:
        return "", False
    if max_chars is None or int(max_chars) <= 0:
        return text, False
    cap = int(max_chars)
    if len(text) <= cap:
        return text, False
    # Reserve three characters for the ellipsis.
    if cap <= 3:
        return ("." * cap), True
    headroom = cap - 3
    trimmed = text[:headroom]
    # Snap to the last whitespace boundary so we don't cut a
    # word in half. ``rfind`` returns -1 when there is no
    # whitespace, in which case we use the headroom slice as
    # is.
    ws = trimmed.rfind(" ")
    if ws > 0:
        trimmed = trimmed[:ws]
    return trimmed.rstrip() + "...", True


def _resolve_text_from_result(result: RetrievalResult) -> str:
    """Return the chunk text carried on a retrieval result.

    Falls back to the truncated ``text_preview`` when the
    full text is not available. This is a defensive fallback
    for callers that built the result list with
    ``include_text=False`` or with a chunk index that did not
    carry the full text.
    """
    # The retrieval result schema only carries ``text_preview``
    # by default. The builder reads the full text from the
    # chunk index first; this fallback is just so the function
    # is well-defined when the chunk index is missing.
    return str(getattr(result, "text_preview", "") or "")


def _load_chunk_text_map(*, data_dir: Path) -> dict[str, str]:
    """Read the chunk index ``chunks.json`` and return ``{chunk_id: text}``.

    Defensive: missing or malformed chunk index returns an
    empty map. The chunk index is the canonical full-text
    store; the BM25 and vector indexes do not embed the full
    text.
    """
    chunks_path = data_dir / "processed" / "chunk_index" / "chunks.json"
    if not chunks_path.exists():
        return {}
    try:
        payload = json.loads(chunks_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
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
    "build_context_pack",
    "build_context_pack_from_results",
    "build_context_pack_in_memory",
]
