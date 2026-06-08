"""Rule-based RAG answer evaluator (Prompt 34 MVP closure).

The evaluator is a small, deterministic function that takes
a :class:`wiki.mock_answer.schema.MockAnswer` and the
:class:`wiki.context_pack.schema.ContextPack` it was built
from, and returns a :class:`wiki.rag_eval.schema.RagAnswerReport`.

The checks are intentionally simple and rule-based; the
evaluator does **not** call any model, does **not** import
any LLM-as-judge library, and does **not** require any
network access. The checks are described in detail on the
:class:`RagCheckResult` class.

The evaluator exposes two entry points:

- :func:`eval_rag` — the on-disk entry point used by the
  CLI. Reads the BM25 and vector indexes from the data dir,
  builds a :class:`ContextPack`, generates the mock answer,
  and evaluates the pair.
- :func:`eval_rag_in_memory` — the in-memory entry point
  used by tests and by callers that already have a
  :class:`ContextPack` and a :class:`MockAnswer`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Sequence

from wiki.config import config
from wiki.context_pack.schema import ContextPack
from wiki.mock_answer.schema import (
    MOCK_ANSWER_BANNER,
    MOCK_ANSWER_TAG,
    MockAnswer,
    NO_CONTEXT_BODY,
)
from wiki.rag_eval.schema import (
    CHECK_CHUNK_COVERAGE,
    CHECK_CITATIONS_PRESENT,
    CHECK_CITATIONS_VALID,
    CHECK_HAS_BODY,
    CHECK_IS_MOCK_FLAG,
    CHECK_MOCK_BANNER,
    CHECK_NON_EMPTY_WHEN_CONTEXT,
    CHECK_NO_HALLUCINATED_SOURCES,
    CHECK_SOURCE_COVERAGE,
    MOCK_TAG_PREFIX,
    RAG_EVAL_SCHEMA_VERSION,
    RagAnswerReport,
    RagCheckResult,
)
from wiki.retrieval.schema import ALLOWED_MODES, DEFAULT_MODE


# Regex used to extract citation labels of the form
# ``[cite:N]`` from the answer body. The regex is
# intentionally permissive on the N value but enforces the
# bracketed ``cite:`` prefix.
_CITATION_RE = re.compile(r"\[cite:([0-9]+)\]")


def eval_rag_in_memory(
    *,
    pack: ContextPack,
    answer: MockAnswer,
) -> RagAnswerReport:
    """Evaluate ``answer`` against ``pack`` in memory.

    The function is pure: it does not call any model, does
    not import any provider, and does not require any network
    access. The report is fully derived from the input pair.

    Parameters
    ----------
    pack:
        The :class:`ContextPack` the answer was built from.
    answer:
        The :class:`MockAnswer` to evaluate.
    """
    if pack is None:
        raise ValueError("pack is required")
    if answer is None:
        raise ValueError("answer is required")

    checks: List[RagCheckResult] = []

    # Check 1: body is non-empty.
    body = str(answer.body or "").strip()
    checks.append(
        RagCheckResult(
            id=CHECK_HAS_BODY,
            name="answer_has_body",
            passed=bool(body),
            detail="" if body else "answer body is empty",
            score=1.0 if body else 0.0,
        )
    )

    # Check 2: body carries the MOCK / NO-LLM banner.
    has_banner = MOCK_ANSWER_BANNER in (answer.body or "")
    detail = ""
    if not has_banner:
        detail = f"missing MOCK / NO-LLM banner: expected {MOCK_ANSWER_BANNER!r}"
    checks.append(
        RagCheckResult(
            id=CHECK_MOCK_BANNER,
            name="answer_marked_mock_no_llm",
            passed=has_banner,
            detail=detail,
            score=1.0 if has_banner else 0.0,
        )
    )

    # Check 3: is_mock flag is True.
    checks.append(
        RagCheckResult(
            id=CHECK_IS_MOCK_FLAG,
            name="answer_is_mock_flag",
            passed=bool(answer.is_mock),
            detail="" if answer.is_mock else "is_mock flag is False",
            score=1.0 if answer.is_mock else 0.0,
        )
    )

    # Check 4: when the answer claims citations, at least one
    # citation label must be present in the body. When the
    # answer claims no citations and the context has no
    # chunks, the check passes vacuously.
    has_citation_labels = bool(answer.citation_labels)
    has_citation_in_body = bool(_CITATION_RE.search(answer.body or ""))
    cited_present = has_citation_labels or has_citation_in_body
    if pack.chunks and not cited_present:
        detail = "context has chunks but answer has no citation labels"
        passed = False
    else:
        detail = ""
        passed = True
    checks.append(
        RagCheckResult(
            id=CHECK_CITATIONS_PRESENT,
            name="cited_answer_has_citations",
            passed=bool(passed),
            detail=detail,
            score=1.0 if passed else 0.0,
        )
    )

    # Check 5: every citation label in the answer exists in
    # the context pack. The check is strict: any hallucinated
    # label fails the check.
    pack_label_set = {str(c.citation_label) for c in pack.chunks}
    pack_label_set.update({f"[cite:{c.rank}]" for c in pack.chunks})
    body_label_set = set(_CITATION_RE.findall(answer.body or ""))
    body_label_set_str = {f"[cite:{n}]" for n in body_label_set}
    answer_label_set = set(str(x) for x in (answer.citation_labels or []))
    union = body_label_set_str | answer_label_set
    unsupported = sorted(union - pack_label_set)
    detail = ""
    if unsupported:
        detail = f"unsupported citation labels: {', '.join(unsupported)}"
    passed = not bool(unsupported)
    checks.append(
        RagCheckResult(
            id=CHECK_CITATIONS_VALID,
            name="citations_exist_in_context",
            passed=passed,
            detail=detail,
            score=1.0 if passed else 0.0,
        )
    )

    # Check 6: every source id in the answer exists in the
    # context pack. The check is strict: any hallucinated
    # source fails the check.
    pack_source_set = {str(s.resource_id) for s in pack.sources}
    answer_source_set = {str(x) for x in (answer.source_ids or [])}
    hallucinated_sources = sorted(answer_source_set - pack_source_set)
    detail = ""
    if hallucinated_sources:
        detail = (
            f"unsupported source ids: {', '.join(hallucinated_sources)}"
        )
    passed = not bool(hallucinated_sources)
    checks.append(
        RagCheckResult(
            id=CHECK_NO_HALLUCINATED_SOURCES,
            name="no_hallucinated_source_ids",
            passed=passed,
            detail=detail,
            score=1.0 if passed else 0.0,
        )
    )

    # Check 7: when the context has chunks, the answer is
    # non-empty *and* not the NO_CONTEXT_BODY placeholder.
    has_chunks = bool(pack.chunks)
    is_placeholder = NO_CONTEXT_BODY in (answer.body or "")
    if has_chunks:
        passed = bool(body) and not is_placeholder
        detail = "" if passed else (
            "context has chunks but answer is the empty/placeholder body"
        )
    else:
        # Vacuous: there are no chunks, the placeholder is
        # the right answer.
        passed = True
        detail = ""
    checks.append(
        RagCheckResult(
            id=CHECK_NON_EMPTY_WHEN_CONTEXT,
            name="answer_non_empty_when_context",
            passed=bool(passed),
            detail=detail,
            score=1.0 if passed else 0.0,
        )
    )

    # Check 8: chunk coverage. The answer should cover at
    # least one chunk when the context has chunks. The score
    # is the actual coverage ratio.
    used_chunk_ids = {str(x) for x in (answer.used_chunk_ids or [])}
    pack_chunk_ids = {str(c.chunk_id) for c in pack.chunks}
    if pack_chunk_ids:
        intersection = used_chunk_ids & pack_chunk_ids
        coverage = len(intersection) / max(1, len(pack_chunk_ids))
    else:
        coverage = 1.0
    has_at_least_one = bool(used_chunk_ids & pack_chunk_ids) if pack_chunk_ids else True
    detail = ""
    if pack_chunk_ids and not has_at_least_one:
        detail = "answer did not cover any context chunk"
    checks.append(
        RagCheckResult(
            id=CHECK_CHUNK_COVERAGE,
            name="context_chunk_coverage",
            passed=has_at_least_one,
            detail=detail,
            score=coverage,
        )
    )

    # Check 9: source coverage. The answer should cover at
    # least one source when the context has sources.
    used_source_ids = {str(x) for x in (answer.source_ids or [])}
    pack_source_ids = {str(s.resource_id) for s in pack.sources}
    if pack_source_ids:
        intersection = used_source_ids & pack_source_ids
        coverage = len(intersection) / max(1, len(pack_source_ids))
    else:
        coverage = 1.0
    has_at_least_one_src = bool(used_source_ids & pack_source_ids) if pack_source_ids else True
    detail = ""
    if pack_source_ids and not has_at_least_one_src:
        detail = "answer did not cover any source"
    checks.append(
        RagCheckResult(
            id=CHECK_SOURCE_COVERAGE,
            name="context_source_coverage",
            passed=has_at_least_one_src,
            detail=detail,
            score=coverage,
        )
    )

    # Aggregate.
    total_checks = len(checks)
    passed_checks = sum(1 for c in checks if c.passed)
    failed_checks = total_checks - passed_checks
    score = (passed_checks / total_checks) if total_checks else 0.0

    return RagAnswerReport(
        schema_version=RAG_EVAL_SCHEMA_VERSION,
        query=str(answer.query),
        mode=str(answer.mode or pack.mode),
        total_checks=total_checks,
        passed_checks=passed_checks,
        failed_checks=failed_checks,
        score=float(score),
        is_mock=bool(answer.is_mock),
        mock_tag=str(answer.mock_tag or MOCK_ANSWER_TAG),
        answer_body=str(answer.body),
        answer_citation_labels=list(answer.citation_labels or []),
        answer_source_ids=list(answer.source_ids or []),
        total_chunks=int(pack.total_chunks),
        used_chars=int(pack.used_chars),
        checks=checks,
        all_passed=bool(passed_checks == total_checks and total_checks > 0),
    )


def eval_rag(
    query: str,
    *,
    mode: str = DEFAULT_MODE,
    limit: int = 10,
    max_chars: int = 0,
    source_types: Optional[Sequence[str]] = None,
    resource_id: Optional[str] = None,
    bm25_weight: float = 0.55,
    vector_weight: float = 0.45,
    index_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> RagAnswerReport:
    """Evaluate a mock answer over the on-disk indexes.

    The on-disk entry point used by the CLI. Reads the BM25
    and vector indexes from the data dir, builds a
    :class:`ContextPack`, generates the mock answer, and
    evaluates the pair via
    :func:`eval_rag_in_memory`.

    Parameters
    ----------
    query:
        The user query. Must be non-empty.
    mode:
        Retrieval mode (``bm25``, ``vector``, ``hybrid``,
        ``graph-lite``). Defaults to ``hybrid``.
    limit:
        Maximum number of retrieval results.
    max_chars:
        Per-chunk char budget. ``0`` disables trimming.
    source_types:
        Optional list of source types to filter by.
    resource_id:
        Optional single resource id to filter by.
    bm25_weight:
        Weight on the BM25 contribution.
    vector_weight:
        Weight on the vector contribution.
    index_dir:
        Optional override for the BM25/vector index dir.
    data_dir:
        Optional override for the wiki data dir.

    Raises
    ------
    ValueError
        If the query is empty or the mode is invalid.
    FileNotFoundError
        If the BM25 or vector index is missing for a mode
        that requires it.
    """
    if not query or not str(query).strip():
        raise ValueError("query is empty")
    if mode not in ALLOWED_MODES:
        raise ValueError(
            f"invalid mode: {mode!r} (allowed: {sorted(ALLOWED_MODES)})"
        )

    base = Path(data_dir) if data_dir is not None else config.LLM_WIKI_DATA_DIR

    # Local imports to avoid an import cycle when the package
    # is imported during tests.
    from wiki.context_pack import build_context_pack
    from wiki.mock_answer import generate_mock_answer_from_pack

    pack = build_context_pack(
        str(query),
        mode=mode,
        limit=limit,
        max_chars=max_chars,
        source_types=source_types,
        resource_id=resource_id,
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
        index_dir=index_dir,
        data_dir=base,
    )
    answer = generate_mock_answer_from_pack(pack, query=str(query))
    return eval_rag_in_memory(pack=pack, answer=answer)


__all__ = [
    "eval_rag",
    "eval_rag_in_memory",
]


# Silence linter complaints about unused imports — these
# imports are part of the public type contract.
_ = (MOCK_ANSWER_BANNER, MOCK_TAG_PREFIX)
