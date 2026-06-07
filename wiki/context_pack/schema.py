"""Public schema for the context-pack builder (Prompt 33).

This module defines the on-the-wire shape of a context pack
that converts a list of :class:`wiki.retrieval.schema.RetrievalResult`
objects into a citation-ready block for future RAG answer
generation. The pack is deterministic, no-LLM, and is consumed
by the ``wiki build-context`` CLI and the context-pack tests.

The schema has three dataclasses:

- :class:`ContextChunk` — one ordered chunk with its rank,
  stable citation label, and trimmed text. The ``text`` field
  is the chunk text as loaded from the on-disk chunk index,
  trimmed to respect the per-chunk char budget (no truncation
  when ``max_chars`` is not set or is non-positive).
- :class:`ContextSource` — one deduplicated source record that
  groups all chunks sharing the same ``resource_id``. The
  ``citation_label`` field is the same stable label assigned
  to every chunk that belongs to this source.
- :class:`ContextPack` — the top-level envelope. Its
  ``schema_version`` is the first field of the JSON
  projection so the CLI output is stable across runs.

The dataclasses are frozen so the pack is immutable and the
``to_dict()`` projections are the contract for the JSON CLI
output. The module has no project imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# =============================================================================
# Constants
# =============================================================================


#: Schema version string for the context pack. Bumped only
#: when the public JSON shape changes in a breaking way. The
#: CLI emits this string as the ``schema_version`` field of
#: the JSON output and the first line of the readable report.
CONTEXT_PACK_SCHEMA_VERSION: str = "context_pack_v1"

#: Default retrieval mode used when the caller does not
#: specify one. Mirrors ``wiki.retrieval.schema.DEFAULT_MODE``.
DEFAULT_MODE: str = "hybrid"

#: Default ``limit`` used when the caller does not specify
#: one. The pack is a tiny context window, so the default is
#: intentionally small. Mirrors the upstream router default.
DEFAULT_LIMIT: int = 10

#: Default ``max_chars`` used when the caller does not
#: specify one. ``0`` (or any non-positive value) means "no
#: per-chunk char budget". The cap is applied *per chunk* and
#: is independent of the retrieval ``limit``; the cap is also
#: independent of the eventual prompt builder (Prompt 35).
DEFAULT_MAX_CHARS: int = 0

#: Hard cap on the number of retrieval results consumed by
#: the pack. Mirrors the upstream ``MAX_LIMIT``.
MAX_LIMIT: int = 100

#: Stable prefix used to build citation labels.
#: Citation labels are deterministic strings of the form
#: ``[cite:N]`` where ``N`` is the 1-based rank of the chunk
#: in the retrieved list (first-seen order, after dedup).
CITATION_LABEL_PREFIX: str = "cite"

#: Stable string used when a field has no meaningful value
#: (e.g. an empty title or an empty source_type). The pack
#: never emits ``null``/``None`` for string fields; the empty
#: string is the sentinel so the schema is uniform.
EMPTY_STRING: str = ""


# =============================================================================
# Context chunk
# =============================================================================


@dataclass(frozen=True)
class ContextChunk:
    """A single ordered chunk in the context pack.

    Fields
    ------
    rank:
        1-based position in the final pack (post-dedup,
        post-trim). The rank is the same as the citation
        number embedded in :attr:`citation_label`.
    citation_label:
        Stable citation label of the form ``[cite:N]`` where
        ``N`` equals :attr:`rank`. The label is the same for
        every chunk that belongs to the same source.
    resource_id:
        The owning resource id (e.g. ``pdf:abc123``).
    chunk_id:
        The chunk id assigned by the chunk index.
    title:
        The chunk's title (typically the parent resource
        title). Empty string when unknown.
    source_type:
        The chunk's source type (e.g. ``pdf``, ``youtube``).
        Empty string when unknown.
    score:
        The retrieval score assigned by the upstream router
        (``RetrievalResult.score``). ``0.0`` when the upstream
        score is missing or the rank was synthesized.
    text:
        The chunk text, trimmed to respect the per-chunk char
        budget. Empty string when the chunk text is missing
        from the chunk index.
    truncated:
        ``True`` when the chunk text was trimmed to respect
        :attr:`ContextPack.max_chars`; ``False`` otherwise.
        The flag is informational and is also useful for
        tests that assert on the trim behavior.
    """

    rank: int
    citation_label: str
    resource_id: str
    chunk_id: str
    title: str
    source_type: str
    score: float
    text: str
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        """Project to a dict in stable field order."""
        return {
            "rank": self.rank,
            "citation_label": self.citation_label,
            "resource_id": self.resource_id,
            "chunk_id": self.chunk_id,
            "title": self.title,
            "source_type": self.source_type,
            "score": self.score,
            "text": self.text,
            "truncated": self.truncated,
        }


# =============================================================================
# Context source
# =============================================================================


@dataclass(frozen=True)
class ContextSource:
    """A deduplicated source record in the context pack.

    Sources are emitted in the order they are first cited by
    the chunk list. The :attr:`chunk_ids` list preserves the
    citation order (the chunk ranks) and is the canonical way
    for downstream consumers to know which chunks came from
    which source.

    Fields
    ------
    citation_label:
        Stable citation label of the form ``[cite:N]``. The
        ``N`` matches the rank of the *first* chunk that
        cited this source.
    resource_id:
        The owning resource id.
    title:
        The resource title. Empty string when unknown.
    source_type:
        The resource source type. Empty string when unknown.
    chunk_ids:
        List of chunk ids that belong to this source, in
        citation order (matches the chunk ranks). The list is
        deduplicated and stable.
    """

    citation_label: str
    resource_id: str
    title: str
    source_type: str
    chunk_ids: list = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Project to a dict in stable field order."""
        return {
            "citation_label": self.citation_label,
            "resource_id": self.resource_id,
            "title": self.title,
            "source_type": self.source_type,
            "chunk_ids": list(self.chunk_ids),
        }


