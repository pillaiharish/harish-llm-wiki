"""Chunk index foundation (Prompt 27).

The chunk index is a deterministic view over the per-resource chunk
files written by the normalizers (PDF, YouTube, webpage, markdown,
local transcript, local audio, local video). It projects the
source-specific chunk shapes into a single uniform record schema
that future search, retrieval, and Graph RAG features can consume.

Public API
----------

- :class:`ChunkIndexBuilder` and :func:`build_chunk_index` – build
  the in-memory index from registry records.
- :func:`write_chunk_index` and :func:`write_public_copy` – write
  the deterministic JSON/JSONL files to the data and site dirs.
- :func:`iter_chunk_index_issues` – re-validate the on-disk index
  and yield ``(severity, code, message)`` tuples.
- :class:`ChunkRecord`, :class:`SourceRef`, :class:`ChunkMetadata` –
  the public Pydantic models.
- :data:`CHUNK_INDEX_SCHEMA_VERSION` – the schema version string.

This module does **not** add BM25 search, vector search, embeddings,
or LLM call paths. Those belong to later prompts.
"""

from __future__ import annotations

from wiki.chunks.builder import (
    ChunkIndexBuilder,
    build_chunk_index,
    build_manifest,
    read_chunks_for_record,
)
from wiki.chunks.export import (
    chunk_index_output_paths,
    public_chunk_paths,
    write_chunk_index,
    write_public_copy,
)
from wiki.chunks.schema import (
    CHUNK_INDEX_SCHEMA_VERSION,
    ChunkIndexResult,
    ChunkMetadata,
    ChunkRecord,
    SourceRef,
)
from wiki.chunks.validate import iter_chunk_index_issues


__all__ = [
    "CHUNK_INDEX_SCHEMA_VERSION",
    "ChunkIndexResult",
    "ChunkMetadata",
    "ChunkRecord",
    "SourceRef",
    "ChunkIndexBuilder",
    "build_chunk_index",
    "build_manifest",
    "chunk_index_output_paths",
    "iter_chunk_index_issues",
    "public_chunk_paths",
    "read_chunks_for_record",
    "write_chunk_index",
    "write_public_copy",
]
