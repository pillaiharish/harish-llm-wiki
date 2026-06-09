---
pageClass: graph-viewer-page
---

# Knowledge Graph Viewer

This page keeps the original graph viewer route available as a
technical/reference surface. It loads the static graph bundle from
`/graph/knowledge_graph.json`, preserves old share URLs, and exposes
the same runtime used by the new graph workspace.

<div id="graph-workspace-handoff" class="graph-workspace-handoff" hidden>
  <div>
    <strong>Open this state in the graph workspace</strong>
    <span>The workspace route uses the same URL state, but presents the graph in a wider app-style layout.</span>
  </div>
  <a id="graph-workspace-handoff-link" class="graph-workspace-handoff-link" href="/graph/explore">Open workspace</a>
</div>

## What This Page Is For

- **Compatibility:** old `/graph/viewer?...` links continue to restore their state here.
- **Provenance:** the page keeps the generated stats, JSON links, and runtime notes close to the graph.
- **Reference:** use this page when you want the original docs-oriented graph presentation.

## Quick Links

| Link | Purpose |
|---|---|
| [Open the graph workspace](/graph/explore) | Primary app-style graph route for demos and exploration |
| [Open the graph landing page](/graph/) | Summary page for graph stats, data files, and navigation |
| [Resource relationships report](/graph/resource-relationships) | Deterministic resource-to-resource relationship summary |

## JSON files

| File | Purpose |
|---|---|
| [/graph/nodes.json](/graph/nodes.json) | All graph nodes |
| [/graph/edges.json](/graph/edges.json) | All graph edges |
| [/graph/knowledge_graph.json](/graph/knowledge_graph.json) | Combined bundle with stats |

## Stats

- Schema version: `1.0.0`
- Nodes: 65
- Edges: 1069
- Generated: 2026-06-09T11:14:32.892319+00:00

### Node type counts

| Type | Count |
|---|---:|
| concept | 14 |
| learn_chapter | 10 |
| resource | 24 |
| review_page | 7 |
| topic | 10 |

### Edge type counts

| Type | Count |
|---|---:|
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

## Interactive Viewer

<div id="graph-live-stats" data-state="loading" aria-live="polite">
<p id="graph-live-stats-line">Loading graph data…</p>
</div>

<div id="graph-viewer">
<GraphExplorer mode="reference" share-base-path="/graph/explore" />

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
    var liveStats = document.getElementById("graph-live-stats");
    if (liveStats && !liveStats.getAttribute("data-state")) {
      liveStats.setAttribute("data-state", "loading");
    }
    window.__graphViewerUrl = url;

    var handoff = document.getElementById("graph-workspace-handoff");
    var link = document.getElementById("graph-workspace-handoff-link");
    var search = (typeof window !== "undefined" && window.location) ? (window.location.search || "") : "";
    if (handoff && link && search) {
      link.setAttribute("href", "/graph/explore" + search);
      handoff.removeAttribute("hidden");
    }
  }
  if (typeof document === "undefined") return;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initGraphViewer);
  } else {
    initGraphViewer();
  }
})();
</script>

## Working With URL State

This route accepts and restores the same graph query params used by
the main workspace:

- `layout`
- `node`
- `source`
- `target`
- `path`
- `lens`
- `neighborhood`

If the page was opened with a query string, the compatibility banner
above preserves the full query string when handing off to
`/graph/explore`.

## How to Use

1. Use **Lens** to focus the graph on resources, topics, concepts,
   learn chapters, or review pages.
2. Use **Layout** to switch between `cose`, `grid`, `circle`, and
   `concentric`.
3. Select a node, then use **Neighborhood mode** to isolate its
   closed neighborhood.
4. Use the **Insight dashboard** to track visible counts and jump to
   highly connected nodes.
5. Use the **Path finder** controls and click **Find path** to trace
   how two nodes connect, then **Clear** to reset the active path.
6. Use **Copy view URL** to create a shareable state and **Reset URL state**
   to clear the active graph query params.

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
  `wiki.graph.builder.GraphBuilder` and exported by
  `wiki.graph.export.export_graph`. The viewer reads those files at
  runtime; it does not modify them.
