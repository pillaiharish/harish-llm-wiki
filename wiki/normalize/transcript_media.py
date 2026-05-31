"""Normalize local media/transcript ASR output into citeable chunks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from wiki.config import config
from wiki.schemas import MediaTranscriptChunk, ResourceRecord, SourceType
from wiki.storage import Storage


TIMESTAMP_LINE_RE = re.compile(
    r"^\s*\[(?P<ts>(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d+)?)\]\s*(?P<text>.+?)\s*$"
)


def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_timestamp(value: str) -> float:
    parts = value.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    return float(value)


class TranscriptMediaNormalizer:
    """Normalize transcript JSON/text files for media-style timestamp citations."""

    def normalize(self, record: ResourceRecord) -> ResourceRecord:
        if not record.local_raw_path:
            raise ValueError(f"No raw path for resource {record.id}")

        raw_dir = Path(record.local_raw_path)
        segments = self._load_segments(raw_dir)
        if not segments:
            raise ValueError(f"No transcript segments found for {record.id}")

        content_hash = record.content_hash or record.id.split(":", 1)[-1]
        subdir = "media" if record.id.startswith("media:") else "transcript"
        norm_dir = config.get_data_path("normalized", subdir, content_hash[:8])
        norm_dir.mkdir(parents=True, exist_ok=True)

        markdown = self._render_markdown(record, segments)
        Storage.write_text(markdown, norm_dir / "transcript.md")

        chunks = self.segments_to_chunks(record, segments)
        with (norm_dir / "chunks.jsonl").open("w", encoding="utf-8") as handle:
            for chunk in chunks:
                handle.write(json.dumps(chunk.model_dump(), ensure_ascii=False) + "\n")

        record.local_normalized_path = norm_dir
        return record

    def _load_segments(self, raw_dir: Path) -> list[dict[str, Any]]:
        transcript_json = raw_dir / "transcript.json"
        segments_jsonl = raw_dir / "segments.jsonl"
        transcript_txt = raw_dir / "transcript.txt"

        if transcript_json.exists():
            data = Storage.read_json(transcript_json)
            if isinstance(data, dict):
                return list(data.get("segments") or [])
            return list(data or [])
        if segments_jsonl.exists():
            return list(Storage.read_jsonl(segments_jsonl))
        if transcript_txt.exists():
            return parse_transcript_text(Storage.read_text(transcript_txt))
        return []

    def _render_markdown(self, record: ResourceRecord, segments: list[dict[str, Any]]) -> str:
        title = record.title or "Local Transcript"
        source_file = record.extra.get("original_path") or record.original_url
        lines = [
            f"# {title}",
            "",
            f"Source file: {source_file}",
            f"ASR provider: {record.extra.get('transcription_provider', 'manual')}",
            f"ASR model: {record.extra.get('asr_model', 'manual')}",
            f"Task: {record.extra.get('asr_task', 'transcribe')}",
            "",
            "## Transcript",
            "",
        ]
        for segment in segments:
            lines.append(f"[{format_timestamp(float(segment.get('start', 0.0)))}] {segment.get('text', '')}")
        return "\n".join(lines).rstrip() + "\n"

    def segments_to_chunks(
        self,
        record: ResourceRecord,
        segments: list[dict[str, Any]],
    ) -> list[MediaTranscriptChunk]:
        chunks: list[MediaTranscriptChunk] = []
        buffer: list[dict[str, Any]] = []
        for segment in segments:
            text = str(segment.get("text", "")).strip()
            if not text:
                continue
            buffer.append(segment)
            words = " ".join(str(item.get("text", "")) for item in buffer).split()
            duration = float(buffer[-1].get("end", buffer[-1].get("start", 0.0))) - float(buffer[0].get("start", 0.0))
            if len(words) >= 140 or duration >= 90:
                chunks.append(self._make_chunk(record, buffer))
                buffer = []
        if buffer:
            chunks.append(self._make_chunk(record, buffer))
        return chunks

    def _make_chunk(self, record: ResourceRecord, segments: list[dict[str, Any]]) -> MediaTranscriptChunk:
        start = float(segments[0].get("start", 0.0))
        end = float(segments[-1].get("end", start))
        source_prefix = "media" if record.id.startswith("media:") else "transcript"
        stable = record.id.split(":", 1)[1] if ":" in record.id else (record.content_hash or record.id)
        chunk_id = f"{source_prefix}:{stable[:8]}-t{int(start):06d}"
        source_type = record.source_type
        if source_type not in {SourceType.LOCAL_AUDIO, SourceType.LOCAL_VIDEO, SourceType.LOCAL_TRANSCRIPT}:
            source_type = SourceType.LOCAL_TRANSCRIPT
        return MediaTranscriptChunk(
            resource_id=record.id,
            chunk_id=chunk_id,
            source_type=source_type,
            text=" ".join(str(segment.get("text", "")).strip() for segment in segments).strip(),
            start_time=start,
            end_time=end,
            citation_label=f"{format_timestamp(start)}-{format_timestamp(end)}",
            source_url=record.original_url,
        )


def parse_transcript_text(content: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    untimed_blocks: list[str] = []
    next_start = 0.0
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = TIMESTAMP_LINE_RE.match(stripped)
        if match:
            start = parse_timestamp(match.group("ts"))
            segments.append({
                "id": len(segments),
                "start": start,
                "end": start + 8.0,
                "text": match.group("text").strip(),
            })
            continue
        untimed_blocks.append(stripped)

    for block in untimed_blocks:
        segments.append({
            "id": len(segments),
            "start": next_start,
            "end": next_start + 30.0,
            "text": block,
        })
        next_start += 30.0
    return segments


transcript_media_normalizer = TranscriptMediaNormalizer()
