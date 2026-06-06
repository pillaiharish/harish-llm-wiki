"""Page generator helpers for the static knowledge graph viewer.

Prompt 25 adds a vanilla HTML/CSS/JavaScript viewer page that
consumes the JSON files emitted by Prompt 23
(``public/graph/knowledge_graph.json``) and the resource-relationship
report page written by Prompt 24. The viewer is intentionally
dependency-free: it does not import D3, Cytoscape, or any other
external library. It is bounded to a "top N by edge degree" default
view and a one-hop neighborhood expansion so it cannot hang on a
large graph.

This module exposes two pure helpers:

- :func:`viewer_payload` – compute the small set of summary fields
  the Markdown template needs in its stats section.
- :func:`viewer_markdown` – render the static template with the
  placeholders filled in.

Both functions are deterministic, so the generated Markdown is
byte-stable across runs for the same input graph (the only variable
is the ``generated_at`` timestamp, which is already a server-side
fallback string the JS does not depend on).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

# Default cap on the "top N by degree" set shown in the mini-graph
# and the neighbor list. The viewer shows the highest-degree nodes
# by default, with a one-hop neighborhood expansion on selection.
VIEWER_DEFAULT_TOP_N = 50

# Placeholder names supported by viewer_markdown. They are listed
# here so the tests and the template stay in sync.
PLACEHOLDER_SCHEMA_VERSION = "{{SCHEMA_VERSION}}"
PLACEHOLDER_GENERATED_AT = "{{GENERATED_AT}}"
PLACEHOLDER_NODE_COUNT = "{{NODE_COUNT}}"
PLACEHOLDER_EDGE_COUNT = "{{EDGE_COUNT}}"
PLACEHOLDER_NODE_TYPE_COUNT_ROWS = "{{NODE_TYPE_COUNT_ROWS}}"
PLACEHOLDER_EDGE_TYPE_COUNT_ROWS = "{{EDGE_TYPE_COUNT_ROWS}}"


def _sorted_type_counts(stats: dict[str, Any], key: str) -> list[tuple[str, int]]:
    """Return ``[(type, count), ...]`` sorted by type name."""
    raw = stats.get(key) or {}
    if not isinstance(raw, dict):
        return []
    return sorted(
        ((str(k), int(v)) for k, v in raw.items()),
        key=lambda item: item[0],
    )


def _top_node_ids_by_degree(
    graph: dict[str, Any], *, top_n: int
) -> list[str]:
    """Return the top-``top_n`` node ids by combined in+out degree.

    Ties are broken by node id (ascending) so the result is
    byte-stable. The list is ordered by descending degree then by
    ascending node id within each degree bucket, but the function
    returns ids in the canonical (degree desc, id asc) order.
    """
    nodes = list(graph.get("nodes", []) or [])
    edges = list(graph.get("edges", []) or [])
    if not nodes or not edges:
        return []
    degree: Counter[str] = Counter()
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source:
            degree[source] += 1
        if target:
            degree[target] += 1
    # Sort nodes by (-degree, id). Items missing from `degree` have
    # degree 0 and sort after the rest.
    sorted_nodes = sorted(
        nodes,
        key=lambda n: (-int(degree.get(n.get("id", ""), 0)), n.get("id", "")),
    )
    return [
        node.get("id", "")
        for node in sorted_nodes[: max(0, int(top_n))]
        if node.get("id")
    ]


def viewer_payload(graph: dict[str, Any]) -> dict[str, Any]:
    """Return summary fields for the viewer template.

    The output dict has these keys:

    - ``schema_version`` (str): the graph schema version string.
    - ``generated_at`` (str): the original timestamp from the graph
      bundle, kept for the server-rendered stats fallback.
    - ``node_count`` (int)
    - ``edge_count`` (int)
    - ``node_type_counts`` (dict[str, int]): sorted by type name.
    - ``edge_type_counts`` (dict[str, int]): sorted by type name.
    - ``top_node_ids`` (list[str]): the top :data:`VIEWER_DEFAULT_TOP_N`
      node ids by combined in+out degree, ordered by descending
      degree then ascending id.
    - ``node_type_list`` (list[str]): unique node types, sorted.
    - ``edge_type_list`` (list[str]): unique edge types, sorted.
    """
    stats = graph.get("stats", {}) or {}
    node_type_counts_list = _sorted_type_counts(stats, "node_type_counts")
    edge_type_counts_list = _sorted_type_counts(stats, "edge_type_counts")
    return {
        "schema_version": str(graph.get("schema_version", "")),
        "generated_at": str(graph.get("generated_at", "")),
        "node_count": int(stats.get("node_count", 0) or 0),
        "edge_count": int(stats.get("edge_count", 0) or 0),
        "node_type_counts": dict(node_type_counts_list),
        "edge_type_counts": dict(edge_type_counts_list),
        "top_node_ids": _top_node_ids_by_degree(
            graph, top_n=VIEWER_DEFAULT_TOP_N
        ),
        "node_type_list": [t for t, _ in node_type_counts_list],
        "edge_type_list": [t for t, _ in edge_type_counts_list],
    }


def _render_type_count_rows(rows: list[tuple[str, int]]) -> str:
    """Render type-count rows as Markdown table rows.

    The output is a sequence of ``| <type> | <count> |`` lines, with
    one trailing newline. An empty input produces an empty string.
    """
    if not rows:
        return ""
    lines = [f"| {node_type} | {count} |" for node_type, count in rows]
    return "\n".join(lines)


def viewer_markdown(graph: dict[str, Any], template: str) -> str:
    """Return the rendered Markdown for ``site/docs/graph/viewer.md``.

    Substitutes the small set of placeholders listed below and does
    no other string mutation. The inline ``<script>`` block is left
    untouched so the JS does not drift from the test assertions.

    Supported placeholders (in the intro / stats section only):

    - ``{{SCHEMA_VERSION}}``
    - ``{{GENERATED_AT}}``
    - ``{{NODE_COUNT}}``
    - ``{{EDGE_COUNT}}``
    - ``{{NODE_TYPE_COUNT_ROWS}}``
    - ``{{EDGE_TYPE_COUNT_ROWS}}``
    """
    payload = viewer_payload(graph)
    rows_node = _render_type_count_rows(
        _sorted_type_counts(graph.get("stats", {}) or {}, "node_type_counts")
    )
    rows_edge = _render_type_count_rows(
        _sorted_type_counts(graph.get("stats", {}) or {}, "edge_type_counts")
    )
    rendered = template
    rendered = rendered.replace(
        PLACEHOLDER_SCHEMA_VERSION, payload["schema_version"]
    )
    rendered = rendered.replace(
        PLACEHOLDER_GENERATED_AT, payload["generated_at"]
    )
    rendered = rendered.replace(
        PLACEHOLDER_NODE_COUNT, str(payload["node_count"])
    )
    rendered = rendered.replace(
        PLACEHOLDER_EDGE_COUNT, str(payload["edge_count"])
    )
    rendered = rendered.replace(PLACEHOLDER_NODE_TYPE_COUNT_ROWS, rows_node)
    rendered = rendered.replace(PLACEHOLDER_EDGE_TYPE_COUNT_ROWS, rows_edge)
    return rendered


__all__ = [
    "VIEWER_DEFAULT_TOP_N",
    "viewer_payload",
    "viewer_markdown",
    "PLACEHOLDER_SCHEMA_VERSION",
    "PLACEHOLDER_GENERATED_AT",
    "PLACEHOLDER_NODE_COUNT",
    "PLACEHOLDER_EDGE_COUNT",
    "PLACEHOLDER_NODE_TYPE_COUNT_ROWS",
    "PLACEHOLDER_EDGE_TYPE_COUNT_ROWS",
]
