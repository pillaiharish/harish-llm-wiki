# Knowledge Graph

The wiki exposes a deterministic knowledge graph as JSON for future
RAG, search, and visualization features.

| File | Purpose |
|---|---|
| [/public/graph/nodes.json](/public/graph/nodes.json) | All graph nodes |
| [/public/graph/edges.json](/public/graph/edges.json) | All graph edges |
| [/public/graph/knowledge_graph.json](/public/graph/knowledge_graph.json) | Combined bundle with stats |

## Stats

- Schema version: `1.0.0`
- Nodes: 64
- Edges: 504

### Node types

| Type | Count |
|---|---:|
| concept | 14 |
| learn_chapter | 10 |
| resource | 23 |
| review_page | 7 |
| topic | 10 |

### Edge types

| Type | Count |
|---|---:|
| concept_in_topic | 95 |
| learn_chapter_uses_resource | 104 |
| resource_has_topic | 43 |
| resource_mentions_concept | 135 |
| review_page_reviews_resource | 39 |
| topic_has_resource | 43 |
| topic_related_to_topic | 45 |

## Provenance

- Generated: 2026-06-05T20:24:25.193963+00:00
