"""BM25 score calculator (Prompt 28).

This module implements a small, pure-Python BM25 scorer. It does
**not** import ``rank_bm25`` or any other BM25 library; the
implementation is intentionally a few dozen lines so the math is
auditable and the scoring is byte-stable.

BM25 parameters
---------------

- ``k1 = 1.5`` (default) – term-frequency saturation. Higher
  values mean a single term's marginal contribution grows more
  slowly with term frequency.
- ``b = 0.75`` (default) – document-length normalization. 0.0
  means no length normalization; 1.0 means full normalization.

Both follow the Robertson–Walker defaults that Lucene, Okapi
BM25, and Elastic also use.

IDF formula
-----------

The IDF formula is the Lucene-style, never-negative variant:

    idf(t) = log( (N - n_t + 0.5) / (n_t + 0.5) + 1 )

where ``N`` is the total number of documents in the corpus and
``n_t`` is the number of documents containing term ``t``. The
``+ 1`` inside the log keeps the score strictly positive even
when a term appears in every document. This is the same formula
``rank_bm25`` uses for ``BM25Okapi``.

Field weights
-------------

The scorer accepts a flat postings structure with a single
``tf`` per (term, chunk) pair. The field weights are applied
**before** the postings are built (in :mod:`wiki.search.index`),
so the scorer itself does not need to know about field weights.
This keeps the math simple and the scorer unit-testable on
in-memory data.

Doc length
----------

The ``doc_length`` is the **weighted virtual length** of the
chunk (text * 1.0 + title * 2.0 + citation_label * 0.5, rounded
to int). This is standard practice in multi-field BM25
implementations (Elastic does the same). The chunk index's
``word_count`` is the raw text-only count and is preserved
separately in ``chunk_meta`` for downstream consumers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


# =============================================================================
# Constants
# =============================================================================


#: Default ``k1`` for BM25 (Robertson–Walker).
BM25_DEFAULT_K1: float = 1.5

#: Default ``b`` for BM25 (Robertson–Walker).
BM25_DEFAULT_B: float = 0.75


# =============================================================================
# Data classes
# =============================================================================


@dataclass(frozen=True)
class Score:
    """A single scored result.

    Attributes
    ----------
    chunk_id:
        The chunk this score applies to.
    score:
        The BM25 score (always non-negative with the Lucene IDF).
    """

    chunk_id: str
    score: float

    def __lt__(self, other: "Score") -> bool:
        # ``-score`` for descending sort, then ``chunk_id`` for
        # deterministic tie-breaking.
        if self.score != other.score:
            return self.score > other.score
        return self.chunk_id < other.chunk_id


@dataclass
class SearchResult:
    """The public search-result schema.

    This is the dataclass that ``wiki.search.search.search_bm25``
    returns (one per result). Its field order is the canonical
    JSON serialization order, matching the schema required by
    ``prompt28.md`` §"Required search result schema".
    """

    rank: int
    score: float
    chunk_id: str
    resource_id: str
    title: str
    source_type: str
    text_preview: str
    citation_label: str
    resource_route: str
    source_ref: dict = field(default_factory=dict)
    matched_terms: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Project to a dict in stable field order.

        We use explicit field ordering (not ``dataclasses.asdict``
        which uses ``__dict__`` order on the dataclass) so the
        serialized JSON keys are stable across runs.
        """
        return {
            "rank": self.rank,
            "score": self.score,
            "chunk_id": self.chunk_id,
            "resource_id": self.resource_id,
            "title": self.title,
            "source_type": self.source_type,
            "text_preview": self.text_preview,
            "citation_label": self.citation_label,
            "resource_route": self.resource_route,
            "source_ref": self.source_ref,
            "matched_terms": self.matched_terms,
            "metadata": self.metadata,
        }


# =============================================================================
# Scorer
# =============================================================================


