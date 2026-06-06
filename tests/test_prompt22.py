"""Tests for Prompt 22: Topic Alias Canonicalization and Duplicate Topic Removal."""

import json
from pathlib import Path

from typer.testing import CliRunner

from wiki import cli
from wiki.config import config
from wiki.generate.page_utils import md_table_cell, resource_route
from wiki.generate.search import search_index_generator
from wiki.generate.topics import topic_generator
from wiki.generate.revision import revision_generator
from wiki.registry import Registry
from wiki.resource_utils import (
    TOPIC_ALIASES,
    TOPIC_DEFINITIONS,
    normalize_topic_list,
    normalize_topic_slug,
    topic_matches,
)
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


def _record(tmp_path: Path, *, title: str = "RAG Hybrid Retrieval", tags: list = None) -> ResourceRecord:
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
        title=title,
        status=ResourceStatus.PROCESSED,
        generated_note_path=note_path,
        local_normalized_path=norm_dir,
        llm_provider="mock",
        llm_model="mock-model",
        prompt_version="harish_llm_wiki_v4",
        tags=tags or ["rag", "retrieval"],
    )


def _security_record(tmp_path: Path) -> ResourceRecord:
    sec_note = tmp_path / "processed" / "resources" / "webpage_sec.md"
    sec_note.parent.mkdir(parents=True, exist_ok=True)
    sec_note.write_text(
        "# Security Notes\n\n## One-line memory hook\n\nPrompt injection matters.\n\n"
        "## Source-backed summary\n\n- Prompt injection is an attack. [source: webpage:sec-c0001]\n\n"
        "## Revision questions\n\n1. What is prompt injection?\n\n"
        "## Provenance\n\n- LLM provider: mock\n",
        encoding="utf-8",
    )
    norm_dir = tmp_path / "normalized_sec"
    norm_dir.mkdir(exist_ok=True)
    chunks = [
        WebpageChunk(
            resource_id="webpage:sec",
            chunk_id="webpage:sec-c0001",
            source_type=SourceType.WEBPAGE,
            text="security chunk",
            citation_label="paragraph 1",
            url="https://example.com/security",
        )
    ]
    Storage.write_jsonl((chunk.model_dump() for chunk in chunks), norm_dir / "chunks.jsonl")
    return ResourceRecord(
        id="webpage:sec",
        source_type=SourceType.WEBPAGE,
        canonical_id="webpage:sec",
        original_url="https://example.com/security",
        title="AI Security Fundamentals",
        status=ResourceStatus.PROCESSED,
        generated_note_path=sec_note,
        local_normalized_path=norm_dir,
        llm_provider="mock",
        llm_model="mock-model",
        prompt_version="harish_llm_wiki_v4",
        tags=["security", "ai"],
    )


class TestNormalizeTopicSlug:
    def test_rag_alias(self):
        assert normalize_topic_slug("rag") == "rag-retrieval"

    def test_security_alias(self):
        assert normalize_topic_slug("security") == "ai-security"

    def test_canonical_passed_through(self):
        assert normalize_topic_slug("rag-retrieval") == "rag-retrieval"

    def test_unknown_slug_passed_through(self):
        assert normalize_topic_slug("agents") == "agents"

    def test_retrieval_alias(self):
        assert normalize_topic_slug("retrieval") == "rag-retrieval"

    def test_ai_safety_alias(self):
        assert normalize_topic_slug("ai-safety") == "ai-security"


class TestNormalizeTopicList:
    def test_dedupe_canonical_and_alias(self):
        assert normalize_topic_list(["rag-retrieval", "rag"]) == ["rag-retrieval"]

    def test_dedupe_security_aliases(self):
        assert normalize_topic_list(["security", "ai-security"]) == ["ai-security"]

    def test_preserves_order(self):
        result = normalize_topic_list(["rag", "agents"])
        assert result == ["rag-retrieval", "agents"]

    def test_filters_nonexistent(self):
        result = normalize_topic_list(["rag-retrieval", "nonexistent"])
        assert result == ["rag-retrieval"]

    def test_empty_list(self):
        assert normalize_topic_list([]) == []

    def test_all_canonical(self):
        result = normalize_topic_list(["rag-retrieval", "agents", "vllm"])
        assert result == ["rag-retrieval", "agents", "vllm"]


