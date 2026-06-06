"""Pure-Python hashing TF-IDF vectorizer (Prompt 29).

The vectorizer is the deterministic local core of the vector search
backend. It does **not** import any third-party library; all math is
over plain ``dict[int, float]`` sparse vectors.

Pipeline
--------

For each chunk:

1. Tokenize ``text`` (weight 1.0), ``title`` (weight 2.0), and
   ``citation_label`` (weight 0.5) using the same tokenizer as the
   BM25 backend (:mod:`wiki.vector.tokenize`).
2. For each token, compute ``(dim, sign) = hash_token(token)``
   using the blake2b signed-feature-hash. Update the chunk's
   sparse vector at ``dim`` by ``sign * tf * idf[token]``.
3. L2-normalize the vector so cosine similarity is a dot product.

For each query:

1. Tokenize the query with the same tokenizer.
2. For each unique query token, compute ``(dim, sign)`` and
   accumulate ``sign * tf_q * idf[token]`` at ``dim``.
3. L2-normalize.

Hash function
-------------

A 64-bit blake2b digest of the token is interpreted as a
big-endian unsigned integer. The low 64 bits mod ``dimension``
yield the dimension index; the high bit (bit 63) is the sign.
The signed-feature-hash is the standard "hashing trick" of
Weinberger et al. (2009) - collisions cancel in expectation.

IDF formula
-----------

The Lucene-style, never-negative variant that the BM25 backend
uses:

    idf(t) = log((N - n_t + 0.5) / (n_t + 0.5) + 1)

``n_t`` is the number of chunks in which the term appears.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from wiki.vector.tokenize import tokenize


# =============================================================================
# Constants
# =============================================================================


#: Default hashing dimension. 1024 gives a good precision / memory
#: trade-off for the small corpora in this project.
DEFAULT_DIMENSION: int = 1024

#: Default minimum token length (passed to the tokenizer).
DEFAULT_MIN_TOKEN_LENGTH: int = 2

#: Default field weights for the per-field term frequencies. The
#: weights are applied at the term-frequency level (a token appearing
#: once in the title contributes 2.0 to the per-chunk counter).
DEFAULT_FIELD_WEIGHTS: dict[str, float] = {
    "text": 1.0,
    "title": 2.0,
    "citation_label": 0.5,
}

#: Hash family name (the only one this prompt ships).
HASH_FAMILY: str = "blake2b_signed"

#: Norm type (the only one this prompt ships; reserved for future
#: expansion).
NORM: str = "l2"


# =============================================================================
# Hash function
# =============================================================================


def _hash_dim(token: str, dimension: int) -> tuple[int, int]:
    """Return ``(dim, sign)`` for ``token``.

    The 64-bit blake2b digest of the token (UTF-8) is interpreted
    as a big-endian unsigned integer. ``dim = value % dimension``
    and ``sign = +1`` if bit 63 is 0, ``-1`` otherwise.
    """
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big", signed=False)
    dim = value % int(dimension)
    sign = 1 if (value >> 63) & 1 == 0 else -1
    return dim, sign


# =============================================================================
# Data classes
# =============================================================================


@dataclass(frozen=True)
class VectorizerConfig:
    """Immutable vectorizer configuration.

    A different configuration produces a different (incompatible)
    index, so the on-disk ``index.json`` records the configuration
    that was used to build it.
    """

    name: str = "hashing_tfidf"
    hash_family: str = HASH_FAMILY
    norm: str = NORM
    dimension: int = DEFAULT_DIMENSION
    min_token_length: int = DEFAULT_MIN_TOKEN_LENGTH
    drop_stopwords: bool = True
    drop_numeric: bool = False
    field_weights: dict = field(default_factory=lambda: dict(DEFAULT_FIELD_WEIGHTS))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "hash_family": self.hash_family,
            "norm": self.norm,
            "dimension": self.dimension,
            "min_token_length": self.min_token_length,
            "drop_stopwords": self.drop_stopwords,
            "drop_numeric": self.drop_numeric,
            "field_weights": dict(self.field_weights),
        }


@dataclass
class VectorizerState:
    """State learned from the corpus at index time.

    The state is part of the on-disk index; loading an index with
    a mismatched ``dimension`` raises ``ValueError``.
    """

    dimension: int
    idf: dict  # term -> float
    field_weights: dict

    def idf_for(self, term: str) -> float:
        """Return the IDF for ``term`` (0.0 if the term is OOV)."""
        return float(self.idf.get(term, 0.0))


# =============================================================================
# Vectorizer
# =============================================================================


@dataclass
class HashingTfidfVectorizer:
    """Deterministic, dependency-free hashing TF-IDF vectorizer.

    The vectorizer is a small dataclass. It does not import
    ``wiki.search`` (BM25); the only project import is
    :mod:`wiki.vector.tokenize`.

    Parameters
    ----------
    config:
        Override :class:`VectorizerConfig` defaults.
    """

    config: VectorizerConfig = field(default_factory=VectorizerConfig)

    # ----- Hash helpers ------------------------------------------------

    def hash_token(self, token: str) -> tuple[int, int]:
        """Return ``(dim, sign)`` for ``token``.

        This is a thin wrapper around the module-level
        :func:`_hash_dim` that uses the configured dimension.
        """
        return _hash_dim(token, self.config.dimension)

    # ----- Per-chunk term frequencies -----------------------------------

    def _per_field_term_counts(
        self,
        text: str = "",
        title: str = "",
        citation_label: str = "",
    ) -> Counter:
        """Build the merged per-chunk ``Counter`` of token frequencies.

        Each field's tokens are counted with the field's weight
        (rounded to int). The merged counter is the input to the
        IDF + hashing-vector build.
        """
        merged: Counter = Counter()
        weights = self.config.field_weights
        for field_name, content, weight in (
            ("text", text or "", float(weights.get("text", 1.0))),
            ("title", title or "", float(weights.get("title", 2.0))),
            ("citation_label", citation_label or "", float(weights.get("citation_label", 0.5))),
        ):
            if not content:
                continue
            tokens = tokenize(
                content,
                min_length=self.config.min_token_length,
                drop_stopwords=self.config.drop_stopwords,
                drop_numeric=self.config.drop_numeric,
            )
            if not tokens:
                continue
            counter: Counter = Counter()
            for tok in tokens:
                counter[tok] += 1
            if weight != 1.0:
                counter = Counter(
                    {tok: int(round(cnt * weight)) for tok, cnt in counter.items()}
                )
            merged.update(counter)
        return merged

    # ----- IDF ---------------------------------------------------------

    def fit_idf(
        self,
        per_chunk_term_counts: Sequence[Counter],
    ) -> dict[str, float]:
        """Compute the Lucene-style IDF table from per-chunk counts.

        Parameters
        ----------
        per_chunk_term_counts:
            A list of ``Counter`` objects, one per chunk. Each
            ``Counter`` has the merged weighted term frequencies
            for that chunk.

        Returns
        -------
        dict[str, float]
            ``{term: idf}`` for every term that appears in the
            corpus. Sorted by term in insertion order (the caller
            is expected to sort for on-disk output).
        """
        n = len(per_chunk_term_counts)
        if n == 0:
            return {}
        # Document frequency per term.
        df: Counter = Counter()
        for counter in per_chunk_term_counts:
            for term in counter.keys():
                df[term] += 1
        idf: dict[str, float] = {}
        for term, n_t in df.items():
            n_t = min(int(n_t), int(n))
            idf[term] = math.log((n - n_t + 0.5) / (n_t + 0.5) + 1.0)
        return idf

    # ----- Sparse vector helpers ---------------------------------------

    @staticmethod
    def _l2_normalize(vec: dict[int, float]) -> dict[int, float]:
        """L2-normalize a sparse vector. Empty vector maps to empty."""
        if not vec:
            return {}
        norm = math.sqrt(sum(weight * weight for weight in vec.values()))
        if norm <= 0.0:
            return {}
        return {dim: weight / norm for dim, weight in vec.items()}

    @staticmethod
    def cosine(a: dict[int, float], b: dict[int, float]) -> float:
        """Cosine similarity of two sparse vectors.

        Both vectors are expected to be L2-normalized, in which
        case the cosine is the dot product. Empty vectors score
        ``0.0``.
        """
        if not a or not b:
            return 0.0
        # Iterate over the smaller side for a small constant-factor
        # speedup. Not asymptotically significant but cheaper for
        # the typical 1-5 token query.
        if len(a) > len(b):
            a, b = b, a
        return sum(weight * b.get(dim, 0.0) for dim, weight in a.items())

    # ----- Transform ---------------------------------------------------

    def _build_sparse(
        self,
        term_counts: Counter,
        idf_map: Mapping[str, float],
    ) -> dict[int, float]:
        """Build a sparse hashed-tfidf vector from per-chunk counts.

        The output is **not** L2-normalized; callers should
        normalize with :meth:`_l2_normalize` before scoring.
        """
        vec: dict[int, float] = {}
        for term, tf in term_counts.items():
            if tf <= 0:
                continue
            dim, sign = self.hash_token(term)
            weight = sign * float(tf) * float(idf_map.get(term, 0.0))
            if weight == 0.0:
                continue
            vec[dim] = vec.get(dim, 0.0) + weight
        return vec

    def transform_chunk(
        self,
        text: str,
        title: str,
        citation_label: str,
        state: VectorizerState,
    ) -> dict[int, float]:
        """Build a sparse L2-normalized vector for one chunk.

        Parameters
        ----------
        text, title, citation_label:
            The three field strings. Any of them may be empty.
        state:
            The :class:`VectorizerState` learned at index time.

        Returns
        -------
        dict[int, float]
            The L2-normalized sparse vector. Empty dict if the
            chunk produced no non-zero entries (e.g. all stopwords).
        """
        counts = self._per_field_term_counts(
            text=text, title=title, citation_label=citation_label
        )
        vec = self._build_sparse(counts, state.idf)
        return self._l2_normalize(vec)

    def transform_query(
        self,
        query_tokens: Iterable[str],
        state: VectorizerState,
    ) -> dict[int, float]:
        """Build a sparse L2-normalized query vector.

        Parameters
        ----------
        query_tokens:
            The tokenized query (typically ``tokenize(query)``).
        state:
            The :class:`VectorizerState` learned at index time.

        Returns
        -------
        dict[int, float]
            The L2-normalized sparse vector. Empty dict if the
            query produced no non-zero entries.
        """
        # Dedupe while preserving order, then accumulate.
        seen: set[str] = set()
        unique_tokens: list[str] = []
        for tok in query_tokens:
            if tok in seen:
                continue
            seen.add(tok)
            unique_tokens.append(tok)
        if not unique_tokens:
            return {}
        counts: Counter = Counter()
        for tok in unique_tokens:
            counts[tok] += 1
        vec = self._build_sparse(counts, state.idf)
        return self._l2_normalize(vec)


__all__ = [
    "DEFAULT_DIMENSION",
    "DEFAULT_FIELD_WEIGHTS",
    "DEFAULT_MIN_TOKEN_LENGTH",
    "HASH_FAMILY",
    "HashingTfidfVectorizer",
    "NORM",
    "VectorizerConfig",
    "VectorizerState",
]
