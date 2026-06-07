"""Public schema for the retrieval evaluation suite (Prompt 31).

This module defines the deterministic on-the-wire shape of an
eval case, an eval result, and a single per-mode/per-k metric
record. The dataclasses are frozen so the result list is
immutable and the ``to_dict()`` projection is the contract for
the JSON CLI output.

The schema is intentionally aligned with the hybrid retrieval
result schema (see :mod:`wiki.retrieval.schema`) so the eval
suite can be applied uniformly across the existing
``bm25`` / ``vector`` / ``hybrid`` / ``graph-lite`` modes.

The schema constants are exported at module level:

- :data:`EVAL_SCHEMA_VERSION` — the schema version string.
- :data:`DEFAULT_K_VALUES` — the default ``k`` values used by
  the CLI when the caller does not specify any.
- :data:`DEFAULT_MODES` — the default modes used by the CLI
  when the caller does not specify any.

The dataclasses are:

- :class:`EvalCase` — one query with expected items, modes, and
  ``k`` values.
- :class:`EvalMetric` — per-mode/per-k metric record.
- :class:`EvalCaseResult` — full per-case evaluation result.
- :class:`EvalReport` — the top-level report envelope.

The module has no project imports. The dataclasses are plain
frozen Python types that can be unit-tested without any of the
BM25, vector, chunk, or graph modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


# =============================================================================
# Constants
# =============================================================================


#: Schema version string for the retrieval evaluation suite.
#: Bumped only when the public JSON shape changes in a breaking
#: way. The CLI emits this string as the ``schema_version`` field
#: of the JSON output.
EVAL_SCHEMA_VERSION: str = "retrieval_eval_v1"

#: Default ``k`` values used by the CLI when the caller does
#: not specify any. The list is sorted in ascending order and
#: contains only positive integers. The largest default ``k``
#: is intentionally small (5) so the eval report is cheap to
#: run against the small fixture dataset.
DEFAULT_K_VALUES: tuple[int, ...] = (1, 3, 5)

#: Default retrieval modes used by the CLI when the caller
#: does not specify any. The list is sorted in stable order.
DEFAULT_MODES: tuple[str, ...] = ("bm25", "vector", "hybrid", "graph-lite")

#: Hard cap on the number of ``k`` values per eval case. The
#: CLI and the loader reject ``k_values`` lists longer than
#: this.
MAX_K_VALUES: int = 16

#: Hard cap on the ``k`` integer itself. The CLI and the
#: loader reject ``k`` values larger than this.
MAX_K: int = 100

#: Hard cap on the number of expected items (resource ids,
#: chunk ids, or terms) per eval case. The CLI and the loader
#: reject lists longer than this.
MAX_EXPECTED_ITEMS: int = 256


# =============================================================================
# Eval case
# =============================================================================


@dataclass(frozen=True)
class EvalCase:
    """A single deterministic retrieval evaluation case.

    The case binds a query to its expectations and the modes
    and ``k`` values that the eval runner should evaluate. The
    expected lists are *all optional* but at least one of them
    must be non-empty for the case to be valid — otherwise
    every metric would be trivially zero.

    The ``id`` field is the unique case identifier; the
    loader rejects duplicate ids.

    Fields
    ------
    id:
        Unique case id. Must be non-empty.
    query:
        The user query. Must be non-empty.
    expected_resource_ids:
        List of expected resource ids. Matched against
        ``RetrievalResult.resource_id``.
    expected_chunk_ids:
        List of expected chunk ids. Matched against
        ``RetrievalResult.chunk_id``. Takes priority over
        ``expected_resource_ids`` when both are present.
    expected_terms:
        List of expected lexical terms. Matched case-insensitive
        against the union of ``RetrievalResult.matched_terms``
        and the ``RetrievalResult.text_preview``. Used to
        compute the ``expected_term_coverage`` metric.
    modes:
        List of retrieval modes to evaluate. Must be a subset
        of :data:`wiki.retrieval.schema.ALLOWED_MODES`.
    k_values:
        List of positive integer ``k`` values to evaluate.
    notes:
        Free-form notes for humans. Defaults to ``""``.
    """

    id: str
    query: str
    expected_resource_ids: list = field(default_factory=list)
    expected_chunk_ids: list = field(default_factory=list)
    expected_terms: list = field(default_factory=list)
    modes: list = field(default_factory=list)
    k_values: list = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Project to a dict in stable field order."""
        return {
            "id": self.id,
            "query": self.query,
            "expected_resource_ids": list(self.expected_resource_ids),
            "expected_chunk_ids": list(self.expected_chunk_ids),
            "expected_terms": list(self.expected_terms),
            "modes": list(self.modes),
            "k_values": list(self.k_values),
            "notes": self.notes,
        }


# =============================================================================
# Per-mode/per-k metric
# =============================================================================


