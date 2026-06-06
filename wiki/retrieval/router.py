"""Deterministic hybrid retrieval router (Prompt 30).

The router unifies the existing BM25 lexical backend (Prompt 28)
and the deterministic local vector backend (Prompt 29) and
overlays a small, bounded **graph-lite** metadata boost using
the existing knowledge graph (Prompt 23 + 24).

Public entry points
-------------------

- :func:`retrieve_hybrid` — the on-disk entry point used by the
  CLI. Reads the BM25 and vector indexes from the data dir.
- :func:`retrieve_hybrid_in_memory` — the in-memory entry point
  used by tests and by callers that already have the indexes in
  memory.

Both functions return a list of :class:`wiki.retrieval.schema.RetrievalResult`
objects in stable rank order. The CLI's ``--json`` flag emits
the same shape via :meth:`RetrievalResult.to_dict`.

Modes
-----

- ``bm25`` — use the BM25 backend only. ``vector`` and
  ``graph_boost`` component scores are zero.
- ``vector`` — use the vector backend only. ``bm25`` and
  ``graph_boost`` component scores are zero.
- ``hybrid`` (default) — combine BM25 and vector scores via
  max-normalized linear fusion.
- ``graph-lite`` — ``hybrid`` plus a small bounded per-chunk
  boost computed from the on-disk knowledge graph.

The router never writes to the data dir and never modifies the
BM25, vector, chunk, or graph backends. It is a read-only
consumer of those indexes.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from wiki.config import config
from wiki.search import search_bm25_in_memory, BM25IndexResult
from wiki.vector import search_vector_in_memory, VectorIndexResult
from wiki.retrieval import graph_lite
from wiki.retrieval import fusion
from wiki.retrieval.schema import (
    ALLOWED_MODES,
    ComponentScores,
    DEFAULT_BM25_WEIGHT,
    DEFAULT_MODE,
    DEFAULT_VECTOR_WEIGHT,
    Explanation,
    GRAPH_LITE_MAX_BOOST,
    HYBRID_FETCH_FACTOR,
    MAX_LIMIT,
    RETRIEVAL_SCHEMA_VERSION,
    RetrievalResult,
)


# =============================================================================
# On-disk entry point
# =============================================================================


def retrieve_hybrid(
    query: str,
    *,
    mode: str = DEFAULT_MODE,
    limit: int = 10,
    source_types: Optional[Iterable[str]] = None,
    resource_id: Optional[str] = None,
    include_text: bool = False,
    bm25_weight: float = DEFAULT_BM25_WEIGHT,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    explain: bool = False,
    index_dir: Path | None = None,
    data_dir: Path | None = None,
) -> list[RetrievalResult]:
    """Run a hybrid retrieval query over the on-disk indexes.

    The on-disk entry point used by the CLI. It loads the BM25
    and vector indexes from the data dir and delegates to
    :func:`retrieve_hybrid_in_memory`.

    Parameters
    ----------
    query:
        The user query. Must be non-empty after stripping.
    mode:
        One of ``bm25``, ``vector``, ``hybrid``, ``graph-lite``.
    limit:
        Maximum number of results. Hard-capped at ``MAX_LIMIT``
        (100).
    source_types:
        Optional iterable of source types to filter by. Applied
        after scoring.
    resource_id:
        Optional single resource id to filter by.
    include_text:
        If ``True``, populate the ``text_preview`` field with
        the chunk text.
    bm25_weight:
        Weight on the BM25 contribution in the linear fusion.
        Default ``DEFAULT_BM25_WEIGHT`` (0.55).
    vector_weight:
        Weight on the vector contribution in the linear fusion.
        Default ``DEFAULT_VECTOR_WEIGHT`` (0.45).
    explain:
        If ``True``, the ``explanation`` block in each result
        includes the per-factor details (``shared_topics``,
        ``shared_concepts``, ``source_type_preference``,
        ``resource_relationship_targets``).
    index_dir:
        Optional override for the BM25/vector index dir.
    data_dir:
        Optional override for the wiki data dir.

    Returns
    -------
    list[RetrievalResult]
        The ranked retrieval results in stable rank order.

    Raises
    ------
    ValueError
        If ``query`` is empty/whitespace, if ``mode`` is not in
        :data:`ALLOWED_MODES`, or if the weights are invalid.
    FileNotFoundError
        If the BM25 or vector index is missing for a mode that
        requires it.
    """
    if not query or not str(query).strip():
        raise ValueError("query is empty")
    if mode not in ALLOWED_MODES:
        raise ValueError(
            f"invalid mode: {mode!r} (allowed: {sorted(ALLOWED_MODES)})"
        )

    base = Path(data_dir) if data_dir is not None else config.LLM_WIKI_DATA_DIR
    base = Path(base)

    # Load the BM25 and vector indexes. We always load both even
    # in single-mode, because we still need the chunk metadata
    # (title, source_type, resource_route) to populate the result
    # schema. In single-mode, the "missing" backend just
    # contributes zero scores.
    from wiki.search import load_bm25_index
    from wiki.search.export import bm25_output_paths
    from wiki.vector import load_vector_index
    from wiki.vector.export import vector_output_paths

    bm25_dir = (
        Path(index_dir)
        if index_dir is not None
        else (base / "processed" / "bm25")
    )
    vector_dir = (
        Path(index_dir)
        if index_dir is not None
        else (base / "processed" / "vector")
    )

    bm25_paths = bm25_output_paths(data_dir=base) if index_dir is None else {
        "index_json": bm25_dir / "index.json",
    }
    vector_paths = (
        vector_output_paths(data_dir=base) if index_dir is None else {
            "index_json": vector_dir / "index.json",
        }
    )

    bm25_index: Optional[BM25IndexResult] = None
    vector_index: Optional[VectorIndexResult] = None
    bm25_path_for_exc = bm25_paths["index_json"]
    vector_path_for_exc = vector_paths["index_json"]

    if bm25_path_for_exc.exists():
        try:
            bm25_index = load_bm25_index(bm25_path_for_exc)
        except (FileNotFoundError, ValueError):
            bm25_index = None
    if vector_path_for_exc.exists():
        try:
            vector_index = load_vector_index(vector_path_for_exc)
        except (FileNotFoundError, ValueError):
            vector_index = None

    # In hybrid/graph-lite mode, the router needs both indexes
    # to produce a non-trivial candidate set. If one is missing,
    # surface a clear error so the user knows to build the
    # missing index. In single-mode, the missing backend is
    # simply skipped.
    if mode in {"hybrid", "graph-lite"}:
        if bm25_index is None:
            raise FileNotFoundError(
                f"BM25 index not found: {bm25_path_for_exc}. Run `wiki build-bm25-index` first."
            )
        if vector_index is None:
            raise FileNotFoundError(
                f"Vector index not found: {vector_path_for_exc}. Run `wiki build-vector-index` first."
            )
    elif mode == "bm25" and bm25_index is None:
        raise FileNotFoundError(
            f"BM25 index not found: {bm25_path_for_exc}. Run `wiki build-bm25-index` first."
        )
    elif mode == "vector" and vector_index is None:
        raise FileNotFoundError(
            f"Vector index not found: {vector_path_for_exc}. Run `wiki build-vector-index` first."
        )

    return retrieve_hybrid_in_memory(
        query=query,
        mode=mode,
        limit=limit,
        source_types=source_types,
        resource_id=resource_id,
        include_text=include_text,
        bm25_index=bm25_index,
        vector_index=vector_index,
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
        explain=explain,
        data_dir=base,
    )


# =============================================================================
# In-memory entry point
# =============================================================================


def retrieve_hybrid_in_memory(
    *,
    query: str,
    bm25_index: Optional[BM25IndexResult] = None,
    vector_index: Optional[VectorIndexResult] = None,
    mode: str = DEFAULT_MODE,
    limit: int = 10,
    source_types: Optional[Iterable[str]] = None,
    resource_id: Optional[str] = None,
    include_text: bool = False,
    bm25_weight: float = DEFAULT_BM25_WEIGHT,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    explain: bool = False,
    data_dir: Path | None = None,
) -> list[RetrievalResult]:
    """Run a hybrid retrieval query in memory.

    The in-memory entry point used by tests and by callers that
    already have the BM25 and vector indexes in memory. Returns
    a list of :class:`RetrievalResult` objects in stable rank
    order.

    Parameters
    ----------
    query:
        The user query. Must be non-empty after stripping.
    bm25_index:
        Optional pre-loaded :class:`BM25IndexResult`. Required
        for ``bm25``, ``hybrid``, and ``graph-lite`` modes.
    vector_index:
        Optional pre-loaded :class:`VectorIndexResult`.
        Required for ``vector``, ``hybrid``, and ``graph-lite``
        modes.
    mode:
        One of ``bm25``, ``vector``, ``hybrid``, ``graph-lite``.
    limit:
        Maximum number of results. Hard-capped at ``MAX_LIMIT``
        (100).
    source_types:
        Optional iterable of source types to filter by.
    resource_id:
        Optional single resource id to filter by.
    include_text:
        If ``True``, populate the ``text_preview`` field with
        the chunk text.
    bm25_weight:
        Weight on the BM25 contribution.
    vector_weight:
        Weight on the vector contribution.
    explain:
        If ``True``, the ``explanation`` block includes
        per-factor details.
    data_dir:
        Optional override for the wiki data dir (used for
        ``--include-text`` lookups).

    Returns
    -------
    list[RetrievalResult]
        The ranked retrieval results in stable rank order.
    """
    if not query or not str(query).strip():
        raise ValueError("query is empty")
    if mode not in ALLOWED_MODES:
        raise ValueError(
            f"invalid mode: {mode!r} (allowed: {sorted(ALLOWED_MODES)})"
        )
    if float(bm25_weight) < 0.0:
        raise ValueError(f"bm25_weight must be >= 0.0 (got {bm25_weight})")
    if float(vector_weight) < 0.0:
        raise ValueError(f"vector_weight must be >= 0.0 (got {vector_weight})")
    if float(bm25_weight) + float(vector_weight) <= 0.0:
        raise ValueError(
            "bm25_weight + vector_weight must be > 0.0 "
            f"(got {bm25_weight} + {vector_weight})"
        )

    limit = max(1, min(int(limit), MAX_LIMIT))
    source_types_set = (
        {str(s).strip() for s in source_types if str(s).strip()}
        if source_types
        else None
    )
    base = Path(data_dir) if data_dir is not None else config.LLM_WIKI_DATA_DIR

    # 1. Fetch the BM25 and vector candidate sets.
    top_k = max(int(limit), int(limit) * int(HYBRID_FETCH_FACTOR))

    bm25_results = []
    vector_results = []
    if bm25_index is not None and mode in {"bm25", "hybrid", "graph-lite"}:
        bm25_results = search_bm25_in_memory(
            query=query,
            bm25_index=bm25_index,
            limit=top_k,
            source_types=source_types_set,
            resource_id=resource_id,
            include_text=include_text,
            data_dir=base,
        )
    if vector_index is not None and mode in {"vector", "hybrid", "graph-lite"}:
        vector_results = search_vector_in_memory(
            query=query,
            vector_index=vector_index,
            limit=top_k,
            source_types=source_types_set,
            resource_id=resource_id,
            include_text=include_text,
            data_dir=base,
        )

    # 2. Build the raw-score maps (keyed by chunk_id).
    bm25_raw: dict[str, float] = {str(r.chunk_id): float(r.score) for r in bm25_results}
    vector_raw: dict[str, float] = {str(r.chunk_id): float(r.score) for r in vector_results}

    # 3. Build the metadata map keyed by chunk_id. We merge the
    # metadata from both backends: if a chunk is in both
    # backends' top-K, we prefer the BM25 metadata (it is the
    # richer source: title, citation_label, resource_route,
    # matched_terms). Otherwise we use the single-backend
    # metadata. The ``text_preview`` is taken from the backend
    # that populated it; with ``include_text=False`` it is
    # always the truncated preview already in the index.
    bm25_by_cid: dict[str, Any] = {str(r.chunk_id): r for r in bm25_results}
    vector_by_cid: dict[str, Any] = {str(r.chunk_id): r for r in vector_results}
    chunk_ids: list[str] = sorted(set(bm25_raw) | set(vector_raw))

    bm25_max = max(bm25_raw.values(), default=0.0)
    vector_max = max(vector_raw.values(), default=0.0)

    # 4. Max-normalize the raw scores.
    bm25_norm = fusion.max_normalize(bm25_raw)
    vector_norm = fusion.max_normalize(vector_raw)

    # 5. Linear fusion. For single-mode, the missing backend
    # has zero contribution; for hybrid, both contribute.
    if mode == "bm25":
        fused = {
            cid: float(bm25_weight) * float(bm25_norm.get(cid, 0.0))
            for cid in bm25_raw
        }
    elif mode == "vector":
        fused = {
            cid: float(vector_weight) * float(vector_norm.get(cid, 0.0))
            for cid in vector_raw
        }
    else:
        fused = fusion.linear_fuse(
            bm25_norm,
            vector_norm,
            bm25_weight=float(bm25_weight),
            vector_weight=float(vector_weight),
        )

    # 6. Graph-lite boost (only in graph-lite mode).
    boost_map: dict[str, float] = {}
    boost_explanations: dict[str, dict[str, Any]] = {}
    if mode == "graph-lite":
        boost_map, boost_explanations = _build_graph_lite_boost(
            chunk_ids=chunk_ids,
            bm25_by_cid=bm25_by_cid,
            vector_by_cid=vector_by_cid,
            data_dir=base,
        )
        fused = fusion.apply_graph_lite_boost(
            fused, boost_map, max_boost=GRAPH_LITE_MAX_BOOST
        )

    # 7. Build the secondary tie-breaker map. The plan
    # specifies ``(-final, resource_id, chunk_id)`` so we need
    # the resource_id for each chunk.
    secondary_keys: dict[str, str] = {}
    for cid in chunk_ids:
        meta = bm25_by_cid.get(cid) or vector_by_cid.get(cid)
        if meta is not None:
            secondary_keys[cid] = str(getattr(meta, "resource_id", "") or "")

    # 8. Sort and truncate.
    sorted_pairs = fusion.sort_keys_deterministically(
        fused, secondary_keys=secondary_keys
    )
    top = fusion.topk(sorted_pairs, limit)

    # 9. Materialize the RetrievalResult list.
    results: list[RetrievalResult] = []
    for rank, (cid, final_score) in enumerate(top, start=1):
        meta_bm25 = bm25_by_cid.get(cid)
        meta_vector = vector_by_cid.get(cid)
        primary = meta_bm25 or meta_vector
        if primary is None:
            continue

        bm25_raw_score = float(bm25_raw.get(cid, 0.0))
        vector_raw_score = float(vector_raw.get(cid, 0.0))
        n_bm25 = float(bm25_norm.get(cid, 0.0))
        n_vector = float(vector_norm.get(cid, 0.0))
        boost = float(boost_map.get(cid, 0.0))

        component = ComponentScores(
            bm25=bm25_raw_score,
            vector=vector_raw_score,
            graph_boost=boost,
            normalized_bm25=n_bm25,
            normalized_vector=n_vector,
            final=float(final_score),
        )

        # Build the explanation block.
        weights_block = {
            "bm25": float(bm25_weight),
            "vector": float(vector_weight),
        }
        normalization_block = {
            "bm25_max": float(bm25_max),
            "vector_max": float(vector_max),
        }
        # When the mode is single-backend, the unused
        # backend's weight is still echoed in the weights
        # block (so the output is always populated), but the
        # corresponding normalization max is zero.
        if mode == "bm25":
            weights_block = {
                "bm25": float(bm25_weight),
                "vector": 0.0,
            }
            normalization_block = {
                "bm25_max": float(bm25_max),
                "vector_max": 0.0,
            }
        elif mode == "vector":
            weights_block = {
                "bm25": 0.0,
                "vector": float(vector_weight),
            }
            normalization_block = {
                "bm25_max": 0.0,
                "vector_max": float(vector_max),
            }

        if mode == "graph-lite":
            expl = boost_explanations.get(cid, {}) or {}
            explanation = Explanation(
                shared_topics=list(expl.get("shared_topics", [])),
                shared_concepts=list(expl.get("shared_concepts", [])),
                source_type_preference=bool(
                    expl.get("source_type_preference", False)
                ),
                resource_relationship_targets=list(
                    expl.get("resource_relationship_targets", [])
                ),
                weights=weights_block,
                normalization=normalization_block,
            )
        else:
            # Non-graph-lite modes: the explanation block
            # has the weights/normalization sub-blocks and
            # # empty per-factor lists, so the verbose
            # # ``--explain`` output is well-defined.
            explanation = Explanation(
                shared_topics=[],
                shared_concepts=[],
                source_type_preference=False,
                resource_relationship_targets=[],
                weights=weights_block,
                normalization=normalization_block,
            )

        # Use BM25 metadata preferentially for title, source_type,
        # citation_label, resource_route, source_ref. Fall back
        # to the vector metadata if the chunk is vector-only.
        meta = primary

        # Text preview: prefer the BM25 text_preview (it is the
        # same as the vector backend's preview when
        # ``include_text=False``; with ``include_text=True``
        # both backends read the chunk index on disk, so
        # either is fine).
        text_preview = str(getattr(meta, "text_preview", "") or "")

        # Build the matched_terms list: prefer the BM25
        # matched_terms (it is more precise than the vector
        # ``query_tokens`` list).
        matched_terms = list(getattr(meta, "matched_terms", []) or [])
        if not matched_terms and meta_vector is not None:
            matched_terms = list(
                getattr(meta_vector, "query_terms", []) or []
            )

        # Build the metadata block (small bag of source URL,
        # tags, topics) from either backend. The BM25 backend
        # carries ``metadata``; the vector backend carries
        # ``metadata`` too.
        meta_block = dict(getattr(meta, "metadata", {}) or {})

        result = RetrievalResult(
            rank=rank,
            score=float(final_score),
            chunk_id=str(cid),
            resource_id=str(getattr(meta, "resource_id", "") or ""),
            title=str(getattr(meta, "title", "") or ""),
            source_type=str(getattr(meta, "source_type", "") or ""),
            text_preview=text_preview,
            citation_label=str(getattr(meta, "citation_label", "") or ""),
            resource_route=str(getattr(meta, "resource_route", "") or ""),
            source_ref=dict(getattr(meta, "source_ref", {}) or {}),
            mode=str(mode),
            component_scores=component,
            matched_terms=matched_terms,
            explanation=explanation,
            metadata=meta_block,
        )
        results.append(result)

    return results


# =============================================================================
# Internal helpers
# =============================================================================


def _build_graph_lite_boost(
    *,
    chunk_ids: list[str],
    bm25_by_cid: Mapping[str, Any],
    vector_by_cid: Mapping[str, Any],
    data_dir: Path | None,
) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    """Build the per-chunk graph-lite boost and explanation maps.

    The function reads the on-disk knowledge graph exactly once
    via :func:`wiki.retrieval.graph_lite.build_boost_map`, then
    computes a small per-chunk explanation block so the
    ``--explain`` output can list the contributing factors.
    """
    # Build the resource -> {chunk_id} map. The router uses the
    # chunk_ids union (sorted) as the candidate set; the boost
    # is applied to those chunks. We derive the candidate
    # resource_ids from the BM25 and vector result lists.
    candidate_resource_ids: set[str] = set()
    candidate_source_types: set[str] = set()
    chunk_resource_id_to_chunk_ids: dict[str, set[str]] = {}
    for cid in chunk_ids:
        meta = bm25_by_cid.get(cid) or vector_by_cid.get(cid)
        if meta is None:
            continue
        rid = str(getattr(meta, "resource_id", "") or "")
        if not rid:
            continue
        candidate_resource_ids.add(rid)
        candidate_source_types.add(
            str(getattr(meta, "source_type", "") or "")
        )
        chunk_resource_id_to_chunk_ids.setdefault(rid, set()).add(cid)

    if not candidate_resource_ids:
        return {}, {}

    boost_map = graph_lite.build_boost_map(
        graph_path=graph_lite.graph_path_for(data_dir=data_dir),
        candidate_resource_ids=candidate_resource_ids,
        candidate_source_types=candidate_source_types,
        chunk_resource_id_to_chunk_ids=chunk_resource_id_to_chunk_ids,
    )

    # Build the per-chunk explanation block. The graph-lite
    # module already computes the boost value; we recompute
    # the per-factor details here so the ``--explain`` output
    # can list the contributing topics, concepts, and
    # relationship targets.
    explanations: dict[str, dict[str, Any]] = {}
    if not boost_map:
        return boost_map, explanations

    # Re-derive the per-chunk explanation from the graph.
    # We re-read the graph once; the build_boost_map call
    # above already read it but does not return per-factor
    # details. We read the bundle directly here to keep the
    # boost_map API simple.
    bundle = _read_graph_for_explanations(data_dir=data_dir)
    if not bundle:
        # Without the bundle we can still return the boost map
        # but with empty explanation blocks.
        for cid in chunk_ids:
            explanations[cid] = {
                "shared_topics": [],
                "shared_concepts": [],
                "source_type_preference": False,
                "resource_relationship_targets": [],
            }
        return boost_map, explanations

    edges = bundle.get("edges") or []
    if not isinstance(edges, list):
        return boost_map, explanations

    # Build the same resource -> topic / concept / relationship
    # maps locally, so we can produce per-chunk explanation
    # blocks. This is a second read of the same file; it is
    # not a graph traversal, and the total work is O(|E|).
    (
        resource_to_topics,
        resource_to_concepts,
        resource_to_relationship_targets,
        topic_to_resources,
        concept_to_resources,
    ) = _index_graph_edges(edges)

    # Map source_type per resource from the graph nodes.
    nodes = bundle.get("nodes") or []
    resource_to_source_type: dict[str, str] = {}
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if str(node.get("type", "")) != "resource":
                continue
            rid = graph_lite_node_id_to_resource_id(
                str(node.get("id", ""))
            )
            if not rid:
                continue
            source_type = str(
                (node.get("metadata") or {}).get("source_type", "")
            )
            if source_type:
                resource_to_source_type[rid] = source_type

    # Determine the dominant source type.
    dominant_source_type: str | None = None
    if len(candidate_source_types) == 1:
        dominant_source_type = next(iter(candidate_source_types))
    else:
        counts: Counter[str] = Counter()
        for rid in candidate_resource_ids:
            st = resource_to_source_type.get(rid)
            if st:
                counts[st] += 1
        if counts:
            dominant_source_type = counts.most_common(1)[0][0]

    for cid in chunk_ids:
        meta = bm25_by_cid.get(cid) or vector_by_cid.get(cid)
        if meta is None:
            continue
        rid = str(getattr(meta, "resource_id", "") or "")
        if not rid:
            explanations[cid] = _empty_graph_explanation()
            continue

        topics = resource_to_topics.get(rid, set())
        shared_topics: set[str] = set()
        if topics:
            for topic_slug in topics:
                other_resources = topic_to_resources.get(topic_slug, set())
                other_resources = other_resources - {rid}
                if other_resources & candidate_resource_ids:
                    shared_topics.add(topic_slug)

        concepts = resource_to_concepts.get(rid, set())
        shared_concepts: set[str] = set()
        if concepts:
            for concept_slug in concepts:
                other_resources = concept_to_resources.get(
                    concept_slug, set()
                )
                other_resources = other_resources - {rid}
                if other_resources & candidate_resource_ids:
                    shared_concepts.add(concept_slug)

        rel_targets = resource_to_relationship_targets.get(rid, set())
        in_candidate = sorted(rel_targets & candidate_resource_ids)

        # Source-type preference flag: only true when the
        # dominant source type is well-defined and the chunk's
        # resource matches.
        resource_source_type = resource_to_source_type.get(rid, "")
        source_type_preference = bool(
            dominant_source_type
            and resource_source_type == dominant_source_type
            and len(candidate_resource_ids) > 1
            and sum(
                1
                for other_rid in candidate_resource_ids
                if resource_to_source_type.get(other_rid)
                == dominant_source_type
            )
            > 1
        )

        explanations[cid] = {
            "shared_topics": sorted(shared_topics),
            "shared_concepts": sorted(shared_concepts),
            "source_type_preference": source_type_preference,
            "resource_relationship_targets": in_candidate,
        }

    return boost_map, explanations


def _empty_graph_explanation() -> dict[str, Any]:
    return {
        "shared_topics": [],
        "shared_concepts": [],
        "source_type_preference": False,
        "resource_relationship_targets": [],
    }


def _read_graph_for_explanations(
    *, data_dir: Path | None
) -> dict | None:
    """Read the on-disk knowledge graph bundle for explanations.

    This is a defensive read; if the bundle is missing we
    return ``None`` and the caller emits empty explanation
    blocks. The read happens at most once per retrieval call.
    """
    return graph_lite._read_graph_payload(
        graph_lite.graph_path_for(data_dir=data_dir)
    )


def _index_graph_edges(
    edges: Sequence[Mapping[str, Any]],
) -> tuple[
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
]:
    """Build the resource -> topic/concept/relationship maps.

    Mirrors the indexing logic in
    :func:`wiki.retrieval.graph_lite.build_boost_map` but
    returns the maps directly so the router can build
    per-chunk explanation blocks without re-parsing edges.
    """
    from wiki.graph.schema import (
        EDGE_TYPE_RESOURCE_HAS_TOPIC,
        EDGE_TYPE_RESOURCE_MENTIONS_CONCEPT,
        RESOURCE_RELATIONSHIP_EDGE_TYPES,
    )

    resource_to_topics: dict[str, set[str]] = {}
    resource_to_concepts: dict[str, set[str]] = {}
    resource_to_relationship_targets: dict[str, set[str]] = {}
    topic_to_resources: dict[str, set[str]] = {}
    concept_to_resources: dict[str, set[str]] = {}

    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        edge_type = str(edge.get("type", ""))
        source_id = str(edge.get("source", ""))
        target_id = str(edge.get("target", ""))
        if not source_id or not target_id:
            continue
        if edge_type == EDGE_TYPE_RESOURCE_HAS_TOPIC:
            rid = _strip_resource_prefix_local(source_id)
            topic_slug = _strip_topic_prefix_local(target_id)
            if not rid or not topic_slug:
                continue
            resource_to_topics.setdefault(rid, set()).add(topic_slug)
            topic_to_resources.setdefault(topic_slug, set()).add(rid)
        elif edge_type == EDGE_TYPE_RESOURCE_MENTIONS_CONCEPT:
            rid = _strip_resource_prefix_local(source_id)
            concept_slug = _strip_concept_prefix_local(target_id)
            if not rid or not concept_slug:
                continue
            resource_to_concepts.setdefault(rid, set()).add(concept_slug)
            concept_to_resources.setdefault(concept_slug, set()).add(rid)
        elif edge_type in RESOURCE_RELATIONSHIP_EDGE_TYPES:
            source_rid = _strip_resource_prefix_local(source_id)
            target_rid = _strip_resource_prefix_local(target_id)
            if not source_rid or not target_rid:
                continue
            resource_to_relationship_targets.setdefault(
                source_rid, set()
            ).add(target_rid)
            resource_to_relationship_targets.setdefault(
                target_rid, set()
            ).add(source_rid)
    return (
        resource_to_topics,
        resource_to_concepts,
        resource_to_relationship_targets,
        topic_to_resources,
        concept_to_resources,
    )


def graph_lite_node_id_to_resource_id(node_id: str) -> str:
    """Convert a graph resource node id back to the canonical record id.

    The graph builder stores resource node ids as
    ``resource:<record_id_with_colons_replaced>``; this helper
    reverses the transformation.
    """
    return _strip_resource_prefix_local(node_id)


def _strip_resource_prefix_local(node_id: str) -> str:
    """Strip the ``resource:`` prefix and re-introduce the colon."""
    prefix = "resource:"
    if not node_id.startswith(prefix):
        return ""
    suffix = node_id[len(prefix):]
    known_namespaces = (
        "pdf",
        "youtube",
        "webpage",
        "markdown",
        "medium_markdown",
        "local_video",
        "local_audio",
        "local_transcript",
    )
    for ns in known_namespaces:
        if suffix.startswith(f"{ns}_"):
            return f"{ns}:" + suffix[len(ns) + 1:]
    if "_" in suffix:
        head, tail = suffix.split("_", 1)
        return f"{head}:{tail}"
    return suffix


def _strip_topic_prefix_local(node_id: str) -> str:
    prefix = "topic:"
    if node_id.startswith(prefix):
        return node_id[len(prefix):]
    return ""


def _strip_concept_prefix_local(node_id: str) -> str:
    prefix = "concept:"
    if node_id.startswith(prefix):
        return node_id[len(prefix):]
    return ""


__all__ = [
    "retrieve_hybrid",
    "retrieve_hybrid_in_memory",
]
