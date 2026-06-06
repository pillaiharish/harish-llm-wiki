"""Tests for Prompt 20: Tags, Gaps, Manifest, Derived View Refresh Consistency."""

import json
from pathlib import Path

from wiki.config import config
from wiki.generate.gaps import gaps_generator
from wiki.generate.tags import tags_generator
from wiki.generate.page_utils import read_note
from wiki.schemas import ResourceRecord, ResourceStatus, SourceType, WebpageChunk
from wiki.storage import Storage


def _note_with_prereqs(*, prereq_line: str = "", next_line: str = "", fallback: bool = False) -> str:
    lines = [
        "# Test Resource",
        "",
        "## Recommended prerequisites",
        "",
    ]
    if prereq_line:
        lines.append(prereq_line)
    else:
        lines.append("- Topic A")
    lines.extend([
        "",
        "## Why this resource matters",
        "",
        "This is important.",
        "",
        "## One-line memory hook",
        "",
        "A short hook.",
        "",
        "## Source-backed summary",
        "",
        "- Claim with citation. [source: webpage:test-c0001]",
        "",
        "## Needs verification",
        "",
        "- Verify the claim.",
        "",
        "## Harish project connections",
        "",
    ])
    if fallback:
        lines.append("- Requires human review to connect this resource to Harish projects.")
    else:
        lines.append("- Connects to RAGOpsBench.")
    lines.extend([
        "",
        "## Suggested next learning topics",
        "",
    ])
    if next_line:
        lines.append(next_line)
    else:
        lines.append("- Hybrid search")
    lines.extend([
        "",
        "## Revision questions",
        "",
        "1. What is retrieval-augmented generation?",
        "",
        "## Citations",
        "",
        "- [source: webpage:test-c0001]",
        "",
        "## Provenance",
        "",
        "- LLM provider: mock",
    ])
    return "\n".join(lines)


def _record(tmp_path: Path, *, weak: bool = False, fallback: bool = False,
             prereq_line: str = "", next_line: str = "", tags: list = None) -> ResourceRecord:
    note_path = tmp_path / "processed" / "resources" / "webpage_test.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(_note_with_prereqs(prereq_line=prereq_line, next_line=next_line, fallback=fallback),
                         encoding="utf-8")
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
    extra = {"requires_human_review": weak or fallback, "quality_status": "weak" if weak else None}
    if fallback:
        extra["note_completed_by_fallback"] = True
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
        tags=tags or ["rag"],
        extra=extra,
    )


class TestTagsGeneration:
    def test_tags_include_source_type(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path)
        tags = tags_generator.generate([record])
        assert "webpage" in tags, f"Expected 'webpage' tag, got: {list(tags.keys())}"

    def test_tags_include_topic_tags(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, tags=["rag"])
        tags = tags_generator.generate([record])
        user_tags = {k for k in tags if k in ("rag", "webpage")}
        assert len(user_tags) >= 2, f"Expected user and type tags, got: {list(tags.keys())[:10]}"

    def test_tags_summary_table(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, tags=["rag", "retrieval"])
        tags = tags_generator.generate([record])
        md_path = tags_generator.save(tags)
        content = md_path.read_text(encoding="utf-8")
        assert "## Summary" in content
        assert "| Tag | Count |" in content

    def test_tags_cleanup_removes_stale_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        tags_dir = config.get_data_path("processed", "tags")
        tags_dir.mkdir(parents=True, exist_ok=True)
        stale = tags_dir / "stale_tag.md"
        stale.write_text("# Stale Tag\nOld content.\n", encoding="utf-8")
        assert stale.exists()
        record = _record(tmp_path, tags=["fresh"])
        tags = tags_generator.generate([record])
        tags_generator.save(tags)
        assert not stale.exists(), "Stale tag file should be removed"