@dataclass(frozen=True)
class EvalMetric:
    """A single per-mode/per-k metric record.

    Fields
    ------
    mode:
        The retrieval mode this metric was evaluated on.
    k:
        The ``k`` value this metric was evaluated at.
    recall:
        ``recall@k``.
    precision:
        ``precision@k``.
    hit:
        ``hit@k`` (``0.0`` or ``1.0``).
    mrr:
        ``MRR`` for the top-``k`` ranking.
    expected_term_coverage:
        ``expected_term_coverage`` for the top-``k`` ranking.
        ``0.0`` when ``expected_terms`` is empty.
    result_count:
        The number of retrieval results considered (i.e. the
        number of items in the top-``k`` list, which may be
        smaller than ``k`` when the underlying retriever
        returns fewer items).
    matched_count:
        The number of expected items that appear in the top
        ``k`` results.
    first_match_rank:
        The 1-based rank of the first matched expected item, or
        ``0`` when no expected item appears in the top ``k``.
    """

    mode: str
    k: int
    recall: float
    precision: float
    hit: float
    mrr: float
    expected_term_coverage: float
    result_count: int
    matched_count: int
    first_match_rank: int

    def to_dict(self) -> dict[str, Any]:
        """Project to a dict in stable field order."""
        return {
            "mode": self.mode,
            "k": self.k,
            "recall": self.recall,
            "precision": self.precision,
            "hit": self.hit,
            "mrr": self.mrr,
            "expected_term_coverage": self.expected_term_coverage,
            "result_count": self.result_count,
            "matched_count": self.matched_count,
            "first_match_rank": self.first_match_rank,
        }


# =============================================================================
# Per-case result
# =============================================================================


@dataclass(frozen=True)
class EvalCaseResult:
    """The full per-case evaluation result.

    Fields
    ------
    case_id:
        The :attr:`EvalCase.id` of the case that produced this
        result.
    query:
        The case query.
    metrics:
        A list of :class:`EvalMetric` records, one per
        ``(mode, k)`` pair. The list is ordered by
        ``(mode, k)`` so the output is deterministic.
    failure:
        ``None`` when the case ran successfully; otherwise a
        short failure message string.
    """

    case_id: str
    query: str
    metrics: list = field(default_factory=list)
    failure: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Project to a dict in stable field order."""
        return {
            "case_id": self.case_id,
            "query": self.query,
            "metrics": [m.to_dict() for m in self.metrics],
            "failure": self.failure,
        }


# =============================================================================
# Report envelope
# =============================================================================


@dataclass(frozen=True)
class EvalReport:
    """The top-level evaluation report.

    Fields
    ------
    schema_version:
        The :data:`EVAL_SCHEMA_VERSION` string.
    total_cases:
        Total number of cases that were evaluated.
    modes:
        The distinct list of modes that were evaluated.
    k_values:
        The distinct list of ``k`` values that were evaluated.
    aggregate_metrics:
        A dict of aggregated metrics keyed by ``mode`` then
        ``k``. Each value is a dict with the same keys as
        :class:`EvalMetric` (except ``mode`` and ``k``).
        Aggregate is the unweighted mean over all successful
        cases for the given ``(mode, k)`` pair.
    case_results:
        The list of :class:`EvalCaseResult` records in the
        stable order the cases were passed in.
    failures:
        The list of :class:`EvalCaseResult` records with a
        non-empty :attr:`EvalCaseResult.failure` field, in the
        same stable order as :attr:`case_results`.
    """

    schema_version: str
    total_cases: int
    modes: list
    k_values: list
    aggregate_metrics: dict
    case_results: list
    failures: list

    def to_dict(self) -> dict[str, Any]:
        """Project to a dict in stable field order."""
        return {
            "schema_version": self.schema_version,
            "total_cases": self.total_cases,
            "modes": list(self.modes),
            "k_values": list(self.k_values),
            "aggregate_metrics": _sort_aggregate(self.aggregate_metrics),
            "case_results": [c.to_dict() for c in self.case_results],
            "failures": [c.to_dict() for c in self.failures],
        }


# =============================================================================
# Helpers
# =============================================================================


def _sort_aggregate(agg: Mapping[str, Mapping[str, Mapping[str, float]]]) -> dict:
    """Sort the aggregate-metrics dict in stable field order.

    Top level: ``mode`` ascending.
    Second level: ``k`` ascending.
    Third level: keys from :class:`EvalMetric.to_dict()` minus
    ``mode`` and ``k``.
    """
    out: dict[str, Any] = {}
    for mode in sorted(agg):
        inner: dict[str, Any] = {}
        for k in sorted(agg[mode], key=lambda v: int(v)):
            entry = agg[mode][k]
            inner[str(k)] = {
                "recall": float(entry.get("recall", 0.0)),
                "precision": float(entry.get("precision", 0.0)),
                "hit": float(entry.get("hit", 0.0)),
                "mrr": float(entry.get("mrr", 0.0)),
                "expected_term_coverage": float(
                    entry.get("expected_term_coverage", 0.0)
                ),
                "case_count": int(entry.get("case_count", 0)),
            }
        out[str(mode)] = inner
    return out


def _ensure_sequences(case: EvalCase) -> tuple[list[str], list[str], list[str], list[str], list[int]]:
    """Return the five list fields as plain lists, in stable order."""
    resource_ids = sorted({str(x) for x in case.expected_resource_ids if str(x)})
    chunk_ids = sorted({str(x) for x in case.expected_chunk_ids if str(x)})
    terms = sorted({str(x) for x in case.expected_terms if str(x)})
    modes = sorted({str(x) for x in case.modes if str(x)})
    k_values = sorted({int(x) for x in case.k_values if int(x) > 0})
    return resource_ids, chunk_ids, terms, modes, k_values


# Type alias used by the runner.
MetricKey = tuple[str, int]


__all__ = [
    "DEFAULT_K_VALUES",
    "DEFAULT_MODES",
    "EVAL_SCHEMA_VERSION",
    "EvalCase",
    "EvalCaseResult",
    "EvalMetric",
    "EvalReport",
    "MAX_EXPECTED_ITEMS",
    "MAX_K",
    "MAX_K_VALUES",
]


# Avoid an "unused import" linter complaint for Mapping and
# Sequence — they are part of the public type contract.
_ = (Mapping, Sequence)
