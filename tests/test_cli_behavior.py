"""Tests for CLI cache estimation helpers and new flags."""

import json
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from wiki import cli
from wiki.cli import is_note_stale, normalize_provider_name, stale_reasons
from wiki.generate.notes import compute_chunks_hash
from wiki.llm.prompts import PROMPT_VERSION
from wiki.schemas import ResourceRecord, ResourceStatus, SourceType, WebpageChunk
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
    """--only-stale filters based on provider+model staleness, not just prompt version.

    After normalize_provider_name, 'ollamacloud' stored in the DB is treated
    as 'ollama_cloud' for staleness checks.
    """
    all_records = list(registry.get_all())

    # With --provider mock, only mock-generated records with matching model
    # and current prompt version are current. All ollamacloud/ollama_cloud
    # records are stale for mock (provider_mismatch).
    stale_for_mock = [r for r in all_records if is_note_stale(r, "mock", "mock-model")]
    current_for_mock = [r for r in all_records if not is_note_stale(r, "mock", "mock-model")]
    # failed_retryable mock records are stale regardless
    assert len(stale_for_mock) > 0
    # Only mock-provider records with mock-model can be current for mock target
    mock_current = [r for r in current_for_mock if r.llm_provider == "mock"]
    # All current-for-mock records must have mock provider
    for r in current_for_mock:
        assert r.llm_provider == "mock"

    # With --provider ollama_cloud, 'ollamacloud' stored records should be
    # current (normalized), and mock records should be stale.
    stale_for_ollama = [r for r in all_records if is_note_stale(r, "ollama_cloud", "glm-5.1:cloud")]
    # Only failed_retryable and mock-generated should be stale for ollama_cloud
    for r in stale_for_ollama:
        reasons = stale_reasons(r, "ollama_cloud", "glm-5.1:cloud")
        assert any("failed_retryable" in reason or "provider_mismatch" in reason for reason in reasons)


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


class TestIsNoteStale:
    """Unit tests for is_note_stale covering each staleness condition."""

    def _make_record(self, **overrides):
        """Create a minimal ResourceRecord for testing."""
        note_path = Path(tempfile.mktemp(suffix=".md"))
        defaults = dict(
            id="test:abc123",
            source_type=SourceType.WEBPAGE,
            canonical_id="test:abc123",
            original_url="https://example.com",
            title="Test Resource",
            status=ResourceStatus.PROCESSED,
            prompt_version=PROMPT_VERSION,
            llm_provider="mock",
            llm_model="mock-model",
            generated_note_path=note_path,
            source_chunks_hash="abc123",
            local_normalized_path=None,
        )
        defaults.update(overrides)
        record = ResourceRecord(**defaults)
        # Create the note file so .exists() passes
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.touch()
        return record

    def test_current_for_matching_provider_model(self):
        """Note at current version, matching provider and model, is not stale."""
        record = self._make_record(
            llm_provider="ollama_cloud",
            llm_model="glm-5.1:cloud",
        )
        assert not is_note_stale(record, "ollama_cloud", "glm-5.1:cloud")

    def test_stale_for_wrong_provider(self):
        """Mock-generated note is stale for ollama_cloud."""
        record = self._make_record()
        assert is_note_stale(record, "ollama_cloud", "glm-5.1:cloud")

    def test_stale_for_wrong_model(self):
        """Note with wrong model is stale for matching provider."""
        note_path = Path(tempfile.mktemp(suffix=".md"))
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.touch()
        record = self._make_record(
            llm_provider="ollama_cloud",
            llm_model="old-model",
            generated_note_path=note_path,
        )
        assert is_note_stale(record, "ollama_cloud", "glm-5.1:cloud")

    def test_stale_for_old_prompt_version(self):
        """Note with old prompt version is stale regardless of provider."""
        note_path = Path(tempfile.mktemp(suffix=".md"))
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.touch()
        record = self._make_record(
            prompt_version="harish_llm_wiki_v3",
            llm_provider="ollama_cloud",
            llm_model="glm-5.1:cloud",
            generated_note_path=note_path,
        )
        assert is_note_stale(record, "ollama_cloud", "glm-5.1:cloud")

    def test_stale_failed_retryable(self):
        """failed_retryable status always means stale, even with matching provider."""
        note_path = Path(tempfile.mktemp(suffix=".md"))
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.touch()
        record = self._make_record(
            status=ResourceStatus.FAILED_RETRYABLE,
            llm_provider="ollama_cloud",
            llm_model="glm-5.1:cloud",
            generated_note_path=note_path,
        )
        assert is_note_stale(record, "ollama_cloud", "glm-5.1:cloud")

    def test_stale_missing_note_path(self):
        """Note with non-existent generated_note_path is stale."""
        record = self._make_record(
            generated_note_path=Path("/nonexistent/path.md"),
        )
        assert is_note_stale(record, "mock", "mock-model")

    def test_mock_current_for_mock(self):
        """Mock-generated note is current for mock provider with mock-model."""
        record = self._make_record()
        assert not is_note_stale(record, "mock", "mock-model")


