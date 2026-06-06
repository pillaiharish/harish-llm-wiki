"""Build the deterministic chunk index from registry records.

The builder walks the registry, looks up each record's
``local_normalized_path``, reads the per-resource ``chunks.jsonl``
(or the ``processed/pdfs/<hash>/chunks.json`` mirror for PDFs) and
projects the source-specific chunk shape into a uniform
:class:`ChunkRecord`. The resulting list is sorted by
``(resource_id, source_type, chunk_index, chunk_id)`` and returned
inside a :class:`ChunkIndexResult` envelope.

Determinism rules
-----------------

1. Resources are walked in sorted ``record.id`` order.
2. Within a resource, chunks are read in the order they appear in
   the per-source ``chunks.jsonl`` (which is byte-stable).
3. The flat chunk list is sorted by
   ``(resource_id, source_type, chunk_index, chunk_id)`` so the
   output is independent of the order in which the registry
   returned the records.
4. The builder does **not** invent chunk IDs; it reuses the
   source-specific ``chunk_id`` already on disk.
5. The builder does **not** re-chunk content. It is a reader of the
   existing per-resource chunk files.

Missing-chunk-file policy
-------------------------

If a record has no ``local_normalized_path`` (typical for records
that have not been normalized yet), the builder emits a warning and
skips the record. It does not raise. This is the "no useful data,
keep going" rule shared with the knowledge graph builder.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, List, Optional

from wiki.config import config
from wiki.generate.page_utils import resource_route
from wiki.schemas import ResourceRecord, SourceType
from wiki.chunks.schema import (
    ChunkIndexResult,
    ChunkMetadata,
    ChunkRecord,
    SourceRef,
)


# =============================================================================
# Constants
# =============================================================================


#: Source types that use the ``chunks.jsonl`` produced by the local
#: transcript / media normalizer.
_TRANSCRIPT_SOURCES = {
    SourceType.LOCAL_TRANSCRIPT,
    SourceType.LOCAL_AUDIO,
    SourceType.LOCAL_VIDEO,
}


#: Token estimate divisor (chars per token). Coarse, deterministic,
#: no tokenizer dependency. The 1/4 heuristic is documented in the
#: plan and is good enough for downstream BM25 / hybrid ranking
#: heuristics in future prompts.
_TOKEN_CHARS_PER_TOKEN: int = 4


# =============================================================================
# ChunkIndexBuilder
# =============================================================================


class ChunkIndexBuilder:
    """Build a deterministic chunk index from registry records.

    The builder is intentionally small. It does no re-chunking; it
    reads the existing per-source ``chunks.jsonl`` files (or the
    ``processed/pdfs/<hash>/chunks.json`` mirror for PDFs) and emits
    a uniform :class:`ChunkRecord` for every chunk line.

    Parameters
    ----------
    data_dir:
        Override the data directory. Defaults to
        ``config.LLM_WIKI_DATA_DIR``. Tests may rebind this.
    include_source_types:
        Optional iterable of source-type values to include. When set,
        only records whose ``source_type.value`` is in the iterable
        are indexed.
    resource_id:
        Optional single resource id. When set, only that record is
        indexed.
    limit:
        Optional cap on the number of resources processed. The cap
        is applied after sorting and filtering.
    """

    def __init__(
        self,
        *,
        data_dir: Optional[Path] = None,
        include_source_types: Optional[Iterable[str]] = None,
        resource_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> None:
        self.data_dir = data_dir or config.LLM_WIKI_DATA_DIR
        self.include_source_types: Optional[set[str]] = (
            set(include_source_types) if include_source_types is not None else None
        )
        self.resource_id = resource_id
        self.limit = limit

    # ------------------------------------------------------------------ public

    def build(self, records: Iterable[ResourceRecord]) -> ChunkIndexResult:
        """Build the index and return a :class:`ChunkIndexResult`.

        The function never raises on missing chunk files. It always
        returns a valid result envelope with the warnings list
        populated. Empty input produces a valid empty index.
        """
        records = self._filter_records(list(records))

        all_chunks: List[ChunkRecord] = []
        warnings: List[dict] = []
        chunk_count_by_resource: dict[str, int] = {}

        for record in records:
            try:
                record_chunks = read_chunks_for_record(record, data_dir=self.data_dir)
            except _ChunkReadError as exc:
                warnings.append(
                    {
                        "resource_id": record.id,
                        "code": exc.code,
                        "message": str(exc),
                    }
                )
                record_chunks = []

            # Dedupe by chunk_id within the resource (first-seen wins).
            seen_chunk_ids: set[str] = set()
            for chunk in record_chunks:
                if chunk.chunk_id in seen_chunk_ids:
                    warnings.append(
                        {
                            "resource_id": record.id,
                            "code": "duplicate_chunk_id",
                            "message": (
                                f"Duplicate chunk_id {chunk.chunk_id!r} within "
                                f"resource {record.id!r}; keeping first occurrence"
                            ),
                        }
                    )
                    continue
                seen_chunk_ids.add(chunk.chunk_id)
                all_chunks.append(chunk)

            chunk_count_by_resource[record.id] = len(record_chunks)

        # Cross-resource dedup of duplicate chunk IDs (first-seen wins,
        # preserving the resource-sorted order).
        deduped: List[ChunkRecord] = []
        seen_chunk_ids: set[str] = set()
        for chunk in all_chunks:
            if chunk.chunk_id in seen_chunk_ids:
                warnings.append(
                    {
                        "resource_id": chunk.resource_id,
                        "code": "duplicate_chunk_id",
                        "message": (
                            f"Duplicate chunk_id {chunk.chunk_id!r} across "
                            f"resources; keeping first occurrence"
                        ),
                    }
                )
                continue
            seen_chunk_ids.add(chunk.chunk_id)
            deduped.append(chunk)

        # Final deterministic sort.
        deduped.sort(
            key=lambda c: (
                c.resource_id,
                c.source_type,
                c.chunk_index,
                c.chunk_id,
            )
        )

        manifest = build_manifest(deduped, warnings)
        return ChunkIndexResult(
            chunks=deduped,
            by_resource={
                entry["resource_id"]: entry["chunk_count"]
                for entry in manifest["by_resource"]
            },
            manifest=manifest,
            warnings=warnings,
            chunk_count_by_resource=chunk_count_by_resource,
        )

    # ------------------------------------------------------------------ helpers

    def _filter_records(
        self, records: List[ResourceRecord]
    ) -> List[ResourceRecord]:
        if self.resource_id is not None:
            records = [r for r in records if r.id == self.resource_id]
        if self.include_source_types is not None:
            records = [
                r
                for r in records
                if r.source_type.value in self.include_source_types
            ]
        records.sort(key=lambda r: r.id)
        if self.limit is not None:
            records = records[: self.limit]
        return records


# =============================================================================
# Module-level helpers
# =============================================================================


def build_chunk_index(
    records: Iterable[ResourceRecord],
    *,
    data_dir: Optional[Path] = None,
    include_source_types: Optional[Iterable[str]] = None,
    resource_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> ChunkIndexResult:
    """Build the chunk index in one call.

    Thin wrapper around :class:`ChunkIndexBuilder`.
    """
    builder = ChunkIndexBuilder(
        data_dir=data_dir,
        include_source_types=include_source_types,
        resource_id=resource_id,
        limit=limit,
    )
    return builder.build(records)


class _ChunkReadError(Exception):
    """Internal exception for missing or malformed chunk files.

    Carries a stable ``code`` so the warning can be matched by tests
    and by ``validate()``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# -----------------------------------------------------------------------------
