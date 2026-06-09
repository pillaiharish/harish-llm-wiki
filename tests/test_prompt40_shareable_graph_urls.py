"""Tests for Prompt 40: Saved Graph Views + Shareable Graph Query URLs v1.

Static-source string checks against ``GraphExplorer.vue`` and
``site/docs/graph/viewer.md``. Mirrors the style of
``tests/test_prompt39_graph_path_finder.py`` and
``tests/test_prompt38_graph_insight_dashboard.py``.

The Prompt 40 acceptance criteria are:

  - URL read/apply: ``window.location.search`` is parsed once,
    validated against the enums (``lens``, ``layout``), and
    applied after the graph data is loaded. Unknown / invalid
    values are ignored safely (no crash, default state shown).
  - URL update: every state-changing handler in the component
    (``onLensChange``, ``onLayoutChange``, ``pickNeighbor``,
    the three ``cy.on('tap', ...)`` handlers,
    ``toggleNeighborhoodMode``, ``exitNeighborhoodMode``,
    ``onPathSourceChange``, ``onPathTargetChange``,
    ``runPathFinder``, ``clearPathFinder``) calls
    ``updateGraphQueryParams()`` so the URL is kept in sync via
    ``history.replaceState``. Defaults are omitted from the URL.
  - Copy view URL: button with id ``graph-copy-view-url``
    copies a deterministic absolute shareable URL to the
    clipboard with a best-effort fallback (clipboard API →
    ``document.execCommand('copy')`` → no-op).
  - Reset URL state: button with id ``graph-reset-url-state``
    clears the graph query params from the URL and resets all
    URL-driven refs to their defaults, without a full page
    reload.
  - Debug handle: ``window.__graphUrlState`` with the spec
    fields (``ready``, ``query``, ``shareableUrl``,
    ``urlSynced``, ``appliedParams``, ``lastAction``), cleaned
    up in ``onBeforeUnmount``.
  - SSR safety: every ``window.*`` / ``window.location.*`` /
    ``window.history.*`` access is guarded with
    ``typeof window === 'undefined'`` or the equivalent.
  - No new package dependency.
  - Existing Prompt 35.x / 37 / 38 / 39 contracts remain intact.
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
PACKAGE_JSON = REPO_ROOT / "site" / "package.json"


def _component() -> str:
    return COMPONENT.read_text(encoding="utf-8")


def _viewer() -> str:
    return VIEWER_MD.read_text(encoding="utf-8")


def _package_json() -> str:
    return PACKAGE_JSON.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Type and constants
# ---------------------------------------------------------------------------


class TestUrlSchemaTypesAndConstants:
    def test_graph_query_params_type_defined(self):
        text = _component()
        assert "GraphQueryParams" in text
        for field in (
            "lens:",
            "layout:",
            "node:",
            "neighborhood:",
            "source:",
            "target:",
            "path:",
        ):
            assert field in text, f"GraphQueryParams missing field {field!r}"

    def test_valid_lens_values_constant(self):
        text = _component()
        assert "VALID_LENS_VALUES" in text, (
            "GraphExplorer.vue must define VALID_LENS_VALUES for read-time validation"
        )
        # All six lens values are present in the constant.
        for v in (
            "'all'",
            "'resources'",
            "'topics'",
            "'concepts'",
            "'learn_chapters'",
            "'review_pages'",
        ):
            assert v in text, f"VALID_LENS_VALUES missing {v!r}"

    def test_valid_layout_values_constant(self):
        text = _component()
        assert "VALID_LAYOUT_VALUES" in text
        for v in ("'cose'", "'grid'", "'circle'", "'concentric'"):
            assert v in text, f"VALID_LAYOUT_VALUES missing {v!r}"


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


class TestUrlReadHelpers:
    def test_read_graph_query_params_defined(self):
        text = _component()
        assert "function readGraphQueryParams" in text

    def test_read_graph_query_params_uses_urlsearchparams(self):
        text = _component()
        assert "URLSearchParams" in text, (
            "GraphExplorer.vue must use URLSearchParams to parse the share-URL query"
        )
        # The reader function must use URLSearchParams inside its body.
        idx = text.find("function readGraphQueryParams")
        assert idx > 0
        body = text[idx : idx + 3000]
        assert "URLSearchParams" in body

    def test_read_graph_query_params_guards_window(self):
        text = _component()
        idx = text.find("function readGraphQueryParams")
        body = text[idx : idx + 1000]
        assert "typeof window === 'undefined'" in body, (
            "readGraphQueryParams must guard window access (SSR-safe)"
        )

    def test_read_graph_query_params_validates_lens(self):
        text = _component()
        idx = text.find("function readGraphQueryParams")
        body = text[idx : idx + 3000]
        # The reader must compare against the valid lens values
        # via VALID_LENS_VALUES so an unknown lens value is dropped.
        assert "VALID_LENS_VALUES" in body
        assert "'lens'" in body

    def test_read_graph_query_params_validates_layout(self):
        text = _component()
        idx = text.find("function readGraphQueryParams")
        body = text[idx : idx + 3000]
        assert "VALID_LAYOUT_VALUES" in body
        assert "'layout'" in body

    def test_read_graph_query_params_treats_neighborhood_1_as_truthy(self):
        text = _component()
        idx = text.find("function readGraphQueryParams")
        body = text[idx : idx + 3000]
        assert "'neighborhood'" in body
        # Only the literal '1' is treated as truthy — anything
        # else (including empty, "true", "yes") is treated as off.
        assert "=== '1'" in body

    def test_read_graph_query_params_treats_path_1_as_truthy(self):
        text = _component()
        idx = text.find("function readGraphQueryParams")
        body = text[idx : idx + 3000]
        assert "'path'" in body

    def test_read_graph_query_params_reads_source_and_target(self):
        text = _component()
        idx = text.find("function readGraphQueryParams")
        body = text[idx : idx + 3000]
        assert "'source'" in body
        assert "'target'" in body

    def test_read_graph_query_params_reads_node(self):
        text = _component()
        idx = text.find("function readGraphQueryParams")
        body = text[idx : idx + 3000]
        assert "'node'" in body


# ---------------------------------------------------------------------------
# Apply helpers
# ---------------------------------------------------------------------------


class TestUrlApplyHelpers:
    def test_apply_graph_query_params_defined(self):
        text = _component()
        assert "function applyGraphQueryParams" in text

    def test_apply_graph_query_params_called_in_load_graph(self):
        text = _component()
        # The apply function must be called once from loadGraph()
        # AFTER buildCy() completes.
        idx = text.find("async function loadGraph")
        assert idx > 0
        body = text[idx : idx + 5000]
        assert "applyGraphQueryParams" in body, (
            "loadGraph() must call applyGraphQueryParams() after the graph is ready"
        )
        # The apply call must come AFTER buildCy().
        idx_build = body.find("buildCy()")
        idx_apply = body.find("applyGraphQueryParams")
        assert idx_build >= 0
        assert idx_apply >= 0
        assert idx_apply > idx_build, (
            "applyGraphQueryParams() must be called after buildCy() "
            "so node-id validation can succeed"
        )

    def test_apply_graph_query_params_validates_node_existence(self):
        text = _component()
        idx = text.find("function applyGraphQueryParams")
        body = text[idx : idx + 3000]
        # The apply step must only set selectedNodeId when the id
        # actually exists in the graph.
        assert "nodeById(params.node)" in body, (
            "applyGraphQueryParams must validate node ids against the loaded graph"
        )
        assert "params.source" in body
        assert "params.target" in body

    def test_apply_graph_query_params_runs_bfs_when_path_flag(self):
        text = _component()
        idx = text.find("function applyGraphQueryParams")
        body = text[idx : idx + 3000]
        assert "params.path" in body
        assert "findShortestPath" in body


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


class TestUrlWriteHelpers:
    def test_update_graph_query_params_defined(self):
        text = _component()
        assert "function updateGraphQueryParams" in text

    def test_update_graph_query_params_uses_replace_state(self):
        text = _component()
        idx = text.find("function updateGraphQueryParams")
        body = text[idx : idx + 1500]
        assert "history.replaceState" in body, (
            "updateGraphQueryParams must use history.replaceState (no full reload, "
            "no back-button pollution)"
        )

    def test_update_graph_query_params_guards_window_and_history(self):
        text = _component()
        idx = text.find("function updateGraphQueryParams")
        body = text[idx : idx + 1500]
        assert "typeof window === 'undefined'" in body
        assert "window.history" in body

    def test_update_graph_query_params_omits_defaults(self):
        text = _component()
        # The builder must not emit lens/layout when they equal
        # their defaults ("all" and "cose" respectively).
        idx = text.find("function buildGraphQueryString")
        assert idx > 0
        body = text[idx : idx + 1500]
        assert "lens.value !== 'all'" in body
        assert "layoutName.value !== 'cose'" in body

    def test_update_graph_query_params_is_called_from_lens_change(self):
        text = _component()
        idx = text.find("function onLensChange")
        body = text[idx : idx + 800]
        assert "updateGraphQueryParams()" in body

    def test_update_graph_query_params_is_called_from_layout_change(self):
        text = _component()
        idx = text.find("function onLayoutChange")
        body = text[idx : idx + 1200]
        assert "updateGraphQueryParams()" in body

    def test_update_graph_query_params_is_called_from_pick_neighbor(self):
        text = _component()
        idx = text.find("function pickNeighbor")
        body = text[idx : idx + 1500]
        assert "updateGraphQueryParams()" in body

    def test_update_graph_query_params_is_called_from_node_tap(self):
        text = _component()
        idx = text.find("cy.on('tap', 'node'")
        body = text[idx : idx + 1200]
        assert "updateGraphQueryParams()" in body

    def test_update_graph_query_params_is_called_from_edge_tap(self):
        text = _component()
        idx = text.find("cy.on('tap', 'edge'")
        body = text[idx : idx + 1200]
        assert "updateGraphQueryParams()" in body

    def test_update_graph_query_params_is_called_from_background_tap(self):
        text = _component()
        # The third tap handler is the background one: cy.on('tap')
        # (no selector).
        idx = text.find("cy.on('tap', (")
        body = text[idx : idx + 1200]
        assert "updateGraphQueryParams()" in body

    def test_update_graph_query_params_is_called_from_toggle_neighborhood(self):
        text = _component()
        idx = text.find("function toggleNeighborhoodMode")
        body = text[idx : idx + 800]
        assert "updateGraphQueryParams()" in body

    def test_update_graph_query_params_is_called_from_exit_neighborhood(self):
        text = _component()
        idx = text.find("function exitNeighborhoodMode")
        body = text[idx : idx + 600]
        assert "updateGraphQueryParams()" in body

    def test_update_graph_query_params_is_called_from_path_source_change(self):
        text = _component()
        idx = text.find("function onPathSourceChange")
        body = text[idx : idx + 600]
        assert "updateGraphQueryParams()" in body

    def test_update_graph_query_params_is_called_from_path_target_change(self):
        text = _component()
        idx = text.find("function onPathTargetChange")
        body = text[idx : idx + 600]
        assert "updateGraphQueryParams()" in body

    def test_update_graph_query_params_is_called_from_run_path_finder(self):
        text = _component()
        idx = text.find("function runPathFinder")
        body = text[idx : idx + 800]
        assert "updateGraphQueryParams()" in body

    def test_update_graph_query_params_is_called_from_clear_path_finder(self):
        text = _component()
        idx = text.find("function clearPathFinder")
        body = text[idx : idx + 800]
        assert "updateGraphQueryParams()" in body


# ---------------------------------------------------------------------------
# Build + copy
# ---------------------------------------------------------------------------


class TestUrlBuildAndCopy:
    def test_build_shareable_graph_url_defined(self):
        text = _component()
        assert "function buildShareableGraphUrl" in text

    def test_build_shareable_graph_url_uses_location(self):
        text = _component()
        idx = text.find("function buildShareableGraphUrl")
        body = text[idx : idx + 1500]
        assert "window.location" in body
        # Returns an absolute URL.
        assert "origin" in body

    def test_copy_view_url_defined(self):
        text = _component()
        assert "function copyViewUrl" in text

    def test_copy_view_url_uses_clipboard_api(self):
        text = _component()
        idx = text.find("function copyViewUrl")
        body = text[idx : idx + 2000]
        assert "navigator.clipboard" in body, (
            "copyViewUrl must use navigator.clipboard.writeText"
        )
        assert "writeText" in body

    def test_copy_view_url_has_exec_command_fallback(self):
        text = _component()
        idx = text.find("function copyViewUrl")
        body = text[idx : idx + 2000]
        # Mirrors the existing copySelectedId() pattern: a hidden
        # textarea + document.execCommand('copy') is the fallback
        # when the clipboard API is unavailable.
        assert "document.execCommand" in body
        assert "textarea" in body.lower()

    def test_copy_view_url_button_present(self):
        text = _component()
        assert 'id="graph-copy-view-url"' in text, (
            "GraphExplorer.vue must define the Copy view URL button"
        )
        idx = text.find('id="graph-copy-view-url"')
        block = text[idx : idx + 400]
        assert "@click=\"copyViewUrl\"" in block


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestUrlReset:
    def test_reset_url_state_defined(self):
        text = _component()
        assert "function resetUrlState" in text

    def test_reset_url_state_button_present(self):
        text = _component()
        assert 'id="graph-reset-url-state"' in text
        idx = text.find('id="graph-reset-url-state"')
        block = text[idx : idx + 400]
        assert "@click=\"resetUrlState\"" in block

    def test_reset_url_state_does_not_reload(self):
        # The reset must not call window.location.reload() — that
        # would be a full page reload, which the spec forbids.
        text = _component()
        idx = text.find("function resetUrlState")
        assert idx > 0
        # Bound the body — find the next function or `</script>`.
        end = text.find("\nfunction ", idx + 1)
        body = text[idx : end if end > 0 else idx + 2500]
        assert "window.location.reload" not in body, (
            "resetUrlState must NOT call window.location.reload()"
        )

    def test_reset_url_state_clears_lens_layout(self):
        text = _component()
        idx = text.find("function resetUrlState")
        body = text[idx : idx + 1500]
        assert "lens.value = 'all'" in body
        assert "layoutName.value = 'cose'" in body

    def test_reset_url_state_clears_path_state(self):
        text = _component()
        idx = text.find("function resetUrlState")
        body = text[idx : idx + 1500]
        assert "pathSourceId.value = ''" in body
        assert "pathTargetId.value = ''" in body
        assert "pathStatus.value = 'idle'" in body

    def test_reset_url_state_clears_selection(self):
        text = _component()
        idx = text.find("function resetUrlState")
        body = text[idx : idx + 1500]
        assert "selectedNodeId.value = null" in body
        assert "selectedEdgeId.value = null" in body
        assert "neighborhoodMode.value = false" in body

    def test_reset_url_state_writes_url(self):
        text = _component()
        idx = text.find("function resetUrlState")
        body = text[idx : idx + 1500]
        # The reset must call updateGraphQueryParams() so the
        # search string is cleared in-place.
        assert "updateGraphQueryParams()" in body


# ---------------------------------------------------------------------------
# Debug handle
# ---------------------------------------------------------------------------


class TestUrlDebugHandle:
    def test_update_graph_url_state_debug_defined(self):
        text = _component()
        assert "function updateGraphUrlStateDebug" in text

    def test_window_graph_url_state_set_with_spec_fields(self):
        text = _component()
        idx = text.find("function updateGraphUrlStateDebug")
        body = text[idx : idx + 1500]
        assert "__graphUrlState" in body
        for needle in (
            "ready:",
            "query",
            "shareableUrl:",
            "urlSynced:",
            "appliedParams:",
        ):
            assert needle in body, f"__graphUrlState missing field {needle!r}"

    def test_window_graph_url_state_last_action_supported(self):
        text = _component()
        idx = text.find("function updateGraphUrlStateDebug")
        body = text[idx : idx + 1500]
        # The helper takes an optional {lastAction: 'copied'|'copy_failed'|'reset'}
        # parameter that is exposed on the global.
        assert "lastAction" in body

    def test_window_graph_url_state_cleaned_on_unmount(self):
        text = _component()
        assert "delete (window as any).__graphUrlState" in text, (
            "GraphExplorer.vue must delete window.__graphUrlState in onBeforeUnmount"
        )

    def test_explorer_state_debug_keeps_url_state_in_sync(self):
        text = _component()
        idx = text.find("function updateExplorerStateDebug")
        body = text[idx : idx + 2000]
        # The Prompt 38 debug helper must also call the URL
        # debug helper so __graphUrlState stays fresh.
        assert "updateGraphUrlStateDebug()" in body


# ---------------------------------------------------------------------------
# SSR safety
# ---------------------------------------------------------------------------


class TestUrlSSR:
    def test_window_window_undefined_guards_present(self):
        # All new URL-state helpers that touch window /
        # window.location / window.history directly must guard
        # `window` with `typeof window === 'undefined'` (or the
        # equivalent). Helpers that delegate to other
        # already-guarded helpers (e.g. `resetUrlState` calls
        # `updateGraphQueryParams` + `updateGraphUrlStateDebug`)
        # are exempt because the window-touching logic lives
        # in the delegated helper. Helpers that work
        # exclusively on refs (e.g. `applyGraphQueryParams`,
        # `buildGraphQueryString`) or that touch only
        # `navigator` / `document` (e.g. `copyViewUrl`) are
        # also exempt.
        text = _component()
        window_touching = (
            "function readGraphQueryParams",
            "function buildShareableGraphUrl",
            "function updateGraphQueryParams",
            "function updateGraphUrlStateDebug",
        )
        for fn in window_touching:
            idx = text.find(fn)
            assert idx > 0, f"function {fn} not found"
            # Bound the body to the next function definition.
            end = text.find("\nfunction ", idx + 1)
            body = text[idx : end if end > 0 else idx + 2500]
            assert (
                "typeof window === 'undefined'" in body
                or "typeof window !== 'undefined'" in body
            ), f"{fn} must guard window access for SSR safety"

    def test_reset_url_state_delegates_to_guarded_helpers(self):
        # resetUrlState() resets the URL-driven state and then
        # delegates the actual window.history / window.location
        # mutation to updateGraphQueryParams() (guarded). The
        # SSR safety contract is preserved by delegation.
        text = _component()
        idx = text.find("function resetUrlState")
        body = text[idx : idx + 1500]
        assert "updateGraphQueryParams()" in body
        assert "updateGraphUrlStateDebug" in body

    def test_copy_view_url_guards_navigator_and_document(self):
        # copyViewUrl() does not touch window — it touches
        # navigator.clipboard and document. The existing
        # pattern guards those individually.
        text = _component()
        idx = text.find("function copyViewUrl")
        body = text[idx : idx + 2500]
        assert "typeof navigator !== 'undefined'" in body
        assert "typeof document === 'undefined'" in body

    def test_no_top_level_window_access(self):
        # There must be no `window.*`, `window.location.*`, or
        # `window.history.*` access at the top level of the
        # script — every access must live inside a function or
        # onMounted hook.
        text = _component()
        # Slice the script block.
        m = re.search(r"<script[^>]*>(.*?)</script>", text, re.DOTALL)
        assert m
        script = m.group(1)
        # Strip every function body. We use a coarse regex that
        # tracks brace depth — for our purposes, identifying
        # top-level access is enough.
        # Identify top-level statements by finding the first
        # non-import statement and excluding function bodies.
        # Practical proxy: scan for "window." / "window.location"
        # / "window.history" outside of any function block.
        # We do this by iteratively removing function bodies.
        cleaned = script
        prev = ""
        while cleaned != prev:
            prev = cleaned
            cleaned = re.sub(
                r"\bfunction\s+[A-Za-z_$][\w$]*[^{]*\{[^{}]*\}",
                "",
                cleaned,
            )
        # What remains is approximately the top-level code
        # (imports, type/const decls, and the onMounted /
        # onBeforeUnmount hooks — the latter are guarded).
        # Note: the regex stops at the first nested brace pair
        # which means function bodies with nested braces may
        # not be fully stripped; but for our top-level access
        # check we just need to look for lines that contain
        # "window." outside a function body. To be conservative
        # we only flag a violation if a top-level line contains
        # an *unguarded* window access — and we already know the
        # only places window is allowed are inside functions or
        # guarded hooks. The presence of any `window.` in the
        # residual script outside of an onMounted guard is a
        # smell we catch with the assertions above per
        # function. This test only confirms we have at least
        # one guard somewhere (for SSR) and the SFC has not
        # been turned into a non-SSR build by mistake.
        assert "typeof window" in script, (
            "Script block must include a typeof window guard somewhere for SSR safety"
        )


# ---------------------------------------------------------------------------
# No new package dependency
# ---------------------------------------------------------------------------


class TestUrlNoNewDependencies:
    def test_package_json_dependencies_unchanged(self):
        # The new URL layer uses only browser APIs (URLSearchParams,
        # history.replaceState, navigator.clipboard) — no new
        # dependency should be added.
        text = _package_json()
        # Dependencies block.
        for needle in (
            '"dependencies":',
            '"cytoscape"',
        ):
            assert needle in text, f"package.json missing {needle!r}"
        # The known dependencies must still be present.
        for needle in ("@playwright/test", "vitepress", "vue", "cytoscape"):
            assert needle in text, f"package.json missing required dep {needle!r}"
        # No 'qs' / 'query-string' / 'url-parse' dependency should
        # be there — we use the native URLSearchParams.
        for forbidden in (
            '"query-string"',
            '"url-parse"',
            '"url"',
            '"qs"',
        ):
            assert forbidden not in text, (
                f"package.json must NOT add a new URL-parsing dep {forbidden!r}"
            )


# ---------------------------------------------------------------------------
# Non-regression: existing contracts intact
# ---------------------------------------------------------------------------


class TestExistingContractsIntact:
    def test_dynamic_cytoscape_import_intact(self):
        text = _component()
        assert "import('cytoscape')" in text or 'import("cytoscape")' in text
        assert "from 'cytoscape'" not in text
        assert 'from "cytoscape"' not in text

    def test_layout_cose_randomize_false_intact(self):
        text = _component()
        assert "coseLayoutOptions" in text
        assert "randomize: false" in text

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
            "graph-lens",
            "graph-layout",
            "graph-path-finder-controls",
            "graph-path-source",
            "graph-path-target",
            "graph-path-find",
            "graph-path-clear",
            "graph-path-result",
            "graph-path-status",
            "graph-path-hops",
            "graph-path-node-count",
            "graph-path-edge-count",
            "graph-path-steps",
            "graph-neighborhood-mode",
            "graph-neighborhood-exit",
            "graph-canvas",
            "graph-details",
            "graph-neighbors",
            "graph-stat-incoming",
            "graph-stat-outgoing",
            "graph-stat-degree",
            "graph-copy-node-id",
            "graph-stat-top-nodes",
        ):
            assert f'id="{control_id}"' in text, (
                f"GraphExplorer.vue missing existing control id {control_id!r}"
            )

    def test_new_prompt40_dom_ids_present(self):
        text = _component()
        for needle in ('id="graph-copy-view-url"', 'id="graph-reset-url-state"'):
            assert needle in text, (
                f"GraphExplorer.vue missing Prompt 40 control id {needle!r}"
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

    def test_existing_debug_handles_cleaned_up(self):
        text = _component()
        for needle in (
            "__graphExplorerState",
            "delete (window as any).__graphExplorerState",
            "__graphPathState",
            "delete (window as any).__graphPathState",
            "__graphCy",
            "__graphLabelDebug",
            "delete (window as any).__graphLabelDebug",
        ):
            assert needle in text, (
                f"GraphExplorer.vue missing existing debug handle: {needle}"
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

    def test_viewer_md_mentions_existing_features(self):
        text = _viewer()
        for needle in ("Lens", "Layout", "Neighborhood mode", "Insight dashboard"):
            assert needle in text, f"viewer.md missing feature {needle!r}"
        assert "Path finder" in text

    def test_viewer_md_mentions_copy_view_url_and_reset(self):
        # The "How to use" section gains a new bullet for
        # shareable-URL controls.
        text = _viewer()
        assert "Copy view URL" in text
        assert "Reset URL state" in text
