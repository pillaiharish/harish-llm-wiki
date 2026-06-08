"""Deterministic extractive mock-answer generator (Prompt 34 MVP closure).

The generator is intentionally simple:

1. Take the top-scoring chunk in the context pack.
2. Split the chunk text into sentences.
3. Keep the first :data:`MAX_SENTENCES_PER_CHUNK` sentences
   that mention at least one query term.
4. Append the citation label of the chunk after each
   sentence.
5. Prepend the MOCK / NO-LLM banner.

When the context pack has no chunks, the body is the
:data:`NO_CONTEXT_BODY` placeholder. When the top chunk has
no sentences that mention a query term, the body falls back
to the first :data:`MAX_SENTENCES_PER_CHUNK` sentences of
the chunk text (still cited).

The generator is pure: it does not call any model, does not
import any provider, and does not require any network access.
The function is deterministic: same input = same output.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from wiki.config import config
from wiki.context_pack.schema import ContextPack
from wiki.mock_answer.schema import (
    MAX_BODY_CHARS,
    MAX_SENTENCES_PER_CHUNK,
    MOCK_ANSWER_BANNER,
    MOCK_ANSWER_SCHEMA_VERSION,
    MOCK_ANSWER_TAG,
    MOCK_ANSWER_VERSION,
    NO_CONTEXT_BODY,
    MockAnswer,
)
from wiki.retrieval.schema import ALLOWED_MODES, DEFAULT_MODE


# Regex used to split chunk text into sentences. The regex
# intentionally keeps things simple: it splits on ``.``, ``!``,
# and ``?`` followed by whitespace or end-of-string, but not
# on common abbreviations (we ignore that edge case for the
# MVP closure; the sentence splitter is good enough to keep
# citations attached to a single sentence).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")

# Regex used to tokenize a string for query-term matching.
# The tokenizer keeps alphanumeric tokens and is intentionally
# simple: it lower-cases the input and yields word-like runs.
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]*")


def generate_mock_answer_from_pack(
    pack: ContextPack,
    *,
    query: Optional[str] = None,
) -> MockAnswer:
    """Build a :class:`MockAnswer` from a pre-computed :class:`ContextPack`.

    The function is pure: it does not call any model, does
    not import any provider, and does not require any network
    access. The answer is fully derived from the
    :class:`ContextPack` (which is itself deterministic).

    Parameters
    ----------
    pack:
        The :class:`ContextPack` to summarize.
    query:
        Optional override for the query. When omitted, the
        pack's :attr:`ContextPack.query` is used.
    """
    if pack is None:
        raise ValueError("pack is required")

    effective_query = str(query) if query is not None else str(pack.query)

    if not pack.chunks:
        return MockAnswer(
            schema_version=MOCK_ANSWER_SCHEMA_VERSION,
            answer_version=MOCK_ANSWER_VERSION,
            query=effective_query,
            mode=str(pack.mode),
            body=_wrap_with_banner(NO_CONTEXT_BODY),
            citation_labels=[],
            source_ids=[],
            total_chunks=int(pack.total_chunks),
            used_chars=int(pack.used_chars),
            mock_tag=MOCK_ANSWER_TAG,
            is_mock=True,
            used_chunk_ids=[],
            used_chunk_ranks=[],
        )

    query_tokens = _tokenize(effective_query)
    query_token_set = set(query_tokens)

    used_chunk_ids: list[str] = []
    used_chunk_ranks: list[int] = []
    citation_labels: list[str] = []
    source_ids: list[str] = []
    body_paragraphs: list[str] = []
    seen_labels: set[str] = set()
    seen_sources: set[str] = set()

    # Walk the chunks in citation order. The first chunk that
    # yields at least one matching sentence becomes the
    # primary paragraph. The remaining chunks are summarized
    # as one-sentence follow-ups, with a hard cap of
    # MAX_SENTENCES_PER_CHUNK per chunk.
    for chunk in pack.chunks:
        sentences = _split_sentences(chunk.text)
        kept = _select_sentences(sentences, query_token_set)
        if not kept:
            # Fall back to the first MAX_SENTENCES_PER_CHUNK
            # sentences so the body is never empty.
            kept = sentences[:MAX_SENTENCES_PER_CHUNK]
        if not kept:
            continue
        cited = _cite_sentences(kept, chunk.citation_label)
        body_paragraphs.append(f"From {chunk.citation_label}:\n\n" + cited)
        used_chunk_ids.append(str(chunk.chunk_id))
        used_chunk_ranks.append(int(chunk.rank))
        if chunk.citation_label and chunk.citation_label not in seen_labels:
            citation_labels.append(str(chunk.citation_label))
            seen_labels.add(str(chunk.citation_label))
        if chunk.resource_id and chunk.resource_id not in seen_sources:
            source_ids.append(str(chunk.resource_id))
            seen_sources.add(str(chunk.resource_id))

    body = _assemble_body(body_paragraphs)
    body = _trim_body(body)

    return MockAnswer(
        schema_version=MOCK_ANSWER_SCHEMA_VERSION,
        answer_version=MOCK_ANSWER_VERSION,
        query=effective_query,
        mode=str(pack.mode),
        body=body,
        citation_labels=citation_labels,
        source_ids=source_ids,
        total_chunks=int(pack.total_chunks),
        used_chars=int(pack.used_chars),
        mock_tag=MOCK_ANSWER_TAG,
        is_mock=True,
        used_chunk_ids=used_chunk_ids,
        used_chunk_ranks=used_chunk_ranks,
    )


def generate_mock_answer(
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
) -> MockAnswer:
    """Build a :class:`MockAnswer` over the on-disk indexes.

    The on-disk entry point used by the CLI. Reads the BM25
    and vector indexes from the data dir, builds a
    :class:`ContextPack`, and delegates to
    :func:`generate_mock_answer_from_pack`.

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

    from wiki.context_pack import build_context_pack

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

    return generate_mock_answer_from_pack(pack, query=str(query))