# Per-record readers
# -----------------------------------------------------------------------------


def read_chunks_for_record(
    record: ResourceRecord,
    *,
    data_dir: Optional[Path] = None,
) -> List[ChunkRecord]:
    """Read and project chunks for a single record.

    The reader is a thin dispatcher over the source-specific reader
    functions. The order of the returned chunks is the per-source
    natural order (page order for PDFs, time order for transcripts,
    section/paragraph order for text).
    """
    base = data_dir or config.LLM_WIKI_DATA_DIR
    if record.source_type == SourceType.PDF:
        return _read_pdf_chunks(record, data_dir=base)
    if record.source_type in _TRANSCRIPT_SOURCES:
        return _read_transcript_chunks(record, data_dir=base, kind="local_time")
    if record.source_type == SourceType.YOUTUBE:
        return _read_youtube_chunks(record, data_dir=base)
    if record.source_type == SourceType.WEBPAGE:
        return _read_webpage_chunks(record, data_dir=base)
    if record.source_type in {SourceType.MARKDOWN, SourceType.MEDIUM_MARKDOWN}:
        return _read_markdown_chunks(record, data_dir=base)
    # Unknown source type: skip with a warning. The builder collects
    # the warning and continues.
    raise _ChunkReadError(
        "unsupported_source_type",
        f"Unsupported source type for chunk index: {record.source_type.value!r}",
    )


