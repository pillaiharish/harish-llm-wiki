# Knowledge Graph Viewer

This page is a read-only, fully static visualization of the wiki's
knowledge graph. It loads the JSON bundle at
`graph/knowledge_graph.json` via `fetch` and never makes
external network calls. The view is bounded: by default it shows
the top 50 nodes by edge degree plus the immediate neighbors of
the selected node.

The interactive UI is rendered by a Vue component
(`<GraphExplorer />`) registered globally by the VitePress
theme at `site/docs/.vitepress/theme/components/GraphExplorer.vue`.
The component mounts Cytoscape.js and provides pan, zoom, drag,
click-to-select, search, type filters, and a fit/reset/show-all
control bar.

## JSON files

| File | Purpose |
| |---|
| [/graph/nodes.json](/graph/nodes.json) | All graph nodes |
| [/graph/edges.json](/graph/edges.json) | All graph edges |
| [/graph/knowledge_graph.json](/graph/knowledge_graph.json) | Combined bundle with stats |

## Resource relationships

See the [Resource Relationships report](/graph/resource-relationships)
for a Markdown table of the resource-to-resource edges added in
Prompt 24 (similarity, shared topics, shared concepts, etc.).

## Stats

- Schema version: `1.0.0`
- Nodes: 65
- Edges: 1069
- Generated: 2026-06-07T19:18:31.721194+00:00

### Node type counts

| Type | Count |
| |---:|
| concept | 14 |
| learn_chapter | 10 |
| resource | 24 |
| review_page | 7 |
| topic | 10 |

### Edge type counts

| Type | Count |
| |---:|
| concept_in_topic | 95 |
| learn_chapter_uses_resource | 104 |
| resource_has_topic | 43 |
| resource_mentions_concept | 135 |
| resource_same_source_type_as_resource | 123 |
| resource_shares_concept_with_resource | 190 |
| resource_shares_topic_with_resource | 60 |
| resource_similar_to_resource | 191 |
| review_page_reviews_resource | 40 |
| topic_has_resource | 43 |
| topic_related_to_topic | 45 |

<noscript>
<p><strong>JavaScript is disabled.</strong> The interactive viewer
below requires JavaScript. The Markdown tables above and the JSON
links above can still be used to browse the graph data.</p>
</noscript>

## Interactive viewer

<div id="graph-live-stats" data-state="loading" aria-live="polite">
<p id="graph-live-stats-line">Loading graph data…</p>
</div>

<div id="graph-viewer">
<GraphExplorer />

<svg id="graph-svg" width="0" height="0" style="display:none" aria-hidden="true" data-legacy-mini-graph="true"></svg>

<div id="graph-details-pane" style="display:none" data-legacy-pane="true">
<p><em>Select a node to see its details and neighbors.</em></p>
</div>
</div>

<script>
(function () {
  "use strict";
  function initGraphViewer(attempt) {
    attempt = attempt || 0;
    if (typeof document === "undefined") return;
    var root = document.getElementById("graph-viewer");
    if (!root) {
      if (attempt < 50) {
        window.setTimeout(function () { initGraphViewer(attempt + 1); }, 100);
      }
      return;
    }
    var base = (import.meta.env.BASE_URL || "/");
    var url = base.replace(/\/$/, "/") + "graph/knowledge_graph.json";
    // The companion <script> only sets up the live-stats state
    // defaults. The Vue component
    // (<GraphExplorer />) takes over and writes the final
    // "Loaded graph: X nodes, Y edges" text once Cytoscape.js
    // has fetched the JSON. We do NOT touch the line text here
    // so the Vue component's update is not overwritten.
    var liveStats = document.getElementById("graph-live-stats");
    if (liveStats && !liveStats.getAttribute("data-state")) {
      liveStats.setAttribute("data-state", "loading");
    }
    window.__graphViewerUrl = url;
  }
  if (typeof document === "undefined") return;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initGraphViewer);
  } else {
    initGraphViewer();
  }
})();
</script>

## How to use

1. Use the **search** box to filter nodes by label, slug, or id.
2. Use the **node type** and **edge type** checkboxes to filter by category.
3. Use the **Lens** dropdown to focus on one node category (Resources,
   Topics, Concepts, Learn chapters, or Review pages); choose **All**
   to remove the lens.
4. Use the **Layout** dropdown to switch the canvas layout between
   `cose` (default, deterministic), `grid`, `circle`, and `concentric`.
5. Select a node and toggle **Neighborhood mode** to restrict the
   canvas to the selected node and its directly connected neighbours;
   click **Exit neighborhood** or tap the background to return to the
   normal view.
6. The **Insight dashboard** above the canvas surfaces total /
   visible node and edge counts, the currently selected node, and the
   top ten most-connected nodes (click any row to focus that node).
7. Click **Fit graph** to center the view; click **Reset zoom** to
   zoom to 1×.
8. Click **Show all** to render the full graph (otherwise the
   explorer shows the top 50 nodes by degree).
9. Click a node in the canvas, the list, or the neighbor list to
   see its details, neighbors, and incoming/outgoing edges. The
   details panel also shows the incoming / outgoing / total degree
   counts and a **Copy node id** button.
10. Click an edge in the canvas to see its source, target, type, and
    metadata.
11. Drag nodes to rearrange them, use the mouse wheel to zoom, and
    click-drag the empty canvas to pan.
  12. Use the **Path finder** above the canvas to ask "How is node A
    connected to node B?" — pick a source and a target from the
    dropdowns, click **Find path**, and the result panel shows the
    shortest hop chain, the hop / node / edge counts, and highlights
    the path on the canvas. Click **Clear** to reset.
  13. Click **Copy view URL** to copy a shareable link that captures
    the current lens, layout, selected node, neighborhood mode, and
    path-finder state — paste it into a new tab to restore the same
    view. Click **Reset URL state** to clear all graph query params
    from the address bar and return the view to its defaults.

## Provenance

- The viewer is generated at build time by
  `wiki.graph.viewer.viewer_markdown`. The template
  (`site/docs/graph/viewer.md`) is the single source of truth.
- The interactive UI is rendered by the `<GraphExplorer />`
  Vue component at
  `site/docs/.vitepress/theme/components/GraphExplorer.vue`,
  which is registered globally by
  `site/docs/.vitepress/theme/index.ts`.
- The graph data itself is generated by
  `wiki.graph.builder.GraphBuilder` (Prompt 23) and exported by
  `wiki.graph.export.export_graph` (Prompt 23/24). The viewer
  reads those files at runtime; it does not modify them.