# =============================================================================
# Context pack
# =============================================================================


@dataclass(frozen=True)
class ContextPack:
    """The top-level context-pack envelope.

    The pack is the deterministic projection of an upstream
    retrieval result list into a citation-ready block. The
    pack is intentionally small and stable: it carries the
    minimum metadata a future RAG answer generator would need
    to quote, cite, and reference each chunk.

    Fields
    ------
    schema_version:
        The :data:`CONTEXT_PACK_SCHEMA_VERSION` string. Always
        the first field of the JSON projection.
    query:
        The user query.
    mode:
        The retrieval mode used to build the pack. One of
        ``bm25``, ``vector``, ``hybrid``, ``graph-lite``.
    limit:
        The ``limit`` argument the pack was built with. Note
        that :attr:`total_chunks` may be smaller than
        :attr:`limit` when the underlying retriever returned
        fewer items, or when the chunk index was missing
        entries.
    max_chars:
        The per-chunk char budget the pack was built with.
        ``0`` (or any non-positive value) means "no per-chunk
        char budget".
    used_chars:
        The total number of characters consumed by the
        ``chunks[].text`` fields. Excludes citation labels,
        titles, and other metadata; it is the sum of the
        per-chunk text lengths after the per-chunk char
        budget was applied.
    total_chunks:
        The number of chunks in :attr:`chunks`. Equals the
        number of distinct chunk ids the pack contains.
    chunks:
        The ordered list of :class:`ContextChunk` records.
        The list is in citation order (rank ascending).
    sources:
        The ordered list of :class:`ContextSource` records.
        The list is in first-cited order; the first source is
        the one cited by :attr:`chunks`[0].
    """

    schema_version: str
    query: str
    mode: str
    limit: int
    max_chars: int
    used_chars: int
    total_chunks: int
    chunks: list = field(default_factory=list)
    sources: list = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Project to a dict in stable field order.

        The top-level key order is fixed and matches the
        spec: ``schema_version`` is the first key, followed
        by the request metadata (``query``, ``mode``,
        ``limit``, ``max_chars``), the totals
        (``used_chars``, ``total_chunks``), and the
        ``chunks`` and ``sources`` lists.
        """
        return {
            "schema_version": self.schema_version,
            "query": self.query,
            "mode": self.mode,
            "limit": self.limit,
            "max_chars": self.max_chars,
            "used_chars": self.used_chars,
            "total_chunks": self.total_chunks,
            "chunks": [c.to_dict() for c in self.chunks],
            "sources": [s.to_dict() for s in self.sources],
        }


# =============================================================================
# Helpers
# =============================================================================


def make_citation_label(rank: int) -> str:
    """Build the stable citation label for a 1-based rank.

    The label format is ``[cite:N]`` where ``N`` is the rank.
    The brackets are part of the label so the label is
    unambiguous when embedded in a larger string.
    """
    return f"[{CITATION_LABEL_PREFIX}:{int(rank)}]"


__all__ = [
    "CITATION_LABEL_PREFIX",
    "CONTEXT_PACK_SCHEMA_VERSION",
    "ContextChunk",
    "ContextPack",
    "ContextSource",
    "DEFAULT_LIMIT",
    "DEFAULT_MAX_CHARS",
    "DEFAULT_MODE",
    "EMPTY_STRING",
    "MAX_LIMIT",
    "make_citation_label",
]
