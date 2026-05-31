"""Tests for VitePress site page rendering."""

from wiki.schemas import ResourceRecord, SourceType, ResourceStatus
from wiki.site.builder import SiteBuilder


def test_resource_page_includes_metadata_header(tmp_path):
    note_path = tmp_path / "processed" / "resources" / "webpage_test.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        "# Generated Title\n\n"
        "## Why this resource matters\n\n"
        "Content\n",
        encoding="utf-8",
    )

    record = ResourceRecord(
        id="webpage:test",
        source_type=SourceType.WEBPAGE,
        canonical_id="webpage:test",
        original_url="https://example.com/post",
        normalized_url="https://example.com/canonical-post",
        title="Real Article",
        author="Example Author",
        status=ResourceStatus.PROCESSED,
        generated_note_path=note_path,
        llm_provider="mock",
        llm_model="mock-model",
        prompt_version="harish_llm_wiki_v3",
    )

    builder = SiteBuilder()
    builder.repo_site_dir = tmp_path / "repo_docs"
    builder.data_site_dir = tmp_path / "site_generated" / "docs"

    builder.data_site_dir.mkdir(parents=True)
    builder.repo_site_dir.mkdir(parents=True)
    builder._build_resources([record])
    builder._sync_to_repo_site()

    page = builder.repo_site_dir / "resources" / "webpage_test.md"
    content = page.read_text(encoding="utf-8")

    assert "| Author/channel | Example Author |" in content
    assert "| Source URL | https://example.com/canonical-post |" in content
    assert "## Resource metadata" in content
    assert "## Resource table of contents" in content
    assert "| Prompt version | harish_llm_wiki_v3 |" in content
    assert content.count("# Real Article") == 1
    assert "# Generated Title" not in content
