"""Tests for Prompt 41: Graphify-style enhanced graph explorer."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SITE = REPO_ROOT / "site"
COMPONENT = (
    SITE
    / "docs"
    / ".vitepress"
    / "theme"
    / "components"
    / "GraphifyExplorer.vue"
)
THEME_INDEX = SITE / "docs" / ".vitepress" / "theme" / "index.ts"
GRAPHIFY_PAGE = SITE / "docs" / "graph" / "graphify.md"
CONFIG = SITE / "docs" / ".vitepress" / "config.ts"
PACKAGE_JSON = SITE / "package.json"
BUILDER = REPO_ROOT / "wiki" / "site" / "builder.py"
STATIC_ROUTES = REPO_ROOT / "scripts" / "verify_site_static_routes.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestPrompt41FilesAndDependencies:
    def test_site_package_declares_vis_dependencies(self):
        text = _read(PACKAGE_JSON)
        assert '"vis-network"' in text
        assert '"vis-data"' in text

    def test_graphify_component_exists_and_registered(self):
        assert COMPONENT.exists()
        text = _read(THEME_INDEX)
        assert "GraphifyExplorer" in text
        assert "app.component('GraphifyExplorer'" in text

    def test_graphify_page_exists_and_mounts_component(self):
        assert GRAPHIFY_PAGE.exists()
        text = _read(GRAPHIFY_PAGE)
        assert "# Graphify Explorer" in text
        assert "<ClientOnly>" in text
        assert "<GraphifyExplorer />" in text


class TestPrompt41ComponentContracts:
    def test_component_uses_vis_runtime_and_vitepress_base(self):
        text = _read(COMPONENT)
        for needle in (
            "withBase",
            "vis-data/peer",
            "vis-network/peer",
            "Network",
            "DataSet",
            "DataView",
        ):
            assert needle in text

    def test_component_fetches_existing_graph_json_through_withbase(self):
        text = _read(COMPONENT)
        assert "fetch(withBase('/graph/nodes.json'))" in text
        assert "fetch(withBase('/graph/edges.json'))" in text

    def test_component_has_required_testids(self):
        text = _read(COMPONENT)
        for testid in (
            'data-testid="graphify-explorer"',
            'data-testid="graphify-network"',
            'data-testid="graphify-search"',
            'data-testid="graphify-fullscreen"',
            'data-testid="graphify-inspector"',
            'data-testid="graphify-open-node"',
        ):
            assert testid in text
        assert "graphify-type-filter-" in text

    def test_component_implements_degree_mapping_and_data_normalization(self):
        text = _read(COMPONENT)
        for needle in (
            "function degreeMapFromEdges",
            "function normalizeNodes",
            "function normalizeEdges",
            "degree[node.id]",
            "value: node.degree",
            "source || edge.from",
            "target || edge.to",
        ):
            assert needle in text

    def test_component_implements_route_mapping(self):
        text = _read(COMPONENT)
        for needle in (
            "function routeForNode",
            "/resources/",
            "/concepts/",
            "/topics/",
            "/learn/",
            "/review/weak-notes",
            "/review/missing-citations",
            "window.location.href = withBase(route)",
        ):
            assert needle in text

    def test_component_implements_search_filters_fullscreen_and_focus(self):
        text = _read(COMPONENT)
        for needle in (
            "function performSearch",
            "function onFiltersChanged",
            "function toggleFullscreen",
            "function applyFocusFade",
            "function focusNode",
            "function clearFocus",
            "getConnectedNodes",
            "getConnectedEdges",
            "requestFullscreen",
            "exitFullscreen",
        ):
            assert needle in text

    def test_component_is_ssr_safe(self):
        text = _read(COMPONENT)
        assert "onMounted" in text
        assert "typeof window === 'undefined'" in text
        assert "typeof document === 'undefined'" in text
        assert "import('vis-data/peer')" in text
        assert "import('vis-network/peer')" in text


class TestPrompt41NavigationAndGeneration:
    def test_graph_sidebar_links_to_graphify(self):
        text = _read(CONFIG)
        assert "{ text: 'Graphify explorer', link: '/graph/graphify' }" in text

    def test_builder_generates_graphify_page_and_landing_link(self):
        text = _read(BUILDER)
        assert "_build_graph_graphify_page(graph)" in text
        assert "template_name=\"graphify.md\"" in text
        assert 'href="/graph/graphify"' in text
        assert "Open Graphify Explorer" in text

    def test_static_route_verifier_includes_graphify(self):
        text = _read(STATIC_ROUTES)
        assert '"/graph/graphify"' in text
        assert '"graphify.md"' in text
