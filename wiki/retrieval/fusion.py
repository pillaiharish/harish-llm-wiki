"""Pure deterministic score-fusion primitives (Prompt 30).

The functions in this module are pure: they have no project
imports and no I/O. They are exposed for unit testing on small
in-memory data without needing the BM25, vector, or graph
backends.

The module implements three primitives:

- :func:`max_normalize` — divides each score by the max score in
  the candidate set. If the max is zero, all normalized scores
  are zero. The result is deterministic for a given input.
- :func:`linear_fuse` — combines a normalized BM25 map and a
  normalized vector map into a single fused score map. The
  linear combination is
  ``bm25_weight * n_bm25 + vector_weight * n_vector``.
- :func:`apply_graph_lite_boost` — adds a small bounded
  graph-lite boost (per chunk) to the fused scores.

The fusion module never writes to disk, never imports
``wiki.search``, ``wiki.vector``, ``wiki.chunks``, or
``wiki.graph``. It depends only on the standard library.
"""

from __future__ import annotations

from typing import Iterable, Mapping


# =============================================================================
# Max-normalization
# =============================================================================


def max_normalize(scores: Mapping[str, float]) -> dict[str, float]:
    """Return ``{key: score / max}`` for a non-empty score map.

    Parameters
    ----------
    scores:
        A ``{key: raw_score}`` mapping. Keys are typically chunk
        ids; values are the raw backend scores (BM25 or vector
        cosine similarity, both always non-negative in the
        existing backends).

    Returns
    -------
    dict[str, float]
        ``{key: score / max}`` where ``max`` is the maximum
        raw score in the input. If the input is empty or every
        score is zero, the function returns ``{}`` (no
        candidates to normalize). The function never raises; an
        empty or zero-max input collapses to an empty result so
        the caller can treat it as a no-op.

    Determinism
    -----------
    The output preserves the iteration order of the input
    mapping. The result is fully deterministic for a given
    input.
    """
    if not scores:
        return {}
    items = list(scores.items())
    raw_max = max((float(v) for _, v in items), default=0.0)
    if raw_max <= 0.0:
        # No positive signal: every normalized score would be 0.
        # Return an empty mapping so callers can treat the
        # backend as "no contribution" without emitting a
        # meaningless flat 0.0 list.
        return {}
    return {str(k): float(v) / raw_max for k, v in items}


# =============================================================================
# Linear fusion
# =============================================================================


def linear_fuse(
    bm25_norm: Mapping[str, float],
    vector_norm: Mapping[str, float],
    *,
    bm25_weight: float,
    vector_weight: float,
) -> dict[str, float]:
    """Linearly combine normalized BM25 and vector scores.

    Parameters
    ----------
    bm25_norm:
        ``{chunk_id: normalized_bm25}``. From
        :func:`max_normalize` applied to the BM25 candidate set.
    vector_norm:
        ``{chunk_id: normalized_vector}``. From
        :func:`max_normalize` applied to the vector candidate
        set.
    bm25_weight:
        Weight on the normalized BM25 contribution. Must be a
        non-negative finite float.
    vector_weight:
        Weight on the normalized vector contribution. Must be a
        non-negative finite float.

    Returns
    -------
    dict[str, float]
        ``{chunk_id: bm25_weight * n_bm25 + vector_weight * n_vector}``
        for the union of keys in ``bm25_norm`` and
        ``vector_norm``. Chunks present in only one backend
        contribute zero from the other side.

    Raises
    ------
    ValueError
        If either weight is negative, or if the two weights sum
        to zero (a zero-weight fusion would collapse every score
        to zero and the router could not produce a meaningful
        ranking).

    Determinism
    -----------
    The output preserves the union of input keys in the
    following order: BM25 keys first (in their original
    iteration order), then any vector-only keys (in their
    original iteration order). The result is fully
    deterministic for a given input.
    """
    if float(bm25_weight) < 0.0:
        raise ValueError(f"bm25_weight must be >= 0.0 (got {bm25_weight})")
    if float(vector_weight) < 0.0:
        raise ValueError(f"vector_weight must be >= 0.0 (got {vector_weight})")
    if float(bm25_weight) + float(vector_weight) <= 0.0:
        raise ValueError(
            "bm25_weight + vector_weight must be > 0.0 "
            f"(got {bm25_weight} + {vector_weight})"
        )

    out: dict[str, float] = {}
    for cid, n_bm25 in bm25_norm.items():
        key = str(cid)
        n_vec = float(vector_norm.get(key, 0.0))
        out[key] = float(bm25_weight) * float(n_bm25) + float(vector_weight) * n_vec
    for cid, n_vec in vector_norm.items():
        key = str(cid)
        if key in out:
            continue  # already computed above
        n_bm25 = float(bm25_norm.get(key, 0.0))
        out[key] = float(bm25_weight) * n_bm25 + float(vector_weight) * float(n_vec)
    return out


