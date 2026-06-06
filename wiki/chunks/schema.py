"""Pydantic schemas for the deterministic chunk index (Prompt 27).

The chunk index is a uniform view over the per-resource ``chunks.jsonl``
files written by the normalizers (PDF, YouTube, webpage, markdown,
local transcript, local audio, local video). It projects the
source-specific chunk shapes into a single record schema that future
search, retrieval, and Graph RAG features can consume.

The schema is intentionally append-only: every required field is always
present, but unknown source-specific keys are preserved in the
``metadata`` bag.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


# =============================================================================
# Schema version constant
# =============================================================================

CHUNK_INDEX_SCHEMA_VERSION: str = "chunk_index_v1"


# =============================================================================
# Source reference (tagged union over per-source shapes)
# =============================================================================


class SourceRef(BaseModel):
    """Tagged source-specific reference for a chunk.

    The ``kind`` field discriminates the shape:

    - ``pdf_pages``: page_start / page_end / file_path
    - ``youtube_time``: start_seconds / end_seconds / url
    - ``local_time``: start_seconds / end_seconds / source_url
    - ``webpage_section``: section_title / paragraph_index / source_url
    - ``markdown_section``: section_title / paragraph_index / file_path
    """

    kind: str
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    file_path: Optional[str] = None
    start_seconds: Optional[float] = None
    end_seconds: Optional[float] = None
    url: Optional[str] = None
    source_url: Optional[str] = None
    section_title: Optional[str] = None
    paragraph_index: Optional[int] = None

    @model_validator(mode="after")
    def _check_kind_specific_fields(self) -> "SourceRef":
        """Sanity-check that ``kind`` is one of the known values.

        The actual per-kind field requirements are deliberately soft:
        missing optional fields are tolerated because the underlying
        normalizer may not have produced them. The shape of
        ``SourceRef`` is intentionally flat (rather than a strict
        Pydantic discriminated union) to keep Pydantic v2 round-trips
        lossless for unknown keys.
        """
        allowed = {
            "pdf_pages",
            "youtube_time",
            "local_time",
            "webpage_section",
            "markdown_section",
        }
        if self.kind not in allowed:
            raise ValueError(
                f"Unknown SourceRef.kind: {self.kind!r} (allowed: {sorted(allowed)})"
            )
        return self


# =============================================================================
# Source-agnostic metadata bag
# =============================================================================


class ChunkMetadata(BaseModel):
    """Source-agnostic metadata bag.

    Required keys for which no value is available are set to ``None``
    (or empty list), not omitted, so the field is always present.
    """

    source_url: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    extraction_method: Optional[str] = None
    extraction_warnings: List[str] = Field(default_factory=list)
    # Any other keys preserved on round-trip live in ``extra``.
    extra: dict = Field(default_factory=dict)


# =============================================================================
# Chunk record (the public index entry)
# =============================================================================


class ChunkRecord(BaseModel):
    """A single uniform chunk record in the chunk index.

    Required fields are always present; ``resource_route`` and
    ``content_hash`` are derived from the record and the chunk text
    respectively. The schema is the contract that future search
    features (BM25, vector, graph retriever, hybrid router) consume.
    """

    chunk_id: str
    resource_id: str
    source_type: str
    title: str
    text: str
    citation_label: str
    source_ref: SourceRef
    resource_route: str = ""
    char_count: int
    word_count: int
    token_estimate: int
    chunk_index: int
    content_hash: str
    metadata: ChunkMetadata

    @model_validator(mode="after")
    def _check_required_fields(self) -> "ChunkRecord":
        if not self.text:
            raise ValueError("ChunkRecord.text must be non-empty")
        if not self.citation_label:
            raise ValueError("ChunkRecord.citation_label must be non-empty")
        if not self.chunk_id:
            raise ValueError("ChunkRecord.chunk_id must be non-empty")
        if not self.resource_id:
            raise ValueError("ChunkRecord.resource_id must be non-empty")
        if self.char_count < 0:
            raise ValueError("ChunkRecord.char_count must be non-negative")
        if self.word_count < 0:
            raise ValueError("ChunkRecord.word_count must be non-negative")
        if self.token_estimate < 0:
            raise ValueError("ChunkRecord.token_estimate must be non-negative")
        if self.chunk_index < 0:
            raise ValueError("ChunkRecord.chunk_index must be non-negative")
        return self


# =============================================================================
# Result envelope
# =============================================================================


class ChunkIndexResult(BaseModel):
    """The in-memory result of a chunk-index build.

    The builder collects the full chunk list, a per-resource summary
    used to render the manifest, and any warnings emitted during the
    build (missing chunk files, malformed JSON, etc.). Warnings are
    informational; they never cause the build to fail.
    """

    chunks: List[ChunkRecord] = Field(default_factory=list)
    by_resource: dict = Field(default_factory=dict)
    manifest: dict = Field(default_factory=dict)
    warnings: List[dict] = Field(default_factory=list)
    # Per-resource counts (resource_id -> int). Kept separate from the
    # manifest for callers that need only the map.
    chunk_count_by_resource: dict = Field(default_factory=dict)


__all__ = [
    "CHUNK_INDEX_SCHEMA_VERSION",
    "SourceRef",
    "ChunkMetadata",
    "ChunkRecord",
    "ChunkIndexResult",
]