def _read_pdf_chunks(
    record: ResourceRecord, *, data_dir: Path
) -> List[ChunkRecord]:
    """Read PDF chunks.

    Strategy: prefer the canonical mirror at
    ``processed/pdfs/<hash[:8]>/chunks.json`` (the source of truth
    the normalizer writes). Fall back to the normalizer's
    ``chunks.jsonl`` if the mirror is missing. If neither is found,
    emit a ``missing_chunks_file`` warning.
    """
    content_hash = record.content_hash or record.id.split(":", 1)[-1]
    mirror = data_dir / "processed" / "pdfs" / content_hash[:8] / "chunks.json"
    jsonl = (
        Path(record.local_normalized_path) / "chunks.jsonl"
        if record.local_normalized_path
        else None
    )

    raw_chunks: list[dict[str, Any]] = []
    if mirror.exists():
        try:
            payload = Storage_read_json(mirror)
        except (OSError, ValueError) as exc:
            raise _ChunkReadError(
                "malformed_chunks_file",
                f"Could not parse {mirror}: {exc}",
            ) from exc
        if isinstance(payload, list):
            raw_chunks = [item for item in payload if isinstance(item, dict)]
        else:
            raise _ChunkReadError(
                "malformed_chunks_file",
                f"{mirror} is not a list",
            )
    elif jsonl is not None and jsonl.exists():
        raw_chunks = _read_jsonl(jsonl)
    else:
        raise _ChunkReadError(
            "missing_chunks_file",
            f"PDF chunks file not found for {record.id} (looked in {mirror} and {jsonl})",
        )

    chunks: List[ChunkRecord] = []
    for raw in raw_chunks:
        try:
            page_start = int(raw.get("page_start", 0))
            page_end = int(raw.get("page_end", page_start))
        except (TypeError, ValueError):
            continue
        text = str(raw.get("text", "") or "")
        if not text:
            continue
        chunk_id = str(raw.get("chunk_id") or _build_pdf_chunk_id(record.id, page_start))
        citation_label = str(raw.get("citation_label") or f"page {page_start}")
        # Mirror the PDF's natural title from the record.
        title = record.title or str(raw.get("title") or record.id)
        file_path = (
            record.extra.get("original_path")
            or raw.get("file_path")
            or None
        )
        source_ref = SourceRef(
            kind="pdf_pages",
            page_start=page_start,
            page_end=page_end,
            file_path=str(file_path) if file_path else None,
        )
        metadata = _build_metadata(record)
        # PDFs preserve extraction_method in the PDF normalizer.
        if record.extra.get("extraction_method"):
            metadata.extraction_method = record.extra["extraction_method"]
        if record.extra.get("extraction_warnings"):
            metadata.extraction_warnings = list(record.extra["extraction_warnings"])

        chunks.append(
            _make_chunk_record(
                record=record,
                chunk_id=chunk_id,
                text=text,
                citation_label=citation_label,
                title=title,
                source_ref=source_ref,
                metadata=metadata,
                chunk_index=len(chunks),
            )
        )
    return chunks


