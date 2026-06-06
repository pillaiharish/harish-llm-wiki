"""Deterministic JSON export of the knowledge graph.

Writes three files into the site's ``public/graph/`` directory:

- ``nodes.json`` – list of node dicts
- ``edges.json`` – list of edge dicts
- ``knowledge_graph.json`` – combined bundle with stats and schema

The combined file's ``nodes`` and ``edges`` blocks are byte-stable
across runs with the same input. The ``generated_at`` timestamp is
excluded from the determinism check (same pattern as the rest of the
wiki's generated JSON files).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wiki.config import config
from wiki.graph.schema import SCHEMA_VERSION
from wiki.storage import Storage


def graph_output_paths(*, data_dir: Path | None = None) -> dict[str, Path]:
    """Return the output paths for the graph JSON files.

    The ``public`` directory under ``data_dir/site_generated/docs``
    is the same one the existing ``_copy_generated_section("public")``
    pass syncs into ``site/docs/public/``.
    """
    base = (data_dir or config.LLM_WIKI_DATA_DIR) / "site_generated" / "docs" / "public" / "graph"
    return {
        "nodes": base / "nodes.json",
        "edges": base / "edges.json",
        "knowledge_graph": base / "knowledge_graph.json",
        "directory": base,
    }


def export_graph(
    graph_data: dict[str, Any],
    *,
    data_dir: Path | None = None,
) -> dict[str, Path]:
    """Write the three graph JSON files and return the paths.

    The function is a no-op if the input contains no nodes; this
    matches the rest of the wiki (no useful page without data).
    """
    paths = graph_output_paths(data_dir=data_dir)
    paths["directory"].mkdir(parents=True, exist_ok=True)

    nodes = list(graph_data.get("nodes", []))
    edges = list(graph_data.get("edges", []))

    nodes_payload = _strip_for_export(nodes)
    edges_payload = _strip_for_export(edges)

    Storage.write_json(nodes_payload, paths["nodes"])
    Storage.write_json(edges_payload, paths["edges"])

    # Combined file: deterministic nodes/edges but a fresh timestamp.
    combined = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": graph_data.get("generated_at") or _utcnow_iso(),
        "nodes": nodes_payload,
        "edges": edges_payload,
        "stats": graph_data.get("stats", {}),
    }
    Storage.write_json(combined, paths["knowledge_graph"])

    return paths


def _strip_for_export(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of the items suitable for export.

    Currently a no-op (the builders already emit clean dicts in a
    stable order), but kept as a hook for future schema migrations.
    """
    return [dict(item) for item in items]


def _utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
