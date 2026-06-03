"""Tests for Prompt 21: Fix broken resource links, Markdown table escaping, and blank Explorer."""

import json
from pathlib import Path

from typer.testing import CliRunner

from wiki import cli
from wiki.config import config
from wiki.generate.page_utils import md_table_cell, resource_route, concept_route, topic_route, learn_route
from wiki.generate.search import search_index_generator
from wiki.registry import Registry
from wiki.schemas import ResourceRecord, ResourceStatus, SourceType, WebpageChunk
from wiki.site.builder import site_builder
from wiki.storage import Storage


PIPE_TITLE = "Better RAG: Hybrid Search in Chat with Documents | BM25 and Ensemble"


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


def _record_with_pipe_title(tmp_path: Path) -> ResourceRecord:
    note_path = tmp_path / "processed" / "resources" / "youtube_r2m9DbEmeqI.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(_note(), encoding="utf-8")
    norm_dir = tmp_path / "normalized"
    norm_dir.mkdir(exist_ok=True)
    chunks = [
        WebpageChunk(
            resource_id="youtube:r2m9DbEmeqI",
            chunk_id=f"youtube:r2m9DbEmeqI-c000{i}",
            source_type=SourceType.WEBPAGE,
            text=f"chunk {i}",
            citation_label=f"paragraph {i}",
            url="https://youtube.com/watch?v=r2m9DbEmeqI",
        )
        for i in range(1, 3)
    ]
    Storage.write_jsonl((chunk.model_dump() for chunk in chunks), norm_dir / "chunks.jsonl")
    return ResourceRecord(
        id="youtube:r2m9DbEmeqI",
        source_type=SourceType.WEBPAGE,
        canonical_id="youtube:r2m9DbEmeqI",
        original_url="https://youtube.com/watch?v=r2m9DbEmeqI",
        title=PIPE_TITLE,
        status=ResourceStatus.PROCESSED,
        generated_note_path=note_path,
        local_normalized_path=norm_dir,
        llm_provider="mock",
        llm_model="mock-model",
        prompt_version="harish_llm_wiki_v4",
        tags=["rag", "retrieval"],
    )


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
    concept_extractor.concepts = {}
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


class TestMdTableCell:
    def test_pipe_escape(self):
        assert md_table_cell("A | B") == r"A \| B"

    def test_none_returns_empty(self):
        assert md_table_cell(None) == ""

    def test_newline_replacement(self):
        assert md_table_cell("multi\nline") == "multi line"

    def test_whitespace_collapse(self):
        assert md_table_cell("  too   many  spaces  ") == "too many spaces"

    def test_mixed_pipe_and_newline(self):
        assert md_table_cell("A | B\nC | D") == r"A \| B C \| D"

    def test_pipe_title_fixture(self):
        result = md_table_cell(PIPE_TITLE)
        assert "|" not in result or "\\|" in result
        assert r"\|" in result


class TestRouteHelpers:
    def test_resource_route(self):
        assert resource_route("youtube:r2m9DbEmeqI") == "/resources/youtube_r2m9DbEmeqI"

    def test_resource_route_no_colon(self):
        assert resource_route("webpage_test") == "/resources/webpage_test"

    def test_concept_route(self):
        assert concept_route("rag-retrieval") == "/concepts/rag-retrieval"

    def test_topic_route(self):
        assert topic_route("embeddings") == "/topics/embeddings"

    def test_learn_route(self):
        assert learn_route("llm-inference") == "/learn/llm-inference"