def _read_transcript_chunks(
    record: ResourceRecord,
    *,
    data_dir: Path,
    kind: str,
) -> List[ChunkRecord]:
    """Read transcript / local-media chunks."""
    jsonl = (
        Path(record.local_normalized_path) / "chunks.jsonl"
        if record.local_normalized_path
        else None
    )
    if jsonl is None or not jsonl.exists():
        raise _ChunkReadError(
            "missing_chunks_file",
            f"Transcript chunks file not found for {record.id}",
        )
    raw_chunks = _read_jsonl(jsonl)

    chunks: List[ChunkRecord] = []
    for raw in raw_chunks:
        text = str(raw.get("text", "") or "")
        if not text:
            continue
        chunk_id = str(raw.get("chunk_id") or "")
        if not chunk_id:
            continue
        citation_label = str(raw.get("citation_label") or "")
        if not citation_label:
            citation_label = _format_timestamp_label(
                float(raw.get("start_time", 0.0) or 0.0),
                float(raw.get("end_time", raw.get("start_time", 0.0)) or 0.0),
            )
        start_seconds = _to_float(raw.get("start_time", 0.0))
        end_seconds = _to_float(raw.get("end_time", start_seconds))
        source_ref = SourceRef(
            kind=kind,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            source_url=record.original_url or None,
        )
        chunks.append(
            _make_chunk_record(
                record=record,
                chunk_id=chunk_id,
                text=text,
                citation_label=citation_label,
                title=record.title or record.id,
                source_ref=source_ref,
                metadata=_build_metadata(record),
                chunk_index=len(chunks),
            )
        )
    return chunks


def _read_youtube_chunks(
    record: ResourceRecord, *, data_dir: Path
) -> List[ChunkRecord]:
    """Read YouTube chunks."""
    jsonl = (
        Path(record.local_normalized_path) / "chunks.jsonl"
        if record.local_normalized_path
        else None
    )
    if jsonl is None or not jsonl.exists():
        raise _ChunkReadError(
            "missing_chunks_file",
            f"YouTube chunks file not found for {record.id}",
        )
    raw_chunks = _read_jsonl(jsonl)

    chunks: List[ChunkRecord] = []
    for raw in raw_chunks:
        text = str(raw.get("text", "") or "")
        if not text:
            continue
        chunk_id = str(raw.get("chunk_id") or "")
        if not chunk_id:
            continue
        citation_label = str(raw.get("citation_label") or "")
        if not citation_label:
            citation_label = _format_timestamp_label(
                float(raw.get("start_time", 0.0) or 0.0),
                float(raw.get("end_time", raw.get("start_time", 0.0)) or 0.0),
            )
        start_seconds = _to_float(raw.get("start_time", 0.0))
        end_seconds = _to_float(raw.get("end_time", start_seconds))
        url = (
            raw.get("url")
            or record.original_url
            or None
        )
        source_ref = SourceRef(
            kind="youtube_time",
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            url=str(url) if url else None,
        )
        chunks.append(
            _make_chunk_record(
                record=record,
                chunk_id=chunk_id,
                text=text,
                citation_label=citation_label,
                title=record.title or record.id,
                source_ref=source_ref,
                metadata=_build_metadata(record),
                chunk_index=len(chunks),
            )
        )
    return chunks


