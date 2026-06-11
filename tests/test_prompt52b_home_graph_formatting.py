"""Prompt 52B home landing and graph dashboard formatting checks."""

from pathlib import Path

from wiki.schemas import ResourceRecord, ResourceStatus, SourceType
from wiki.site.builder import SiteBuilder


def test_home_features_are_clickable_links_and_keep_branding_defaults(tmp_path):
    builder = SiteBuilder()
    builder.data_site_dir = tmp_path / "site_generated" / "docs"
    builder.repo_site_dir = tmp_path / "repo_docs"
    builder.data_site_dir.mkdir(parents=True)
    builder.repo_site_dir.mkdir(parents=True)

    records = [
        ResourceRecord(
            id="webpage:processed",
            canonical_id="webpage:processed",
            source_type=SourceType.WEBPAGE,
            original_url="https://example.com/processed",
            title="Processed Resource",
            status=ResourceStatus.PROCESSED,
        ),
        ResourceRecord(
            id="webpage:new",
            canonical_id="webpage:new",
            source_type=SourceType.WEBPAGE,
            original_url="https://example.com/new",
            title="New Resource",
            status=ResourceStatus.NEW,
        ),
    ]

    builder._build_home(records)
    home = (builder.data_site_dir / "index.md").read_text(encoding="utf-8")

    assert 'name: "Harish LLM Wiki"' in home
    assert 'text: "Personal Learning Wiki"' in home
    assert "📚 2 Resources" in home
    assert "✅ 1 Processed" in home
    for expected in [
        "link: /resources/",
        "link: /review/",
        "link: /explorer/",
        "link: /timeline",
        "link: /ingest/",
    ]:
        assert expected in home


def test_graph_dashboard_uses_structured_rows_and_metadata_grid():
    component = Path("site/docs/.vitepress/theme/components/GraphExplorer.vue").read_text(
        encoding="utf-8"
    )

    for expected in [
        'class="ge-top-node-row"',
        'class="gn-pick ge-top-node-button"',
        'class="ge-top-rank"',
        'class="ge-degree-badge"',
        'class="ge-metadata-grid"',
        'class="ge-metadata-row"',
    ]:
        assert expected in component
    assert "(degree:" not in component
    assert 'class="ge-metadata-table"' not in component


def test_shared_css_keeps_home_features_on_one_wide_row():
    css = Path("site/docs/.vitepress/theme/style.css").read_text(encoding="utf-8")

    assert ".VPHome .VPFeatures .items > .item.grid-4" in css
    assert "width: 20% !important;" in css
    assert ".VPHome .VPFeature[href]" in css
