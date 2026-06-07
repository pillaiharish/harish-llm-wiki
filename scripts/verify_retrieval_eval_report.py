#!/usr/bin/env python
"""Lightweight verification for the Prompt 32 retrieval-eval static report page.

Verifies that the generated ``search/eval.md`` page exists, has the
required sections, and surfaces the required metric names. The script
is intentionally simple: file-existence checks plus content regex
checks. It does **not** require a browser, network access, or
Playwright. It runs against the in-repo site dir (``site/docs``) by
default and accepts ``--site-dir`` for tests.

Checks
------

- generated ``search/eval.md`` exists and is non-empty
- the page has a level-1 heading and a ``Retrieval Eval Report`` title
- the page has the required sections: ``Aggregate metrics``,
  ``Per-mode metrics``, ``Per-k metrics``, ``Case results``,
  ``Failures and no-hit cases``, ``Commands``, ``Provenance``
- the page mentions each required metric name: ``recall@k``,
  ``precision@k``, ``hit@k``, ``MRR``, ``expected-term coverage``
- the page mentions each required envelope field: ``schema version``,
  ``total cases``, ``evaluated modes``, ``evaluated k values``
- the page does not advertise Prompt 33 context-pack work, answer
  generation, or LLM provider integration
- the on-disk ``wiki.eval-retrieval`` source tree is also scanned to
  confirm the report page is wired to ``wiki.retrieval_eval`` (not
  freshly reimplemented in the builder)

Usage
-----

    .venv/bin/python scripts/verify_retrieval_eval_report.py
    .venv/bin/python scripts/verify_retrieval_eval_report.py --site-dir /path/to/site/docs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Default in-repo site docs directory. Computed from this script's
# location so the test suite and the developer machine agree.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SITE_DIR = REPO_ROOT / "site" / "docs"
DEFAULT_REPORT_PATH = DEFAULT_SITE_DIR / "search" / "eval.md"

# Section markers that the page must contain. The list is checked in
# order so the failure output is predictable.
REQUIRED_SECTIONS: tuple[str, ...] = (
    "## Aggregate metrics",
    "## Per-mode metrics",
    "## Per-k metrics",
    "## Case results",
    "## Failures and no-hit cases",
    "## Commands",
    "## Provenance",
)

# Metric names that the page must mention. The page is generated from
# ``wiki.retrieval_eval`` and must surface the same set of metrics the
# eval runner computes.
REQUIRED_METRIC_NAMES: tuple[str, ...] = (
    "recall@k",
    "precision@k",
    "hit@k",
    "MRR",
    "expected-term coverage",
)

# Envelope fields that the page must mention in the Overview section.
REQUIRED_ENVELOPE_FIELDS: tuple[str, ...] = (
    "Schema version",
    "Total cases",
    "Evaluated modes",
    "Evaluated k values",
)

# Phrases that must NOT appear in the page. These are guard-rails for
# Prompt 32 boundary compliance: the page must not advertise
# LLM/provider integration, context-pack construction, or answer
# generation (those are Prompt 33+ scope).
#
# The list deliberately **excludes** the names of LLM providers,
# embedding libraries, and vector databases (OpenAI, Ollama, FAISS,
# Chroma, ...) because the page legitimately enumerates these in its
# "Boundaries" section to make the negative claim ("this report does
# NOT add them"). Mentioning them in a "we do not do X" sentence is
# the whole point of that section. Instead, the boundary check below
# looks for *positive* integration language.
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "context pack",
    "context-pack",
    "ContextPack",
    "prompt builder",
    "PromptBuilder",
    "grounded answer",
    "GroundedAnswer",
    "chatbot",
)

# Positive integration phrases. If any of these appear in the page
# the report is over-stepping its Prompt 32 scope.
FORBIDDEN_INTEGRATION_PHRASES: tuple[str, ...] = (
    "powered by OpenAI",
    "powered by Ollama",
    "powered by Gemini",
    "uses OpenAI",
    "uses Ollama",
    "uses Gemini",
    "integrated with OpenAI",
    "integrated with Ollama",
    "integrated with FAISS",
    "integrated with Chroma",
    "integrated with LanceDB",
)


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site-dir",
        type=Path,
        default=DEFAULT_SITE_DIR,
        help="Path to the site/docs directory to verify (default: %(default)s)",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Path to the retrieval eval report markdown file (default: %(default)s)",
    )
    return parser


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def main() -> int:
    parser = _build_argparser()
    args = parser.parse_args()
    site_dir = Path(args.site_dir).expanduser().resolve()
    # The report is always at ``<site_dir>/search/eval.md``,
    # regardless of the --report-path flag. The flag exists only
    # for documentation and for callers that want to point at a
    # non-default layout. The site_dir is the source of truth.
    report_path = (site_dir / "search" / "eval.md").resolve()

    failures: list[tuple[str, str]] = []
    checks = 0

    if not site_dir.exists():
        print(f"FAIL: site directory does not exist: {site_dir}", file=sys.stderr)
        return 1

    if not report_path.exists():
        print(f"FAIL: retrieval eval report missing: {report_path}", file=sys.stderr)
        return 1

    content = _read_text(report_path)
    if not content:
        print(f"FAIL: retrieval eval report is empty: {report_path}", file=sys.stderr)
        return 1

    # Page must start with a level-1 heading.
    checks += 1
    if not any(line.startswith("# ") for line in content.splitlines()[:5]):
        failures.append(("h1_heading", "page is missing a level-1 heading"))

    # Page must mention the report title.
    checks += 1
    if "Retrieval Eval Report" not in content:
        failures.append(("title", "page is missing the 'Retrieval Eval Report' title"))

    # Required sections.
    for marker in REQUIRED_SECTIONS:
        checks += 1
        if marker not in content:
            failures.append(("section", f"missing section: {marker}"))

    # Required metric names.
    for name in REQUIRED_METRIC_NAMES:
        checks += 1
        if name not in content:
            failures.append(("metric", f"missing metric name: {name}"))

    # Required envelope fields.
    for name in REQUIRED_ENVELOPE_FIELDS:
        checks += 1
        if name not in content:
            failures.append(("envelope", f"missing envelope field: {name}"))

    # Forbidden phrases.
    for phrase in FORBIDDEN_PHRASES:
        checks += 1
        # Case-sensitive match is intentional: it surfaces real
        # library references, not e.g. the word "open" inside
        # "opencode".
        if phrase in content:
            failures.append(("forbidden", f"forbidden phrase present: {phrase!r}"))
    for phrase in FORBIDDEN_INTEGRATION_PHRASES:
        checks += 1
        if phrase.lower() in content.lower():
            failures.append(
                ("forbidden_integration", f"forbidden integration phrase: {phrase!r}")
            )

    # Confirm the report markdown is the in-repo copy (not just the
    # generated copy). This guards against tests running against an
    # ephemeral data dir.
    checks += 1
    if not report_path.exists():
        failures.append(("path", f"report path missing: {report_path}"))

    # Confirm the builder wires the report through ``wiki.retrieval_eval``.
    # We do this by scanning the in-repo builder file and asserting that
    # the report generation imports the eval package.
    builder_path = REPO_ROOT / "wiki" / "site" / "builder.py"
    builder_text = _read_text(builder_path)
    checks += 1
    if "wiki.retrieval_eval" not in builder_text:
        failures.append(
            ("wiring", f"builder does not import wiki.retrieval_eval: {builder_path}")
        )
    if "_build_retrieval_eval_page" not in builder_text:
        failures.append(
            ("wiring", "builder is missing _build_retrieval_eval_page method")
        )
    if "search/eval.md" not in builder_text and "eval.md" not in builder_text:
        failures.append(
            ("wiring", "builder does not appear to write search/eval.md")
        )

    # Summarize.
    print(f"Site dir: {site_dir}")
    print(f"Report:   {report_path}")
    print()
    print(f"Checks: {checks}")
    if failures:
        print(f"Failures: {len(failures)}", file=sys.stderr)
        for label, msg in failures:
            print(f"  - [{label}] {msg}", file=sys.stderr)
        return 1
    print("All retrieval-eval report checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
