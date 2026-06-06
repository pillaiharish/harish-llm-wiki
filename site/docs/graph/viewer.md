# Knowledge Graph Viewer

This page is a read-only, fully static visualization of the wiki's
knowledge graph. It loads the JSON bundle at
`public/graph/knowledge_graph.json` via `fetch` and never makes
external network calls. The view is bounded: by default it shows
the top 50 nodes by edge degree plus the immediate neighbors of
the selected node.

## JSON files

| File | Purpose |
|---|---|
| [/public/graph/nodes.json](/public/graph/nodes.json) | All graph nodes |
| [/public/graph/edges.json](/public/graph/edges.json) | All graph edges |
| [/public/graph/knowledge_graph.json](/public/graph/knowledge_graph.json) | Combined bundle with stats |

## Resource relationships

See the [Resource Relationships report](/graph/resource-relationships)
for a Markdown table of the resource-to-resource edges added in
Prompt 24 (similarity, shared topics, shared concepts, etc.).

## Stats

- Schema version: `1.0.0`
- Nodes: 33
- Edges: 60
- Generated: 2026-06-05T22:00:22.802237+00:00

### Node type counts

| Type | Count |
|---|---:|
| concept | 3 |
| learn_chapter | 10 |
| resource | 1 |
| review_page | 7 |
| tag | 2 |
| topic | 10 |

### Edge type counts

| Type | Count |
|---|---:|
| concept_in_topic | 3 |
| learn_chapter_uses_resource | 2 |
| resource_has_tag | 2 |
| resource_has_topic | 1 |
| resource_mentions_concept | 3 |
| review_page_reviews_resource | 3 |
| topic_has_resource | 1 |
| topic_related_to_topic | 45 |

<noscript>
<p><strong>JavaScript is disabled.</strong> The interactive viewer
below requires JavaScript. The Markdown tables above and the JSON
links above can still be used to browse the graph data.</p>
</noscript>

## Interactive viewer

<div id="graph-viewer">
  <div id="graph-controls">
    <label for="graph-search">Search nodes:</label>
    <input id="graph-search" type="search" placeholder="label, slug, or id" />
    <button id="graph-show-all" type="button" data-state="top">Show all</button>
    <fieldset id="graph-filter-node-type">
      <legend>Node types</legend>
    </fieldset>
    <fieldset id="graph-filter-edge-type">
      <legend>Edge types</legend>
    </fieldset>
  </div>

  <div id="graph-main">
    <div id="graph-list-pane">
      <h3>Nodes</h3>
      <div id="graph-node-list"><p>Loading...</p></div>
    </div>

    <div id="graph-svg-pane">
      <h3>Mini-graph (top nodes by degree)</h3>
      <svg id="graph-svg" width="400" height="300" role="img" aria-label="Knowledge graph mini-view"></svg>
    </div>
  </div>

  <div id="graph-details-pane">
    <h3>Details</h3>
    <div id="graph-details"><p>Select a node to see its details and neighbors.</p></div>
    <h3>Neighbors</h3>
    <div id="graph-neighbors"><p>No node selected.</p></div>
    <h3>Edges</h3>
    <div id="graph-edges"><p>No node selected.</p></div>
  </div>
</div>

