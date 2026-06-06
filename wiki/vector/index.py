"""Build the deterministic vector index from the chunk index (Prompt 29).

The vector index builder is a read-only consumer of the chunk index
produced by :mod:`wiki.chunks`. It walks the in-memory
:class:`wiki.chunks.ChunkIndexResult` and produces an in-memory
:class:`VectorIndexResult` suitable for the cosine-similarity
search runtime.

Output structure
----------------

- ``state``: :class:`wiki.vector.vectorizer.VectorizerState` - the
  IDF table and dimension learned at index time.
- ``config``: :class:`wiki.vector.vectorizer.VectorizerConfig` -
  the vectorizer configuration.
- ``vectors``: ``{chunk_id: {"entries": {dim: weight}, "norm":
  float, "resource_id": str, "source_type": str, "title": str,
  "citation_label": str, "resource_route": str, "source_ref":
  dict, "text_preview": str, "word_count": int}}``. ``norm`` is
  always ``1.0`` for L2-normalized vectors but is stored explicitly
  so the schema can later support unnormalized representations
  without a break.
- ``chunk_count``: number of chunks indexed.
- ``resource_count``: number of distinct resource ids.
- ``schema_version``: ``"vector_index_v1"``.

The index is intentionally **not** Pydantic-typed at the
in-memory layer; the on-disk writer (:mod:`wiki.vector.export`)
projects to plain dicts. This keeps the in-memory layer fast
and avoids a Pydantic round-trip on every rebuild.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Sequence

from wiki.chunks import ChunkIndexResult, ChunkRecord
from wiki.vector.vectorizer import (
    DEFAULT_FIELD_WEIGHTS,
    HashingTfidfVectorizer,
    VectorizerConfig,
    VectorizerState,
)


# =============================================================================
# Constants
# =============================================================================


#: Default text-preview length for ``text_preview`` stored in the
#: index. Mirrors the BM25 backend's value
#: (``wiki.search.index.TEXT_PREVIEW_CHARS``) so the two backends
#: produce the same preview length.
TEXT_PREVIEW_CHARS: int = 240


# =============================================================================
# Result envelope
# =============================================================================


@dataclass
class VectorIndexResult:
    """The in-memory vector index produced by :class:`VectorIndexBuilder`.

    The structure mirrors the on-disk layout so the writer is a
    thin projection.
    """

    schema_version: str = "vector_index_v1"
    config: VectorizerConfig = field(default_factory=VectorizerConfig)
    state: Optional[VectorizerState] = None
    chunk_count: int = 0
    resource_count: int = 0
    vocab_size: int = 0
    total_nnz: int = 0
    vectors: dict = field(default_factory=dict)
    chunk_meta: dict = field(default_factory=dict)

    def text_preview(self, chunk_id: str) -> str:
        """Return a deterministic ``text_preview`` string for a chunk.

        Empty if the chunk has no text or is not in the index.
        """
        meta = self.chunk_meta.get(chunk_id) or {}
        text = str(meta.get("text", "") or "")
        if not text:
            return ""
        if len(text) <= TEXT_PREVIEW_CHARS:
            return text
        return text[:TEXT_PREVIEW_CHARS]


# =============================================================================
# Builder
# =============================================================================


class VectorIndexBuilder:
    """Build a deterministic vector index from chunk records.

    Parameters
    ----------
    config:
        Override :class:`VectorizerConfig` defaults. A different
        ``dimension`` or ``field_weights`` produces a different
        (incompatible) index.
    min_token_length:
        Pass-through to the tokenizer.
    drop_stopwords:
        Pass-through to the tokenizer.
    """

    def __init__(
        self,
        *,
        config: Optional[VectorizerConfig] = None,
        min_token_length: int = 2,
        drop_stopwords: bool = True,
    ) -> None:
        if config is None:
            config = VectorizerConfig(
                min_token_length=min_token_length,
                drop_stopwords=drop_stopwords,
            )
        else:
            # Allow callers to override min_token_length /
            # drop_stopwords even when they passed a config.
            if min_token_length != 2:
                config = VectorizerConfig(
                    **{**config.to_dict(), "min_token_length": int(min_token_length)}
                )
            if not drop_stopwords:
                config = VectorizerConfig(
                    **{**config.to_dict(), "drop_stopwords": bool(drop_stopwords)}
                )
        self.config = config
        self.vectorizer = HashingTfidfVectorizer(config=config)

    def build(self, chunk_index: ChunkIndexResult) -> VectorIndexResult:
        """Build the vector index from a :class:`ChunkIndexResult`.

        The function is pure: it does not write to disk. Call
        :func:`wiki.vector.export.write_vector_index` to persist.
        """
        vectors: dict[str, dict] = {}
        chunk_meta: dict[str, dict] = {}
        per_chunk_term_counts: List[Counter] = []

        for chunk in chunk_index.chunks:
            cid = chunk.chunk_id
            if not cid:
                continue
            text = chunk.text or ""
            title = chunk.title or ""
            citation_label = chunk.citation_label or ""
            counts = self.vectorizer._per_field_term_counts(
                text=text,
                title=title,
                citation_label=citation_label,
            )
            per_chunk_term_counts.append(counts)

            chunk_meta[cid] = {
                "chunk_id": cid,
                "resource_id": chunk.resource_id,
                "source_type": chunk.source_type,
                "title": title,
                "citation_label": citation_label,
                "resource_route": chunk.resource_route,
                "source_ref": chunk.source_ref.model_dump(),
                "word_count": chunk.word_count,
                "char_count": chunk.char_count,
                "text": text,
            }

        # Learn the IDF table.
        idf_map = self.vectorizer.fit_idf(per_chunk_term_counts)
        state = VectorizerState(
            dimension=self.config.dimension,
            idf=dict(idf_map),
            field_weights=dict(self.config.field_weights),
        )

        # Second pass: build sparse L2-normalized vectors.
        total_nnz = 0
        for chunk, counts in zip(chunk_index.chunks, per_chunk_term_counts):
            cid = chunk.chunk_id
            if not cid:
                continue
            vec = self.vectorizer._build_sparse(counts, state.idf)
            vec = self.vectorizer._l2_normalize(vec)
            vectors[cid] = {
                "entries": vec,
                "norm": math_sqrt_sum(vec),
                "resource_id": chunk.resource_id,
                "source_type": chunk.source_type,
                "title": chunk.title or "",
                "citation_label": chunk.citation_label or "",
                "resource_route": chunk.resource_route,
                "source_ref": chunk.source_ref.model_dump(),
                "text_preview": (
                    (chunk.text or "")[:TEXT_PREVIEW_CHARS]
                ),
            }
            total_nnz += len(vec)

        # Distinct resource count.
        resource_ids: set[str] = set()
        for meta in chunk_meta.values():
            rid = str(meta.get("resource_id", ""))
            if rid:
                resource_ids.add(rid)

        return VectorIndexResult(
            schema_version="vector_index_v1",
            config=self.config,
            state=state,
            chunk_count=len(vectors),
            resource_count=len(resource_ids),
            vocab_size=len(idf_map),
            total_nnz=total_nnz,
            vectors=vectors,
            chunk_meta=chunk_meta,
        )


# =============================================================================
# Local helpers
# =============================================================================


def math_sqrt_sum(vec: dict[int, float]) -> float:
    """Return the L2 norm of a sparse vector (0.0 for empty)."""
    if not vec:
        return 0.0
    import math

    return math.sqrt(sum(weight * weight for weight in vec.values()))


# =============================================================================
# Module-level helpers
# =============================================================================


def build_vector_index(
    chunk_index: ChunkIndexResult,
    *,
    config: Optional[VectorizerConfig] = None,
    min_token_length: int = 2,
    drop_stopwords: bool = True,
) -> VectorIndexResult:
    """Build the vector index in one call.

    Thin wrapper around :class:`VectorIndexBuilder`.
    """
    builder = VectorIndexBuilder(
        config=config,
        min_token_length=min_token_length,
        drop_stopwords=drop_stopwords,
    )
    return builder.build(chunk_index)


def load_vector_index(index_path) -> VectorIndexResult:
    """Load a vector index from a JSON file on disk.

    Used by the CLI search command. Returns an in-memory
    :class:`VectorIndexResult`. The function reads the JSON file,
    validates the schema version and dimension, and rehydrates the
    dataclass.

    Raises
    ------
    FileNotFoundError
        If the index file does not exist.
    ValueError
        If the schema version is not ``vector_index_v1``, the
        dimension is non-positive, or the JSON is malformed.
    """
    from pathlib import Path

    path = Path(index_path)
    if not path.exists():
        raise FileNotFoundError(f"Vector index not found: {path}")
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(
            f"Vector index root is not a dict: {type(payload).__name__}"
        )
    schema_version = payload.get("schema_version")
    if schema_version != "vector_index_v1":
        raise ValueError(
            f"Unexpected vector schema_version: {schema_version!r} "
            f"(expected 'vector_index_v1')"
        )

    raw_config = payload.get("vectorizer") or {}
    dimension = int(raw_config.get("dimension", 0))
    if dimension <= 0:
        raise ValueError(
            f"Vector index dimension is not positive: {dimension!r}"
        )

    config = VectorizerConfig(
        name=str(raw_config.get("name", "hashing_tfidf")),
        hash_family=str(raw_config.get("hash_family", "blake2b_signed")),
        norm=str(raw_config.get("norm", "l2")),
        dimension=dimension,
        min_token_length=int(raw_config.get("min_token_length", 2)),
        drop_stopwords=bool(raw_config.get("drop_stopwords", True)),
        drop_numeric=bool(raw_config.get("drop_numeric", False)),
        field_weights=dict(raw_config.get("field_weights") or DEFAULT_FIELD_WEIGHTS),
    )

    idf_map = dict(payload.get("idf") or {})
    state = VectorizerState(
        dimension=dimension,
        idf=idf_map,
        field_weights=dict(config.field_weights),
    )

    vectors_raw = payload.get("vectors") or {}
    vectors: dict = {}
    chunk_meta: dict = {}
    if isinstance(vectors_raw, dict):
        for cid, entry in vectors_raw.items():
            if not isinstance(entry, dict):
                continue
            entries_raw = entry.get("entries") or {}
            # Convert string keys back to int (JSON limitation).
            entries: dict = {}
            if isinstance(entries_raw, dict):
                for k, v in entries_raw.items():
                    try:
                        entries[int(k)] = float(v)
                    except (TypeError, ValueError):
                        continue
            vectors[cid] = {
                "entries": entries,
                "norm": float(entry.get("norm", 0.0)),
                "resource_id": str(entry.get("resource_id", "")),
                "source_type": str(entry.get("source_type", "")),
                "title": str(entry.get("title", "")),
                "citation_label": str(entry.get("citation_label", "")),
                "resource_route": str(entry.get("resource_route", "")),
                "source_ref": dict(entry.get("source_ref") or {}),
                "text_preview": str(entry.get("text_preview", "")),
            }
            chunk_meta[cid] = {
                "chunk_id": cid,
                "resource_id": str(entry.get("resource_id", "")),
                "source_type": str(entry.get("source_type", "")),
                "title": str(entry.get("title", "")),
                "citation_label": str(entry.get("citation_label", "")),
                "resource_route": str(entry.get("resource_route", "")),
                "source_ref": dict(entry.get("source_ref") or {}),
                "text": str(entry.get("text_preview", "")),
            }

    return VectorIndexResult(
        schema_version=schema_version,
        config=config,
        state=state,
        chunk_count=int(payload.get("chunk_count", 0)),
        resource_count=int(payload.get("resource_count", 0)),
        vocab_size=int(payload.get("vocab_size", 0)),
        total_nnz=int(payload.get("total_nnz", 0)),
        vectors=vectors,
        chunk_meta=chunk_meta,
    )


__all__ = [
    "DEFAULT_FIELD_WEIGHTS",
    "TEXT_PREVIEW_CHARS",
    "VectorIndexBuilder",
    "VectorIndexResult",
    "build_vector_index",
    "load_vector_index",
]