class TestTopicMatchesCanonical:
    def test_no_duplicate_canonical_and_alias(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, tags=["rag", "retrieval"])
        topics = topic_matches(record)
        assert "rag" not in topics, f"Alias 'rag' should not appear in {topics}"
        assert "rag-retrieval" in topics, f"Canonical 'rag-retrieval' should appear in {topics}"

    def test_security_matches_canonical(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _security_record(tmp_path)
        topics = topic_matches(record)
        assert "security" not in topics, f"Alias 'security' should not appear in {topics}"
        assert "ai-security" in topics, f"Canonical 'ai-security' should appear in {topics}"


class TestTopicDefinitionsNoAliases:
    def test_no_rag_alias_in_definitions(self):
        assert "rag" not in TOPIC_DEFINITIONS, "Alias 'rag' should not be in TOPIC_DEFINITIONS"

    def test_no_security_alias_in_definitions(self):
        assert "security" not in TOPIC_DEFINITIONS, "Alias 'security' should not be in TOPIC_DEFINITIONS"

    def test_rag_retrieval_in_definitions(self):
        assert "rag-retrieval" in TOPIC_DEFINITIONS

    def test_ai_security_in_definitions(self):
        assert "ai-security" in TOPIC_DEFINITIONS

    def test_learn_slugs_all_in_definitions(self):
        from wiki.resource_utils import LEARN_DEFINITION_SLUGS
        for slug in LEARN_DEFINITION_SLUGS:
            assert slug in TOPIC_DEFINITIONS, f"Learn slug '{slug}' missing from TOPIC_DEFINITIONS"


class TestTopicGeneratorNoDuplicates:
    def test_no_duplicate_display_names(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, tags=["rag", "retrieval"])
        topics = topic_generator.generate([record])
        display_names = []
        for slug in topics:
            if slug in TOPIC_DEFINITIONS:
                display_names.append(TOPIC_DEFINITIONS[slug]["name"])
        assert len(display_names) == len(set(display_names)), f"Duplicate display names: {display_names}"

    def test_no_alias_slug_pages(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, tags=["rag", "retrieval"])
        topics = topic_generator.generate([record])
        for slug in topics:
            assert slug not in TOPIC_ALIASES, f"Alias slug '{slug}' should not be generated as a topic page"


class TestSearchIndexNoAliasTopics:
    def test_resource_topics_canonical_only(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, tags=["rag", "retrieval"])
        item = search_index_generator._resource_item(record)
        for slug in item["topics"]:
            assert slug not in TOPIC_ALIASES, f"Alias slug '{slug}' in resource topics"

    def test_all_json_no_alias_topic_entries(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, tags=["rag", "retrieval"])
        indexes = search_index_generator.generate([record])
        for item in indexes["all"]:
            item_id = item.get("id", "")
            if item_id.startswith("topic:"):
                slug = item_id.replace("topic:", "")
                assert slug not in TOPIC_ALIASES, f"Alias topic slug '{slug}' in all.json"

    def test_no_topic_rag_or_security_ids(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, tags=["rag", "retrieval"])
        indexes = search_index_generator.generate([record])
        ids = [item["id"] for item in indexes["all"]]
        assert "topic:rag" not in ids, "topic:rag should not appear in search index"
        assert "topic:security" not in ids, "topic:security should not appear in search index"


class TestRevisionNoAliasTopics:
    def test_revision_questions_use_canonical_topic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, tags=["rag"])
        data = revision_generator.generate([record])
        topics = {item["topic"] for item in data["questions"]}
        assert "rag" not in topics
        assert "rag-retrieval" in topics


class TestTopicMapNoDuplicateDisplayNames:
    def test_topic_index_no_duplicate_names(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, tags=["rag", "retrieval"])
        topics = topic_generator.generate([record])
        path = topic_generator.save(topics)
        index_content = (path / "index.md").read_text(encoding="utf-8")
        import re
        names = re.findall(r"- \[(.+?)\]", index_content)
        assert len(names) == len(set(names)), f"Duplicate topic display names in Topic Map: {names}"

    def test_rag_retrieval_appears_once(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, tags=["rag", "retrieval"])
        topics = topic_generator.generate([record])
        path = topic_generator.save(topics)
        index_content = (path / "index.md").read_text(encoding="utf-8")
        count = index_content.count("RAG / Retrieval")
        assert count == 1, f"'RAG / Retrieval' appears {count} times, expected 1"

    def test_ai_security_appears_once(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _security_record(tmp_path)
        topics = topic_generator.generate([record])
        path = topic_generator.save(topics)
        index_content = (path / "index.md").read_text(encoding="utf-8")
        count = index_content.count("AI Security")
        assert count == 1, f"'AI Security' appears {count} times, expected 1"
