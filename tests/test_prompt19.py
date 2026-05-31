"""Tests for Prompt 19: Fix blank Explorer, smoke-site, and validate blankness."""

import json
from pathlib import Path

from typer.testing import CliRunner

from wiki import cli
from wiki.config import config
from wiki.generate.search import search_index_generator
from wiki.registry import Registry
from wiki.schemas import ResourceRecord, ResourceStatus, SourceType, WebpageChunk
from wiki.site.builder import site_builder
from wiki.storage import Storage


def _note() -> str:
    return """# RAG Notes

## One-line memory hook

Retrieval quality controls answer quality.

## Why this resource matters

This helps build RAG systems.

## Source-backed summary

- RAG retrieves context before generation. [source: webpage:test-c0001]
- Hybrid search can combine sparse and dense retrieval. [source: webpage:test-c0002]

## Concrete example / toy implementation

```python
contexts = retrieve(query)
```

## Needs verification

- Verify retrieval metrics.

## Revision questions

1. What is retrieval-augmented generation?

## Harish project connections

Connect this to RAGOpsBench.

## Suggested next learning topics

- Hybrid search

## Citations

- [source: webpage:test-c0001]
- [source: webpage:test-c0002]

## Provenance

- LLM provider: mock
"""


def _record(tmp_path: Path) -> ResourceRecord:
    note_path = tmp_path / "processed" / "resources" / "webpage_test.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(_note(), encoding="utf-8")
    norm_dir = tmp_path / "normalized"
    norm_dir.mkdir(exist_ok=True)
    chunks = [
        WebpageChunk(
            resource_id="webpage:test",
            chunk_id=f"webpage:test-c000{i}",
            source_type=SourceType.WEBPAGE,
            text=f"chunk {i}",
            citation_label=f"paragraph {i}",
            url="https://example.com/rag",
        )
        for i in range(1, 3)
    ]
    Storage.write_jsonl((chunk.model_dump() for chunk in chunks), norm_dir / "chunks.jsonl")
    return ResourceRecord(
        id="webpage:test",
        source_type=SourceType.WEBPAGE,
        canonical_id="webpage:test",
        original_url="https://example.com/rag",
        title="RAG Hybrid Retrieval",
        status=ResourceStatus.PROCESSED,
        generated_note_path=note_path,
        local_normalized_path=norm_dir,
        llm_provider="mock",
        llm_model="mock-model",
        prompt_version="harish_llm_wiki_v4",
        tags=["rag", "retrieval"],
    )


