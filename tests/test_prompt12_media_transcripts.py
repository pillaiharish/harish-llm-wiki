"""Tests for Prompt 12 local transcript/media workflows."""

from pathlib import Path

from typer.testing import CliRunner

from wiki import cli
from wiki.asr.mock import MockASRProvider
from wiki.ingest.media import ffmpeg_extract_command
from wiki.normalize.transcript_media import parse_transcript_text, transcript_media_normalizer
from wiki.registry import Registry
from wiki.schemas import ResourceRecord, SourceType
from wiki.storage import Storage


def _isolated_registry(tmp_path, monkeypatch) -> Registry:
    monkeypatch.setattr(cli.config, "LLM_WIKI_DATA_DIR", tmp_path)
    cli.config.ensure_directories()
    reg = Registry()
    monkeypatch.setattr(cli, "registry", reg)
    return reg


def test_medium_markdown_import_parses_frontmatter(tmp_path, monkeypatch):
    reg = _isolated_registry(tmp_path, monkeypatch)
    md = tmp_path / "article.md"
    md.write_text(
        """---
title: "Understanding RAG Chunking"
author: "Author Name"
original_url: "https://medium.com/example"
tags:
  - rag
  - chunking
---

# Understanding RAG Chunking

Chunking matters for retrieval.
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "import-medium-markdown",
            "--file",
            str(md),
            "--original-url",
            "https://medium.com/example",
        ],
    )

    assert result.exit_code == 0, result.output
    record = next(reg.get_all())
    assert record.source_type == SourceType.MEDIUM_MARKDOWN
    assert record.title == "Understanding RAG Chunking"
    assert record.author == "Author Name"
    assert record.tags == ["rag", "chunking"]
    assert record.extra["platform"] == "medium"
    assert (Path(record.local_normalized_path) / "chunks.jsonl").exists()


def test_media_file_content_hash_dedupe(tmp_path, monkeypatch):
    reg = _isolated_registry(tmp_path, monkeypatch)
    media = tmp_path / "clip.mp3"
    media.write_bytes(b"fake mp3 bytes")

    first = CliRunner().invoke(cli.app, ["add-media", "--file", str(media)])
    second = CliRunner().invoke(cli.app, ["add-media", "--file", str(media)])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert "Duplicate media skipped" in second.output
    assert len(list(reg.get_all())) == 1
    record = next(reg.get_all())
    assert record.id.startswith("media:")
    assert record.source_type == SourceType.LOCAL_AUDIO
    assert record.extra["transcription_status"] == "pending"


def test_ffmpeg_command_construction(tmp_path):
    command = ffmpeg_extract_command(tmp_path / "input.mp4", tmp_path / "audio.wav")

    assert command[:4] == ["ffmpeg", "-y", "-i", str(tmp_path / "input.mp4")]
    assert "-ar" in command
    assert "16000" in command
    assert "-ac" in command
    assert command[-1] == str(tmp_path / "audio.wav")


def test_transcript_segment_to_chunk_conversion(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.config, "LLM_WIKI_DATA_DIR", tmp_path)
    record = ResourceRecord(
        id="transcript:abcdef123456",
        source_type=SourceType.LOCAL_TRANSCRIPT,
        canonical_id="transcript:abcdef123456",
        original_url="local:///tmp/transcript.txt",
        content_hash="abcdef123456",
    )
    chunks = transcript_media_normalizer.segments_to_chunks(
        record,
        [
            {"id": 0, "start": 120.3, "end": 130.0, "text": "First segment."},
            {"id": 1, "start": 130.0, "end": 155.4, "text": "Second segment."},
        ],
    )

    assert chunks[0].chunk_id == "transcript:abcdef12-t000120"
    assert chunks[0].citation_label == "02:00-02:35"
    assert chunks[0].source_type == SourceType.LOCAL_TRANSCRIPT


def test_import_transcript_creates_normalized_chunks(tmp_path, monkeypatch):
    reg = _isolated_registry(tmp_path, monkeypatch)
    transcript = tmp_path / "sample.txt"
    transcript.write_text("[00:00:01] Hello world.\n[00:00:08] More detail.\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli.app,
        ["import-transcript", "--file", str(transcript), "--source-title", "Sample Local Transcript"],
    )

    assert result.exit_code == 0, result.output
    record = next(reg.get_all())
    assert record.id.startswith("transcript:")
    assert record.title == "Sample Local Transcript"
    chunks = list(Storage.read_jsonl(Path(record.local_normalized_path) / "chunks.jsonl"))
    assert chunks
    assert chunks[0]["chunk_id"].startswith("transcript:")
    assert chunks[0]["citation_label"] == "00:01-00:16"


def test_mock_asr_provider_returns_deterministic_segments(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"not real wav")

    result = MockASRProvider().transcribe(audio)

    assert len(result.segments) == 2
    assert result.segments[0].text == "This is a mock transcript."


def test_local_media_citations_render_timestamps(tmp_path, monkeypatch):
    from wiki.generate.citations import render_source_chunks_section

    monkeypatch.setattr(cli.config, "LLM_WIKI_DATA_DIR", tmp_path)
    record = ResourceRecord(
        id="media:abcdef123456",
        source_type=SourceType.LOCAL_AUDIO,
        canonical_id="media:abcdef123456",
        original_url="local:///tmp/audio.mp3",
        content_hash="abcdef123456",
    )
    chunk = transcript_media_normalizer.segments_to_chunks(
        record,
        [{"id": 0, "start": 120.0, "end": 155.0, "text": "Timestamped local media."}],
    )[0]

    rendered = render_source_chunks_section({chunk.chunk_id: chunk}, {chunk.chunk_id})

    assert "local media timestamp: 02:00-02:35" in rendered
    assert "Source type: local_audio" in rendered


def test_parse_transcript_text_without_timestamps():
    segments = parse_transcript_text("First paragraph.\n\nSecond paragraph.")

    assert segments[0]["start"] == 0.0
    assert segments[1]["start"] == 30.0
