"""Fixture loader for the retrieval evaluation suite (Prompt 31).

The fixture loader reads a small JSON file from
``tests/fixtures/retrieval_eval/cases.json`` (or an explicit
override) and yields a deterministic, validated list of
:class:`wiki.retrieval_eval.schema.EvalCase` objects.

The loader is intentionally strict: it raises
:class:`EvalCaseError` on any schema problem (missing field,
empty ``id`` or ``query``, unknown mode, non-positive ``k``,
missing expectations, duplicate case ids, etc.). The CLI
catches this error and surfaces a clear message to the user.

The loader has no project imports beyond the schema module,
so it can be unit-tested without any of the BM25, vector,
chunk, or graph backends.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from wiki.retrieval.schema import ALLOWED_MODES
from wiki.retrieval_eval.schema import (
    DEFAULT_K_VALUES,
    DEFAULT_MODES,
    EvalCase,
    MAX_EXPECTED_ITEMS,
    MAX_K,
    MAX_K_VALUES,
)


# =============================================================================
# Constants
# =============================================================================


#: Default path to the checked-in fixture file. Resolved
#: relative to the project root so the loader works from any
#: working directory.
DEFAULT_FIXTURE_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "fixtures"
    / "retrieval_eval"
    / "cases.json"
)


# =============================================================================
# Errors
# =============================================================================


class EvalCaseError(ValueError):
    """Raised when an eval case fails validation.

    The CLI catches this error and surfaces a clear message
    to the user. Tests can also assert on the message.
    """


# =============================================================================
# Public API
# =============================================================================


def load_cases(path: Path | str | None = None) -> list[EvalCase]:
    """Load and validate eval cases from a JSON file.

    Parameters
    ----------
    path:
        Optional override for the fixture path. Defaults to
        :data:`DEFAULT_FIXTURE_PATH`.

    Returns
    -------
    list[EvalCase]
        The validated eval cases in the order they appear in
        the JSON file. Duplicates are rejected (see
        :func:`_validate_cases`).

    Raises
    ------
    FileNotFoundError
        When the fixture file does not exist.
    EvalCaseError
        When the fixture is malformed or contains an
        invalid case.
    json.JSONDecodeError
        When the fixture file is not valid JSON.
    """
    fixture_path = Path(path) if path is not None else DEFAULT_FIXTURE_PATH
    if not fixture_path.exists():
        raise FileNotFoundError(f"Eval fixture not found: {fixture_path}")
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    return parse_cases(raw)


def parse_cases(raw: Any) -> list[EvalCase]:
    """Parse and validate a raw ``cases`` list.

    The input is the top-level payload from the fixture
    file. The payload may be either a bare list of case
    dicts, or a dict with a ``cases`` key (and an optional
    ``schema_version`` key). The function returns the list
    of validated :class:`EvalCase` objects in the same order.

    Validation rules:

    - Each entry must be a dict.
    - ``id`` must be a non-empty string.
    - ``query`` must be a non-empty string.
    - At least one of ``expected_resource_ids``,
      ``expected_chunk_ids``, ``expected_terms`` must be
      non-empty.
    - ``modes`` (when present) must be a non-empty list of
      valid mode strings; defaults to :data:`DEFAULT_MODES`.
    - ``k_values`` (when present) must be a non-empty list of
      positive integers; defaults to
      :data:`DEFAULT_K_VALUES`.
    - Duplicate ``id`` values are rejected.
    - ``k_values`` may not contain values greater than
      :data:`MAX_K` and the list length is bounded by
      :data:`MAX_K_VALUES`.
    - Expected item lists are bounded by
      :data:`MAX_EXPECTED_ITEMS`.

    Raises
    ------
    EvalCaseError
        When the input is malformed.
    """
    if isinstance(raw, dict):
        if "cases" not in raw:
            raise EvalCaseError(
                f"eval fixture dict must contain a 'cases' key "
                f"(got keys: {sorted(raw)})"
            )
        raw_cases = raw["cases"]
    elif isinstance(raw, list):
        raw_cases = raw
    else:
        raise EvalCaseError(
            f"eval cases must be a list or dict (got {type(raw).__name__})"
        )

    if not isinstance(raw_cases, list):
        raise EvalCaseError(
            f"eval 'cases' must be a list (got {type(raw_cases).__name__})"
        )

    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for idx, entry in enumerate(raw_cases):
        if not isinstance(entry, dict):
            raise EvalCaseError(
                f"case #{idx} is not a dict (got {type(entry).__name__})"
            )
        case = _parse_case(entry, idx)
        if case.id in seen_ids:
            raise EvalCaseError(f"duplicate eval case id: {case.id!r}")
        seen_ids.add(case.id)
        cases.append(case)
    return cases


# =============================================================================
# Internal helpers
# =============================================================================


def _parse_case(entry: dict, idx: int) -> EvalCase:
    """Parse a single case dict and validate it."""
    case_id = entry.get("id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise EvalCaseError(
            f"case #{idx}: 'id' must be a non-empty string "
            f"(got {case_id!r})"
        )

    query = entry.get("query")
    if not isinstance(query, str) or not query.strip():
        raise EvalCaseError(
            f"case {case_id!r}: 'query' must be a non-empty string "
            f"(got {query!r})"
        )

    expected_resource_ids = _string_list(
        entry.get("expected_resource_ids", []),
        field="expected_resource_ids",
        case_id=case_id,
    )
    expected_chunk_ids = _string_list(
        entry.get("expected_chunk_ids", []),
        field="expected_chunk_ids",
        case_id=case_id,
    )
    expected_terms = _string_list(
        entry.get("expected_terms", []),
        field="expected_terms",
        case_id=case_id,
    )

    if (
        not expected_resource_ids
        and not expected_chunk_ids
        and not expected_terms
    ):
        raise EvalCaseError(
            f"case {case_id!r}: at least one of "
            "'expected_resource_ids', 'expected_chunk_ids', "
            "or 'expected_terms' must be non-empty"
        )

    modes = _modes(entry.get("modes", list(DEFAULT_MODES)), case_id=case_id)
    k_values = _k_values(entry.get("k_values", list(DEFAULT_K_VALUES)), case_id=case_id)

    notes = entry.get("notes", "")
    if notes is None:
        notes = ""
    if not isinstance(notes, str):
        raise EvalCaseError(
            f"case {case_id!r}: 'notes' must be a string (got {type(notes).__name__})"
        )

    return EvalCase(
        id=case_id.strip(),
        query=query.strip(),
        expected_resource_ids=expected_resource_ids,
        expected_chunk_ids=expected_chunk_ids,
        expected_terms=expected_terms,
        modes=modes,
        k_values=k_values,
        notes=notes,
    )


def _string_list(
    value: Any, *, field: str, case_id: str
) -> list[str]:
    """Validate that ``value`` is a list of strings."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise EvalCaseError(
            f"case {case_id!r}: '{field}' must be a list "
            f"(got {type(value).__name__})"
        )
    if len(value) > MAX_EXPECTED_ITEMS:
        raise EvalCaseError(
            f"case {case_id!r}: '{field}' has too many entries "
            f"({len(value)} > {MAX_EXPECTED_ITEMS})"
        )
    out: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise EvalCaseError(
                f"case {case_id!r}: '{field}' entries must be strings "
                f"(got {type(entry).__name__})"
            )
        s = entry.strip()
        if s:
            out.append(s)
    return out


