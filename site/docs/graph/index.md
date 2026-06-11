---
pageClass: graph-landing-page
---

# Knowledge Graph

The graph turns the wiki into a connected map of **resources**,
**topics**, **concepts**, and **review pages**. It is deterministic,
fully static, and designed to make relationships inspectable without
a backend service.

<div class="graph-cta-grid">
  <a class="graph-cta-card graph-cta-card-primary" href="/graph/explore">
    <strong>Open Interactive Graph</strong>
    <span>Launch the full graph workspace with filters, path-finding, and node inspection.</span>
  </a>
  <a class="graph-cta-card" href="/graph/graphify">
    <strong>Open Graphify Explorer</strong>
    <span>Explore the same graph data in a dark, search-first vis-network view.</span>
  </a>
  <a class="graph-cta-card" href="/graph/viewer">
    <strong>View Technical Reference</strong>
    <span>Open the compatibility viewer with provenance notes, JSON links, and runtime details.</span>
  </a>
  <a class="graph-cta-card" href="/graph/resource-relationships">
    <strong>View Resource Relationships</strong>
    <span>Review deterministic resource-to-resource relationships and jump into the graph workspace.</span>
  </a>
  <a class="graph-cta-card" href="/graph/knowledge_graph.json">
    <strong>View Graph JSON/Data</strong>
    <span>Browse the generated graph bundle and supporting node/edge exports.</span>
  </a>
</div>

## At a Glance

<div class="graph-stat-grid">
  <div class="graph-stat-card"><span class="graph-stat-kicker">Nodes</span><strong>69</strong><span>Entities currently in the graph.</span></div>
  <div class="graph-stat-card"><span class="graph-stat-kicker">Edges</span><strong>1150</strong><span>Connections generated from the existing wiki data.</span></div>
  <div class="graph-stat-card"><span class="graph-stat-kicker">Node types</span><strong>5</strong><span>Distinct entity categories ready to explore.</span></div>
  <div class="graph-stat-card"><span class="graph-stat-kicker">Edge types</span><strong>11</strong><span>Different relationship kinds available in the current build.</span></div>
</div>

## What You Can Explore

- **Resources** connect source material to the topics and concepts they cover.
- **Topics** act as stable learning buckets and collect related resources.
- **Concepts** tie recurring ideas together across multiple resources and topics.
- **Review pages** surface weak notes, missing citations, stale notes, and other quality signals.

## How Entities Connect

The graph is built from the same generated wiki data that powers the
resource pages, concept pages, review pages, and learning chapters.
That means every visible connection is backed by files already present
in the wiki build rather than by a runtime inference layer.

| File | Purpose |
|---|---|
| [/graph/nodes.json](/graph/nodes.json) | All graph nodes |
| [/graph/edges.json](/graph/edges.json) | All graph edges |
| [/graph/knowledge_graph.json](/graph/knowledge_graph.json) | Combined bundle with stats |
| [Open the graph workspace](/graph/explore) | App-style graph workspace for exploration and demos |
| [Open the Graphify explorer](/graph/graphify) | Dark enhanced graph view using vis-network |
| [Open the compatibility viewer](/graph/viewer) | Technical/reference page with the same graph runtime |
| [Open the relationship report](/graph/resource-relationships) | Deterministic resource-to-resource relationship summary |

## Stats

- Schema version: `1.0.0`
- Nodes: 69
- Edges: 1150

### Node types

| Type | Count |
|---|---:|
| concept | 18 |
| learn_chapter | 10 |
| resource | 24 |
| review_page | 7 |
| topic | 10 |

### Edge types

| Type | Count |
|---|---:|
| concept_in_topic | 103 |
| learn_chapter_uses_resource | 110 |
| resource_has_topic | 45 |
| resource_mentions_concept | 146 |
| resource_same_source_type_as_resource | 126 |
| resource_shares_concept_with_resource | 210 |
| resource_shares_topic_with_resource | 68 |
| resource_similar_to_resource | 211 |
| review_page_reviews_resource | 41 |
| topic_has_resource | 45 |
| topic_related_to_topic | 45 |

## Provenance

- Generated: 2026-06-11T08:04:58.691132+00:00
