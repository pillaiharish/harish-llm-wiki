"""Tests for CLI cache estimation helpers."""

import json
from pathlib import Path

from wiki import cli
from wiki.generate.notes import compute_chunks_hash
from wiki.llm.prompts import PROMPT_VERSION
from wiki.schemas import ResourceRecord, SourceType, WebpageChunk


def _record_with_chunks(tmp_path: Path) -> tuple[ResourceRecord, list[WebpageChunk]]:
    norm_dir = tmp_path / "normalized"
    norm_dir.mkdir()
    note_path = tmp_path / "note.md"
    note_path.write_text("# Note\n", encoding="utf-8")
    chunks = [
        WebpageChunk(
            resource_id="webpage:test",
            chunk_id="chunk-001",
            source_type=SourceType.WEBPAGE,
            text="RAG retrieves context.",
            citation_label="paragraph 1",
            url="https://example.com",
        )
    ]
    with open(norm_dir / "chunks.jsonl", "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.model_dump(), default=str) + "\n")

    record = ResourceRecord(
        id="webpage:test",
        source_type=SourceType.WEBPAGE,
        canonical_id="webpage:test",
        original_url="https://example.com",
        local_normalized_path=norm_dir,
        generated_note_path=note_path,
        source_chunks_hash=compute_chunks_hash(chunks),
        prompt_version=PROMPT_VERSION,
        llm_model="mock-model",
    )
    return record, chunks


def test_would_regenerate_note_detects_cache_hit(tmp_path, monkeypatch):
    record, _ = _record_with_chunks(tmp_path)
    monkeypatch.setattr(cli.config, "LLM_PROVIDER", "mock")

    assert cli.would_regenerate_note(record) is False


def test_would_regenerate_note_respects_force(tmp_path, monkeypatch):
    record, _ = _record_with_chunks(tmp_path)
    monkeypatch.setattr(cli.config, "LLM_PROVIDER", "mock")

    assert cli.would_regenerate_note(record, force=True) is True


def test_would_regenerate_note_detects_prompt_version_change(tmp_path, monkeypatch):
    record, _ = _record_with_chunks(tmp_path)
    record.prompt_version = "old"
    monkeypatch.setattr(cli.config, "LLM_PROVIDER", "mock")

    assert cli.would_regenerate_note(record) is True