def _modes(value: Any, *, case_id: str) -> list[str]:
    """Validate the ``modes`` list."""
    if value is None:
        return list(DEFAULT_MODES)
    if not isinstance(value, list):
        raise EvalCaseError(
            f"case {case_id!r}: 'modes' must be a list "
            f"(got {type(value).__name__})"
        )
    if not value:
        raise EvalCaseError(
            f"case {case_id!r}: 'modes' must be a non-empty list"
        )
    out: list[str] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise EvalCaseError(
                f"case {case_id!r}: 'modes' entries must be non-empty strings "
                f"(got {entry!r})"
            )
        m = entry.strip()
        if m not in ALLOWED_MODES:
            raise EvalCaseError(
                f"case {case_id!r}: invalid mode {m!r} "
                f"(allowed: {sorted(ALLOWED_MODES)})"
            )
        if m in seen:
            continue
        seen.add(m)
        out.append(m)
    return out


def _k_values(value: Any, *, case_id: str) -> list[int]:
    """Validate the ``k_values`` list."""
    if value is None:
        return list(DEFAULT_K_VALUES)
    if not isinstance(value, list):
        raise EvalCaseError(
            f"case {case_id!r}: 'k_values' must be a list "
            f"(got {type(value).__name__})"
        )
    if not value:
        raise EvalCaseError(
            f"case {case_id!r}: 'k_values' must be a non-empty list"
        )
    if len(value) > MAX_K_VALUES:
        raise EvalCaseError(
            f"case {case_id!r}: 'k_values' has too many entries "
            f"({len(value)} > {MAX_K_VALUES})"
        )
    out: list[int] = []
    seen: set[int] = set()
    for entry in value:
        try:
            n = int(entry)
        except (TypeError, ValueError):
            raise EvalCaseError(
                f"case {case_id!r}: 'k_values' entries must be positive integers "
                f"(got {entry!r})"
            ) from None
        if n < 1:
            raise EvalCaseError(
                f"case {case_id!r}: 'k_values' entries must be positive "
                f"(got {n})"
            )
        if n > MAX_K:
            raise EvalCaseError(
                f"case {case_id!r}: 'k_values' entry {n} exceeds MAX_K={MAX_K}"
            )
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


__all__ = [
    "DEFAULT_FIXTURE_PATH",
    "EvalCaseError",
    "load_cases",
    "parse_cases",
]


# Silence linter complaints about unused imports — these
# imports are part of the public type contract.
_ = (Iterable,)