def _read_webpage_chunks(
    record: ResourceRecord, *, data_dir: Path
) -> List[ChunkRecord]:
    """Read webpage chunks."""
    jsonl = (
        Path(record.local_normalized_path) / "chunks.jsonl"
        if record.local_normalized_path
        else None
    )
    if jsonl is None or not jsonl.exists():
        raise _ChunkReadError(
            "missing_chunks_file",
            f"Webpage chunks file not found for {record.id}",
        )
    raw_chunks = _read_jsonl(jsonl)

    chunks: List[ChunkRecord] = []
    for raw in raw_chunks:
        text = str(raw.get("text", "") or "")
        if not text:
            continue
        chunk_id = str(raw.get("chunk_id") or "")
        if not chunk_id:
            continue
        citation_label = str(raw.get("citation_label") or "")
        if not citation_label:
            section = raw.get("section_heading")
            paragraph = raw.get("paragraph_index")
            if section and paragraph is not None:
                citation_label = f"{section}, paragraph {paragraph}"
            elif section:
                citation_label = str(section)
            elif paragraph is not None:
                citation_label = f"paragraph {paragraph}"
            else:
                citation_label = record.title or record.id
        source_ref = SourceRef(
            kind="webpage_section",
            section_title=str(raw.get("section_heading") or "") or None,
            paragraph_index=(
                int(raw["paragraph_index"])
                if isinstance(raw.get("paragraph_index"), int)
                else None
            ),
            source_url=record.original_url or None,
        )
        metadata = _build_metadata(record)
        chunks.append(
            _make_chunk_record(
                record=record,
                chunk_id=chunk_id,
                text=text,
                citation_label=citation_label,
                title=record.title or record.id,
                source_ref=source_ref,
                metadata=metadata,
                chunk_index=len(chunks),
            )
        )
    return chunks


def _read_markdown_chunks(
    record: ResourceRecord, *, data_dir: Path
) -> List[ChunkRecord]:
    """Read markdown / medium_markdown chunks."""
    jsonl = (
        Path(record.local_normalized_path) / "chunks.jsonl"
        if record.local_normalized_path
        else None
    )
    if jsonl is None or not jsonl.exists():
        raise _ChunkReadError(
            "missing_chunks_file",
            f"Markdown chunks file not found for {record.id}",
        )
    raw_chunks = _read_jsonl(jsonl)

    chunks: List[ChunkRecord] = []
    for raw in raw_chunks:
        text = str(raw.get("text", "") or "")
        if not text:
            continue
        chunk_id = str(raw.get("chunk_id") or "")
        if not chunk_id:
            continue
        citation_label = str(raw.get("citation_label") or "")
        if not citation_label:
            section = raw.get("section_heading")
            paragraph = raw.get("paragraph_index")
            if section and paragraph is not None:
                citation_label = f"{section}, paragraph {paragraph}"
            elif section:
                citation_label = str(section)
            elif paragraph is not None:
                citation_label = f"paragraph {paragraph}"
            else:
                citation_label = record.title or record.id
        source_ref = SourceRef(
            kind="markdown_section",
            section_title=str(raw.get("section_heading") or "") or None,
            paragraph_index=(
                int(raw["paragraph_index"])
                if isinstance(raw.get("paragraph_index"), int)
                else None
            ),
            file_path=str(raw.get("file_path") or "") or None,
        )
        chunks.append(
            _make_chunk_record(
                record=record,
                chunk_id=chunk_id,
                text=text,
                citation_label=citation_label,
                title=record.title or record.id,
                source_ref=source_ref,
                metadata=_build_metadata(record),
                chunk_index=len(chunks),
            )
        )
    return chunks


# -----------------------------------------------------------------------------
# Local helpers
# -----------------------------------------------------------------------------


def _make_chunk_record(
    *,
    record: ResourceRecord,
    chunk_id: str,
    text: str,
    citation_label: str,
    title: str,
    source_ref: SourceRef,
    metadata: ChunkMetadata,
    chunk_index: int,
) -> ChunkRecord:
    """Construct a :class:`ChunkRecord` and fill in the derived fields.

    The derived fields are:

    - ``char_count`` = ``len(text)``
    - ``word_count`` = ``len(text.split())``
    - ``token_estimate`` = ``round(char_count / 4)``
    - ``content_hash`` = ``sha256(text)``
    - ``resource_route`` = ``/resources/<id-with-colons-replaced-by-underscore>``
    - ``chunk_index`` = the 0-based position of this chunk within the
      resource, in the order produced by the source-specific reader.

    The caller (``read_chunks_for_record``) is expected to pass
    chunks in the source-specific natural order; this helper assigns
    the index from the caller. The builder then sorts the final list
    deterministically.
    """
    char_count = len(text)
    word_count = len(text.split())
    token_estimate = round(char_count / _TOKEN_CHARS_PER_TOKEN)
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return ChunkRecord(
        chunk_id=chunk_id,
        resource_id=record.id,
        source_type=record.source_type.value,
        title=title,
        text=text,
        citation_label=citation_label,
        source_ref=source_ref,
        resource_route=resource_route(record.id),
        char_count=char_count,
        word_count=word_count,
        token_estimate=token_estimate,
        chunk_index=chunk_index,
        content_hash=content_hash,
        metadata=metadata,
    )


