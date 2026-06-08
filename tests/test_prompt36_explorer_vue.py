"""Tests for Prompt 36: Fix /explorer VitePress side-effect tags.

The Prompt 36 acceptance criteria are:

  - /explorer/ opens without Vite overlay (no raw <script>/<style>
    side-effect warning).
  - The interactive explorer is rendered by a Vue component
    (``<SearchExplorer />``) registered globally by the VitePress
    theme.
  - The Markdown at ``site/docs/explorer/index.md`` (and the
    generated Markdown from ``wiki/generate/search.py``) does not
    contain raw ``<script>`` or ``<style>`` blocks.
  - Existing explorer functionality is preserved: load
    ``/search/all.json`` at runtime, render an interactive search
    UI with a deterministic error fallback, and surface a static
    resource summary and "Recent resources" table for no-JS / SSR
    contexts.
  - The graph viewer still works (regression check).

The tests below are split into two groups:

  1. Static checks against the in-repo Markdown files and theme
     files. These do not run VitePress, so they are fast and
     reliable across platforms.
  2. Behavioural checks against ``_explorer()`` (the Python
     template generator) and the Vue component source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wiki.generate.search import search_index_generator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DOCS = REPO_ROOT / "site" / "docs"
EXPLORER_MD = SITE_DOCS / "explorer" / "index.md"
THEME_INDEX_TS = SITE_DOCS / ".vitepress" / "theme" / "index.ts"
COMPONENTS_DIR = SITE_DOCS / ".vitepress" / "theme" / "components"
SEARCH_EXPLORER_VUE = COMPONENTS_DIR / "SearchExplorer.vue"


# ---------------------------------------------------------------------------
# Static checks against the in-repo Markdown / theme files
# ---------------------------------------------------------------------------


class TestExplorerMarkdown:
    """The in-repo Markdown must not contain side-effect tags."""

    def test_explorer_md_exists(self):
        assert EXPLORER_MD.exists(), f"Missing {EXPLORER_MD}"

    def test_explorer_md_no_raw_script_tag(self):
        content = EXPLORER_MD.read_text(encoding="utf-8")
        # The page must not contain a literal ``<script>...</script>``
        # block. VitePress would strip it and emit a side-effect
        # warning in the dev server.
        assert "<script>" not in content, (
            "explorer/index.md still has a raw <script> tag — VitePress "
            "will warn about side-effect tags in client component "
            "templates."
        )
        assert "<script " not in content, (
            "explorer/index.md has a raw <script ...> tag — VitePress "
            "will warn about side-effect tags."
        )
        assert "</script>" not in content, (
            "explorer/index.md has a closing </script> tag."
        )

    def test_explorer_md_no_raw_style_tag(self):
        content = EXPLORER_MD.read_text(encoding="utf-8")
        assert "<style>" not in content, (
            "explorer/index.md still has a raw <style> tag."
        )
        assert "<style " not in content
        assert "</style>" not in content

    def test_explorer_md_mounts_search_explorer_component(self):
        content = EXPLORER_MD.read_text(encoding="utf-8")
        assert "<SearchExplorer" in content, (
            "explorer/index.md must mount the <SearchExplorer /> "
            "Vue component to render the interactive UI."
        )

    def test_explorer_md_keeps_legacy_wiki_explorer_marker(self):
        # Older smoke / validate checks look for the
        # ``<div id="wiki-explorer">`` marker. We keep it as a
        # wrapper so those checks continue to pass.
        content = EXPLORER_MD.read_text(encoding="utf-8")
        assert 'id="wiki-explorer"' in content
        assert "## Resource summary" in content
        assert "## Recent resources" in content
        assert "search/all.json" in content
        # The error fallback string is mentioned in the page
        # description (wrapped in bold Markdown).
        assert "Could not load search index" in content
        assert "/search/all.json" in content


class TestSearchExplorerVueComponent:
    """The Vue component must exist and be registered globally."""

    def test_component_file_exists(self):
        assert SEARCH_EXPLORER_VUE.exists(), (
            f"Missing {SEARCH_EXPLORER_VUE}. The <SearchExplorer /> "
            "component must live at "
            "site/docs/.vitepress/theme/components/."
        )

    def test_component_uses_vue_3_sfc_syntax(self):
        content = SEARCH_EXPLORER_VUE.read_text(encoding="utf-8")
        # SFC: <script setup>, <template>, <style scoped>
        assert "<script setup" in content or "<script" in content
        assert "<template>" in content
        assert "</template>" in content
        # Scoped style block. Must NOT be ``<style>`` (that
        # would leak into the page and clash with VitePress's
        # theme).
        assert "<style scoped" in content

    def test_component_imports_vue_and_uses_ssr_safe_hooks(self):
        content = SEARCH_EXPLORER_VUE.read_text(encoding="utf-8")
        # The component must guard window/document/fetch access
        # by running browser-only logic inside onMounted.
        assert "onMounted" in content
        # The component explicitly checks ``typeof window ===
        # 'undefined'`` or similar SSR guard before touching the
        # DOM. Accept either pattern.
        assert (
            "typeof window === 'undefined'" in content
            or "import.meta.env.SSR" in content
        )
        # And it does not declare a raw ``<script>`` block
        # outside the SFC.
        assert content.count("<script") == 1

    def test_component_uses_search_all_json_url(self):
        content = SEARCH_EXPLORER_VUE.read_text(encoding="utf-8")
        # The component reads the on-disk search index at the
        # canonical ``/search/all.json`` path. It should use
        # ``import.meta.env.BASE_URL`` to support both root and
        # subpath deployments.
        assert "search/all.json" in content
        assert "import.meta.env.BASE_URL" in content

    def test_component_surfaces_error_state_message(self):
        content = SEARCH_EXPLORER_VUE.read_text(encoding="utf-8")
        # The component must surface the canonical fallback
        # error string when ``/search/all.json`` cannot be
        # loaded.
        assert "Could not load search index" in content
        assert "/search/all.json" in content

    def test_component_uses_fetch_inside_onmounted(self):
        # The fetch call must not happen at the top level of
        # ``<script setup>`` (which would run during SSR).
        # It must live inside the onMounted hook, possibly via
        # a small wrapper function.
        content = SEARCH_EXPLORER_VUE.read_text(encoding="utf-8")
        # Locate the body of the onMounted callback.
        m = re.search(r"onMounted\([^{]*\{(.*?)\n\}\)\)?\s*\n", content, re.DOTALL)
        assert m, "Component must define onMounted"
        onmounted_body = m.group(1)
        # The onMounted block must either call ``fetch(``
        # directly, or invoke a wrapper that does. We accept
        # either pattern as long as something async+fetch
        # related lives in the onMounted body.
        assert (
            "fetch(" in onmounted_body
            or "await fetch" in onmounted_body
            or "loadIndex()" in onmounted_body
        ), (
            "fetch() (or a wrapper that calls fetch) must live "
            "inside the onMounted hook to be SSR-safe."
        )
        # And the top of <script setup> must not call fetch
        # directly outside of any function. The onMounted guard
        # is what keeps SSR safe.
        script_open = content.find("<script")
        script_body = content[script_open:]
        # The fetch() call must not appear before onMounted is
        # defined.
        fetch_idx = script_body.find("fetch(")
        onmounted_idx = script_body.find("onMounted")
        assert fetch_idx == -1 or onmounted_idx < fetch_idx, (
            "fetch() must not appear in <script setup> before "
            "onMounted is defined."
        )

    def test_component_does_not_emit_external_network_calls(self):
        content = SEARCH_EXPLORER_VUE.read_text(encoding="utf-8")
        # No http(s):// fetch URLs in the component. The only
        # network resource is the on-disk ``/search/all.json``.
        urls = re.findall(r"https?://[^\s'\"`]+", content)
        assert not urls, f"Component must not fetch external URLs, got: {urls}"


class TestThemeRegistration:
    """The VitePress theme must register the <SearchExplorer /> component."""

    def test_theme_index_registers_search_explorer(self):
        content = THEME_INDEX_TS.read_text(encoding="utf-8")
        assert "SearchExplorer" in content, (
            "site/docs/.vitepress/theme/index.ts must import and "
            "register the SearchExplorer component."
        )
        # The component must be both imported and registered.
        assert "import SearchExplorer" in content
        assert "app.component('SearchExplorer'" in content

    def test_theme_index_still_registers_graph_explorer(self):
        # Regression: the graph viewer registration must remain.
        content = THEME_INDEX_TS.read_text(encoding="utf-8")
        assert "GraphExplorer" in content
        assert "app.component('GraphExplorer'" in content


# ---------------------------------------------------------------------------
# Behavioural checks against the Python template generator
# ---------------------------------------------------------------------------


class TestExplorerTemplateGenerator:
    """The Python ``_explorer()`` template must emit side-effect-free Markdown."""

    def test_explorer_md_has_no_raw_script_tag(self):
        items = []
        html = search_index_generator._explorer(items)
        assert "<script>" not in html
        assert "<script " not in html
        assert "</script>" not in html

    def test_explorer_md_has_no_raw_style_tag(self):
        items = []
        html = search_index_generator._explorer(items)
        assert "<style>" not in html
        assert "<style " not in html
        assert "</style>" not in html

    def test_explorer_md_mounts_search_explorer_component(self):
        items = []
        html = search_index_generator._explorer(items)
        assert "<SearchExplorer" in html, (
            "_explorer() must mount the <SearchExplorer /> Vue "
            "component instead of an inline <script> block."
        )

    def test_explorer_md_keeps_legacy_wiki_explorer_marker(self):
        items = []
        html = search_index_generator._explorer(items)
        assert 'id="wiki-explorer"' in html
        assert "## Resource summary" in html
        assert "## Recent resources" in html

    def test_explorer_md_mentions_search_index_path(self):
        items = []
        html = search_index_generator._explorer(items)
        assert "search/all.json" in html
        assert "Could not load search index" in html
        assert "/search/all.json" in html

    def test_explorer_md_with_real_items_includes_static_table(self):
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
        assert "Test Resource" in html
        # The Vue component, not a <script> block, is responsible
        # for the interactive UI.
        assert "<SearchExplorer" in html
        assert "<script>" not in html
