"""Output formatters for the retrieval evaluation suite (Prompt 31).

The output module provides two deterministic formatters for
the :class:`wiki.retrieval_eval.schema.EvalReport`:

- :func:`format_readable` — a small Rich-table friendly text
  report intended for interactive CLI use. The report is
  stable enough for tests (no timestamps, no random ordering).
- :func:`format_json` — a deterministic JSON document. The
  ``schema_version`` is always the first field, the modes
  and ``k`` values are sorted, and the per-case results are
  in the same order the cases were passed in.

The formatters never raise on empty reports; they emit a
small ``No eval cases.`` placeholder for the readable
formatter and a valid JSON document with
``total_cases: 0`` for the JSON formatter.
"""

from __future__ import annotations

import json
from typing import Any

from wiki.retrieval_eval.schema import (
    EVAL_SCHEMA_VERSION,
    EvalReport,
)


# =============================================================================
# Public API
# =============================================================================


def format_readable(report: EvalReport) -> str:
    """Format an :class:`EvalReport` as a stable plain-text report.

    The output is a deterministic string with no timestamps.
    Empty reports emit a one-line placeholder so the CLI does
    not produce blank output.
    """
    lines: list[str] = []
    lines.append("Retrieval Evaluation Report")
    lines.append("=" * 40)
    lines.append(f"Schema version: {report.schema_version}")
    lines.append(f"Total cases: {report.total_cases}")

    if not report.modes:
        lines.append("Evaluated modes: (none)")
    else:
        lines.append(f"Evaluated modes: {', '.join(report.modes)}")
    if not report.k_values:
        lines.append("Evaluated k values: (none)")
    else:
        lines.append(f"Evaluated k values: {', '.join(str(k) for k in report.k_values)}")

    if report.aggregate_metrics:
        lines.append("")
        lines.append("Aggregate metrics (mean over cases):")
        for mode in sorted(report.aggregate_metrics):
            inner = report.aggregate_metrics[mode]
            lines.append(f"  mode={mode}")
            for k in sorted(inner, key=lambda v: int(v)):
                entry = inner[k]
                lines.append(
                    "    k={k} cases={n} recall={r:.3f} "
                    "precision={p:.3f} hit={h:.3f} mrr={m:.3f} "
                    "term_cov={t:.3f}".format(
                        k=k,
                        n=int(entry.get("case_count", 0)),
                        r=float(entry.get("recall", 0.0)),
                        p=float(entry.get("precision", 0.0)),
                        h=float(entry.get("hit", 0.0)),
                        m=float(entry.get("mrr", 0.0)),
                        t=float(entry.get("expected_term_coverage", 0.0)),
                    )
                )

    failures = list(report.failures or [])
    if failures:
        lines.append("")
        lines.append(f"Failures ({len(failures)}):")
        for f in failures:
            lines.append(f"  - {f.case_id}: {f.failure}")

    if report.total_cases == 0:
        lines.append("")
        lines.append("No eval cases.")

    return "\n".join(lines) + "\n"


def format_json(report: EvalReport) -> str:
    """Format an :class:`EvalReport` as a deterministic JSON document."""
    payload: dict[str, Any] = report.to_dict()
    # Make sure the schema_version is the first key in the
    # document by re-constructing the dict in the canonical
    # order. The ``to_dict()`` projection already sorts the
    # ``aggregate_metrics`` sub-dict; we only need to ensure
    # the top-level keys are emitted in the right order.
    ordered: dict[str, Any] = {
        "schema_version": payload["schema_version"],
        "total_cases": payload["total_cases"],
        "modes": payload["modes"],
        "k_values": payload["k_values"],
        "aggregate_metrics": payload["aggregate_metrics"],
        "case_results": payload["case_results"],
        "failures": payload["failures"],
    }
    return json.dumps(ordered, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


__all__ = [
    "format_json",
    "format_readable",
]


# Silence linter complaints about unused imports — these
# imports are part of the public type contract.
_ = EVAL_SCHEMA_VERSION
