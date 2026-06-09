"""Tests for Prompt 38: Graph Insight Dashboard + Graph Lenses v1.

These tests are static-source string checks against the in-repo
``GraphExplorer.vue`` component and the ``site/docs/graph/viewer.md``
template. They mirror the style of ``TestGraphExplorerComponent``
in ``tests/test_prompt25_graph_visualization.py``.

The Prompt 38 acceptance criteria are:

  - Insight Dashboard with total / visible node + edge counts,
    selected-node row, and a top-connected-nodes list.
  - Lens selector with All / Resources / Topics / Concepts /
    Learn chapters / Review pages.
  - Layout selector with cose / grid / circle / concentric (cose
    is default and keeps its deterministic options).
  - Neighborhood mode toggle that restricts the visible set to
    the selected node's closed neighbourhood.
  - Details panel additions: incoming / outgoing / total degree +
    Copy node id button.
  - Existing Prompt 35.x / 25 / 37 contracts remain intact.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPONENT = (
    REPO_ROOT
    / "site"
    / "docs"
    / ".vitepress"
    / "theme"
    / "components"
    / "GraphExplorer.vue"
)
VIEWER_MD = REPO_ROOT / "site" / "docs" / "graph" / "viewer.md"


def _component() -> str:
    return COMPONENT.read_text(encoding="utf-8")


def _viewer() -> str:
    return VIEWER_MD.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class TestDashboard:
    def test_dashboard_has_required_ids(self):
        text = _component()
        for needle in (
            'id="graph-dashboard"',
            'id="graph-stat-total-nodes"',
            'id="graph-stat-total-edges"',
            'id="graph-stat-visible-nodes"',
            'id="graph-stat-visible-edges"',
            'id="graph-stat-selected"',
            'id="graph-stat-top-nodes"',
        ):
            assert needle in text, f"GraphExplorer.vue missing dashboard id {needle!r}"

    def test_dashboard_uses_computed_counts(self):
        text = _component()
        for needle in (
            "totalNodeCount",
            "totalEdgeCount",
            "visibleNodeCount",
            "visibleEdgeCount",
            "selectedDisplay",
            "topConnectedIds",
            "topConnectedNodes",
        ):
            assert needle in text, (
                f"GraphExplorer.vue missing dashboard computed/symbol {needle!r}"
            )

    def test_dashboard_renders_loading_and_error_states(self):
        text = _component()
        assert "dataState === 'loading'" in text
        assert "dataState === 'error'" in text
        assert "graph-dashboard-loading" in text
        assert "graph-dashboard-error" in text


# ---------------------------------------------------------------------------
# Lens selector
# ---------------------------------------------------------------------------


class TestLensSelector:
    def test_lens_selector_has_required_id_and_options(self):
        text = _component()
        assert 'id="graph-lens"' in text
        for option in (
            'value="all"',
            'value="resources"',
            'value="topics"',
            'value="concepts"',
            'value="learn_chapters"',
            'value="review_pages"',
        ):
            assert option in text, f"GraphExplorer.vue missing lens option {option!r}"

    def test_lens_default_is_all(self):
        text = _component()
        assert "lens = ref<LensValue>('all')" in text, (
            "GraphExplorer.vue lens ref must default to 'all'"
        )

    def test_lens_filters_by_node_type(self):
        text = _component()
        # The lens table maps each lens value to one of the canonical
        # node type strings. The 'all' value is intentionally null.
        for line in (
            "all: null",
            "resources: 'resource'",
            "topics: 'topic'",
            "concepts: 'concept'",
            "learn_chapters: 'learn_chapter'",
            "review_pages: 'review_page'",
        ):
            assert line in text, f"GraphExplorer.vue lens table missing {line!r}"
        assert "function lensAllowsType" in text
        assert "onLensChange" in text


# ---------------------------------------------------------------------------
# Layout selector
# ---------------------------------------------------------------------------


class TestLayoutSelector:
    def test_layout_selector_has_required_id_and_options(self):
        text = _component()
        assert 'id="graph-layout"' in text
        for option in (
            'value="cose"',
            'value="grid"',
            'value="circle"',
            'value="concentric"',
        ):
            assert option in text, f"GraphExplorer.vue missing layout option {option!r}"

    def test_layout_default_is_cose(self):
        text = _component()
        assert "layoutName = ref<LayoutValue>('cose')" in text, (
            "GraphExplorer.vue layoutName ref must default to 'cose'"
        )

    def test_layout_options_includes_grid_circle_concentric(self):
        text = _component()
        # The layout function returns cytoscape options keyed by name.
        assert "name: 'grid'" in text
        assert "name: 'circle'" in text
        assert "name: 'concentric'" in text
        assert "function layoutOptionsFor" in text
        # And the cose branch must delegate to the existing
        # coseLayoutOptions() so the deterministic contract holds.
        assert "coseLayoutOptions" in text
        assert "randomize: false" in text

    def test_layout_change_handler_runs_layout(self):
        text = _component()
        assert "onLayoutChange" in text
        assert "cy.layout(layoutOptionsFor" in text


# ---------------------------------------------------------------------------
# Neighborhood mode
# ---------------------------------------------------------------------------


class TestNeighborhoodMode:
    def test_neighborhood_button_has_required_id(self):
        text = _component()
        assert 'id="graph-neighborhood-mode"' in text

    def test_neighborhood_default_off(self):
        text = _component()
        assert "neighborhoodMode = ref<boolean>(false)" in text, (
            "neighborhoodMode ref must default to false"
        )

    def test_neighborhood_toggle_function_exists(self):
        text = _component()
        assert "function toggleNeighborhoodMode" in text
        assert "function exitNeighborhoodMode" in text
        # The exit affordance is rendered when the mode is on.
        assert 'id="graph-neighborhood-exit"' in text

    def test_neighborhood_button_disabled_without_selection(self):
        text = _component()
        assert ":disabled=\"!selectedNodeId\"" in text
        assert "aria-disabled" in text

    def test_neighborhood_filters_visible_nodes(self):
        text = _component()
        # The visibleNodeIds() function takes the closed-neighbourhood
        # path when neighborhood mode is on and a node is selected.
        assert "neighborhoodMode.value && selectedNodeId.value" in text
        assert "function closedNeighborhoodIds" in text

    def test_neighborhood_auto_disable_on_background_tap(self):
        text = _component()
        # The tap-on-background handler must clear neighborhood mode
        # so the user does not see an empty canvas.
        idx = text.find("evt.target === cy")
        assert idx > 0, "tap-on-background handler not found"
        block = text[idx : idx + 500]
        assert "neighborhoodMode.value = false" in block, (
            "tap-on-background handler must auto-disable neighborhood mode"
        )


# ---------------------------------------------------------------------------
# Details panel upgrade
# ---------------------------------------------------------------------------


class TestDetailsPanelUpgrade:
    def test_details_panel_has_incoming_outgoing_degree(self):
        text = _component()
        for needle in (
            'id="graph-stat-incoming"',
            'id="graph-stat-outgoing"',
            'id="graph-stat-degree"',
        ):
            assert needle in text, (
                f"GraphExplorer.vue details panel missing id {needle!r}"
            )
        # These ids must live inside the selectedNode block.
        sel_idx = text.find('v-else-if="selectedNode"')
        assert sel_idx != -1
        sel_block_end = text.find("v-else-if=\"selectedEdge\"", sel_idx)
        sel_block = text[sel_idx:sel_block_end]
        for needle in (
            'id="graph-stat-incoming"',
            'id="graph-stat-outgoing"',
            'id="graph-stat-degree"',
        ):
            assert needle in sel_block, (
                f"{needle} must be rendered inside the selectedNode block"
            )

    def test_details_panel_has_copy_node_id_button(self):
        text = _component()
        assert 'id="graph-copy-node-id"' in text
        assert "function copySelectedId" in text or "async function copySelectedId" in text

    def test_details_panel_helpers_exist(self):
        text = _component()
        assert "function incomingCountFor" in text
        assert "function outgoingCountFor" in text
        # And computed values that wrap them.
        assert "selectedIncomingCount" in text
        assert "selectedOutgoingCount" in text
        assert "selectedDegree" in text


# ---------------------------------------------------------------------------
# Debug surface: __graphExplorerState
# ---------------------------------------------------------------------------


class TestExplorerStateDebug:
    def test_window_explorer_state_handle_exposed(self):
        text = _component()
        assert "__graphExplorerState" in text, (
            "GraphExplorer.vue must expose window.__graphExplorerState "
            "for Playwright introspection"
        )
        assert "function updateExplorerStateDebug" in text

    def test_window_explorer_state_cleaned_up_on_unmount(self):
        text = _component()
        assert "delete (window as any).__graphExplorerState" in text, (
            "GraphExplorer.vue must delete window.__graphExplorerState in "
            "onBeforeUnmount so SPA navigations do not leak a stale handle"
        )


# ---------------------------------------------------------------------------
# Non-regression: existing Prompt 35.x / 25 / 37 contracts
# ---------------------------------------------------------------------------


class TestExistingContractsIntact:
    def test_dynamic_cytoscape_import_intact(self):
        text = _component()
        assert "import('cytoscape')" in text or 'import("cytoscape")' in text
        # No top-level static import.
        assert "from 'cytoscape'" not in text
        assert 'from "cytoscape"' not in text

    def test_semantic_zoom_symbols_intact(self):
        text = _component()
        for needle in (
            "ZOOM_TIER_LOW_MAX",
            "ZOOM_TIER_HIGH_MIN",
            "SEMANTIC_TIER_SPECS",
            "currentTier",
            "pickSemanticTier",
            "function applyNodeRoleClasses",
            "isSelected || inNeighborhood || isHover",
            "HUB_DEGREE_THRESHOLD_LOW_ZOOM",
            "__graphLabelDebug",
            "delete (window as any).__graphLabelDebug",
        ):
            assert needle in text, f"missing existing semantic-zoom symbol: {needle}"

    def test_existing_required_dom_ids_intact(self):
        text = _component()
        for control_id in (
            "graph-search",
            "graph-fit",
            "graph-reset-zoom",
            "graph-zoom-in",
            "graph-zoom-out",
            "graph-show-all",
            "graph-filter-node-type",
            "graph-filter-edge-type",
            "graph-canvas",
            "graph-details",
            "graph-neighbors",
        ):
            assert f'id="{control_id}"' in text, (
                f"GraphExplorer.vue missing existing control id {control_id!r}"
            )

    def test_no_duplicate_template_ids(self):
        text = _component()
        tmpl_match = re.search(r"<template>(.*?)</template>", text, re.DOTALL)
        assert tmpl_match, "no <template> block found"
        tmpl = tmpl_match.group(1)
        ids = re.findall(r'(?<=\s)id="([^"]+)"', tmpl)
        seen: dict[str, int] = {}
        for i in ids:
            seen[i] = seen.get(i, 0) + 1
        duplicates = sorted([k for k, v in seen.items() if v > 1])
        assert not duplicates, (
            f"GraphExplorer.vue has duplicate template DOM ids: {duplicates}"
        )

    def test_viewer_md_keeps_existing_contracts(self):
        text = _viewer()
        assert "<GraphExplorer />" in text
        assert '<svg id="graph-svg"' in text
        assert "<noscript>" in text
        assert "</noscript>" in text
        assert "initGraphViewer" in text
        assert "import.meta.env.BASE_URL" in text
        assert "/graph/resource-relationships" in text

    def test_viewer_md_mentions_new_features(self):
        # The "How to use" section gains lens / layout / neighborhood
        # / dashboard mentions so the help text stays accurate.
        text = _viewer()
        assert "Lens" in text
        assert "Layout" in text
        assert "Neighborhood mode" in text
        assert "Insight dashboard" in text
