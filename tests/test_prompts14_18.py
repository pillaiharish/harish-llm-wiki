"""Tests for Prompts 14-18 generated wiki layers."""

from pathlib import Path
import tarfile

from typer.testing import CliRunner

from wiki import cli
from wiki.config import config
from wiki.generate.learn import learn_generator
from wiki.generate.review import review_generator
from wiki.generate.search import search_index_generator
from wiki.generate.revision import revision_generator
from wiki.registry import Registry
from wiki.schemas import ResourceRecord, ResourceStatus, SourceType, WebpageChunk
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
- Chunking affects retrieval quality. [source: webpage:test-c0003]

## Concrete example / toy implementation

```python
contexts = retrieve(query)
```

## Needs verification

- Verify retrieval metrics.

## Revision questions

1. What is retrieval-augmented generation?
2. Why does chunking affect RAG quality?

## Harish project connections

Connect this to RAGOpsBench.

## Suggested next learning topics

- Hybrid search

## Citations

- [source: webpage:test-c0001]
- [source: webpage:test-c0002]
- [source: webpage:test-c0003]

## Provenance

- LLM provider: mock
"""


def _record(tmp_path: Path, *, weak: bool = False) -> ResourceRecord:
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
        for i in range(1, 4)
    ]
    Storage.write_jsonl((chunk.model_dump() for chunk in chunks), norm_dir / "chunks.jsonl")
    extra = {"requires_human_review": weak, "quality_status": "weak" if weak else None}
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
        extra=extra,
    )


def test_learn_pages_generate_requested_slugs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    record = _record(tmp_path)

    chapters = learn_generator.generate([record])
    path = learn_generator.save(chapters)

    assert (path / "rag-retrieval.md").exists()
    assert (path / "embeddings.md").exists()
    content = (path / "rag-retrieval.md").read_text(encoding="utf-8")
    assert "## Source-backed synthesis" in content
    assert "RAG retrieves context" in content


def test_review_pages_detect_weak_fallback_failed_and_missing_citations(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    weak = _record(tmp_path, weak=True)
    fallback = _record(tmp_path, weak=True)
    fallback.id = fallback.canonical_id = "webpage:fallback"
    fallback.extra["note_completed_by_fallback"] = True
    failed = _record(tmp_path)
    failed.id = failed.canonical_id = "webpage:failed"
    failed.status = ResourceStatus.FAILED_RETRYABLE

    data = review_generator.generate([weak, fallback, failed])
    path = review_generator.save(data)

    assert data["weak"]
    assert data["fallback"]
    assert data["failed"]
    assert (path / "index.md").exists()
    assert "Weak notes" in (path / "index.md").read_text(encoding="utf-8")


def test_search_index_explorer_and_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    record = _record(tmp_path)
    learn_dir = tmp_path / "processed" / "learn"
    learn_dir.mkdir(parents=True)
    (learn_dir / "rag-retrieval.md").write_text("# Topic: RAG / Retrieval\n", encoding="utf-8")

    indexes = search_index_generator.generate([record])
    path = search_index_generator.save(indexes)

    item = indexes["resources"][0]
    assert {"id", "title", "type", "summary", "tags", "topics", "source_url", "local_page", "provider", "model", "prompt_version", "requires_human_review", "created_at", "updated_at"} <= set(item)
    assert indexes["all"]
    assert (path / "all.json").exists()
    assert (tmp_path / "site_generated" / "docs" / "explorer" / "index.md").exists()
    assert (tmp_path / "site_generated" / "docs" / "sources" / "index.md").exists()


def test_revision_generation_and_exports(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    record = _record(tmp_path, weak=True)
    learn_dir = tmp_path / "processed" / "learn"
    learn_dir.mkdir(parents=True)
    (learn_dir / "rag-retrieval.md").write_text("# Topic: RAG / Retrieval\n\n## Source-backed synthesis\n\n- One claim.\n", encoding="utf-8")

    data = revision_generator.generate([record])
    path = revision_generator.save(data)
    json_export = revision_generator.export(data, "json")
    csv_export = revision_generator.export(data, "csv")

    assert data["questions"]
    assert data["flashcards"]
    assert data["weak_areas"]
    assert (path / "flashcards.md").exists()
    assert json_export.exists()
    assert csv_export.exists()


def test_doctor_status_backup_restore_and_release_checklist(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    config.ensure_directories()
    reg = Registry()
    monkeypatch.setattr(cli, "registry", reg)

    result = CliRunner().invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    assert "Python >= 3.11" in result.output

    result = CliRunner().invoke(cli.app, ["status-report"])
    assert result.exit_code == 0
    assert list((tmp_path / "reports").glob("status_report_*.json"))

    (tmp_path / "tmp").mkdir(exist_ok=True)
    (tmp_path / "tmp" / "skip.txt").write_text("skip", encoding="utf-8")
    result = CliRunner().invoke(cli.app, ["backup"])
    assert result.exit_code == 0
    backup_path = next((tmp_path / "backups").glob("*.tar.gz"))
    with tarfile.open(backup_path, "r:gz") as tar:
        assert all(not member.name.startswith("tmp/") for member in tar.getmembers())

    restore_target = tmp_path / "restored"
    result = CliRunner().invoke(cli.app, ["restore", "--file", str(backup_path), "--target-dir", str(restore_target)])
    assert result.exit_code == 0
    assert (restore_target / "registry" / "resources.sqlite").exists()
    assert Path("docs/RELEASE_CHECKLIST.md").exists()


def test_vitepress_config_includes_new_sections():
    content = Path("site/docs/.vitepress/config.ts").read_text(encoding="utf-8")
    for text in ["Learn", "Review", "Explorer", "Sources", "Revision"]:
        assert text in content
