"""Prompt52F read-only operations dashboard checks."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from wiki.schemas import ResourceRecord, ResourceStatus, SourceType
from wiki.site.builder import SiteBuilder


def _record() -> ResourceRecord:
    return ResourceRecord(
        id="webpage:attention",
        source_type=SourceType.WEBPAGE,
        canonical_id="webpage:attention",
        original_url="https://example.com/attention",
        title="Attention Resource",
        status=ResourceStatus.PROCESSED,
        llm_provider="mock",
        llm_model="mock-model",
        user_consumed_at=datetime(2026, 6, 11),
        tags=["transformers"],
        extra={"topics": ["llm-internals"], "concepts": ["attention"]},
    )


def _builder(tmp_path: Path, monkeypatch) -> SiteBuilder:
    builder = SiteBuilder()
    builder.data_site_dir = tmp_path / "generated" / "docs"
    builder.repo_site_dir = tmp_path / "repo" / "site" / "docs"
    builder.data_site_dir.mkdir(parents=True)
    builder.repo_site_dir.mkdir(parents=True)
    monkeypatch.setattr("wiki.site.builder.config.LLM_WIKI_DATA_DIR", tmp_path / "data")
    return builder


def test_operations_snapshot_generation_is_safe_and_public(tmp_path, monkeypatch):
    builder = _builder(tmp_path, monkeypatch)
    review_dir = builder.data_site_dir / "review"
    review_dir.mkdir(parents=True)
    (review_dir / "review.json").write_text(
        json.dumps(
            {
                "weak": [{"id": "webpage:attention"}],
                "fallback": [],
                "failed": [],
                "missing_citations": [],
                "stale": [],
                "manual": [],
                "untitled": [],
            }
        ),
        encoding="utf-8",
    )
    graph_dir = builder.data_site_dir / "public" / "graph"
    graph_dir.mkdir(parents=True)
    (graph_dir / "nodes.json").write_text(
        json.dumps([{"id": "resource:webpage:attention", "type": "resource"}]),
        encoding="utf-8",
    )
    (graph_dir / "edges.json").write_text(json.dumps([{"id": "edge:1"}]), encoding="utf-8")

    builder._build_operations_snapshot([_record()])

    snapshot_path = builder.data_site_dir / "public" / "operations" / "operations_snapshot.json"
    assert snapshot_path.exists()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["schema_version"] == "operations_snapshot_v1"
    assert snapshot["resource_count"] == 1
    assert snapshot["review_summary"]["weak"] == 1
    assert snapshot["graph_summary"] == {"nodes": 1, "edges": 1, "resources": 1}
    assert snapshot["resources"][0]["links"]["resource"] == "/resources/webpage_attention"
    assert snapshot["resources"][0]["review_flags"] == ["weak"]
    assert snapshot["resources"][0]["topics"] == ["llm-internals"]
    assert snapshot["resources"][0]["concepts"] == ["attention"]

    payload_text = json.dumps(snapshot).lower()
    for forbidden in ("api_key", "token", "password", "secret", "authorization", "bearer", ".env"):
        assert forbidden not in payload_text
    assert "token_ledger" not in payload_text
    assert "processing_runs.jsonl" not in payload_text


def test_operations_route_component_nav_and_verifier_are_registered():
    page = Path("site/docs/operations/index.md").read_text(encoding="utf-8")
    component = Path(
        "site/docs/.vitepress/theme/components/OperationsDashboard.vue"
    ).read_text(encoding="utf-8")
    theme = Path("site/docs/.vitepress/theme/index.ts").read_text(encoding="utf-8")
    config = Path("site/docs/.vitepress/config.ts").read_text(encoding="utf-8")
    verifier = Path("scripts/verify_site_static_routes.py").read_text(encoding="utf-8")
    builder = Path("wiki/site/builder.py").read_text(encoding="utf-8")

    assert "<OperationsDashboard />" in page
    assert 'data-testid="operations-dashboard"' in component
    assert "withBase('/operations/operations_snapshot.json')" in component
    assert "OperationsDashboard" in theme
    assert "{ text: 'Operations', link: '/operations/' }" in config
    assert '"/operations/"' in verifier
    assert "_build_operations_snapshot" in builder

    forbidden_component_text = component.lower()
    for forbidden in ("post /api/process-new", "post /api/reprocess", "type=\"password\""):
        assert forbidden not in forbidden_component_text