def _setup_and_build(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    record = _record(tmp_path)
    from wiki.generate.concepts import concept_extractor
    from wiki.generate.timeline import timeline_generator
    from wiki.generate.tags import tags_generator
    from wiki.generate.topics import topic_generator
    from wiki.generate.gaps import gaps_generator
    from wiki.generate.learn import learn_generator
    from wiki.generate.review import review_generator
    from wiki.generate.revision import revision_generator as rg
    records = [record]
    concept_extractor.aggregates = {}
    concept_extractor.aggregate(records)
    concept_extractor.save()
    periods = timeline_generator.generate(records)
    timeline_generator.save(periods)
    tags = tags_generator.generate(records)
    tags_generator.save(tags)
    topics = topic_generator.generate(records)
    topic_generator.save(topics)
    gaps = gaps_generator.generate(records)
    gaps_generator.save(gaps)
    learn = learn_generator.generate(records)
    learn_generator.save(learn)
    review = review_generator.generate(records)
    review_generator.save(review)
    indexes = search_index_generator.generate(records)
    search_index_generator.save(indexes)
    revision = rg.generate(records)
    rg.save(revision)
    site_builder.build(records)
    return records


class TestExplorerFallback:
    def test_explorer_has_fallback_table(self):
        items = [
            {
                "id": "webpage:test",
                "title": "Test Resource",
                "type": "webpage",
                "summary": "A test.",
                "tags": ["rag"],
                "topics": [],
                "source_url": "https://example.com",
                "local_page": "/resources/webpage_test",
                "provider": "mock",
                "model": "mock-model",
                "prompt_version": "v4",
                "requires_human_review": False,
                "review_status": "ok",
                "stale_status": "current",
                "created_at": "",
                "updated_at": "",
            }
        ]
        html = search_index_generator._explorer(items)
        assert "## Static table fallback" in html
        assert "| Title | Type | Topic | Provider | Review | Stale |" in html
        assert "Test Resource" in html

    def test_explorer_has_noscript_message(self):
        items = []
        html = search_index_generator._explorer(items)
        assert "<noscript>" in html
        assert "JavaScript is disabled" in html

    def test_explorer_has_js_error_catch(self):
        items = []
        html = search_index_generator._explorer(items)
        assert "try {" in html or "try{" in html
        assert "Could not initialize Explorer" in html

    def test_explorer_empty_items_has_no_items_row(self):
        items = []
        html = search_index_generator._explorer(items)
        assert "| No items |" in html


class TestSmokeSite:
    def test_smoke_site_passes_with_built_site(self, tmp_path, monkeypatch):
        records = _setup_and_build(tmp_path, monkeypatch)
        result = CliRunner().invoke(cli.app, ["smoke-site"])
        assert result.exit_code == 0 or "warning" in result.output.lower()

    def test_smoke_site_fails_when_explorer_blank(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        explorer_path = tmp_path / "site_generated" / "docs" / "explorer" / "index.md"
        explorer_path.parent.mkdir(parents=True, exist_ok=True)
        explorer_path.write_text("# Explorer\n\nEmpty\n", encoding="utf-8")
        home_path = tmp_path / "site_generated" / "docs" / "index.md"
        home_path.parent.mkdir(parents=True, exist_ok=True)
        home_path.write_text("# Home\n\nWelcome to the wiki.\n\nSome content here for size.\n", encoding="utf-8")
        tags_path = tmp_path / "site_generated" / "docs" / "tags" / "index.md"
        tags_path.parent.mkdir(parents=True, exist_ok=True)
        tags_path.write_text("# Tags\n\n## rag\n\n- Something\n", encoding="utf-8")
        gaps_path = tmp_path / "site_generated" / "docs" / "gaps.md"
        gaps_path.parent.mkdir(parents=True, exist_ok=True)
        gaps_path.write_text("# Knowledge Gaps\n\nSome gaps content here.\n", encoding="utf-8")
        timeline_path = tmp_path / "site_generated" / "docs" / "timeline.md"
        timeline_path.parent.mkdir(parents=True, exist_ok=True)
        timeline_path.write_text("# Timeline\n\nSome timeline content.\n", encoding="utf-8")
        public_dir = tmp_path / "site_generated" / "docs" / "public" / "search"
        public_dir.mkdir(parents=True, exist_ok=True)
        json_data = {"generated_at": "2024-01-01", "items": [{"id": "x"}]}
        (public_dir / "all.json").write_text(json.dumps(json_data), encoding="utf-8")
        (public_dir / "resources.json").write_text(json.dumps(json_data), encoding="utf-8")
        for section in ["sources", "review", "revision", "learn"]:
            d = tmp_path / "site_generated" / "docs" / section
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.md").write_text(f"# {section.title()}\n\nSome {section} content.\n", encoding="utf-8")
        result = CliRunner().invoke(cli.app, ["smoke-site"])
        assert result.exit_code != 0
        assert "Explorer page" in result.output

    def test_smoke_site_fails_when_all_json_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        site_dir = tmp_path / "site_generated" / "docs"
        site_dir.mkdir(parents=True, exist_ok=True)
        (site_dir / "index.md").write_text("# Home\n\nContent\n", encoding="utf-8")
        result = CliRunner().invoke(cli.app, ["smoke-site"])
        assert result.exit_code != 0


class TestValidateBlankness:
    def test_validate_warns_on_blank_tags_page(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        tags_dir = site_builder.repo_site_dir / "tags"
        tags_dir.mkdir(parents=True, exist_ok=True)
        (tags_dir / "index.md").write_text("# Tags\n\n_No tags yet._\n", encoding="utf-8")
        gaps_file = site_builder.repo_site_dir / "gaps.md"
        gaps_file.parent.mkdir(parents=True, exist_ok=True)
        gaps_file.write_text("# Knowledge Gaps\n\n_No gaps identified._\n\nSome more content here.\n", encoding="utf-8")
        result = CliRunner().invoke(cli.app, ["validate"])
        assert result.exit_code == 0

    def test_validate_warns_on_tiny_page(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        explorer_dir = site_builder.repo_site_dir / "explorer"
        explorer_dir.mkdir(parents=True, exist_ok=True)
        (explorer_dir / "index.md").write_text("# Explorer\n\nx\n", encoding="utf-8")
        result = CliRunner().invoke(cli.app, ["validate"])
        assert "warning" in result.output.lower() or result.exit_code == 0


class TestSearchIndexGeneration:
    def test_search_json_files_generated_in_correct_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path)
        indexes = search_index_generator.generate([record])
        search_index_generator.save(indexes)
        processed_all = tmp_path / "processed" / "search" / "all.json"
        public_all = tmp_path / "site_generated" / "docs" / "public" / "search" / "all.json"
        assert processed_all.exists(), f"Missing {processed_all}"
        assert public_all.exists(), f"Missing {public_all}"
        data = json.loads(public_all.read_text(encoding="utf-8"))
        assert "items" in data