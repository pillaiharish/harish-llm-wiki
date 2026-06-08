# Knowledge Graph

The wiki exposes a deterministic knowledge graph as JSON for future
RAG, search, and visualization features.

| File | Purpose |
|---|---|
| [/graph/nodes.json](/graph/nodes.json) | All graph nodes |
| [/graph/edges.json](/graph/edges.json) | All graph edges |
| [/graph/knowledge_graph.json](/graph/knowledge_graph.json) | Combined bundle with stats |
| [Open the graph viewer](/graph/viewer) | Interactive neighborhood + filter explorer (Prompt 25) |

## Stats

- Schema version: `1.0.0`
- Nodes: 33
- Edges: 60

### Node types

| Type | Count |
|---|---:|
| concept | 3 |
| learn_chapter | 10 |
| resource | 1 |
| review_page | 7 |
| tag | 2 |
| topic | 10 |

### Edge types

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

## Provenance

- Generated: 2026-06-08T15:31:27.993847+00:00
