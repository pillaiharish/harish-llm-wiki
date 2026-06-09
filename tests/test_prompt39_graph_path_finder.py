"""Tests for Prompt 39: Graph Path Finder and Relationship Explorer v1.

Static-source string checks against ``GraphExplorer.vue`` and
``site/docs/graph/viewer.md``, plus a pure-Python BFS reference
that locks in the algorithm's semantics independently of the
SFC. Mirrors the style of
``tests/test_prompt38_graph_insight_dashboard.py`` and
``tests/test_prompt25_graph_visualization.py``.

The Prompt 39 acceptance criteria are:

  - Path-finder state: ``pathSourceId``, ``pathTargetId``,
    ``pathStatus`` (idle / missing_input / same_node / found /
    not_found), ``pathNodeIds``, ``pathEdgeIds``, ``pathSteps``.
  - BFS algorithm over ``graph.value.edges``, undirected,
    deterministic (sorted adjacency), tracked by edge id.
  - UI: section title "Path finder", source selector, target
    selector, Find path button, Clear path button, path result
    panel, readable path chain, path stats (hops / nodes /
    edges).
  - Graph highlighting: ``.path-highlight`` class on path nodes
    and edges; non-path elements faded via the existing
    ``.faded`` class; highlight is removed on Clear.
  - Debug handle: ``window.__graphPathState`` with the spec
    fields, cleaned up in ``onBeforeUnmount``.
  - Existing Prompt 35.x / 37 / 38 contracts remain intact.
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
# Types and state
# ---------------------------------------------------------------------------


class TestPathFinderTypeAndState:
    def test_path_status_type_defined(self):
        text = _component()
        assert "PathStatus" in text
        # The five internal states are present in the union type.
        for state in (
            "'idle'",
            "'missing_input'",
            "'same_node'",
            "'found'",
            "'not_found'",
        ):
            assert state in text, f"PathStatus union missing state {state!r}"

    def test_path_step_type_defined(self):
        text = _component()
        assert "PathStep" in text
        for field in ("fromId", "fromLabel", "edgeId", "edgeType", "toId", "toLabel"):
            assert field in text, f"PathStep missing field {field!r}"

    def test_path_result_type_defined(self):
        text = _component()
        assert "PathResult" in text
        for field in (
            "sourceId",
            "targetId",
            "status",
            "pathNodeIds",
            "pathEdgeIds",
            "hopCount",
            "steps",
        ):
            assert field in text, f"PathResult missing field {field!r}"

    def test_path_state_refs_declared(self):
        text = _component()
        for ref in (
            "pathSourceId",
            "pathTargetId",
            "pathStatus",
            "pathNodeIds",
            "pathEdgeIds",
            "pathSteps",
        ):
            assert ref in text, f"GraphExplorer.vue missing path-finder ref {ref!r}"

    def test_path_node_options_computed_exists(self):
        text = _component()
        assert "pathNodeOptions" in text, (
            "GraphExplorer.vue must define a pathNodeOptions computed "
            "that returns sorted {id, label, type} tuples"
        )


# ---------------------------------------------------------------------------
# BFS algorithm
# ---------------------------------------------------------------------------


class TestPathFinderBFS:
    def test_find_shortest_path_is_defined(self):
        text = _component()
        assert "function findShortestPath" in text, (
            "GraphExplorer.vue must define a pure findShortestPath(sourceId, targetId) "
            "helper that returns a PathResult"
        )

    def test_find_shortest_path_uses_adjacency_map(self):
        text = _component()
        # The BFS must build an adjacency Map with both endpoints
        # pushed (undirected).
        assert "new Map<string, Array<" in text or "new Map<string" in text
        # The adj map is built by iterating edges and pushing both
        # directions.
        idx = text.find("function findShortestPath")
        assert idx > 0
        body = text[idx : idx + 5000]
        assert "adj.get(e.source)" in body, (
            "BFS must push e.target into adj[e.source]"
        )
        assert "adj.get(e.target)" in body, (
            "BFS must push e.source into adj[e.target] (undirected)"
        )

    def test_find_shortest_path_sorts_adjacency(self):
        text = _component()
        idx = text.find("function findShortestPath")
        assert idx > 0
        body = text[idx : idx + 5000]
        # The sort key must be (neighborId, edgeId) ascending.
        assert ".sort(" in body
        assert "a.neighborId" in body and "b.neighborId" in body
        assert "a.edgeId" in body and "b.edgeId" in body

    def test_find_shortest_path_uses_bfs_queue_and_parent_map(self):
        text = _component()
        idx = text.find("function findShortestPath")
        assert idx > 0
        body = text[idx : idx + 5000]
        assert "parent" in body and "new Map<string" in body
        assert "visited" in body and "new Set<string>" in body
        # FIFO queue with shift().
        assert ".shift(" in body or "queue.shift" in body
        # parent.set(neighborId, { prevId, edgeId })
        assert "parent.set(neighborId" in body or "parent.set(" in body

    def test_find_shortest_path_reconstructs_node_and_edge_ids(self):
        text = _component()
        idx = text.find("function findShortestPath")
        assert idx > 0
        body = text[idx : idx + 6000]
        # Walks back from target to source accumulating edge ids.
        assert "pathEdgeIds" in body
        assert "pathNodeIds" in body
        assert "pathNodeIdsLocal.reverse" in body or ".reverse()" in body
        # Final return assembles the PathResult with the reconstructed
        # node/edge lists and a hopCount derived from pathNodeIds.length.
        assert "hopCount: pathNodeIdsLocal.length - 1" in body or (
            "hopCount: pathNodeIdsLocal.length - 1" in text
        )

    def test_find_shortest_path_is_pure(self):
        # The function must not touch cy, window, document, navigator,
        # or ResizeObserver — that keeps it trivially unit-testable
        # and SSR-safe.
        text = _component()
        idx = text.find("function findShortestPath")
        assert idx > 0
        # Body length is bounded; using the next function definition
        # as a sentinel.
        next_def = text.find("\nfunction ", idx + 1)
        body = text[idx:next_def if next_def > 0 else idx + 6000]
        for forbidden in ("cy.", "window.", "document.", "navigator.", "ResizeObserver"):
            assert forbidden not in body, (
                f"findShortestPath must be pure — found {forbidden!r} in its body"
            )

    def test_find_shortest_path_handles_same_node(self):
        text = _component()
        idx = text.find("function findShortestPath")
        body = text[idx : idx + 6000]
        # source === target branch returns same_node with 0 hops.
        assert "sourceId === targetId" in body
        assert "'same_node'" in body

    def test_find_shortest_path_uses_edge_type_filter(self):
        text = _component()
        idx = text.find("function findShortestPath")
        body = text[idx : idx + 6000]
        # BFS must respect the visible-edge filter.
        assert "edgeTypeFilter" in body
        assert "!edgeTypeFilter.value.has(e.type)" in body or "edgeTypeFilter.value.has(e.type)" in body


# ---------------------------------------------------------------------------
# UI bindings
# ---------------------------------------------------------------------------


class TestPathFinderUIBindings:
    def test_path_finder_ids_present(self):
        text = _component()
        for needle in (
            'id="graph-path-finder-controls"',
            'id="graph-path-source"',
            'id="graph-path-target"',
            'id="graph-path-find"',
            'id="graph-path-clear"',
            'id="graph-path-result"',
            'id="graph-path-status"',
            'id="graph-path-hops"',
            'id="graph-path-node-count"',
            'id="graph-path-edge-count"',
            'id="graph-path-steps"',
        ):
            assert needle in text, f"GraphExplorer.vue missing path-finder id {needle!r}"

    def test_path_finder_section_uses_correct_legend(self):
        text = _component()
        # The controls fieldset declares its purpose via a <legend>.
        idx = text.find('id="graph-path-finder-controls"')
        assert idx > 0
        # Look forward — the <legend> lives inside the fieldset,
        # after the opening tag.
        block = text[idx : idx + 200]
        assert "<legend>Path finder</legend>" in block

    def test_path_finder_selects_iterate_pathNodeOptions(self):
        text = _component()
        assert "v-for=\"n in pathNodeOptions\"" in text, (
            "Both source and target <select> must iterate over pathNodeOptions"
        )

    def test_path_finder_steps_iterate_pathSteps(self):
        text = _component()
        assert "v-for=\"(s, i) in pathSteps\"" in text, (
            "The steps <ol> must iterate over pathSteps"
        )

    def test_path_finder_result_status_attribute(self):
        text = _component()
        # The result panel exposes its internal status via data-status
        # for e2e selectors.
        assert ':data-status="pathStatus"' in text

    def test_find_button_disabled_until_both_set(self):
        text = _component()
        idx = text.find('id="graph-path-find"')
        assert idx > 0
        # Look forward 200 chars for the disabled binding.
        block = text[idx : idx + 400]
        assert ":disabled=" in block
        assert "pathSourceId" in block
        assert "pathTargetId" in block

    def test_clear_button_has_handler(self):
        text = _component()
        assert "@click=\"clearPathFinder\"" in text


# ---------------------------------------------------------------------------
# Highlighting
# ---------------------------------------------------------------------------


class TestPathFinderHighlighting:
    def test_apply_path_highlight_defined(self):
        text = _component()
        assert "function applyPathHighlight" in text, (
            "GraphExplorer.vue must define applyPathHighlight()"
        )

    def test_path_highlight_rule_in_makeStyle(self):
        text = _component()
        # The rule must use the .path-highlight selector and the
        # canonical blue (#1976d2) colour.
        assert "'.path-highlight'" in text or "'.path-highlight'," in text
        # Border / line / arrow colour is the path-finder blue.
        idx = text.find("'.path-highlight'")
        block = text[idx : idx + 800]
        assert "#1976d2" in block
        # z-index 12 wins over selection (10) and hover (11).
        assert "z-index" in block
        # Pull the z-index number from the block.
        m = re.search(r"'z-index'\s*:\s*(\d+)", block)
        assert m, ".path-highlight rule must set z-index"
        assert int(m.group(1)) >= 12, (
            f".path-highlight z-index must be >= 12, got {m.group(1)}"
        )

    def test_path_highlight_rule_after_highlighted(self):
        # The .path-highlight rule must come after the existing
        # .highlighted / edge:selected rules so it wins when both
        # are present on the same element.
        text = _component()
        idx_highlighted = text.find("'.highlighted'")
        idx_selected_edge = text.find("'edge:selected'")
        idx_path = text.find("'.path-highlight'")
        assert idx_path > 0
        if idx_highlighted > 0:
            assert idx_path > idx_highlighted, (
                ".path-highlight rule must come after .highlighted"
            )
        if idx_selected_edge > 0:
            assert idx_path > idx_selected_edge, (
                ".path-highlight rule must come after edge:selected"
            )

    def test_apply_path_highlight_strips_and_readds(self):
        text = _component()
        idx = text.find("function applyPathHighlight")
        assert idx > 0
        body = text[idx : idx + 1500]
        # Strips .path-highlight first (idempotent).
        assert "removeClass('path-highlight')" in body
        # Re-adds .path-highlight to the path elements.
        assert "addClass('path-highlight')" in body
        # Uses the existing .faded class for the non-path elements.
        assert "'faded'" in body
        # And un-fades the path elements.
        assert "removeClass('faded')" in body

    def test_re_render_cy_calls_apply_path_highlight(self):
        text = _component()
        # The path highlight must survive any canvas re-render
        # (lens / layout / search / show all) so the user's path
        # is not lost when they interact.
        idx = text.find("function reRenderCy")
        assert idx > 0
        body = text[idx : idx + 1500]
        assert "applyPathHighlight()" in body, (
            "reRenderCy() must call applyPathHighlight() at the end"
        )

    def test_run_path_finder_invokes_highlight(self):
        text = _component()
        idx = text.find("function runPathFinder")
        body = text[idx : idx + 800]
        assert "applyPathHighlight()" in body

    def test_clear_path_finder_invokes_highlight(self):
        text = _component()
        idx = text.find("function clearPathFinder")
        body = text[idx : idx + 800]
        assert "applyPathHighlight()" in body


# ---------------------------------------------------------------------------
# Debug handle
# ---------------------------------------------------------------------------


class TestPathFinderDebug:
    def test_window_path_state_set_in_update(self):
        text = _component()
        assert "function updatePathStateDebug" in text
        idx = text.find("function updatePathStateDebug")
        body = text[idx : idx + 1500]
        assert "window" in body
        assert "__graphPathState" in body

    def test_window_path_state_has_spec_fields(self):
        text = _component()
        idx = text.find("function updatePathStateDebug")
        body = text[idx : idx + 1500]
        for needle in (
            "sourceId:",
            "targetId:",
            "status:",
            "pathNodeIds:",
            "pathEdgeIds:",
            "hopCount:",
        ):
            assert needle in body, f"__graphPathState missing field {needle!r}"

    def test_window_path_state_cleaned_on_unmount(self):
        text = _component()
        assert "delete (window as any).__graphPathState" in text, (
            "GraphExplorer.vue must delete window.__graphPathState "
            "in onBeforeUnmount"
        )

    def test_path_finder_state_in_explorer_state(self):
        # The Prompt 38 __graphExplorerState payload gains a
        # pathFinder sub-object for backward compatibility /
        # convenience.
        text = _component()
        idx = text.find("function updateExplorerStateDebug")
        body = text[idx : idx + 2000]
        assert "pathFinder" in body, (
            "__graphExplorerState must include a pathFinder sub-object"
        )
        for needle in ("status:", "hopCount:", "sourceId:", "targetId:"):
            assert needle in body


# ---------------------------------------------------------------------------
# Edge-type recompute
# ---------------------------------------------------------------------------


class TestPathFinderEdgeTypeRecompute:
    def test_edge_type_checkbox_reruns_bfs(self):
        text = _component()
        idx = text.find("function onEdgeTypeCheckbox")
        body = text[idx : idx + 1500]
        # When a path is currently active (found or same_node), the
        # handler must re-run the BFS so the result, the highlight,
        # and the debug handle stay in sync.
        assert "findShortestPath" in body
        assert "applyPathHighlight" in body
        assert "updatePathStateDebug" in body


# ---------------------------------------------------------------------------
# Pure-Python BFS reference (independent of the SFC)
# ---------------------------------------------------------------------------


def _bfs(nodes, edges, source, target, edge_types=None):
    """Reference BFS that mirrors the Vue component's algorithm.

    Returns (status, path_node_ids, path_edge_ids, hop_count).
    """
    if source == "" or target == "":
        return ("missing_input", [], [], 0)
    if source not in nodes or target not in nodes:
        return ("not_found", [], [], 0)
    if source == target:
        return ("same_node", [source], [], 0)
    allowed = set(edge_types) if edge_types is not None else {e["type"] for e in edges}
    adj: dict[str, list[tuple[str, str]]] = {n: [] for n in nodes}
    for e in edges:
        if e["type"] not in allowed:
            continue
        adj.setdefault(e["source"], []).append((e["target"], e["id"]))
        adj.setdefault(e["target"], []).append((e["source"], e["id"]))
    for k in adj:
        adj[k].sort()
    visited = {source}
    parent: dict[str, tuple[str, str]] = {}
    queue = [source]
    while queue:
        cur = queue.pop(0)
        if cur == target:
            break
        for nb, eid in adj.get(cur, []):
            if nb in visited:
                continue
            visited.add(nb)
            parent[nb] = (cur, eid)
            queue.append(nb)
    if target not in visited:
        return ("not_found", [], [], 0)
    path_node_ids: list[str] = []
    path_edge_ids: list[str] = []
    cur = target
    while cur != source:
        path_node_ids.append(cur)
        prev, eid = parent[cur]
        path_edge_ids.append(eid)
        cur = prev
    path_node_ids.append(source)
    path_node_ids.reverse()
    path_edge_ids.reverse()
    return ("found", path_node_ids, path_edge_ids, len(path_node_ids) - 1)


class TestPathFinderPythonReference:
    """Independent Python reference — locks the BFS contract."""

    def test_shortcut_wins_over_longer_path(self):
        nodes = ["A", "B", "C", "D"]
        edges = [
            {"id": "e1", "type": "x", "source": "A", "target": "B"},
            {"id": "e2", "type": "x", "source": "B", "target": "C"},
            {"id": "e3", "type": "x", "source": "C", "target": "D"},
            {"id": "e4", "type": "x", "source": "A", "target": "D"},
        ]
        status, nids, eids, hops = _bfs(nodes, edges, "A", "D")
        assert status == "found"
        assert hops == 1
        assert nids == ["A", "D"]
        assert eids == ["e4"]

    def test_same_node_status(self):
        nodes = ["A", "B"]
        edges = []
        status, nids, eids, hops = _bfs(nodes, edges, "A", "A")
        assert status == "same_node"
        assert nids == ["A"]
        assert eids == []
        assert hops == 0

    def test_missing_input_status(self):
        nodes = ["A", "B"]
        edges = []
        assert _bfs(nodes, edges, "", "B")[0] == "missing_input"
        assert _bfs(nodes, edges, "A", "")[0] == "missing_input"

    def test_unknown_node_is_not_found(self):
        nodes = ["A", "B"]
        edges = [{"id": "e1", "type": "x", "source": "A", "target": "B"}]
        assert _bfs(nodes, edges, "A", "Z")[0] == "not_found"

    def test_disconnected_components(self):
        nodes = ["A", "B", "C", "D"]
        edges = [
            {"id": "e1", "type": "x", "source": "A", "target": "B"},
            {"id": "e2", "type": "x", "source": "C", "target": "D"},
        ]
        status, nids, eids, hops = _bfs(nodes, edges, "A", "C")
        assert status == "not_found"
        assert nids == []
        assert eids == []

    def test_edge_type_filter_excludes_required_edge(self):
        nodes = ["A", "B", "C"]
        edges = [
            {"id": "e1", "type": "t1", "source": "A", "target": "B"},
            {"id": "e2", "type": "t2", "source": "B", "target": "C"},
        ]
        # Allow only t1 — A→C needs the t2 edge, so no path.
        status, _, _, _ = _bfs(nodes, edges, "A", "C", edge_types={"t1"})
        assert status == "not_found"
        # Allowing both: A→B→C is found.
        status, nids, eids, hops = _bfs(nodes, edges, "A", "C", edge_types={"t1", "t2"})
        assert status == "found"
        assert hops == 2
        assert nids == ["A", "B", "C"]
        assert eids == ["e1", "e2"]

    def test_bfs_is_deterministic(self):
        # Two runs of the same BFS on the same input must yield
        # byte-identical results — this is the determinism
        # contract the SFC's sorted adjacency guarantees.
        nodes = ["A", "B", "C", "D", "E"]
        edges = [
            {"id": "e1", "type": "x", "source": "A", "target": "C"},
            {"id": "e2", "type": "x", "source": "A", "target": "B"},
            {"id": "e3", "type": "x", "source": "B", "target": "D"},
            {"id": "e4", "type": "x", "source": "C", "target": "E"},
            {"id": "e5", "type": "x", "source": "D", "target": "E"},
        ]
        run1 = _bfs(nodes, edges, "A", "E")
        run2 = _bfs(nodes, edges, "A", "E")
        assert run1 == run2


# ---------------------------------------------------------------------------
# Non-regression: existing contracts intact
# ---------------------------------------------------------------------------


class TestExistingContractsIntact:
    def test_dynamic_cytoscape_import_intact(self):
        text = _component()
        assert "import('cytoscape')" in text or 'import("cytoscape")' in text
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
            "HUB_DEGREE_THRESHOLD_LOW_ZOOM",
            "__graphLabelDebug",
            "delete (window as any).__graphLabelDebug",
        ):
            assert needle in text, f"missing existing semantic-zoom symbol: {needle}"

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
            "__graphCy",
        ):
            assert needle in text

    def test_viewer_md_keeps_existing_contracts(self):
        text = _viewer()
        assert "<GraphExplorer " in text
        assert '<svg id="graph-svg"' in text
        assert "<noscript>" in text
        assert "</noscript>" in text
        assert "initGraphViewer" in text
        assert "import.meta.env.BASE_URL" in text
        assert "/graph/resource-relationships" in text

    def test_viewer_md_mentions_existing_features(self):
        text = _viewer()
        assert "Lens" in text
        assert "Layout" in text
        assert "Neighborhood mode" in text
        assert "Insight dashboard" in text

    def test_viewer_md_mentions_path_finder(self):
        # The "How to use" section gains a new bullet describing
        # the path finder.
        text = _viewer()
        assert "Path finder" in text
        assert "Find path" in text
        assert "Clear" in text
