"""Prompt 52A formatting and ingest clarity checks."""

from datetime import datetime
from pathlib import Path

from wiki.generate.search import search_index_generator
from wiki.schemas import ResourceRecord, ResourceStatus, SourceType
from wiki.site.builder import SiteBuilder


def test_resources_index_uses_cards_instead_of_wrapping_table(tmp_path):
    record = ResourceRecord(
        id="medium_markdown:test-resource",
        canonical_id="medium_markdown:test-resource",
        source_type=SourceType.MEDIUM_MARKDOWN,
        original_url="https://example.com/long-resource",
        title="COG-RAG-Giving-RAG-A-Brain",
        status=ResourceStatus.FAILED_RETRYABLE,
        first_seen_at=datetime(2026, 6, 6),
    )

    builder = SiteBuilder()
    builder.data_site_dir = tmp_path / "site_generated" / "docs"
    builder.repo_site_dir = tmp_path / "repo_docs"
    builder.data_site_dir.mkdir(parents=True)
    builder.repo_site_dir.mkdir(parents=True)
    builder._build_resources([record])

    content = (builder.data_site_dir / "resources" / "index.md").read_text(encoding="utf-8")

    assert "| Title | Type | Status | Date |" not in content
    assert "wiki-resource-grid" in content
    assert "wiki-resource-card" in content
    assert "wiki-type-chip" in content
    assert "medium markdown" in content
    assert "wiki-status-chip" in content
    assert "failed retryable" in content
    assert "wiki-date-cell" in content
    assert "2026-06-06" in content
    assert "wiki-resource-id" in content


def test_sources_page_uses_cards_instead_of_wrapping_table():
    content = search_index_generator._sources(
        [
            {
                "title": "COG-RAG-Giving-RAG-A-Brain",
                "type": "medium_markdown",
                "source_url": "https://pub.towardsai.net/cog-rag-giving-rag-a-brain-that-thinks-before-it-retrieves",
                "local_page": "/resources/medium_markdown_test",
                "provider": "ollama_cloud",
                "model": "glm-4.5:cloud",
            }
        ]
    )

    assert "| Source URL | Resource | Type | Provider/model |" not in content
    assert "wiki-source-grid" in content
    assert "wiki-source-card" in content
    assert "wiki-source-url" in content
    assert "wiki-type-chip" in content
    assert "medium markdown" in content
    assert "wiki-provider-chip" in content
    assert "ollama cloud" in content
    assert "wiki-model-chip" in content
    assert "glm-4.5:cloud" in content


def test_theme_css_protects_generated_chips_from_letter_wrapping():
    css = Path("site/docs/.vitepress/theme/style.css").read_text(encoding="utf-8")

    for selector in [
        ".wiki-data-table",
        ".wiki-nowrap-chip",
        ".wiki-status-chip",
        ".wiki-provider-chip",
        ".wiki-date-cell",
        ".wiki-resource-grid",
        ".wiki-source-grid",
    ]:
        assert selector in css
    assert "white-space: nowrap;" in css
    assert "word-break: normal;" in css


def test_ingest_page_keeps_command_builder_first_and_names_control_plane_boundary():
    content = Path("site/docs/ingest/index.md").read_text(encoding="utf-8")

    builder_index = content.index("<IngestCommandBuilder />")
    reference_index = content.index("## Choose Your Processing Mode")
    assert builder_index < reference_index
    assert "This page builds commands only." in content
    assert "Use the local control plane prompt next" in content
    assert "These cards are secondary reference." in content
