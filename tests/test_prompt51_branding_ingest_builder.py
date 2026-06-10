"""Prompt 51 branding and static ingest command builder checks."""

from pathlib import Path

from wiki.schemas import ResourceRecord, ResourceStatus, SourceType
from wiki.site.branding import load_branding_config, render_vitepress_branding
from wiki.site.builder import SiteBuilder


def test_branding_defaults_preserve_current_site_identity():
    cfg = load_branding_config(Path("missing-branding-config.yaml"))

    assert cfg.site.title == "Harish LLM Wiki"
    assert cfg.site.owner_name == "Harish"
    assert cfg.site.description == "Personal static learning wiki"
    assert cfg.site.footer_message == "Generated with Harish LLM Wiki"
    assert cfg.site.github.edit_pattern == (
        "https://github.com/pillaiharish/harish-llm-wiki/edit/main/site/docs/:path"
    )

    rendered = render_vitepress_branding(cfg)
    assert "Harish LLM Wiki" in rendered
    assert "Personal static learning wiki" in rendered
    assert "pillaiharish/harish-llm-wiki" in rendered


def test_custom_branding_config_changes_home_and_vitepress_artifact(tmp_path):
    config_path = tmp_path / "wiki_config.yaml"
    config_path.write_text(
        """
site:
  title: "Team Knowledge Bench"
  owner_name: "Team"
  description: "Configurable local knowledge workbench"
  footer_message: "Generated with Team Knowledge Bench"
  hero:
    name: "Team Knowledge Bench"
    text: "Local Knowledge Workbench"
    tagline: "A configurable static learning system"
  github:
    owner: "example"
    repo: "knowledge-bench"
    branch: "main"
""",
        encoding="utf-8",
    )

    cfg = load_branding_config(config_path)
    rendered = render_vitepress_branding(cfg)

    assert "Team Knowledge Bench" in rendered
    assert "Configurable local knowledge workbench" in rendered
    assert "example/knowledge-bench/edit/main/site/docs/:path" in rendered

    builder = SiteBuilder()
    builder.branding = cfg
    builder.repo_site_dir = tmp_path / "repo_docs"
    builder.data_site_dir = tmp_path / "site_generated" / "docs"
    builder.repo_site_dir.mkdir(parents=True)
    builder.data_site_dir.mkdir(parents=True)

    record = ResourceRecord(
        id="webpage:test",
        canonical_id="webpage:test",
        source_type=SourceType.WEBPAGE,
        original_url="https://example.com",
        title="Example",
        status=ResourceStatus.PROCESSED,
    )
    builder._build_home([record])

    home = (builder.data_site_dir / "index.md").read_text(encoding="utf-8")
    assert 'name: "Team Knowledge Bench"' in home
    assert 'text: "Local Knowledge Workbench"' in home
    assert 'tagline: "A configurable static learning system"' in home
    assert "Configurable local knowledge workbench." in home


def test_vitepress_config_imports_generated_branding_artifact():
    config = Path("site/docs/.vitepress/config.ts").read_text(encoding="utf-8")
    artifact = Path("site/docs/.vitepress/site-branding.generated.ts").read_text(encoding="utf-8")

    assert "site-branding.generated" in config
    assert "title: siteBranding.title" in config
    assert "description: siteBranding.description" in config
    assert "pattern: siteBranding.githubEditPattern" in config
    assert "export const siteBranding" in artifact


def test_ingest_page_mounts_static_command_builder_and_keeps_token_boundary():
    content = Path("site/docs/ingest/index.md").read_text(encoding="utf-8")

    assert "<IngestCommandBuilder />" in content
    assert "does not accept API keys in the browser" in content
    assert "does not trigger provider calls from a page button" in content
    for expected in [
        ".venv/bin/python",
        "LLM_PROVIDER=mock",
        "--provider mock",
        "ollama_local",
        "ollama_cloud",
        "openai_compatible",
        ".env",
        "--dry-run",
        "--yes",
    ]:
        assert expected in content


def test_yaml_manifest_is_guidance_only_not_generated_command():
    component = Path("site/docs/.vitepress/theme/components/IngestCommandBuilder.vue").read_text(
        encoding="utf-8"
    )

    assert 'data-testid="ingest-command-builder"' in component
    assert "inputs/resources.example.yaml" in component
    assert "No YAML import CLI exists yet" in component
    for forbidden in [
        "add-yaml",
        "import-resources",
        "add-resources",
        "add-resource --dry-run",
    ]:
        assert forbidden not in component
