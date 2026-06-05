"""Validation helpers for the knowledge graph.

The validate module exposes three entry points:

- :func:`validate_graph` – validate a full in-memory graph bundle
  (shape produced by ``GraphBuilder.build()`` and the
  ``knowledge_graph.json`` file).
- :func:`iter_issues_from_files` – re-validate the on-disk JSON files
  (used by ``validate`` and ``smoke-site``). The per-file validation
  matches the shape of each file (``nodes.json`` and ``edges.json`` are
  JSON arrays; ``knowledge_graph.json`` is a full bundle).
- :func:`validate_nodes_file` / :func:`validate_edges_file` – validate
  a single array payload in isolation.

Issues are 3-tuples of ``(severity, code, message)`` where ``severity``
is ``"error"`` or ``"warning"``. Issues are deliberately
informational: callers decide what to do with them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wiki.graph.schema import (
    ALLOWED_EDGE_TYPES,
    ALLOWED_NODE_TYPES,
    BLOCKED_ALIAS_TOPIC_SLUGS,
    EDGE_TYPE_RESOURCE_HAS_TOPIC,
    NODE_TYPE_RESOURCE,
    NODE_TYPE_TOPIC,
    RESOURCE_RELATIONSHIP_EDGE_TYPES,
    parse_node_id,
)


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def validate_graph(graph_data: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Validate a full in-memory knowledge graph bundle.

    A full bundle is a dict with at least ``schema_version``, ``nodes``,
    ``edges``, and ``stats`` keys (the shape produced by
    :func:`wiki.graph.builder.GraphBuilder.build` and the
    ``knowledge_graph.json`` file written by
    :func:`wiki.graph.export.export_graph`).

    File-level validation (e.g. validating the raw ``nodes.json`` and
    ``edges.json`` arrays in isolation) is handled by
    :func:`iter_issues_from_files` so that we never pass a partial dict
    to this function.
    """
    issues: list[tuple[str, str, str]] = []
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    issues.extend(_check_required_keys(graph_data))
    # Skip the rest of the checks if the bundle is malformed: there's
    # nothing useful we can say about the nodes/edges if the bundle
    # itself is missing the required top-level keys.
    if any(
        code == "missing_key" for _sev, code, _msg in issues
    ):
        return issues

    issues.extend(_check_unique_node_ids(nodes))
    issues.extend(_check_unique_edge_ids(edges))
    issues.extend(_check_duplicate_edge_triples(edges))
    issues.extend(_check_edge_endpoints_exist(nodes, edges))
    issues.extend(_check_no_alias_topic_nodes(nodes))
    issues.extend(_check_node_types(nodes))
    issues.extend(_check_edge_types(edges))
    issues.extend(_check_deterministic_order(nodes, edges))
    issues.extend(_check_resource_topic_connectivity(nodes, edges))
    issues.extend(_check_stats_consistency(nodes, edges, graph_data.get("stats", {})))
    issues.extend(_check_relationship_endpoints_are_resources(nodes, edges))
    issues.extend(_check_no_self_relationship_edges(edges))

    return issues


def validate_nodes_file(payload: Any) -> list[tuple[str, str, str]]:
    """Validate the raw ``nodes.json`` file payload (a list)."""
    issues: list[tuple[str, str, str]] = []
    if not isinstance(payload, list):
        issues.append(
            (
                "error",
                "nodes_file_not_list",
                f"nodes.json must be a JSON array, got {type(payload).__name__}",
            )
        )
        return issues
    nodes = payload
    issues.extend(_check_unique_node_ids(nodes))
    issues.extend(_check_no_alias_topic_nodes(nodes))
    issues.extend(_check_node_types(nodes))
    return issues


def validate_edges_file(payload: Any) -> list[tuple[str, str, str]]:
    """Validate the raw ``edges.json`` file payload (a list)."""
    issues: list[tuple[str, str, str]] = []
    if not isinstance(payload, list):
        issues.append(
            (
                "error",
                "edges_file_not_list",
                f"edges.json must be a JSON array, got {type(payload).__name__}",
            )
        )
        return issues
    edges = payload
    issues.extend(_check_unique_edge_ids(edges))
    issues.extend(_check_duplicate_edge_triples(edges))
    issues.extend(_check_edge_types(edges))
    return issues


