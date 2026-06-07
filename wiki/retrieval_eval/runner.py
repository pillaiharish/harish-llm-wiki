"""Deterministic eval runner for the retrieval evaluation suite (Prompt 31).

The runner wires the eval-case schema to the existing hybrid
retrieval API (:func:`wiki.retrieval.retrieve_hybrid` and
:func:`wiki.retrieval.retrieve_hybrid_in_memory`). It does
**not** reimplement retrieval scoring; it simply calls the
existing API and feeds the results to
:func:`wiki.retrieval_eval.metrics.compute_metric`.

The runner is **read-only**: it never writes to the data
dir, never modifies the BM25, vector, chunk, or graph
backends, and it makes no LLM calls of any kind. It is
safe to use from tests and from the CLI.

The runner supports two entry points:

- :func:`run_eval` — the on-disk entry point used by the
  CLI. Loads the BM25 and vector indexes from the data
  dir and delegates to :func:`run_eval_in_memory`.
- :func:`run_eval_in_memory` — the in-memory entry point
  used by tests and by callers that already have the
  indexes in memory.

Both functions return an :class:`wiki.retrieval_eval.schema.EvalReport`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from wiki.config import config
from wiki.retrieval import (
    ALLOWED_MODES,
    DEFAULT_MODE,
    retrieve_hybrid,
    retrieve_hybrid_in_memory,
)
from wiki.retrieval.schema import RetrievalResult
from wiki.search import BM25IndexResult
from wiki.vector import VectorIndexResult
from wiki.retrieval_eval.metrics import aggregate_metrics, compute_metric
from wiki.retrieval_eval.schema import (
    DEFAULT_K_VALUES,
    DEFAULT_MODES,
    EVAL_SCHEMA_VERSION,
    EvalCase,
    EvalCaseResult,
    EvalMetric,
    EvalReport,
)


# =============================================================================
# On-disk entry point
# =============================================================================


def run_eval(
    cases: Sequence[EvalCase],
    *,
    mode_filter: Optional[str] = None,
    k_filter: Optional[int] = None,
    data_dir: Path | None = None,
    bm25_weight: float = 0.55,
    vector_weight: float = 0.45,
) -> EvalReport:
    """Run the eval cases against the on-disk indexes.

    Parameters
    ----------
    cases:
        The eval cases to run.
    mode_filter:
        Optional single mode to evaluate. When provided, the
        runner restricts each case to this mode (and ignores
        the case's own ``modes`` list). The value must be in
        :data:`wiki.retrieval.schema.ALLOWED_MODES`.
    k_filter:
        Optional single ``k`` value to evaluate. When
        provided, the runner restricts each case to this ``k``
        (and ignores the case's own ``k_values`` list). The
        value must be a positive integer.
    data_dir:
        Optional override for the wiki data dir. Defaults to
        :data:`wiki.config.config.LLM_WIKI_DATA_DIR`.
    bm25_weight:
        BM25 weight for hybrid/graph-lite modes.
    vector_weight:
        Vector weight for hybrid/graph-lite modes.

    Returns
    -------
    EvalReport
        The aggregated report.
    """
    if mode_filter is not None and mode_filter not in ALLOWED_MODES:
        raise ValueError(
            f"invalid mode_filter: {mode_filter!r} "
            f"(allowed: {sorted(ALLOWED_MODES)})"
        )
    if k_filter is not None and int(k_filter) < 1:
        raise ValueError(f"k_filter must be >= 1 (got {k_filter})")

    base = Path(data_dir) if data_dir is not None else config.LLM_WIKI_DATA_DIR

    # Load the indexes from disk. We do this exactly once and
    # then call the in-memory eval for every case.
    from wiki.search import load_bm25_index
    from wiki.search.export import bm25_output_paths
    from wiki.vector import load_vector_index
    from wiki.vector.export import vector_output_paths

    bm25_path = (
        bm25_output_paths(data_dir=base)["index_json"]
    )
    vector_path = (
        vector_output_paths(data_dir=base)["index_json"]
    )

    bm25_index = None
    if bm25_path.exists():
        try:
            bm25_index = load_bm25_index(bm25_path)
        except (FileNotFoundError, ValueError):
            bm25_index = None

    vector_index = None
    if vector_path.exists():
        try:
            vector_index = load_vector_index(vector_path)
        except (FileNotFoundError, ValueError):
            vector_index = None

    return run_eval_in_memory(
        cases,
        mode_filter=mode_filter,
        k_filter=k_filter,
        bm25_index=bm25_index,
        vector_index=vector_index,
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
        data_dir=base,
    )


# =============================================================================
# In-memory entry point
# =============================================================================


def run_eval_in_memory(
    cases: Sequence[EvalCase],
    *,
    mode_filter: Optional[str] = None,
    k_filter: Optional[int] = None,
    bm25_index: Optional[BM25IndexResult] = None,
    vector_index: Optional[VectorIndexResult] = None,
    bm25_weight: float = 0.55,
    vector_weight: float = 0.45,
    data_dir: Path | None = None,
) -> EvalReport:
    """Run the eval cases against the in-memory indexes.

    Parameters
    ----------
    cases:
        The eval cases to run.
    mode_filter:
        Optional single mode to evaluate. When provided, the
        runner restricts each case to this mode (and ignores
        the case's own ``modes`` list).
    k_filter:
        Optional single ``k`` value to evaluate. When
        provided, the runner restricts each case to this ``k``
        (and ignores the case's own ``k_values`` list).
    bm25_index:
        Optional pre-loaded :class:`BM25IndexResult`. Required
        for ``bm25``, ``hybrid``, and ``graph-lite`` modes.
    vector_index:
        Optional pre-loaded :class:`VectorIndexResult`.
        Required for ``vector``, ``hybrid``, and ``graph-lite``
        modes.
    bm25_weight:
        BM25 weight for hybrid/graph-lite modes.
    vector_weight:
        Vector weight for hybrid/graph-lite modes.
    data_dir:
        Optional override for the wiki data dir (used for
        ``--include-text`` lookups).

    Returns
    -------
    EvalReport
        The aggregated report.

    Notes
    -----
    When the underlying index for a mode is missing, the
    runner records the case as a failure with a clear
    message and continues. This matches the on-disk entry
    point's behavior of raising a :class:`FileNotFoundError`
    on a missing index — but the eval runner needs to
    continue so a missing index in one mode does not
    block the rest of the eval.
    """
    if mode_filter is not None and mode_filter not in ALLOWED_MODES:
        raise ValueError(
            f"invalid mode_filter: {mode_filter!r} "
            f"(allowed: {sorted(ALLOWED_MODES)})"
        )
    if k_filter is not None and int(k_filter) < 1:
        raise ValueError(f"k_filter must be >= 1 (got {k_filter})")

    all_metrics: list[EvalMetric] = []
    case_results: list[EvalCaseResult] = []
    failures: list[EvalCaseResult] = []
    modes_set: set[str] = set()
    k_set: set[int] = set()

    for case in cases:
        modes_to_run = [mode_filter] if mode_filter is not None else list(case.modes)
        k_values_to_run = [int(k_filter)] if k_filter is not None else list(case.k_values)

        case_metrics: list[EvalMetric] = []
        case_failure: str | None = None

        for mode in modes_to_run:
            if mode in {"bm25", "hybrid", "graph-lite"} and bm25_index is None:
                case_failure = f"BM25 index missing for mode={mode!r}"
                break
            if mode in {"vector", "hybrid", "graph-lite"} and vector_index is None:
                case_failure = f"Vector index missing for mode={mode!r}"
                break

            try:
                results: list[RetrievalResult] = retrieve_hybrid_in_memory(
                    query=case.query,
                    bm25_index=bm25_index,
                    vector_index=vector_index,
                    mode=mode,
                    limit=max(k_values_to_run) if k_values_to_run else 5,
                    bm25_weight=bm25_weight,
                    vector_weight=vector_weight,
                    data_dir=data_dir,
                )
            except FileNotFoundError as exc:
                case_failure = f"index missing for mode={mode!r}: {exc}"
                break
            except ValueError as exc:
                case_failure = f"retrieval error for mode={mode!r}: {exc}"
                break

            for k in k_values_to_run:
                metric = compute_metric(
                    results=results,
                    mode=mode,
                    k=int(k),
                    expected_resource_ids=case.expected_resource_ids,
                    expected_chunk_ids=case.expected_chunk_ids,
                    expected_terms=case.expected_terms,
                )
                case_metrics.append(metric)
                modes_set.add(metric.mode)
                k_set.add(int(metric.k))

        all_metrics.extend(case_metrics)
        result = EvalCaseResult(
            case_id=case.id,
            query=case.query,
            metrics=case_metrics,
            failure=case_failure,
        )
        case_results.append(result)
        if case_failure is not None:
            failures.append(result)

    aggregate = aggregate_metrics(all_metrics)

    return EvalReport(
        schema_version=EVAL_SCHEMA_VERSION,
        total_cases=len(list(cases)),
        modes=sorted(modes_set),
        k_values=sorted(int(k) for k in k_set),
        aggregate_metrics=aggregate,
        case_results=case_results,
        failures=failures,
    )


__all__ = [
    "run_eval",
    "run_eval_in_memory",
]


# Silence linter complaints about unused imports — these
# imports are part of the public type contract.
_ = (Any, Iterable, DEFAULT_MODE, DEFAULT_K_VALUES, DEFAULT_MODES)