class TestResourceTablePipeEscape:
    def test_pipe_title_does_not_break_resources_table(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record_with_pipe_title(tmp_path)
        monkeypatch.setattr(site_builder, "data_site_dir", tmp_path / "site_generated" / "docs")
        site_builder.data_site_dir = tmp_path / "site_generated" / "docs"
        site_builder.data_site_dir.mkdir(parents=True, exist_ok=True)
        site_builder._build_resources([record])
        index_path = site_builder.data_site_dir / "resources" / "index.md"
        content = index_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.startswith("|") and "BM25" in line:
                assert r"\|" in line, f"Pipe not escaped in: {line}"
                cells = line.split("|")
                assert len(cells) <= 7, f"Too many pipe cells in: {line}"

    def test_resources_table_links_no_md_suffix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path)
        site_builder.data_site_dir = tmp_path / "site_generated" / "docs"
        site_builder.data_site_dir.mkdir(parents=True, exist_ok=True)
        site_builder._build_resources([record])
        index_path = site_builder.data_site_dir / "resources" / "index.md"
        content = index_path.read_text(encoding="utf-8")
        assert ".md)" not in content, "Resource links should not use .md suffix"

    def test_resource_page_created_without_generated_note(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path)
        record.generated_note_path = None
        site_builder.data_site_dir = tmp_path / "site_generated" / "docs"
        site_builder.data_site_dir.mkdir(parents=True, exist_ok=True)
        site_builder._build_resources([record])
        resource_path = site_builder.data_site_dir / "resources" / "webpage_test.md"
        assert resource_path.exists()
        content = resource_path.read_text(encoding="utf-8")
        assert "## Resource metadata" in content
        assert "No generated note is available" in content


class TestExplorerNoInlineJson:
    def test_explorer_no_const_items(self):
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
        assert "const items = [" not in html
        assert "const items =" not in html

    def test_explorer_loads_search_json(self):
        items = []
        html = search_index_generator._explorer(items)
        assert "search/all.json" in html
        assert "fetch(" in html

    def test_explorer_has_static_fallback_table(self):
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
        assert "## Resource summary" in html
        assert "## Recent resources" in html
        assert "| [" in html

    def test_explorer_fetch_error_message(self):
        items = []
        html = search_index_generator._explorer(items)
        assert "Could not load search index. Check /search/all.json." in html

    def test_explorer_pipe_title_escaped(self):
        items = [
            {
                "id": "youtube:r2m9DbEmeqI",
                "title": PIPE_TITLE,
                "type": "youtube",
                "summary": "A test.",
                "tags": [],
                "topics": [],
                "source_url": "https://youtube.com/watch?v=r2m9DbEmeqI",
                "local_page": "/resources/youtube_r2m9DbEmeqI",
                "provider": "llm_cache_hit",
                "model": "",
                "prompt_version": "v4",
                "requires_human_review": False,
                "review_status": "ok",
                "stale_status": "current",
                "created_at": "2026-05-31",
                "updated_at": "",
            }
        ]
        html = search_index_generator._explorer(items)
        assert r"\|" in html
        assert ".md)" not in html