def iter_issues_from_files(
    nodes_path: Path,
    edges_path: Path,
    *,
    knowledge_graph_path: Path | None = None,
) -> list[tuple[str, str, str]]:
    """Re-validate by reading the on-disk JSON files.

    File-level checks are performed against the payload shape of each
    individual file:

    - ``nodes.json`` – a JSON array of node dicts
    - ``edges.json`` – a JSON array of edge dicts
    - ``knowledge_graph.json`` – a full bundle with ``schema_version``,
      ``nodes``, ``edges``, and ``stats`` keys

    We do **not** call :func:`validate_graph` with a partial dict built
    from the per-array files. The combined bundle is validated via
    :func:`validate_graph` only when the ``knowledge_graph.json`` file
    is present and parses successfully.
    """
    issues: list[tuple[str, str, str]] = []
    for label, path in (
        ("nodes.json", nodes_path),
        ("edges.json", edges_path),
    ):
        if not path.exists():
            issues.append(("error", "missing_file", f"Missing {label}: {path}"))
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(("error", "invalid_json", f"{label} is not valid JSON: {exc}"))
            continue
        if label == "nodes.json":
            issues.extend(validate_nodes_file(payload))
        else:
            issues.extend(validate_edges_file(payload))

    # Cross-file edge endpoint check: edges reference nodes, so we
    # need both arrays loaded. We only run this lightweight check here;
    # the full structural validation lives in validate_graph and is
    # also re-run on the combined bundle below.
    if nodes_path.exists() and edges_path.exists():
        try:
            nodes = json.loads(nodes_path.read_text(encoding="utf-8"))
            edges = json.loads(edges_path.read_text(encoding="utf-8"))
            if isinstance(nodes, list) and isinstance(edges, list):
                issues.extend(_check_edge_endpoints_exist(nodes, edges))
        except json.JSONDecodeError:
            pass

    if knowledge_graph_path is not None and knowledge_graph_path.exists():
        try:
            bundle = json.loads(knowledge_graph_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(
                (
                    "error",
                    "invalid_json",
                    f"knowledge_graph.json is not valid JSON: {exc}",
                )
            )
            return issues
        if not isinstance(bundle, dict):
            issues.append(
                (
                    "error",
                    "knowledge_graph_not_object",
                    f"knowledge_graph.json must be a JSON object, got {type(bundle).__name__}",
                )
            )
            return issues
        issues.extend(validate_graph(bundle))
    return issues


# -----------------------------------------------------------------------------
# Individual checks
# -----------------------------------------------------------------------------

def _check_unique_node_ids(nodes: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            issues.append(("error", "missing_node_id", f"Node missing id field: {node}"))
            continue
        if node_id in seen:
            issues.append(("error", "duplicate_node_id", f"Duplicate node id: {node_id}"))
        else:
            seen.add(node_id)
    return issues


def _check_unique_edge_ids(edges: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for edge in edges:
        edge_id = edge.get("id")
        if not edge_id:
            issues.append(("error", "missing_edge_id", f"Edge missing id field: {edge}"))
            continue
        if edge_id in seen:
            issues.append(("error", "duplicate_edge_id", f"Duplicate edge id: {edge_id}"))
        else:
            seen.add(edge_id)
    return issues


def _check_duplicate_edge_triples(edges: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        triple = (edge.get("type", ""), edge.get("source", ""), edge.get("target", ""))
        if triple in seen:
            issues.append(
                (
                    "error",
                    "duplicate_edge_triple",
                    f"Duplicate edge triple: type={triple[0]} source={triple[1]} target={triple[2]}",
                )
            )
        else:
            seen.add(triple)
    return issues


def _check_edge_endpoints_exist(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    node_ids = {n.get("id") for n in nodes}
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source not in node_ids:
            issues.append(("error", "edge_source_missing", f"Edge {edge.get('id')!r} source {source!r} not in nodes"))
        if target not in node_ids:
            issues.append(("error", "edge_target_missing", f"Edge {edge.get('id')!r} target {target!r} not in nodes"))
    return issues


def _check_no_alias_topic_nodes(nodes: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    for node in nodes:
        if node.get("type") != NODE_TYPE_TOPIC:
            continue
        slug = node.get("slug") or parse_node_id(node.get("id", ""))[1]
        if slug in BLOCKED_ALIAS_TOPIC_SLUGS:
            issues.append(
                (
                    "error",
                    "alias_topic_node",
                    f"Topic node uses alias slug: {slug!r} (id={node.get('id')!r})",
                )
            )
    return issues


def _check_node_types(nodes: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    for node in nodes:
        node_type = node.get("type")
        if node_type not in ALLOWED_NODE_TYPES:
            issues.append(
                (
                    "error",
                    "unknown_node_type",
                    f"Node {node.get('id')!r} has unknown type: {node_type!r}",
                )
            )
    return issues


def _check_edge_types(edges: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    for edge in edges:
        edge_type = edge.get("type")
        if edge_type not in ALLOWED_EDGE_TYPES:
            issues.append(
                (
                    "error",
                    "unknown_edge_type",
                    f"Edge {edge.get('id')!r} has unknown type: {edge_type!r}",
                )
            )
    return issues


def _check_deterministic_order(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    if [n.get("id") for n in nodes] != sorted(n.get("id", "") for n in nodes):
        issues.append(("warning", "nodes_not_sorted", "Nodes are not in sorted id order"))
    if [e.get("id") for e in edges] != sorted(e.get("id", "") for e in edges):
        issues.append(("warning", "edges_not_sorted", "Edges are not in sorted id order"))
    return issues


def _check_resource_topic_connectivity(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    resources = [n for n in nodes if n.get("type") == "resource"]
    if not resources:
        return issues
    topics = [n for n in nodes if n.get("type") == "topic"]
    if not topics:
        return issues
    resource_ids = {n["id"] for n in resources}
    topic_ids = {n["id"] for n in topics}
    connected = set()
    for edge in edges:
        if edge.get("type") != EDGE_TYPE_RESOURCE_HAS_TOPIC:
            continue
        if edge.get("source") in resource_ids and edge.get("target") in topic_ids:
            connected.add(edge["source"])
    for resource in resources:
        if resource["id"] not in connected:
            issues.append(
                (
                    "warning",
                    "resource_without_topic",
                    f"Resource {resource['id']!r} has no resource_has_topic edge",
                )
            )
    return issues


def _check_required_keys(
    graph_data: dict[str, Any], prefix: str = "graph"
) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    for key in ("schema_version", "nodes", "edges", "stats"):
        if key not in graph_data:
            issues.append(("error", "missing_key", f"{prefix} missing required key: {key}"))
    if graph_data.get("schema_version") and graph_data["schema_version"] != "1.0.0":
        issues.append(
            (
                "warning",
                "schema_version_mismatch",
                f"{prefix} schema_version is {graph_data['schema_version']!r}, expected '1.0.0'",
            )
        )
    return issues


def _check_stats_consistency(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    stats: dict[str, Any],
) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    if not isinstance(stats, dict):
        return issues
    if "node_count" in stats and stats["node_count"] != len(nodes):
        issues.append(
            (
                "warning",
                "stats_node_count_mismatch",
                f"stats.node_count={stats['node_count']} but {len(nodes)} nodes present",
            )
        )
    if "edge_count" in stats and stats["edge_count"] != len(edges):
        issues.append(
            (
                "warning",
                "stats_edge_count_mismatch",
                f"stats.edge_count={stats['edge_count']} but {len(edges)} edges present",
            )
        )
    return issues


# -----------------------------------------------------------------------------
# Resource-to-resource relationship edge checks (Prompt 24)
# -----------------------------------------------------------------------------


def _check_relationship_endpoints_are_resources(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[tuple[str, str, str]]:
    """For every resource-relationship edge, both endpoints must be resource nodes.

    Catches mistakes like a relationship edge whose target is a topic
    or concept node. Reported as ``relationship_endpoint_not_resource``
    so consumers can distinguish this from the generic
    ``edge_source_missing`` / ``edge_target_missing`` codes.
    """
    issues: list[tuple[str, str, str]] = []
    node_types_by_id: dict[str, str] = {
        n.get("id"): n.get("type") for n in nodes if n.get("id")
    }
    for edge in edges:
        edge_type = edge.get("type")
        if edge_type not in RESOURCE_RELATIONSHIP_EDGE_TYPES:
            continue
        source_type = node_types_by_id.get(edge.get("source"))
        target_type = node_types_by_id.get(edge.get("target"))
        if source_type != NODE_TYPE_RESOURCE:
            issues.append(
                (
                    "error",
                    "relationship_endpoint_not_resource",
                    f"Relationship edge {edge.get('id')!r} source "
                    f"{edge.get('source')!r} is not a resource node "
                    f"(type={source_type!r})",
                )
            )
        if target_type != NODE_TYPE_RESOURCE:
            issues.append(
                (
                    "error",
                    "relationship_endpoint_not_resource",
                    f"Relationship edge {edge.get('id')!r} target "
                    f"{edge.get('target')!r} is not a resource node "
                    f"(type={target_type!r})",
                )
            )
    return issues


def _check_no_self_relationship_edges(
    edges: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    """For every resource-relationship edge, source must differ from target."""
    issues: list[tuple[str, str, str]] = []
    for edge in edges:
        edge_type = edge.get("type")
        if edge_type not in RESOURCE_RELATIONSHIP_EDGE_TYPES:
            continue
        if edge.get("source") == edge.get("target"):
            issues.append(
                (
                    "error",
                    "self_relationship_edge",
                    f"Relationship edge {edge.get('id')!r} has source == target",
                )
            )
    return issues
