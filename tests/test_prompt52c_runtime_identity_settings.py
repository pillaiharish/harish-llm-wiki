"""Prompt 52C runtime identity and launch settings checks."""

from __future__ import annotations

import json
from pathlib import Path

from wiki.site.branding import (
    configure_runtime_identity,
    load_branding_config,
    render_public_runtime_identity,
    render_vitepress_branding,
)


def test_runtime_identity_defaults_match_current_public_branding():
    cfg = load_branding_config(Path("missing-runtime-identity-config.yaml"))

    assert cfg.runtime_identity.default_owner_name == "Harish"
    assert cfg.runtime_identity.default_site_title == "Harish LLM Wiki"
    assert cfg.runtime_identity.allow_browser_override is True

    payload = json.loads(render_public_runtime_identity(cfg))
    assert payload == {
        "schemaVersion": "runtime_identity_v1",
        "defaultOwnerName": "Harish",
        "defaultSiteTitle": "Harish LLM Wiki",
        "allowBrowserOverride": True,
    }


def test_custom_runtime_identity_config_changes_public_json_and_vitepress_payload(tmp_path):
    config_path = tmp_path / "wiki_config.yaml"
    config_path.write_text(
        """
site:
  title: "Team Knowledge Bench"
  owner_name: "Team"
  description: "Configurable local knowledge workbench"
runtime_identity:
  default_owner_name: "Team"
  default_site_title: "Team Knowledge Bench"
  allow_browser_override: false
""",
        encoding="utf-8",
    )

    cfg = load_branding_config(config_path)
    runtime_payload = json.loads(render_public_runtime_identity(cfg))
    vitepress_payload = render_vitepress_branding(cfg)

    assert runtime_payload["defaultOwnerName"] == "Team"
    assert runtime_payload["defaultSiteTitle"] == "Team Knowledge Bench"
    assert runtime_payload["allowBrowserOverride"] is False
    assert "Team Knowledge Bench" in vitepress_payload


def test_configure_runtime_identity_writes_config_and_artifacts(tmp_path):
    config_path = tmp_path / "wiki_config.yaml"
    vitepress_output = tmp_path / "site-branding.generated.ts"
    public_output = tmp_path / "site-branding.json"

    config_out, vitepress_out, public_out = configure_runtime_identity(
        owner_name="Ada",
        title="Ada Knowledge Lab",
        config_path=config_path,
        vitepress_output_path=vitepress_output,
        public_identity_output_path=public_output,
    )

    assert config_out == config_path
    assert vitepress_out == vitepress_output
    assert public_out == public_output
    assert "default_owner_name: Ada" in config_path.read_text(encoding="utf-8")
    assert "default_site_title: Ada Knowledge Lab" in config_path.read_text(
        encoding="utf-8"
    )
    assert "Ada Knowledge Lab" in vitepress_output.read_text(encoding="utf-8")
    assert json.loads(public_output.read_text(encoding="utf-8")) == {
        "schemaVersion": "runtime_identity_v1",
        "defaultOwnerName": "Ada",
        "defaultSiteTitle": "Ada Knowledge Lab",
        "allowBrowserOverride": True,
    }


def test_settings_page_components_and_navigation_are_registered():
    page = Path("site/docs/settings/index.md").read_text(encoding="utf-8")
    config = Path("site/docs/.vitepress/config.ts").read_text(encoding="utf-8")
    theme = Path("site/docs/.vitepress/theme/index.ts").read_text(encoding="utf-8")
    provider = Path(
        "site/docs/.vitepress/theme/components/RuntimeIdentityProvider.vue"
    ).read_text(encoding="utf-8")
    settings = Path(
        "site/docs/.vitepress/theme/components/RuntimeIdentitySettings.vue"
    ).read_text(encoding="utf-8")
    builder = Path("wiki/site/builder.py").read_text(encoding="utf-8")
    cli = Path("wiki/cli.py").read_text(encoding="utf-8")

    assert "<RuntimeIdentitySettings />" in page
    assert "{ text: 'Settings', link: '/settings/' }" in config
    assert "'/settings/'" in config
    assert "RuntimeIdentityProvider" in theme
    assert "RuntimeIdentitySettings" in theme
    assert "withBase('/site-branding.json')" in provider
    assert "llmWiki.runtimeIdentity.v1" in provider
    assert "llmWiki.runtimeIdentity.v1" in settings
    assert "write_public_runtime_identity" in builder
    assert '@app.command("configure-site")' in cli


def test_public_branding_json_excludes_provider_or_secret_terms():
    payload_text = Path("site/docs/public/site-branding.json").read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    lower = payload_text.lower()

    assert payload["defaultOwnerName"] == "Harish"
    assert payload["defaultSiteTitle"] == "Harish LLM Wiki"
    for forbidden in [
        "api_key",
        "apikey",
        "token",
        "provider",
        "openai",
        "ollama",
        ".env",
        "secret",
    ]:
        assert forbidden not in lower