<script>
(function () {
  "use strict";
  // Vanilla-JS knowledge graph viewer (Prompt 25).
  // No external libraries. No external network calls.
  async function initGraphViewer() {
    const root = document.getElementById("graph-viewer");
    if (!root) return;
    const base = (import.meta.env.BASE_URL || "/");
    const url = base.replace(/\/$/, "/") + "public/graph/knowledge_graph.json";
    let data;
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error("HTTP " + response.status);
      data = await response.json();
    } catch (e) {
      const list = document.getElementById("graph-node-list");
      if (list) list.innerHTML = "<p>Could not load graph data. Check /public/graph/knowledge_graph.json.</p>";
      return;
    }
    const nodes = Array.isArray(data.nodes) ? data.nodes : [];
    const edges = Array.isArray(data.edges) ? data.edges : [];
    const state = {
      selectedNodeId: null,
      showAll: false,
      nodeTypeFilter: new Set(),
      edgeTypeFilter: new Set(),
      searchTerm: "",
    };
    const allNodeTypes = Array.from(new Set(nodes.map(function (n) { return n.type; }).filter(Boolean))).sort();
    const allEdgeTypes = Array.from(new Set(edges.map(function (e) { return e.type; }).filter(Boolean))).sort();
    state.nodeTypeFilter = new Set(allNodeTypes);
    state.edgeTypeFilter = new Set(allEdgeTypes);

    function buildTypeFilter(fieldId, types, onChange) {
      const field = document.getElementById(fieldId);
      if (!field) return;
      // Clear existing options (defensive)
      while (field.firstChild && field.firstChild.tagName !== "LEGEND") {
        field.removeChild(field.firstChild.nextSibling);
      }
      types.forEach(function (t) {
        const id = fieldId + "-" + t;
        const label = document.createElement("label");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.id = id;
        cb.value = t;
        cb.checked = true;
        cb.addEventListener("change", function () {
          if (cb.checked) state[onChange].add(t);
          else state[onChange].delete(t);
          render();
        });
        label.appendChild(cb);
        label.appendChild(document.createTextNode(" " + t + " "));
        field.appendChild(label);
      });
    }
    buildTypeFilter("graph-filter-node-type", allNodeTypes, "nodeTypeFilter");
    buildTypeFilter("graph-filter-edge-type", allEdgeTypes, "edgeTypeFilter");

    const searchInput = document.getElementById("graph-search");
    if (searchInput) {
      searchInput.addEventListener("input", function () {
        state.searchTerm = searchInput.value.trim().toLowerCase();
        render();
      });
    }
    const showAllBtn = document.getElementById("graph-show-all");
    if (showAllBtn) {
      showAllBtn.addEventListener("click", function () {
        state.showAll = !state.showAll;
        showAllBtn.textContent = state.showAll ? "Show top" : "Show all";
        showAllBtn.setAttribute("data-state", state.showAll ? "all" : "top");
        render();
      });
    }

    function degree(nodeId) {
      let d = 0;
      for (let i = 0; i < edges.length; i++) {
        const e = edges[i];
        if (!state.edgeTypeFilter.has(e.type)) continue;
        if (e.source === nodeId || e.target === nodeId) d += 1;
      }
      return d;
    }
    function topNodeIds(n) {
      const arr = nodes.map(function (nd) { return { id: nd.id, d: degree(nd.id) }; });
      arr.sort(function (a, b) { return (b.d - a.d) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0); });
      return arr.slice(0, n).map(function (x) { return x.id; });
    }

    const CAP = 50;
    function visibleNodeIds() {
      const base = state.showAll ? nodes.map(function (n) { return n.id; }) : topNodeIds(CAP);
      const q = state.searchTerm;
      const filteredByType = base.filter(function (id) {
        const n = nodes.find(function (nd) { return nd.id === id; });
        if (!n) return false;
        if (!state.nodeTypeFilter.has(n.type)) return false;
        if (!q) return true;
        const hay = ((n.label || "") + " " + (n.slug || "") + " " + (n.id || "")).toLowerCase();
        return hay.indexOf(q) !== -1;
      });
      return filteredByType;
    }
    function neighborsOf(nodeId) {
      const out = [];
      for (let i = 0; i < edges.length; i++) {
        const e = edges[i];
        if (!state.edgeTypeFilter.has(e.type)) continue;
        if (e.source === nodeId) out.push({ edge: e, neighbor: e.target, direction: "out" });
        else if (e.target === nodeId) out.push({ edge: e, neighbor: e.source, direction: "in" });
      }
      return out;
    }
    function nodeById(id) {
      for (let i = 0; i < nodes.length; i++) if (nodes[i].id === id) return nodes[i];
      return null;
    }
    function nodeRoute(n) {
      if (!n) return null;
      if (n.type === "resource") {
        const safe = String(n.slug || "").replace(/[^a-zA-Z0-9_-]/g, "_");
        return "/resources/" + safe;
      }
      if (n.type === "topic") return "/topics/" + n.slug;
      if (n.type === "concept") return "/concepts/" + n.slug;
      if (n.type === "tag") return "/tags/#" + n.slug;
      if (n.type === "learn_chapter") return "/learn/" + n.slug;
      if (n.type === "review_page") return "/review/";
      return null;
    }
    function renderNodeList(visibleIds) {
      const list = document.getElementById("graph-node-list");
      if (!list) return;
      if (!visibleIds.length) { list.innerHTML = "<p>No matching nodes.</p>"; return; }
      const rows = visibleIds.slice(0, 200).map(function (id) {
        const n = nodeById(id);
        if (!n) return "";
        const sel = state.selectedNodeId === id ? " data-selected=\"true\"" : "";
        return "<div class=\"gn-row\"" + sel + " data-node-id=\"" + id.replace(/"/g, "&quot;") + "\">" +
               "<button type=\"button\" class=\"gn-pick\" data-node-id=\"" + id.replace(/"/g, "&quot;") + "\">" +
               "<span class=\"gn-type\">" + n.type + "</span> " +
               "<span class=\"gn-label\">" + (n.label || n.id) + "</span>" +
               "</button></div>";
      });
      list.innerHTML = rows.join("");
      Array.from(list.querySelectorAll(".gn-pick")).forEach(function (btn) {
        btn.addEventListener("click", function () {
          state.selectedNodeId = btn.getAttribute("data-node-id");
          render();
        });
      });
    }
    function renderSvg(visibleIds) {
      const svg = document.getElementById("graph-svg");
      if (!svg) return;
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      const visible = new Set(visibleIds);
      const W = svg.getAttribute("width") ? parseInt(svg.getAttribute("width"), 10) : 400;
      const H = svg.getAttribute("height") ? parseInt(svg.getAttribute("height"), 10) : 300;
      const cx = W / 2, cy = H / 2;
      const layout = {};
      const arr = Array.from(visible);
      arr.forEach(function (id, i) {
        const angle = (2 * Math.PI * i) / Math.max(1, arr.length);
        const r = Math.min(W, H) * 0.4;
        layout[id] = { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
      });
      // Edges
      for (let i = 0; i < edges.length; i++) {
        const e = edges[i];
        if (!state.edgeTypeFilter.has(e.type)) continue;
        if (!visible.has(e.source) || !visible.has(e.target)) continue;
        const a = layout[e.source], b = layout[e.target];
        if (!a || !b) continue;
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
        line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
        line.setAttribute("stroke", "#888");
        line.setAttribute("stroke-width", "0.5");
        svg.appendChild(line);
      }
      // Nodes
      for (let i = 0; i < arr.length; i++) {
        const id = arr[i];
        const n = nodeById(id);
        if (!n) continue;
        const p = layout[id];
        const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        c.setAttribute("cx", p.x); c.setAttribute("cy", p.y);
        const r = n.type === "resource" ? 6 : (n.type === "topic" ? 5 : 4);
        c.setAttribute("r", r);
        c.setAttribute("fill", state.selectedNodeId === id ? "#e22" : "#345");
        c.setAttribute("data-node-id", id);
        c.addEventListener("click", function () { state.selectedNodeId = id; render(); });
        svg.appendChild(c);
      }
    }
    function renderDetails() {
      const details = document.getElementById("graph-details");
      const neighbors = document.getElementById("graph-neighbors");
      const edgesBox = document.getElementById("graph-edges");
      if (!details) return;
      if (!state.selectedNodeId) {
        details.innerHTML = "<p>Select a node to see its details and neighbors.</p>";
        if (neighbors) neighbors.innerHTML = "<p>No node selected.</p>";
        if (edgesBox) edgesBox.innerHTML = "<p>No node selected.</p>";
        return;
      }
      const n = nodeById(state.selectedNodeId);
      if (!n) {
        details.innerHTML = "<p>Node not found.</p>";
        return;
      }
      const meta = n.metadata || {};
      const metaKeys = Object.keys(meta);
      const metaRows = metaKeys.length
        ? "<table><tr><th>Field</th><th>Value</th></tr>" +
          metaKeys.map(function (k) { return "<tr><td>" + k + "</td><td>" + String(meta[k]) + "</td></tr>"; }).join("") +
          "</table>"
        : "<p><em>No metadata.</em></p>";
      const route = nodeRoute(n);
      const routeLink = route ? "<p>Open in wiki: <a href=\"" + route + "\">" + route + "</a></p>" : "";
      details.innerHTML =
        "<h4>" + (n.label || n.id) + "</h4>" +
        "<p><strong>ID:</strong> <code>" + n.id + "</code><br/>" +
        "<strong>Type:</strong> " + n.type + "<br/>" +
        "<strong>Slug:</strong> " + (n.slug || "") + "</p>" +
        routeLink +
        "<h5>Metadata</h5>" + metaRows;
      if (neighbors) {
        const list = neighborsOf(state.selectedNodeId);
        if (!list.length) {
          neighbors.innerHTML = "<p>No neighbors.</p>";
        } else {
          neighbors.innerHTML = "<ul>" + list.slice(0, 200).map(function (item) {
            const nn = nodeById(item.neighbor);
            const nnLabel = nn ? (nn.label || nn.id) : item.neighbor;
            return "<li>" + item.direction + ": <button type=\"button\" class=\"gn-pick\" data-node-id=\"" +
                   String(item.neighbor).replace(/"/g, "&quot;") + "\">" + nnLabel + "</button>" +
                   " <small>(" + item.edge.type + ")</small></li>";
          }).join("") + "</ul>";
          Array.from(neighbors.querySelectorAll(".gn-pick")).forEach(function (btn) {
            btn.addEventListener("click", function () {
              state.selectedNodeId = btn.getAttribute("data-node-id");
              render();
            });
          });
        }
      }
      if (edgesBox) {
        const list = neighborsOf(state.selectedNodeId);
        if (!list.length) {
          edgesBox.innerHTML = "<p>No edges.</p>";
        } else {
          edgesBox.innerHTML = "<ul>" + list.slice(0, 200).map(function (item) {
            const meta = item.edge.metadata || {};
            const metaKeys = Object.keys(meta);
            const metaLine = metaKeys.length
              ? "<small>" + metaKeys.map(function (k) { return k + "=" + String(meta[k]); }).join(", ") + "</small>"
              : "";
            return "<li><code>" + item.edge.id + "</code> " + metaLine + "</li>";
          }).join("") + "</ul>";
        }
      }
    }
    function render() {
      const visibleIds = visibleNodeIds();
      renderNodeList(visibleIds);
      renderSvg(visibleIds);
      renderDetails();
    }
    render();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initGraphViewer);
  } else {
    initGraphViewer();
  }
})();
</script>

## How to use

1. Use the search box to filter nodes by label, slug, or id.
2. Use the checkboxes to filter by node type and edge type.
3. Click a node in the list, in the SVG, or in the neighbor list
   to see its details, incoming/outgoing edges, and immediate
   neighbors.
4. The default view is the top 50 nodes by edge degree; press
   **Show all** to expand to the full set.

## Provenance

- The viewer is generated at build time by
  `wiki.graph.viewer.viewer_markdown`. The template
  (`site/docs/graph/viewer.md`) is the single source of truth.
- The graph data itself is generated by
  `wiki.graph.builder.GraphBuilder` (Prompt 23) and exported by
  `wiki.graph.export.export_graph` (Prompt 23/24). The viewer
  reads those files at runtime; it does not modify them.