class TestSmokeSitePrompt21:
    def test_smoke_detects_md_links_in_resources(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        resources_dir = tmp_path / "site_generated" / "docs" / "resources"
        resources_dir.mkdir(parents=True, exist_ok=True)
        index = resources_dir / "index.md"
        index.write_text(
            "# Resources\n\n| Title | Type | Status | Date |\n|---|---|---|---|\n"
            "| [Test](./webpage_test.md) | webpage | processed | 2026-01-01 |\n",
            encoding="utf-8",
        )
        for section in ["explorer", "sources", "review", "revision", "learn", "tags"]:
            d = tmp_path / "site_generated" / "docs" / section
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.md").write_text(f"# {section.title()}\n\nContent here.\n", encoding="utf-8")
        timeline = tmp_path / "site_generated" / "docs" / "timeline.md"
        timeline.write_text("# Timeline\n\nSome timeline content.\n", encoding="utf-8")
        gaps = tmp_path / "site_generated" / "docs" / "gaps.md"
        gaps.write_text("# Knowledge Gaps\n\nSome gaps content.\n", encoding="utf-8")
        home = tmp_path / "site_generated" / "docs" / "index.md"
        home.write_text("# Home\n\nWelcome to the wiki.\n\nSome content here for size.\n", encoding="utf-8")
        public_dir = tmp_path / "site_generated" / "docs" / "public" / "search"
        public_dir.mkdir(parents=True, exist_ok=True)
        json_data = {"generated_at": "2026-01-01", "items": [{"id": "x"}]}
        (public_dir / "all.json").write_text(json.dumps(json_data), encoding="utf-8")
        (public_dir / "resources.json").write_text(json.dumps(json_data), encoding="utf-8")
        explorer_dir = tmp_path / "site_generated" / "docs" / "explorer"
        explorer_dir.mkdir(parents=True, exist_ok=True)
        (explorer_dir / "index.md").write_text(
            "# Explorer\n\n<div id='wiki-explorer'></div>\n"
            "<script>async function initExplorer() { const base = '/'; const r = await fetch(base+'search/all.json'); }</script>\n"
            "## Resource summary\n\n| Count | Value |\n|---|---:|\n| Indexed items | 1 |\n\n"
            "## Recent resources\n\n| Title | Type |\n|---|---|\n| [Test](/resources/test) | webpage |\n",
            encoding="utf-8",
        )
        result = CliRunner().invoke(cli.app, ["smoke-site"])
        assert ".md)" in result.output or result.exit_code != 0, "Should detect .md) links"


class TestValidatePrompt21:
    def test_validate_detects_md_resource_links(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        resources_dir = site_builder.repo_site_dir / "resources"
        resources_dir.mkdir(parents=True, exist_ok=True)
        (resources_dir / "index.md").write_text(
            "# Resources\n\n| Title | Type | Status | Date |\n|---|---|---|---|\n"
            "| [Test](./webpage_test.md) | webpage | processed | 2026-01-01 |\n",
            encoding="utf-8",
        )
        for section in ["review", "explorer", "sources", "revision", "learn", "tags"]:
            d = site_builder.repo_site_dir / section
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.md").write_text(f"# {section.title()}\n\nContent.\n", encoding="utf-8")
        (site_builder.repo_site_dir / "timeline.md").write_text("# Timeline\n\nContent.\n", encoding="utf-8")
        (site_builder.repo_site_dir / "gaps.md").write_text("# Gaps\n\nContent.\n", encoding="utf-8")
        public_dir = site_builder.repo_site_dir / "public" / "search"
        public_dir.mkdir(parents=True, exist_ok=True)
        json_data = {"generated_at": "2026-01-01", "items": [{"id": "x", "local_page": "/resources/test"}]}
        (public_dir / "all.json").write_text(json.dumps(json_data), encoding="utf-8")
        (public_dir / "resources.json").write_text(json.dumps(json_data), encoding="utf-8")
        result = CliRunner().invoke(cli.app, ["validate"])
        assert ".md)" in result.output or "error" in result.output.lower()

    def test_validate_detects_missing_search_local_page_target(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        reg = Registry()
        monkeypatch.setattr(cli, "registry", reg)
        for section in ["review", "explorer", "sources", "revision", "learn", "tags"]:
            d = site_builder.repo_site_dir / section
            d.mkdir(parents=True, exist_ok=True)
            if section == "explorer":
                (d / "index.md").write_text(
                    "# Explorer\n\n<div id='wiki-explorer'></div>\n"
                    "<script>fetch('/search/all.json')</script>\n"
                    "Could not load search index. Check /search/all.json.\n\n"
                    "## Resource summary\n\n| Count | Value |\n|---|---:|\n| Indexed items | 1 |\n\n"
                    "## Recent resources\n\n| Title | Type |\n|---|---|\n| [Missing](/resources/missing) | webpage |\n",
                    encoding="utf-8",
                )
            else:
                (d / "index.md").write_text(f"# {section.title()}\n\nContent.\n", encoding="utf-8")
        (site_builder.repo_site_dir / "timeline.md").write_text("# Timeline\n\nContent.\n", encoding="utf-8")
        (site_builder.repo_site_dir / "gaps.md").write_text("# Gaps\n\nContent.\n", encoding="utf-8")
        public_dir = site_builder.repo_site_dir / "public" / "search"
        public_dir.mkdir(parents=True, exist_ok=True)
        json_data = {"generated_at": "2026-01-01", "items": [{"id": "x", "local_page": "/resources/missing"}]}
        (public_dir / "all.json").write_text(json.dumps(json_data), encoding="utf-8")
        (public_dir / "resources.json").write_text(json.dumps(json_data), encoding="utf-8")
        result = CliRunner().invoke(cli.app, ["validate"])
        assert "local_page target missing" in result.output


class TestCLIAliases:
    def test_regenerate_derived_alias_exists(self):
        from wiki.cli import app
        command_names = [cmd.name for cmd in app.registered_commands]
        assert "regenerate-derived" in command_names

    def test_regenerate_revision_alias_exists(self):
        from wiki.cli import app
        command_names = [cmd.name for cmd in app.registered_commands]
        assert "regenerate-revision" in command_names

    def test_regenerate_notes_alias_exists(self):
        from wiki.cli import app
        command_names = [cmd.name for cmd in app.registered_commands]
        assert "regenerate-notes" in command_names


class TestSearchIndexNoMdLinks:
    def test_resource_item_local_page_no_md(self):
        record = _record_with_pipe_title(Path("/tmp/dummy"))
        item = search_index_generator._resource_item(record)
        assert not item["local_page"].endswith(".md"), f"local_page should not end with .md: {item['local_page']}"
        assert item["local_page"] == "/resources/youtube_r2m9DbEmeqI"

    def test_citation_item_local_page_no_md(self):
        record = _record_with_pipe_title(Path("/tmp/dummy"))
        items = search_index_generator._citation_items([record])
        if items:
            assert not items[0]["local_page"].endswith(".md")


class TestFullBuildWithPipeTitle:
    def test_full_build_pipe_title_escaped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        pipe_record = _record_with_pipe_title(tmp_path)
        normal_record = _record(tmp_path)
        normal_note_path = tmp_path / "processed" / "resources" / "webpage_test.md"
        normal_note_path.write_text(_note(), encoding="utf-8")

        from wiki.generate.concepts import concept_extractor
        from wiki.generate.timeline import timeline_generator
        from wiki.generate.tags import tags_generator
        from wiki.generate.topics import topic_generator
        from wiki.generate.gaps import gaps_generator
        from wiki.generate.learn import learn_generator
        from wiki.generate.review import review_generator
        from wiki.generate.revision import revision_generator as rg

        records = [pipe_record, normal_record]
        concept_extractor.concepts = {}
        concept_extractor.aggregate(records)
        concept_extractor.save()
        timeline_generator.save(timeline_generator.generate(records))
        tags_generator.save(tags_generator.generate(records))
        topic_generator.save(topic_generator.generate(records))
        gaps_generator.save(gaps_generator.generate(records))
        learn_generator.save(learn_generator.generate(records))
        review_generator.save(review_generator.generate(records))
        search_index_generator.save(search_index_generator.generate(records))
        rg.save(rg.generate(records))

        site_builder.data_site_dir = tmp_path / "site_generated" / "docs"
        site_builder.repo_site_dir.mkdir(parents=True, exist_ok=True)
        site_builder._build_resources(records)

        index_path = site_builder.data_site_dir / "resources" / "index.md"
        content = index_path.read_text(encoding="utf-8")
        assert ".md)" not in content
        for line in content.splitlines():
            if "BM25" in line and line.startswith("|"):
                assert r"\|" in line

    def test_explorer_generated_with_fetch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path)
        indexes = search_index_generator.generate([record])
        search_index_generator.save(indexes)
        explorer_path = tmp_path / "site_generated" / "docs" / "explorer" / "index.md"
        explorer_path.parent.mkdir(parents=True, exist_ok=True)
        explorer_content = search_index_generator._explorer(indexes["all"])
        Storage.write_text(explorer_content, explorer_path)
        content = explorer_path.read_text(encoding="utf-8")
        assert "const items = [" not in content
        assert "search/all.json" in content
