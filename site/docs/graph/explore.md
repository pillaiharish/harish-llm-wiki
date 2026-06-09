---
pageClass: graph-explore-page
aside: false
sidebar: false
---

# Graph Workspace

The graph workspace is the primary public route for exploring the
wiki’s knowledge graph. It keeps the same deterministic graph data and
URL state as the compatibility viewer, but prioritizes a wider,
app-style layout for demos, inspection, and path-based exploration.

<div class="graph-workspace-header">
  <div class="graph-workspace-summary">
    <p class="graph-workspace-kicker">Interactive graph workspace</p>
    <p>Search, filter, trace paths, and inspect nodes without leaving the page.</p>
  </div>
  <div class="graph-workspace-actions">
    <a class="graph-inline-link" href="/graph/">Graph landing</a>
    <a class="graph-inline-link" href="/graph/viewer">Technical reference</a>
    <a class="graph-inline-link" href="/graph/resource-relationships">Relationship report</a>
  </div>
</div>

<div id="graph-live-stats" data-state="loading" aria-live="polite">
<p id="graph-live-stats-line">Loading graph data…</p>
</div>

<div id="graph-viewer">
<GraphExplorer mode="workspace" share-base-path="/graph/explore" />

<svg id="graph-svg" width="0" height="0" style="display:none" aria-hidden="true" data-legacy-mini-graph="true"></svg>

<div id="graph-details-pane" style="display:none" data-legacy-pane="true">
<p><em>Select a node to see its details and neighbors.</em></p>
</div>
</div>

<script>
(function () {
  "use strict";
  function initGraphWorkspace(attempt) {
    attempt = attempt || 0;
    if (typeof document === "undefined") return;
    var root = document.getElementById("graph-viewer");
    if (!root) {
      if (attempt < 50) {
        window.setTimeout(function () { initGraphWorkspace(attempt + 1); }, 100);
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
  }
  if (typeof document === "undefined") return;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initGraphWorkspace);
  } else {
    initGraphWorkspace();
  }
})();
</script>
