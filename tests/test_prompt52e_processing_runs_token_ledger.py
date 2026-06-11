"""Prompt52E processing run and token ledger checks."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import wiki.cli as cli
from wiki import control_plane
from wiki.generate.notes import NoteGenerator, compute_chunks_hash
from wiki.llm.mock import MockProvider
from wiki.llm.prompts import PROMPT_VERSION
from wiki.runs import (
    append_processing_run,
    build_token_entry,
    estimate_tokens,
    get_run,
    make_run_id,
    parse_provider_usage,
    processing_runs_path,
    read_processing_runs,
    read_token_ledger,
    record_cache_hit,
    record_dry_run_plan,
    token_ledger_path,
    token_ledger_summary,
)
from wiki.schemas import ResourceRecord, ResourceStatus, SourceType, WebpageChunk


def _set_data_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli.config, "LLM_WIKI_DATA_DIR", tmp_path)
    monkeypatch.setattr(control_plane.config, "LLM_WIKI_DATA_DIR", tmp_path)


def _record_with_chunks(tmp_path: Path) -> ResourceRecord:
    norm_dir = tmp_path / "normalized" / "webpage-test"
    norm_dir.mkdir(parents=True)
    chunk = WebpageChunk(
        resource_id="webpage:test",
        chunk_id="webpage:test-c0000",
        source_type=SourceType.WEBPAGE,
        text="Attention lets a model connect relevant context across a sequence.",
        citation_label="paragraph 1",
        url="https://example.com/attention",
    )
    (norm_dir / "chunks.jsonl").write_text(
        json.dumps(chunk.model_dump(), default=str) + "\n",
        encoding="utf-8",
    )
    return ResourceRecord(
        id="webpage:test",
        source_type=SourceType.WEBPAGE,
        canonical_id="webpage:test",
        original_url="https://example.com/attention",
        title="Attention Test",
        local_normalized_path=norm_dir,
        status=ResourceStatus.NORMALIZED,
    )


def test_jsonl_run_storage_is_append_only_and_run_ids_are_unique(tmp_path, monkeypatch):
    _set_data_dir(monkeypatch, tmp_path)

    first = make_run_id("resource:a", "note_generation")
    second = make_run_id("resource:a", "note_generation")
    assert first != second

    append_processing_run({"run_id": first, "status": "success"})
    append_processing_run({"run_id": second, "status": "failed"})

    rows = read_processing_runs()
    assert [row["run_id"] for row in rows] == [first, second]
    assert processing_runs_path().read_text(encoding="utf-8").count("\n") == 2


def test_token_estimation_and_provider_usage_parsing_are_deterministic():
    assert estimate_tokens("hello world") == estimate_tokens("hello world")
    assert estimate_tokens("hello world") > 0

    openai_usage = parse_provider_usage(
        "openai_compatible",
        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    assert openai_usage["provider_input_tokens"] == 10
    assert openai_usage["provider_output_tokens"] == 5
    assert openai_usage["provider_total_tokens"] == 15

    ollama_usage = parse_provider_usage(
        "ollama_local",
        {"prompt_eval_count": 7, "eval_count": 3},
    )
    assert ollama_usage["provider_input_tokens"] == 7
    assert ollama_usage["provider_output_tokens"] == 3
    assert ollama_usage["provider_total_tokens"] == 10

    estimated_entry = build_token_entry(
        run_id="run-estimated",
        resource_id="resource:x",
        operation="note_generation",
        provider="ollama_cloud",
        model="glm",
        prompt_version=PROMPT_VERSION,
        prompt_hash="hash",
        prompt="prompt text",
        system="system text",
        output="output text",
        provider_usage=None,
    )
    assert estimated_entry["usage_source"] == "estimated"
    assert estimated_entry["total_tokens"] == estimated_entry["estimated_total_tokens"]


def test_mock_note_generation_records_zero_cost_token_ledger(tmp_path, monkeypatch):
    _set_data_dir(monkeypatch, tmp_path)
    record = _record_with_chunks(tmp_path)
    provider = MockProvider()

    NoteGenerator(provider).generate(record)

    runs = read_processing_runs()
    ledger = read_token_ledger()
    assert any(row["operation"] == "note_generation" for row in runs)
    assert ledger
    assert all(row["provider"] == "mock" for row in ledger)
    assert all(row["estimated_cost"] == 0.0 for row in ledger)
    assert all(row["usage_source"] == "estimated" for row in ledger)


def test_cache_hit_records_run_without_token_ledger(tmp_path, monkeypatch):
    _set_data_dir(monkeypatch, tmp_path)
    record = _record_with_chunks(tmp_path)
    chunks = list((Path(record.local_normalized_path) / "chunks.jsonl").read_text(encoding="utf-8").splitlines())
    record.generated_note_path = tmp_path / "existing.md"
    record.generated_note_path.write_text("# Existing\n", encoding="utf-8")
    record.source_chunks_hash = compute_chunks_hash([
        WebpageChunk.model_validate(json.loads(line)) for line in chunks
    ])
    record.prompt_hash = "cached-prompt"
    record.prompt_version = PROMPT_VERSION
    record.llm_model = "mock-model"

    path = NoteGenerator(MockProvider()).generate(record)

    assert path == record.generated_note_path
    assert record.status == ResourceStatus.LLM_CACHE_HIT
    assert read_processing_runs()[0]["status"] == "cache_hit"
    assert read_token_ledger() == []


def test_dry_run_plan_records_zero_cost_run_without_token_ledger(tmp_path, monkeypatch):
    _set_data_dir(monkeypatch, tmp_path)
    record = _record_with_chunks(tmp_path)

    run = record_dry_run_plan(
        record=record,
        provider="mock",
        model="mock-model",
        would_ingest=True,
        would_normalize=True,
        would_call_llm=True,
        would_cache_hit=False,
    )

    assert run["operation"] == "process_new_dry_run"
    assert run["status"] == "planned"
    assert run["estimated_cost"] == 0.0
    assert run["would_call_llm"] is True
    assert read_processing_runs()[0]["run_id"] == run["run_id"]
    assert read_token_ledger() == []


def test_cli_run_and_token_ledger_read_commands(tmp_path, monkeypatch):
    _set_data_dir(monkeypatch, tmp_path)
    run_id = "run-cli-1"
    append_processing_run(
        {
            "run_id": run_id,
            "resource_id": "resource:cli",
            "operation": "note_generation",
            "status": "success",
            "provider": "mock",
            "model": "mock-model",
            "completed_at": "2026-06-11T00:00:00Z",
            "total_tokens": 12,
        }
    )
    token_ledger_path().write_text(
        json.dumps(
            {
                "run_id": run_id,
                "resource_id": "resource:cli",
                "provider": "mock",
                "model": "mock-model",
                "total_tokens": 12,
                "estimated_cost": 0,
                "usage_source": "estimated",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    listed = runner.invoke(cli.app, ["runs", "list"])
    assert listed.exit_code == 0
    assert run_id in listed.output

    shown = runner.invoke(cli.app, ["runs", "show", run_id])
    assert shown.exit_code == 0
    assert "resource:cli" in shown.output

    summary = runner.invoke(cli.app, ["token-ledger", "summary"])
    assert summary.exit_code == 0
    assert "Token ledger summary" in summary.output
    assert "Total tokens: 12" in summary.output


def test_control_plane_run_and_ledger_endpoints_are_read_only_and_redacted(tmp_path, monkeypatch):
    _set_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(control_plane.config, "OPENAI_COMPATIBLE_API_KEY", "sk-run-secret")

    append_processing_run(
        {
            "run_id": "run-secret",
            "resource_id": "resource:secret",
            "operation": "note_generation",
            "status": "failed",
            "provider": "openai_compatible",
            "model": "secret-model",
            "error": "Authorization: Bearer sk-run-secret",
            "completed_at": "2026-06-11T00:00:00Z",
            "total_tokens": 0,
        }
    )

    for path in [
        "/api/runs",
        "/api/runs/run-secret",
        "/api/token-ledger",
        "/api/token-ledger/summary",
    ]:
        status, payload = control_plane.dispatch_api("GET", path)
        assert status == 200
        text = json.dumps(control_plane.redact_payload(payload))
        assert "sk-run-secret" not in text
        assert "process-new" not in text

    assert get_run("run-secret") is not None
    assert token_ledger_summary()["run_count"] == 1
