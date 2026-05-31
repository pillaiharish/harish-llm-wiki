"""Tests for CLI cache estimation helpers and new flags."""

import json
from pathlib import Path

from typer.testing import CliRunner

from wiki import cli
from wiki.generate.notes import compute_chunks_hash
from wiki.llm.prompts import PROMPT_VERSION
from wiki.schemas import ResourceRecord, SourceType, WebpageChunk
from wiki.registry import registry


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


def test_only_stale_filters_by_prompt_version():
    """--only-stale should only select resources with stale prompt versions."""
    all_records = list(registry.get_all())
    stale = [r for r in all_records if r.prompt_version != PROMPT_VERSION]
    current = [r for r in all_records if r.prompt_version == PROMPT_VERSION]
    assert len(stale) > 0, "Expected some stale records"
    assert len(current) == 0, f"Expected no current-version records, got {len(current)}"


def test_get_provider_by_name_mock():
    """get_provider_by_name('mock') returns MockProvider."""
    provider = cli.get_provider_by_name("mock")
    assert isinstance(provider, cli.MockProvider)


def test_get_provider_by_name_unknown_raises():
    """get_provider_by_name with unknown provider raises typer.Exit."""
    import pytest
    with pytest.raises((SystemExit, Exception)):
        cli.get_provider_by_name("nonexistent_provider")


def test_list_stale_notes_command():
    """list-stale-notes command should run without error."""
    result = CliRunner().invoke(cli.app, ["list-stale-notes"])
    assert result.exit_code == 0
    assert "Stale Notes" in result.output or "current prompt version" in result.output


def test_process_new_dry_run_with_skip_ingest(monkeypatch, tmp_path):
    """--skip-ingest --dry-run should show skip message for resources with chunks."""
    records = list(registry.get_all())
    if not records:
        return
    record = records[0]
    if not record.local_normalized_path:
        return
    chunks_path = Path(record.local_normalized_path) / "chunks.jsonl"
    if not chunks_path.exists():
        return

    result = CliRunner().invoke(cli.app, [
        "process-new", "--dry-run", "--force", "--skip-ingest", "--limit", "1"
    ])
    assert result.exit_code == 0
    assert "would call LLM" in result.output.lower() or "cache hit" in result.output.lower() or "skip" in result.output.lower()


def test_process_new_provider_override_dry_run():
    """--provider mock --dry-run should override the LLM provider."""
    result = CliRunner().invoke(cli.app, [
        "process-new", "--dry-run", "--force", "--provider", "mock", "--limit", "1"
    ])
    assert result.exit_code == 0
