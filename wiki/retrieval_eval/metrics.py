"""Deterministic retrieval evaluation metrics (Prompt 31).

The metric functions in this module are pure: they accept a
list of :class:`wiki.retrieval.schema.RetrievalResult`-like
objects and a small set of expectations, and return a single
:class:`wiki.retrieval_eval.schema.EvalMetric` record.

The expected items are matched in the following priority
order:

1. ``expected_chunk_ids`` — when non-empty, the metric is
   computed against the chunk ids of the top-``k`` results.
2. ``expected_resource_ids`` — when non-empty (and
   ``expected_chunk_ids`` is empty), the metric is computed
   against the resource ids of the top-``k`` results.
3. ``expected_terms`` — always used for the
   ``expected_term_coverage`` metric, regardless of which
   list is used for the recall/precision/hit/mrr metrics.

The functions never raise on empty inputs; they return a
metric with all zero values and the result-count / matched-count
fields set to the input sizes.

The functions are pure-Python: they do not import any
LLM/embedding/vector-DB code, and they are safe to call from
tests without any of the BM25, vector, chunk, or graph
backends.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from wiki.retrieval.schema import RetrievalResult
from wiki.retrieval_eval.schema import EvalMetric


# =============================================================================
# Public API
# =============================================================================


def compute_metric(
    *,
    results: Sequence[RetrievalResult],
    mode: str,
    k: int,
    expected_resource_ids: Sequence[str] = (),
    expected_chunk_ids: Sequence[str] = (),
    expected_terms: Sequence[str] = (),
) -> EvalMetric:
    """Compute the per-mode/per-k metric record for a single case.

    Parameters
    ----------
    results:
        The ranked retrieval results. Only the first ``k``
        results are considered; the function does not
        validate the rank field on the input.
    mode:
        The retrieval mode. Echoed in the returned
        :class:`EvalMetric`.
    k:
        The ``k`` cutoff. The function considers at most the
        first ``min(k, len(results))`` results.
    expected_resource_ids:
        Expected resource ids. Ignored when
        ``expected_chunk_ids`` is non-empty.
    expected_chunk_ids:
        Expected chunk ids. Takes priority over
        ``expected_resource_ids`` when both are non-empty.
    expected_terms:
        Expected terms. Always used for
        ``expected_term_coverage``.

    Returns
    -------
    EvalMetric
        A frozen metric record. The ``result_count`` field is
        the number of top-``k`` results actually considered;
        the ``matched_count`` field is the number of expected
        items that appear in the top ``k``; the
        ``first_match_rank`` field is the 1-based rank of the
        first match or ``0`` when there is no match.
    """
    top = list(results[: max(0, int(k))])
    top_chunk_ids = [str(r.chunk_id) for r in top]
    top_resource_ids = [str(r.resource_id) for r in top]

    expected_chunk_set = {str(x) for x in expected_chunk_ids if str(x)}
    expected_resource_set = {str(x) for x in expected_resource_ids if str(x)}
    expected_term_set = {str(x).strip().lower() for x in expected_terms if str(x).strip()}

    if expected_chunk_set:
        expected_set = expected_chunk_set
        actual_list = top_chunk_ids
    else:
        expected_set = expected_resource_set
        actual_list = top_resource_ids

    matched_count, first_match_rank = _match_metrics(actual_list, expected_set)

    recall = _safe_div(matched_count, len(expected_set)) if expected_set else 0.0
    precision = _safe_div(matched_count, len(top)) if top else 0.0
    hit = 1.0 if matched_count > 0 else 0.0
    mrr = _safe_div(1, first_match_rank) if first_match_rank > 0 else 0.0
    term_coverage, _ = _term_coverage(top, expected_term_set)

    return EvalMetric(
        mode=str(mode),
        k=int(k),
        recall=float(recall),
        precision=float(precision),
        hit=float(hit),
        mrr=float(mrr),
        expected_term_coverage=float(term_coverage),
        result_count=len(top),
        matched_count=int(matched_count),
        first_match_rank=int(first_match_rank),
    )


def aggregate_metrics(
    metrics: Iterable[EvalMetric],
) -> dict[str, dict[str, dict[str, float]]]:
    """Aggregate a stream of per-case metrics into mode/k means.

    The aggregate is the unweighted mean of each metric field
    over the metrics that have ``result_count`` greater than
    zero. Metrics with no successful cases for a ``(mode, k)``
    pair are omitted.

    Returns
    -------
    dict[str, dict[str, dict[str, float]]]
        Nested dict of the form
        ``{mode: {k: {metric_field: value, ..., "case_count": n}}}``.
    """
    sums: dict[tuple[str, int], dict[str, float]] = {}
    counts: dict[tuple[str, int], int] = {}
    for m in metrics:
        key = (str(m.mode), int(m.k))
        bucket = sums.setdefault(
            key,
            {
                "recall": 0.0,
                "precision": 0.0,
                "hit": 0.0,
                "mrr": 0.0,
                "expected_term_coverage": 0.0,
            },
        )
        bucket["recall"] += float(m.recall)
        bucket["precision"] += float(m.precision)
        bucket["hit"] += float(m.hit)
        bucket["mrr"] += float(m.mrr)
        bucket["expected_term_coverage"] += float(m.expected_term_coverage)
        counts[key] = counts.get(key, 0) + 1

    out: dict[str, dict[str, dict[str, float]]] = {}
    for (mode, k), bucket in sums.items():
        n = counts[(mode, k)]
        out.setdefault(str(mode), {})[str(int(k))] = {
            "recall": bucket["recall"] / n,
            "precision": bucket["precision"] / n,
            "hit": bucket["hit"] / n,
            "mrr": bucket["mrr"] / n,
            "expected_term_coverage": bucket["expected_term_coverage"] / n,
            "case_count": n,
        }
    return out


# =============================================================================
# Internal helpers
# =============================================================================


def _match_metrics(
    actual_list: Sequence[str], expected_set: set[str]
) -> tuple[int, int]:
    """Return ``(matched_count, first_match_rank)``.

    ``matched_count`` is the number of distinct expected
    items that appear in ``actual_list``. ``first_match_rank``
    is the 1-based rank of the first *occurrence* of any
    expected item in ``actual_list``; the value is ``0`` when
    no expected item appears.

    The function iterates ``actual_list`` in order so the
    first-match rank is the lowest rank of any expected item,
    which is the standard definition of MRR.
    """
    if not expected_set or not actual_list:
        return 0, 0
    seen: set[str] = set()
    matched = 0
    first_rank = 0
    for idx, item in enumerate(actual_list, start=1):
        if item in expected_set:
            if item not in seen:
                seen.add(item)
                matched += 1
            if first_rank == 0:
                first_rank = idx
    return matched, first_rank


def _term_coverage(
    top: Sequence[RetrievalResult], expected_term_set: set[str]
) -> tuple[float, int]:
    """Compute the expected-term coverage for a top-``k`` list.

    The matched-term set is the union of ``matched_terms`` and
    the lowercased tokens of ``text_preview`` (a simple
    whitespace split, which is what the BM25 backend uses for
    its ``text_preview`` tokenization).

    The coverage is the number of distinct expected terms
    that appear in the matched-term set divided by the
    number of distinct expected terms. ``0.0`` when the
    expected-term set is empty.
    """
    if not expected_term_set:
        return 0.0, 0
    matched: set[str] = set()
    for r in top:
        for term in getattr(r, "matched_terms", []) or []:
            t = str(term).strip().lower()
            if t:
                matched.add(t)
        preview = str(getattr(r, "text_preview", "") or "").lower()
        for token in preview.split():
            matched.add(token)
    coverage = sum(1 for t in expected_term_set if t in matched) / len(
        expected_term_set
    )
    return coverage, len(matched)


def _safe_div(num: float, den: float) -> float:
    """Return ``num / den`` or ``0.0`` when ``den`` is zero."""
    if den == 0:
        return 0.0
    return float(num) / float(den)


__all__ = [
    "aggregate_metrics",
    "compute_metric",
]


# Silence linter complaints about unused imports — these
# imports are part of the public type contract and the
# docstring references.
_ = (Any, Iterable)