# =============================================================================
# Graph-lite boost
# =============================================================================


def apply_graph_lite_boost(
    fused: Mapping[str, float],
    boost_map: Mapping[str, float],
    *,
    max_boost: float,
) -> dict[str, float]:
    """Add the per-chunk graph-lite boost to a fused-score map.

    The boost is added per chunk. The result is clipped at
    ``max_boost`` so the total contribution cannot exceed the
    configured cap (default ``GRAPH_LITE_MAX_BOOST = 0.10`` in
    :mod:`wiki.retrieval.schema`).

    Parameters
    ----------
    fused:
        ``{chunk_id: fused_score}``. From :func:`linear_fuse`.
    boost_map:
        ``{chunk_id: boost_value}``. From
        :func:`wiki.retrieval.graph_lite.build_boost_map`. The
        caller is responsible for ensuring each value is
        non-negative and not greater than ``max_boost``; this
        function is defensive and clamps anyway.
    max_boost:
        The maximum total boost any single chunk can receive.

    Returns
    -------
    dict[str, float]
        ``{chunk_id: fused + clamp(boost, 0, max_boost)}``.
        Chunks not in ``boost_map`` keep their fused score
        unchanged. Chunks in ``boost_map`` but not in ``fused``
        are ignored (the boost is only applied to candidates
        that survived the BM25/vector fusion pass).

    Determinism
    -----------
    The output preserves the iteration order of ``fused``. The
    result is fully deterministic for a given input.
    """
    if max_boost < 0.0:
        raise ValueError(f"max_boost must be >= 0.0 (got {max_boost})")
    out: dict[str, float] = {}
    for cid, score in fused.items():
        key = str(cid)
        raw_boost = float(boost_map.get(key, 0.0))
        if raw_boost < 0.0:
            raw_boost = 0.0
        elif raw_boost > float(max_boost):
            raw_boost = float(max_boost)
        out[key] = float(score) + raw_boost
    return out


# =============================================================================
# Public helpers
# =============================================================================


def sort_keys_deterministically(
    scores: Mapping[str, float],
    *,
    secondary_keys: Mapping[str, str] | None = None,
) -> list[tuple[str, float]]:
    """Sort ``(key, score)`` pairs by ``(-score, key)`` for output.

    Parameters
    ----------
    scores:
        ``{key: score}`` mapping. Scores are typically the final
        ``RetrievalResult.component_scores.final`` value.
    secondary_keys:
        Optional ``{key: tie_breaker}`` mapping. When two
        scores are equal, the secondary tie-breaker is used. If
        not provided, the primary ``key`` is used. The
        ``secondary_keys`` values are typically the
        ``resource_id`` of the chunk, and ``key`` is the
        ``chunk_id``, so the full tie-break order is
        ``(-final, resource_id, chunk_id)``.

    Returns
    -------
    list[tuple[str, float]]
        The sorted ``(key, score)`` pairs.
    """
    if secondary_keys is None:
        secondary_keys = {}

    def sort_key(item: tuple[str, float]) -> tuple:
        key, score = item
        secondary = str(secondary_keys.get(key, ""))
        return (-float(score), secondary, str(key))

    return sorted(scores.items(), key=sort_key)


def topk(
    sorted_pairs: Iterable[tuple[str, float]],
    limit: int,
) -> list[tuple[str, float]]:
    """Truncate a sorted pair list to the top ``limit`` items.

    Defensive: if ``limit`` is non-positive, returns an empty
    list.
    """
    if int(limit) <= 0:
        return []
    out: list[tuple[str, float]] = []
    for index, pair in enumerate(sorted_pairs):
        if index >= int(limit):
            break
        out.append((str(pair[0]), float(pair[1])))
    return out


__all__ = [
    "apply_graph_lite_boost",
    "linear_fuse",
    "max_normalize",
    "sort_keys_deterministically",
    "topk",
]
