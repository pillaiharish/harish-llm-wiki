"""Deterministic retrieval evaluation suite (Prompt 31).

The :mod:`wiki.retrieval_eval` package is a thin evaluation
layer around the existing hybrid retrieval API (Prompt 30).
It does **not** modify the BM25, vector, chunk, or graph
backends; it loads a small, versioned set of eval cases and
runs them against the existing retrieval API to produce
deterministic aggregate metrics.

The package is pure-Python and deterministic: same eval
cases + same indexes + same retrieval API = same metrics. It
does not call any LLM, does not import model embeddings, and
does not import any vector DB.

Public API
----------

- :func:`wiki.retrieval_eval.runner.run_eval` — on-disk
  entry point. Loads the BM25 and vector indexes from the
  data dir and runs the cases.
- :func:`wiki.retrieval_eval.runner.run_eval_in_memory` —
  in-memory entry point used by tests and by callers that
  already have the indexes in memory.
- :func:`wiki.retrieval_eval.fixtures.load_cases` — load
  and validate the checked-in fixture cases.
- :func:`wiki.retrieval_eval.fixtures.parse_cases` — parse
  and validate an in-memory list of case dicts.
- :func:`wiki.retrieval_eval.metrics.compute_metric` — the
  per-mode/per-k metric function.
- :func:`wiki.retrieval_eval.metrics.aggregate_metrics` —
  the metric aggregation function.
- :func:`wiki.retrieval_eval.output.format_readable` — the
  readable CLI formatter.
- :func:`wiki.retrieval_eval.output.format_json` — the JSON
  CLI formatter.
- :class:`EvalCase`, :class:`EvalCaseResult`,
  :class:`EvalMetric`, :class:`EvalReport` — the public
  dataclasses.
- :data:`EVAL_SCHEMA_VERSION`, :data:`DEFAULT_K_VALUES`,
  :data:`DEFAULT_MODES` — the public constants.
"""

from wiki.retrieval_eval.fixtures import (
    DEFAULT_FIXTURE_PATH,
    EvalCaseError,
    load_cases,
    parse_cases,
)
from wiki.retrieval_eval.metrics import (
    aggregate_metrics,
    compute_metric,
)
from wiki.retrieval_eval.output import (
    format_json,
    format_readable,
)
from wiki.retrieval_eval.runner import (
    run_eval,
    run_eval_in_memory,
)
from wiki.retrieval_eval.schema import (
    DEFAULT_K_VALUES,
    DEFAULT_MODES,
    EVAL_SCHEMA_VERSION,
    EvalCase,
    EvalCaseResult,
    EvalMetric,
    EvalReport,
    MAX_EXPECTED_ITEMS,
    MAX_K,
    MAX_K_VALUES,
)


__all__ = [
    "DEFAULT_FIXTURE_PATH",
    "DEFAULT_K_VALUES",
    "DEFAULT_MODES",
    "EVAL_SCHEMA_VERSION",
    "EvalCase",
    "EvalCaseError",
    "EvalCaseResult",
    "EvalMetric",
    "EvalReport",
    "MAX_EXPECTED_ITEMS",
    "MAX_K",
    "MAX_K_VALUES",
    "aggregate_metrics",
    "compute_metric",
    "format_json",
    "format_readable",
    "load_cases",
    "parse_cases",
    "run_eval",
    "run_eval_in_memory",
]
