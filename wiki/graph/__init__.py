"""Knowledge graph data model and JSON export.

Public API:

- :class:`GraphBuilder`  – builds nodes/edges from registry + derived data.
- :func:`export_graph`  – writes deterministic JSON files.
- :func:`validate_graph` – runs the 10 validation rules.
- :func:`iter_issues_from_files` – re-validates the on-disk JSON.

The graph is the foundation for future graph RAG, hybrid search, and
graph visualization. Prompt 23 only covers the data model and the JSON
export; no retrieval, embeddings, or UI is included.
"""

from wiki.graph.builder import GraphBuilder, build_graph
from wiki.graph.export import export_graph, graph_output_paths
from wiki.graph.schema import (
    ALLOWED_EDGE_TYPES,
    ALLOWED_NODE_TYPES,
    BLOCKED_ALIAS_TOPIC_SLUGS,
    EDGE_TYPE_CONCEPT_IN_TOPIC,
    EDGE_TYPE_LEARN_CHAPTER_USES_RESOURCE,
    EDGE_TYPE_REVIEW_PAGE_REVIEWS_RESOURCE,
    EDGE_TYPE_RESOURCE_HAS_TAG,
    EDGE_TYPE_RESOURCE_HAS_TOPIC,
    EDGE_TYPE_RESOURCE_MENTIONS_CONCEPT,
    EDGE_TYPE_TOPIC_HAS_RESOURCE,
    EDGE_TYPE_TOPIC_RELATED_TO_TOPIC,
    NODE_TYPE_CONCEPT,
    NODE_TYPE_LEARN_CHAPTER,
    NODE_TYPE_RESOURCE,
    NODE_TYPE_REVIEW_PAGE,
    NODE_TYPE_TAG,
    NODE_TYPE_TOPIC,
    SCHEMA_VERSION,
    make_edge_id,
    make_node_id,
)
from wiki.graph.validate import (
    iter_issues_from_files,
    validate_edges_file,
    validate_graph,
    validate_nodes_file,
)

__all__ = [
    "GraphBuilder",
    "build_graph",
    "export_graph",
    "graph_output_paths",
    "validate_graph",
    "validate_nodes_file",
    "validate_edges_file",
    "iter_issues_from_files",
    "SCHEMA_VERSION",
    "ALLOWED_NODE_TYPES",
    "ALLOWED_EDGE_TYPES",
    "BLOCKED_ALIAS_TOPIC_SLUGS",
    "NODE_TYPE_TOPIC",
    "NODE_TYPE_TAG",
    "NODE_TYPE_RESOURCE",
    "NODE_TYPE_CONCEPT",
    "NODE_TYPE_LEARN_CHAPTER",
    "NODE_TYPE_REVIEW_PAGE",
    "EDGE_TYPE_RESOURCE_HAS_TOPIC",
    "EDGE_TYPE_RESOURCE_HAS_TAG",
    "EDGE_TYPE_TOPIC_HAS_RESOURCE",
    "EDGE_TYPE_TOPIC_RELATED_TO_TOPIC",
    "EDGE_TYPE_RESOURCE_MENTIONS_CONCEPT",
    "EDGE_TYPE_CONCEPT_IN_TOPIC",
    "EDGE_TYPE_LEARN_CHAPTER_USES_RESOURCE",
    "EDGE_TYPE_REVIEW_PAGE_REVIEWS_RESOURCE",
    "make_node_id",
    "make_edge_id",
]