class TestGapsGeneration:
    def test_gaps_populates_weak_notes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, weak=True)
        report = gaps_generator.generate([record])
        weak_names = [g.concept_name for g in report.weak_examples]
        assert report.weak_examples, "Expected weak note gaps"
        assert "RAG Hybrid Retrieval" in weak_names

    def test_gaps_populates_fallback_notes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, fallback=True)
        report = gaps_generator.generate([record])
        fallback_names = [g.concept_name for g in report.weak_examples]
        assert report.weak_examples, "Expected fallback gaps"
        assert any("RAG Hybrid Retrieval" in n for n in fallback_names)

    def test_gaps_no_placeholder_sections(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path)
        report = gaps_generator.generate([record])
        md_path = gaps_generator.save(report)
        content = md_path.read_text(encoding="utf-8")
        assert "To be populated" not in content, "Gap page should not contain placeholder text"

    def test_gaps_missing_prerequisites(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, prereq_line="- Vector databases — not yet in wiki")
        report = gaps_generator.generate([record])
        prereq_gaps = [g for g in report.needs_verification if g.gap_type == "missing_prerequisite"]
        assert prereq_gaps, "Expected missing prerequisite gaps"
        assert any("Vector databases" in g.concept_name for g in prereq_gaps)

    def test_gaps_missing_next_topics(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, next_line="- PagedAttention — not yet in wiki")
        report = gaps_generator.generate([record])
        next_gaps = [g for g in report.needs_verification if g.gap_type == "missing_next_topic"]
        assert next_gaps, "Expected missing next topic gaps"
        assert any("PagedAttention" in g.concept_name for g in next_gaps)

    def test_gaps_duplicates_grouped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        r1 = _record(tmp_path, prereq_line="- Vector databases — not yet in wiki")
        r1.id = r1.canonical_id = "webpage:test1"
        r2_note = tmp_path / "processed" / "resources" / "webpage_test2.md"
        r2_note.parent.mkdir(parents=True, exist_ok=True)
        r2_note.write_text(_note_with_prereqs(prereq_line="- Vector databases — not yet in wiki"),
                          encoding="utf-8")
        r2_norm = tmp_path / "normalized2"
        r2_norm.mkdir(exist_ok=True)
        chunks2 = [
            WebpageChunk(
                resource_id="webpage:test2",
                chunk_id="webpage:test2-c0001",
                source_type=SourceType.WEBPAGE,
                text="chunk 1",
                citation_label="paragraph 1",
                url="https://example.com/rag2",
            )
        ]
        Storage.write_jsonl((c.model_dump() for c in chunks2), r2_norm / "chunks.jsonl")
        r2 = ResourceRecord(
            id="webpage:test2",
            source_type=SourceType.WEBPAGE,
            canonical_id="webpage:test2",
            original_url="https://example.com/rag2",
            title="Another RAG Resource",
            status=ResourceStatus.PROCESSED,
            generated_note_path=r2_note,
            local_normalized_path=r2_norm,
            llm_provider="mock",
            llm_model="mock-model",
            prompt_version="harish_llm_wiki_v4",
            tags=["rag"],
        )
        report = gaps_generator.generate([r1, r2])
        prereq_gaps = [g for g in report.needs_verification if g.gap_type == "missing_prerequisite"]
        vector_gaps = [g for g in prereq_gaps if "Vector databases" in g.concept_name]
        assert len(vector_gaps) == 1, f"Expected grouped gap, got {len(vector_gaps)}"
        assert len(vector_gaps[0].mentioned_in) == 2, f"Should mention both resources, got {vector_gaps[0].mentioned_in}"

    def test_gaps_cleanup_removes_stale_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        gaps_dir = config.get_data_path("processed", "gaps")
        gaps_dir.mkdir(parents=True, exist_ok=True)
        stale = gaps_dir / "stale_gaps.md"
        stale.write_text("# Stale Gaps\nOld content.\n", encoding="utf-8")
        assert stale.exists()
        record = _record(tmp_path)
        report = gaps_generator.generate([record])
        gaps_generator.save(report)
        assert not stale.exists(), "Stale gaps file should be removed"


class TestGenerationManifest:
    def test_manifest_created_after_derived_views(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        from wiki import cli
        from wiki.generate.concepts import concept_extractor
        from wiki.generate.timeline import timeline_generator
        from wiki.generate.tags import tags_generator as tg
        from wiki.generate.topics import topic_generator
        from wiki.generate.gaps import gaps_generator as gg
        from wiki.generate.learn import learn_generator
        from wiki.generate.review import review_generator
        from wiki.generate.search import search_index_generator
        from wiki.generate.revision import revision_generator

        record = _record(tmp_path)
        reg = __import__("wiki.registry", fromlist=["Registry"]).Registry()
        monkeypatch.setattr(cli, "registry", reg)
        monkeypatch.setattr(cli, "concept_extractor", concept_extractor)
        monkeypatch.setattr(cli, "timeline_generator", timeline_generator)
        monkeypatch.setattr(cli, "tags_generator", tg)
        monkeypatch.setattr(cli, "topic_generator", topic_generator)
        monkeypatch.setattr(cli, "gaps_generator", gg)
        monkeypatch.setattr(cli, "learn_generator", learn_generator)
        monkeypatch.setattr(cli, "review_generator", review_generator)
        monkeypatch.setattr(cli, "search_index_generator", search_index_generator)
        monkeypatch.setattr(cli, "revision_generator", revision_generator)

        manifest = cli.generate_derived_views([record])
        manifest_path = config.get_data_path("processed", "generated_manifest.json")
        assert manifest_path.exists()
        assert manifest["generated_at"]
        assert manifest["resource_count"] >= 1
        assert manifest["timeline_periods"] >= 1
        assert manifest["timeline_entries"] >= 1
        assert manifest["search_index_items"] >= 1

    def test_manifest_counts_tags_and_gaps(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, tags=["rag", "retrieval"])
        report = gaps_generator.generate([record])
        tags = tags_generator.generate([record])
        from wiki import cli
        manifest_path = cli.write_generation_manifest(
            [record], tags=tags, gaps=report,
        )
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["tag_count"] >= 1
        assert "gaps_count" in data
        assert "timeline_entries" in data

    def test_tags_include_topic_fallback_from_title(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        record = _record(tmp_path, tags=[])
        tags = tags_generator.generate([record])
        assert "rag-retrieval" in tags


class TestConceptsCleanup:
    def test_concepts_cleanup_removes_stale_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        concepts_dir = config.get_data_path("processed", "concepts")
        concepts_dir.mkdir(parents=True, exist_ok=True)
        stale = concepts_dir / "stale_concept.md"
        stale.write_text("# Stale Concept\nOld content.\n", encoding="utf-8")
        stale_json = concepts_dir / "stale_concept.json"
        stale_json.write_text("{}", encoding="utf-8")
        assert stale.exists()
        from wiki.generate.concepts import concept_extractor
        concept_extractor.concepts = {}
        concept_extractor.aggregate([])
        concept_extractor.save()
        assert not stale.exists(), "Stale concept file should be removed"


class TestRevisionCleanup:
    def test_revision_cleanup_removes_stale_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        revision_dir = config.get_data_path("processed", "revision")
        revision_dir.mkdir(parents=True, exist_ok=True)
        stale = revision_dir / "stale_revision.md"
        stale.write_text("# Stale Revision\nOld content.\n", encoding="utf-8")
        assert stale.exists()
        from wiki.generate.revision import revision_generator
        data = revision_generator.generate([])
        revision_generator.save(data)
        assert not stale.exists(), "Stale revision file should be removed"