# =============================================================================
# Helpers
# =============================================================================


def _tokenize(text: str) -> List[str]:
    """Lower-case alphanumeric tokens of ``text``."""
    if not text:
        return []
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


def _split_sentences(text: str) -> List[str]:
    """Split ``text`` into sentences, dropping empty fragments."""
    if not text:
        return []
    raw = _SENTENCE_SPLIT_RE.split(text.strip())
    return [s.strip() for s in raw if s and s.strip()]


def _select_sentences(sentences: Sequence[str], query_token_set: set) -> List[str]:
    """Return the sentences that mention at least one query term.

    The order of the input list is preserved. The selection is
    capped at :data:`MAX_SENTENCES_PER_CHUNK` sentences. The
    cap is applied to the matching sentences; the function
    returns the *first* matches (in input order) when there
    are more than the cap.
    """
    if not sentences or not query_token_set:
        return list(sentences[:MAX_SENTENCES_PER_CHUNK])
    matches: list[str] = []
    for sentence in sentences:
        tokens = set(_tokenize(sentence))
        if tokens & query_token_set:
            matches.append(sentence)
            if len(matches) >= MAX_SENTENCES_PER_CHUNK:
                break
    return matches


def _cite_sentences(sentences: Iterable[str], citation_label: str) -> str:
    """Append ``citation_label`` to each sentence.

    The label is appended with a single space separator. The
    function never raises on an empty input.
    """
    if not citation_label:
        return " ".join(sentences)
    return " ".join(
        (s.rstrip() + " " + citation_label).rstrip()
        for s in sentences
        if s and s.strip()
    )


def _assemble_body(paragraphs: Sequence[str]) -> str:
    """Assemble the body from the per-chunk paragraphs.

    The body always starts with the MOCK / NO-LLM banner. The
    paragraphs are joined with a blank line.
    """
    parts: list[str] = []
    parts.append(f"[{MOCK_ANSWER_BANNER}]")
    parts.append("")
    parts.append(
        "This is a deterministic extractive answer generated without any "
        "language model. Every sentence is followed by the citation label "
        "of the chunk it came from."
    )
    parts.append("")
    parts.extend(p for p in paragraphs if p and p.strip())
    return "\n".join(parts).rstrip() + "\n"


def _wrap_with_banner(body: str) -> str:
    """Wrap a body string in the MOCK / NO-LLM banner."""
    text = str(body).rstrip()
    return f"[{MOCK_ANSWER_BANNER}]\n\n{text}\n"


def _trim_body(body: str) -> str:
    """Trim ``body`` to :data:`MAX_BODY_CHARS` characters.

    The trim is applied to the assembled body *after* the
    citations are appended, so the citation labels always
    survive the trim. The trim is at a sentence boundary
    when possible; otherwise at the hard cap.
    """
    if len(body) <= MAX_BODY_CHARS:
        return body
    trimmed = body[:MAX_BODY_CHARS]
    # Try to trim at the last sentence boundary.
    last_period = max(
        trimmed.rfind(". "),
        trimmed.rfind("! "),
        trimmed.rfind("? "),
    )
    if last_period > 0 and last_period > MAX_BODY_CHARS - 200:
        trimmed = trimmed[: last_period + 1]
    return trimmed.rstrip() + "\n"


__all__ = [
    "generate_mock_answer",
    "generate_mock_answer_from_pack",
]