@dataclass
class BM25Scorer:
    """BM25 score calculator.

    The scorer is a pure object: feed it the pre-built postings
    and chunk meta and call :meth:`score_query`. It does no I/O.

    Parameters
    ----------
    k1:
        Term-frequency saturation. Default 1.5.
    b:
        Document-length normalization. Default 0.75.
    """

    k1: float = BM25_DEFAULT_K1
    b: float = BM25_DEFAULT_B

    def idf(self, n_t: int, n: int) -> float:
        """Compute Lucene-style IDF for a term.

        ``idf(t) = log((N - n_t + 0.5) / (n_t + 0.5) + 1)``.

        Always non-negative. The implementation clamps
        ``n_t`` to ``n`` defensively so a degenerate call (e.g.
        ``n_t > n``) cannot return a negative value.
        """
        if n <= 0 or n_t <= 0:
            return 0.0
        # Defensive clamp: a term cannot appear in more documents
        # than the corpus has. Without this clamp the formula
        # would return a negative value for ``n_t > n``.
        n_t = min(int(n_t), int(n))
        return math.log((n - n_t + 0.5) / (n_t + 0.5) + 1.0)

    def score_term(
        self,
        tf: int,
        doc_length: int,
        avg_doc_length: float,
        idf: float,
    ) -> float:
        """Compute the BM25 score contribution for a single term.

        ``score = idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))``
        """
        if tf <= 0 or doc_length <= 0 or avg_doc_length <= 0:
            return 0.0
        denom = tf + self.k1 * (1.0 - self.b + self.b * (doc_length / avg_doc_length))
        if denom <= 0:
            return 0.0
        return idf * (tf * (self.k1 + 1.0)) / denom

    def score_query(
        self,
        query_tokens: Iterable[str],
        postings: Mapping[str, Mapping],
        chunk_meta: Mapping[str, dict],
        *,
        matched_terms_out: dict | None = None,
    ) -> list[Score]:
        """Score ``query_tokens`` against the in-memory index.

        Parameters
        ----------
        query_tokens:
            Iterable of query tokens (typically ``tokenize(query)``).
        postings:
            ``{term: {"df": int, "postings": [{"chunk_id": ...,
            "tf": ...}, ...]}}``. Each value is a small dict with
            a ``df`` count and a ``postings`` list. The postings
            are sorted by ``(tf desc, chunk_id asc)`` at index
            time; the scorer does not re-sort them.
        chunk_meta:
            ``{chunk_id: {"doc_length": int, ...}}``. Must contain
            ``doc_length`` for every chunk referenced in
            ``postings``.
        matched_terms_out:
            Optional mutable dict. If provided, the scorer writes
            ``{chunk_id: set(matched_terms)}`` so the caller can
            include ``matched_terms`` in each :class:`SearchResult`
            without a second pass over the index.

        Returns
        -------
        list[Score]
            Scores sorted by ``(-score, chunk_id asc)``. The list
            is empty if ``query_tokens`` is empty or no query
            term appears in the index.
        """
        # Dedupe the query while preserving order.
        seen: set[str] = set()
        unique_tokens: list[str] = []
        for tok in query_tokens:
            if tok in seen:
                continue
            seen.add(tok)
            unique_tokens.append(tok)
        if not unique_tokens:
            return []
        if not postings:
            return []

        # Total document count: the union of chunk_ids in postings.
        all_chunk_ids: set[str] = set()
        for term, payload in postings.items():
            if not isinstance(payload, Mapping):
                continue
            for entry in payload.get("postings", []) or []:
                cid = entry.get("chunk_id")
                if cid:
                    all_chunk_ids.add(cid)
        n = len(all_chunk_ids)
        if n == 0:
            return []

        # Average doc length.
        lengths = [
            int(chunk_meta[cid].get("doc_length", 0))
            for cid in all_chunk_ids
            if cid in chunk_meta
        ]
        if not lengths:
            return []
        avg_doc_length = sum(lengths) / len(lengths)

        # Accumulate scores per chunk.
        scores: dict[str, float] = {}
        if matched_terms_out is not None:
            matched_terms_out.clear()
        for term in unique_tokens:
            payload = postings.get(term)
            if not payload:
                continue
            plist = payload.get("postings") if isinstance(payload, Mapping) else None
            if not plist:
                continue
            n_t = len(plist)
            idf = self.idf(n_t, n)
            if idf <= 0.0:
                continue
            for entry in plist:
                cid = entry.get("chunk_id")
                if not cid:
                    continue
                tf = int(entry.get("tf", 0))
                if tf <= 0:
                    continue
                meta = chunk_meta.get(cid) or {}
                doc_length = int(meta.get("doc_length", 0))
                contrib = self.score_term(tf, doc_length, avg_doc_length, idf)
                if contrib <= 0.0:
                    continue
                scores[cid] = scores.get(cid, 0.0) + contrib
                if matched_terms_out is not None:
                    bucket = matched_terms_out.setdefault(cid, set())
                    bucket.add(term)

        # Sort by (-score, chunk_id asc).
        scored = [Score(chunk_id=cid, score=s) for cid, s in scores.items()]
        scored.sort()
        return scored


__all__ = [
    "BM25_DEFAULT_B",
    "BM25_DEFAULT_K1",
    "BM25Scorer",
    "Score",
    "SearchResult",
]
