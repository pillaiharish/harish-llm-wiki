"""Build the BM25 inverted index from the chunk index (Prompt 28).

The index builder is a read-only consumer of the chunk index
produced by Prompt 27. It walks the in-memory
:class:`wiki.chunks.ChunkIndexResult` and produces an in-memory
inverted index suitable for the BM25 scorer.

Output structure
----------------

- ``vocab``: ``{term: {"df": int, "postings": [{"chunk_id":
  str, "tf": int}, ...]}}``. Postings are sorted by
  ``(tf desc, chunk_id asc)`` for deterministic iteration.
- ``chunk_meta``: ``{chunk_id: {resource_id, source_type,
  title, citation_label, resource_route, source_ref,
  doc_length, word_count}}``. Keys sorted alphabetically.
- ``avg_doc_length``: the average weighted virtual length.
- ``doc_count``: the number of chunks indexed.
- ``schema_version``: ``"bm25_index_v1"``.

The index is intentionally **not** Pydantic-typed at the
in-memory layer; the on-disk writer (:mod:`wiki.search.export`)
projects to plain dicts. This keeps the in-memory layer fast
and avoids a Pydantic round-trip on every rebuild.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional

from wiki.chunks import ChunkIndexResult, ChunkRecord
from wiki.search.tokenize import tokenize


# =============================================================================
# Constants
# =============================================================================


#: Field weights for the weighted virtual doc length and per-field
#: term frequency. Title terms get a 2.0 boost (high-signal),
#: citation labels get 0.5 (short, often duplicated).
DEFAULT_FIELD_WEIGHTS: dict[str, float] = {
    "text": 1.0,
    "title": 2.0,
    "citation_label": 0.5,
}

#: Character length at which we truncate ``text_preview`` to keep
#: the search-result preview byte-stable.
TEXT_PREVIEW_CHARS: int = 240


# =============================================================================
# Result envelope
# =============================================================================


@dataclass
class BM25IndexResult:
    """The in-memory BM25 index produced by :class:`BM25IndexBuilder`.

    The structure mirrors the on-disk layout so the writer is a
    thin projection. ``vocab`` and ``chunk_meta`` are already
    sorted at build time, so the on-disk writer does no further
    sorting.
    """

    schema_version: str = "bm25_index_v1"
    k1: float = 1.5
    b: float = 0.75
    field_weights: dict = field(default_factory=lambda: dict(DEFAULT_FIELD_WEIGHTS))
    avg_doc_length: float = 0.0
    doc_count: int = 0
    vocab: dict = field(default_factory=dict)
    chunk_meta: dict = field(default_factory=dict)

    def matched_terms(self, query_tokens: Iterable[str]) -> dict[str, list[str]]:
        """Return ``{chunk_id: sorted(matched_terms)}`` for a tokenized query.

        The function does not score; it only reports which terms
        of the query appear in each chunk. The order of the
        returned dict matches Python 3.7+ insertion order, but
        callers should not rely on it (use the keys directly).
        """
        unique = list(dict.fromkeys(query_tokens))
        matched: dict[str, list[str]] = {}
        for cid, meta in self.chunk_meta.items():
            # We approximate "matched terms" by checking which
            # query tokens appear in the chunk's text + title +
            # citation_label, using the tokenizer. This is more
            # honest than walking the postings (a query token
            # may match a chunk via a different field than
            # ``text``).
            text_blob = " ".join(
                [
                    str(meta.get("text", "") or ""),
                    str(meta.get("title", "") or ""),
                    str(meta.get("citation_label", "") or ""),
                ]
            )
            tokens = set(tokenize(text_blob))
            hits = sorted(t for t in unique if t in tokens)
            if hits:
                matched[cid] = hits
        return matched

    def text_preview(self, chunk_id: str) -> str:
        """Return a deterministic ``text_preview`` string for a chunk.

        The function is a method on the in-memory result so the
        search runtime does not have to re-read the chunk index.
        """
        meta = self.chunk_meta.get(chunk_id) or {}
        text = str(meta.get("text", "") or "")
        if not text:
            return ""
        return text[:TEXT_PREVIEW_CHARS]


# =============================================================================
# Builder
# =============================================================================


class BM25IndexBuilder:
    """Build a deterministic BM25 inverted index from chunk records.

    Parameters
    ----------
    field_weights:
        Override :data:`DEFAULT_FIELD_WEIGHTS`. Keys must be a
        subset of ``{"text", "title", "citation_label"}``.
    k1:
        BM25 k1 constant. Default 1.5.
    b:
        BM25 b constant. Default 0.75.
    min_token_length:
        Pass-through to :func:`wiki.search.tokenize.tokenize`.
    drop_stopwords:
        Pass-through to :func:`wiki.search.tokenize.tokenize`.
    """

    def __init__(
        self,
        *,
        field_weights: Optional[dict[str, float]] = None,
        k1: float = 1.5,
        b: float = 0.75,
        min_token_length: int = 2,
        drop_stopwords: bool = True,
    ) -> None:
        weights = dict(DEFAULT_FIELD_WEIGHTS)
        if field_weights:
            for k, v in field_weights.items():
                if k in weights:
                    weights[k] = float(v)
        self.field_weights = weights
        self.k1 = float(k1)
        self.b = float(b)
        self.min_token_length = int(min_token_length)
        self.drop_stopwords = bool(drop_stopwords)

    def build(self, chunk_index: ChunkIndexResult) -> BM25IndexResult:
        """Build the BM25 index from a :class:`ChunkIndexResult`.

        The function is pure: it does not write to disk. Call
        :func:`wiki.search.export.write_bm25_index` to persist.
        """
        vocab: dict[str, dict] = {}
        chunk_meta: dict[str, dict] = {}
        doc_lengths: list[int] = []

        for chunk in chunk_index.chunks:
            cid = chunk.chunk_id
            if not cid:
                continue
            text = chunk.text or ""
            title = chunk.title or ""
            citation_label = chunk.citation_label or ""

            # Per-field term frequencies.
            tf_by_field: dict[str, Counter] = {}
            for field_name, content, weight in (
                ("text", text, self.field_weights.get("text", 1.0)),
                ("title", title, self.field_weights.get("title", 1.0)),
                ("citation_label", citation_label, self.field_weights.get("citation_label", 0.5)),
            ):
                if not content:
                    continue
                tokens = tokenize(
                    content,
                    min_length=self.min_token_length,
                    drop_stopwords=self.drop_stopwords,
                )
                if not tokens:
                    continue
                counter: Counter = Counter()
                for tok in tokens:
                    counter[tok] += 1
                if weight != 1.0:
                    counter = Counter(
                        {tok: round(cnt * weight) for tok, cnt in counter.items()}
                    )
                tf_by_field[field_name] = counter

            # Merge into a single per-chunk counter.
            merged: Counter = Counter()
            for counter in tf_by_field.values():
                merged.update(counter)
            if not merged:
                # Chunk contributes nothing to the index. We still
                # record its meta so callers can report it.
                weighted_len = 0
            else:
                # Weighted virtual doc length.
                weighted_len = int(
                    sum(
                        round(
                            self.field_weights.get(fname, 1.0) * sum(counter.values())
                        )
                        for fname, counter in tf_by_field.items()
                    )
                )
            doc_lengths.append(weighted_len)
            chunk_meta[cid] = {
                "chunk_id": cid,
                "resource_id": chunk.resource_id,
                "source_type": chunk.source_type,
                "title": title,
                "citation_label": citation_label,
                "resource_route": chunk.resource_route,
                "source_ref": chunk.source_ref.model_dump(),
                "doc_length": weighted_len,
                "word_count": chunk.word_count,
                "text": text,
            }
            # Update postings.
            for term, tf in merged.items():
                bucket = vocab.setdefault(term, {"df": 0, "postings": []})
                bucket["postings"].append({"chunk_id": cid, "tf": int(tf)})

        # Finalize: df counts and sort postings.
        for term, payload in vocab.items():
            payload["df"] = len(payload["postings"])
            payload["postings"].sort(
                key=lambda p: (-int(p["tf"]), str(p["chunk_id"]))
            )

        # Sort vocab keys; chunk_meta keys.
        sorted_vocab = {term: vocab[term] for term in sorted(vocab.keys())}
        sorted_meta = {cid: chunk_meta[cid] for cid in sorted(chunk_meta.keys())}

        avg_doc_length = (
            sum(doc_lengths) / len(doc_lengths) if doc_lengths else 0.0
        )

        return BM25IndexResult(
            schema_version="bm25_index_v1",
            k1=self.k1,
            b=self.b,
            field_weights=dict(self.field_weights),
            avg_doc_length=avg_doc_length,
            doc_count=len(chunk_meta),
            vocab=sorted_vocab,
            chunk_meta=sorted_meta,
        )


# =============================================================================
# Module-level helpers
# =============================================================================


def build_bm25_index(
    chunk_index: ChunkIndexResult,
    *,
    field_weights: Optional[dict[str, float]] = None,
    k1: float = 1.5,
    b: float = 0.75,
) -> BM25IndexResult:
    """Build the BM25 index in one call.

    Thin wrapper around :class:`BM25IndexBuilder`.
    """
    builder = BM25IndexBuilder(
        field_weights=field_weights, k1=k1, b=b
    )
    return builder.build(chunk_index)


def load_bm25_index(index_path: str | Any) -> BM25IndexResult:
    """Load a BM25 index from a JSON file on disk.

    Used by the CLI search command. Returns an in-memory
    :class:`BM25IndexResult`. The function reads the JSON
    file, validates the schema version, and rehydrates the
    dataclass.

    Raises
    ------
    FileNotFoundError
        If the index file does not exist.
    ValueError
        If the schema version is not ``bm25_index_v1`` or the
        JSON is malformed.
    """
    from pathlib import Path
    from wiki.search.export import BM25_SCHEMA_VERSION

    path = Path(index_path)
    if not path.exists():
        raise FileNotFoundError(f"BM25 index not found: {path}")
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(
            f"BM25 index root is not a dict: {type(payload).__name__}"
        )
    schema_version = payload.get("schema_version")
    if schema_version != BM25_SCHEMA_VERSION:
        raise ValueError(
            f"Unexpected BM25 schema_version: {schema_version!r} "
            f"(expected {BM25_SCHEMA_VERSION!r})"
        )
    return BM25IndexResult(
        schema_version=schema_version,
        k1=float(payload.get("k1", 1.5)),
        b=float(payload.get("b", 0.75)),
        field_weights=dict(payload.get("field_weights") or {}),
        avg_doc_length=float(payload.get("avg_doc_length", 0.0)),
        doc_count=int(payload.get("doc_count", 0)),
        vocab=dict(payload.get("vocab") or {}),
        chunk_meta=dict(payload.get("chunk_meta") or {}),
    )


__all__ = [
    "BM25IndexBuilder",
    "BM25IndexResult",
    "DEFAULT_FIELD_WEIGHTS",
    "TEXT_PREVIEW_CHARS",
    "build_bm25_index",
    "load_bm25_index",
]