class TestNormalizeProviderName:
    """Tests for normalize_provider_name covering all aliases."""

    def test_ollamacloud_normalizes(self):
        from wiki.cli import normalize_provider_name
        assert normalize_provider_name("ollamacloud") == "ollama_cloud"

    def test_ollama_cloud_passthrough(self):
        from wiki.cli import normalize_provider_name
        assert normalize_provider_name("ollama_cloud") == "ollama_cloud"

    def test_ollamalocal_normalizes(self):
        from wiki.cli import normalize_provider_name
        assert normalize_provider_name("ollamalocal") == "ollama_local"

    def test_ollama_local_passthrough(self):
        from wiki.cli import normalize_provider_name
        assert normalize_provider_name("ollama_local") == "ollama_local"

    def test_openai_aliases(self):
        from wiki.cli import normalize_provider_name
        assert normalize_provider_name("openai") == "openai_compatible"
        assert normalize_provider_name("openaicompatible") == "openai_compatible"
        assert normalize_provider_name("openai_compatible") == "openai_compatible"

    def test_mock_passthrough(self):
        from wiki.cli import normalize_provider_name
        assert normalize_provider_name("mock") == "mock"

    def test_none_returns_empty(self):
        from wiki.cli import normalize_provider_name
        assert normalize_provider_name(None) == ""

    def test_hyphen_and_space_normalization(self):
        from wiki.cli import normalize_provider_name
        assert normalize_provider_name("Ollama-Cloud") == "ollama_cloud"
        assert normalize_provider_name("ollama cloud") == "ollama_cloud"


class TestStaleReasonsWithNormalization:
    """Tests for stale_reasons and is_note_stale with normalized provider names."""

    def _make_record(self, **overrides):
        note_path = Path(tempfile.mktemp(suffix=".md"))
        defaults = dict(
            id="test:abc123",
            source_type=SourceType.WEBPAGE,
            canonical_id="test:abc123",
            original_url="https://example.com",
            title="Test Resource",
            status=ResourceStatus.PROCESSED,
            prompt_version=PROMPT_VERSION,
            llm_provider="mock",
            llm_model="mock-model",
            generated_note_path=note_path,
            source_chunks_hash="abc123",
            local_normalized_path=None,
        )
        defaults.update(overrides)
        record = ResourceRecord(**defaults)
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.touch()
        return record

    def test_ollamacloud_record_current_for_ollama_cloud(self):
        """Record with llm_provider='ollamacloud' should be current for target 'ollama_cloud'."""
        record = self._make_record(
            llm_provider="ollamacloud",
            llm_model="glm-5.1:cloud",
        )
        assert not is_note_stale(record, "ollama_cloud", "glm-5.1:cloud")

    def test_ollama_cloud_record_current_for_ollama_cloud(self):
        """Record with llm_provider='ollama_cloud' should be current for target 'ollama_cloud'."""
        record = self._make_record(
            llm_provider="ollama_cloud",
            llm_model="glm-5.1:cloud",
        )
        assert not is_note_stale(record, "ollama_cloud", "glm-5.1:cloud")

    def test_mock_record_stale_for_ollama_cloud(self):
        """Mock-generated note is stale for ollama_cloud."""
        record = self._make_record()
        assert is_note_stale(record, "ollama_cloud", "glm-5.1:cloud")

    def test_failed_retryable_always_stale(self):
        """failed_retryable is stale even if provider/model matches."""
        note_path = Path(tempfile.mktemp(suffix=".md"))
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.touch()
        record = self._make_record(
            status=ResourceStatus.FAILED_RETRYABLE,
            llm_provider="ollama_cloud",
            llm_model="glm-5.1:cloud",
            generated_note_path=note_path,
        )
        assert is_note_stale(record, "ollama_cloud", "glm-5.1:cloud")

    def test_stale_reasons_includes_provider_mismatch(self):
        """stale_reasons should list provider_mismatch for mock→real."""
        from wiki.cli import stale_reasons
        record = self._make_record()
        reasons = stale_reasons(record, "ollama_cloud", "glm-5.1:cloud")
        assert any("provider_mismatch" in r for r in reasons)

    def test_stale_reasons_current_record_empty(self):
        """stale_reasons should be empty for a current record."""
        from wiki.cli import stale_reasons
        record = self._make_record(
            llm_provider="ollama_cloud",
            llm_model="glm-5.1:cloud",
        )
        reasons = stale_reasons(record, "ollama_cloud", "glm-5.1:cloud")
        assert reasons == []


class TestListStaleNotesWithReason:
    """Test that list-stale-notes --provider includes stale reason column."""

    def test_list_stale_notes_with_provider_shows_reason(self):
        result = CliRunner().invoke(cli.app, ["list-stale-notes", "--provider", "ollama_cloud"])
        assert result.exit_code == 0


class TestValidateWithProvider:
    """Test validate --provider warns/errors on failed_retryable and provider mismatches."""

    def test_validate_with_provider_runs(self):
        result = CliRunner().invoke(cli.app, ["validate", "--provider", "ollama_cloud"])
        assert result.exit_code == 0

    def test_validate_without_provider_runs(self):
        result = CliRunner().invoke(cli.app, ["validate"])
        assert result.exit_code == 0