def _build_metadata(record: ResourceRecord) -> ChunkMetadata:
    """Build a :class:`ChunkMetadata` from a resource record."""
    topics: list[str] = []
    return ChunkMetadata(
        source_url=record.original_url or None,
        tags=list(record.tags or []),
        topics=topics,
        extraction_method=None,
        extraction_warnings=[],
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file, ignoring blank lines. Malformed lines are skipped."""
    items: list[dict[str, Any]] = []
    if not path.exists():
        return items
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                items.append(payload)
    return items


def _build_pdf_chunk_id(resource_id: str, page_start: int) -> str:
    """Build a stable PDF chunk id when the normalizer didn't provide one."""
    return f"{resource_id}-p{page_start:04d}"


def _format_timestamp_label(start: float, end: float) -> str:
    """Format seconds as ``MM:SS-MM:SS`` (or ``HH:MM:SS-HH:MM:SS``)."""
    return f"{_format_timestamp(start)}-{_format_timestamp(end)}"


def _format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def Storage_read_json(path: Path) -> Any:
    """Read a JSON file using the project's Storage helper, with a defensive import."""
    from wiki.storage import Storage

    return Storage.read_json(path)


# -----------------------------------------------------------------------------
# Manifest builder
# -----------------------------------------------------------------------------


def build_manifest(
    chunks: List[ChunkRecord], warnings: List[dict]
) -> dict:
    """Build the deterministic manifest for the chunk index.

    The manifest shape matches ``prompt27.md``:

    - ``schema_version`` (string, e.g. ``chunk_index_v1``)
    - ``chunk_count`` (int)
    - ``resource_count`` (int)
    - ``by_source_type`` (dict of source_type -> chunk_count, sorted)
    - ``by_resource`` (list of per-resource entries, sorted by resource_id)
    - ``warnings`` (list of warning dicts, sorted by code + resource_id)

    No timestamps are included in the manifest; they live in
    ``stats.json`` (the only file allowed to drift between runs).
    """
    from wiki.chunks.schema import CHUNK_INDEX_SCHEMA_VERSION

    by_resource: dict[str, list[ChunkRecord]] = {}
    for chunk in chunks:
        by_resource.setdefault(chunk.resource_id, []).append(chunk)

    per_resource_entries: list[dict[str, Any]] = []
    for resource_id in sorted(by_resource.keys()):
        resource_chunks = by_resource[resource_id]
        first = resource_chunks[0]
        per_resource_entries.append(
            {
                "resource_id": resource_id,
                "source_type": first.source_type,
                "title": first.title,
                "chunk_count": len(resource_chunks),
                "first_chunk_id": first.chunk_id,
                "last_chunk_id": resource_chunks[-1].chunk_id,
                "resource_route": first.resource_route,
            }
        )

    by_source_type = dict(
        sorted(Counter(c.source_type for c in chunks).items())
    )

    sorted_warnings = sorted(
        warnings,
        key=lambda w: (w.get("code", ""), w.get("resource_id", ""), w.get("message", "")),
    )

    return {
        "schema_version": CHUNK_INDEX_SCHEMA_VERSION,
        "chunk_count": len(chunks),
        "resource_count": len(by_resource),
        "by_source_type": by_source_type,
        "by_resource": per_resource_entries,
        "warnings": sorted_warnings,
    }


__all__ = [
    "ChunkIndexBuilder",
    "build_chunk_index",
    "build_manifest",
    "read_chunks_for_record",
]
