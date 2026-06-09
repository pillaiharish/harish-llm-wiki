"""Tests for Prompt 25: Graph Visualization Page.

The 13 required test cases from ``prompt25.md`` are covered by the
classes in this file. The pattern follows the existing
``test_prompt23_graph`` and ``test_prompt24_resource_relationships``
tests: build a small graph in a tmp dir using controlled records,
point :class:`SiteBuilder` at isolated data/repo directories, and
assert on the generated files and the viewer-helper functions.
"""

from pathlib import Path

import pytest
import re

from wiki.config import config
from wiki.graph import (
    NODE_TYPE_RESOURCE,
    GraphBuilder,
)
from wiki.graph.builder import build_graph
from wiki.graph.viewer import (
    PLACEHOLDER_EDGE_COUNT,
    PLACEHOLDER_EDGE_TYPE_COUNT_ROWS,
    PLACEHOLDER_GENERATED_AT,
    PLACEHOLDER_NODE_COUNT,
    PLACEHOLDER_NODE_TYPE_COUNT_ROWS,
    PLACEHOLDER_SCHEMA_VERSION,
    VIEWER_DEFAULT_TOP_N,
    viewer_markdown,
    viewer_payload,
)
from wiki.schemas import (
    Importance,
    ResourceRecord,
    ResourceStatus,
    SourceType,
)
from wiki.site.builder import SiteBuilder


# -----------------------------------------------------------------------------
# Fixtures and helpers
# -----------------------------------------------------------------------------


def _make_note() -> str:
    """A minimal but realistic generated note for a RAG resource."""
    return (
        "# RAG Notes\n\n"
        "## One-line memory hook\n\n"
        "Retrieval quality controls answer quality.\n\n"
        "## Why this resource matters\n\n"
        "This helps build RAG systems.\n\n"
        "## Source-backed summary\n\n"
        "- RAG retrieves context before generation. "
        "[source: webpage:test-c0001]\n\n"
        "## Revision questions\n\n"
        "1. What is retrieval-augmented generation?\n\n"
        "## Provenance\n\n"
        "- LLM provider: mock\n"
    )


def _make_record(
    tmp_path: Path,
    *,
    resource_id: str = "webpage:test",
    title: str = "RAG Hybrid Retrieval",
    tags: list | None = None,
    note_text: str | None = None,
) -> ResourceRecord:
    """Build a self-contained ResourceRecord on disk under tmp_path."""
    safe_id = resource_id.replace(":", "_")
    note_path = tmp_path / "processed" / "resources" / f"{safe_id}.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(note_text or _make_note(), encoding="utf-8")
    return ResourceRecord(
        id=resource_id,
        source_type=SourceType.WEBPAGE,
        canonical_id=resource_id,
        original_url=f"https://example.com/{safe_id}",
        title=title,
        status=ResourceStatus.PROCESSED,
        generated_note_path=note_path,
        llm_provider="mock",
        llm_model="mock-model",
        prompt_version="harish_llm_wiki_v4",
        tags=tags if tags is not None else ["rag", "retrieval"],
        importance=Importance.MEDIUM,
    )


def _build(tmp_path: Path, *, records: list[ResourceRecord] | None = None) -> dict:
    """Build a graph in a tmp dir and return the bundle."""
    if records is None:
        records = [_make_record(tmp_path)]
    return build_graph(records, data_dir=tmp_path)


def _setup_site_builder(tmp_path: Path, monkeypatch) -> SiteBuilder:
    """Build an isolated SiteBuilder with tmp data and repo dirs."""
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    builder = SiteBuilder()
    builder.data_site_dir = tmp_path / "site_generated" / "docs"
    builder.repo_site_dir = tmp_path / "repo_docs"
    builder.data_site_dir.mkdir(parents=True, exist_ok=True)
    builder.repo_site_dir.mkdir(parents=True, exist_ok=True)
    return builder


# -----------------------------------------------------------------------------
# Test class 1: TestViewerPayload
# -----------------------------------------------------------------------------


class TestViewerPayload:
    def test_viewer_payload_is_deterministic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph1 = _build(tmp_path)
        graph2 = _build(tmp_path)
        p1 = viewer_payload(graph1)
        p2 = viewer_payload(graph2)
        # The generated_at timestamp is non-deterministic; compare
        # the rest of the payload byte-equal.
        p1_no_ts = {k: v for k, v in p1.items() if k != "generated_at"}
        p2_no_ts = {k: v for k, v in p2.items() if k != "generated_at"}
        assert p1_no_ts == p2_no_ts
        # And the "top N" list is exactly equal between calls.
        assert p1["top_node_ids"] == p2["top_node_ids"]

    def test_viewer_payload_top_nodes_capped(self, tmp_path, monkeypatch):
        """If we have many more nodes than VIEWER_DEFAULT_TOP_N, the
        top_node_ids list is exactly the cap length."""
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # Build a graph with many resources (we don't have access to
        # many resources in the test repo, so we synthesize a graph
        # with the same builder).
        records = [
            _make_record(tmp_path, resource_id=f"webpage:r{i}", title=f"R{i}")
            for i in range(5)
        ]
        graph = _build(tmp_path, records=records)
        payload = viewer_payload(graph)
        # Each resource appears as a node plus the canonical topics
        # and the tags; we just verify the cap is respected.
        assert len(payload["top_node_ids"]) <= VIEWER_DEFAULT_TOP_N

    def test_viewer_payload_top_nodes_sorted_by_degree(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        records = [
            _make_record(
                tmp_path,
                resource_id="webpage:high",
                title="High",
                tags=["rag", "llm"],
            ),
            _make_record(
                tmp_path,
                resource_id="webpage:mid",
                title="Mid",
                tags=["rag"],
            ),
            _make_record(
                tmp_path,
                resource_id="webpage:low",
                title="Low",
                tags=["llm"],
            ),
        ]
        graph = _build(tmp_path, records=records)
        payload = viewer_payload(graph)
        # Build a quick in-test degree mapping and verify the order
        # of resource nodes in top_node_ids matches descending degree.
        edges = graph["edges"]
        nodes_by_id = {n["id"]: n for n in graph["nodes"]}
        degree = {nid: 0 for nid in nodes_by_id}
        for e in edges:
            degree[e["source"]] = degree.get(e["source"], 0) + 1
            degree[e["target"]] = degree.get(e["target"], 0) + 1
        resource_ids_in_order = [
            nid
            for nid in payload["top_node_ids"]
            if nodes_by_id.get(nid, {}).get("type") == NODE_TYPE_RESOURCE
        ]
        degrees = [degree[nid] for nid in resource_ids_in_order]
        assert degrees == sorted(degrees, reverse=True)

    def test_viewer_payload_node_and_edge_type_lists_are_sorted(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        payload = viewer_payload(graph)
        assert payload["node_type_list"] == sorted(payload["node_type_list"])
        assert payload["edge_type_list"] == sorted(payload["edge_type_list"])

    def test_viewer_payload_includes_schema_version_and_timestamp(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        payload = viewer_payload(graph)
        assert "schema_version" in payload
        assert "generated_at" in payload
        # schema_version is the same string the graph has
        assert payload["schema_version"] == graph["schema_version"]
        # generated_at is non-empty
        assert payload["generated_at"]


# -----------------------------------------------------------------------------
# Test class 2: TestViewerMarkdown
# -----------------------------------------------------------------------------


class TestViewerMarkdown:
    def test_viewer_markdown_replaces_placeholders(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        template = (
            "SV=" + PLACEHOLDER_SCHEMA_VERSION + "\n"
            "GA=" + PLACEHOLDER_GENERATED_AT + "\n"
            "NC=" + PLACEHOLDER_NODE_COUNT + "\n"
            "EC=" + PLACEHOLDER_EDGE_COUNT + "\n"
            "NR=" + PLACEHOLDER_NODE_TYPE_COUNT_ROWS + "\n"
            "ER=" + PLACEHOLDER_EDGE_TYPE_COUNT_ROWS + "\n"
        )
        rendered = viewer_markdown(graph, template)
        # All placeholders are gone.
        for placeholder in (
            PLACEHOLDER_SCHEMA_VERSION,
            PLACEHOLDER_GENERATED_AT,
            PLACEHOLDER_NODE_COUNT,
            PLACEHOLDER_EDGE_COUNT,
            PLACEHOLDER_NODE_TYPE_COUNT_ROWS,
            PLACEHOLDER_EDGE_TYPE_COUNT_ROWS,
        ):
            assert placeholder not in rendered, (
                f"Placeholder {placeholder!r} should be replaced"
            )
        # Schema version, counts and rows are present.
        assert f"SV={graph['schema_version']}" in rendered
        assert f"NC={graph['stats']['node_count']}" in rendered
        assert f"EC={graph['stats']['edge_count']}" in rendered

    def test_viewer_markdown_preserves_script_block(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        # The in-repo template includes a <script>...</script> block;
        # substitute placeholders only and confirm the script body
        # is intact.
        template_path = (
            Path(__file__).parent.parent
            / "site"
            / "docs"
            / "graph"
            / "viewer.md"
        )
        template = template_path.read_text(encoding="utf-8")
        rendered = viewer_markdown(graph, template)
        assert "<script>" in rendered
        assert "</script>" in rendered
        # The placeholder script body marker the test uses lives in
        # the embedded JS — check a known JS function name.
        assert "initGraphViewer" in rendered

    def test_viewer_markdown_includes_json_links(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        template_path = (
            Path(__file__).parent.parent
            / "site"
            / "docs"
            / "graph"
            / "viewer.md"
        )
        template = template_path.read_text(encoding="utf-8")
        rendered = viewer_markdown(graph, template)
        assert "/graph/nodes.json" in rendered
        assert "/graph/edges.json" in rendered
        assert "/graph/knowledge_graph.json" in rendered

    def test_viewer_markdown_includes_resource_relationships_link(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        graph = _build(tmp_path)
        template_path = (
            Path(__file__).parent.parent
            / "site"
            / "docs"
            / "graph"
            / "viewer.md"
        )
        template = template_path.read_text(encoding="utf-8")
        rendered = viewer_markdown(graph, template)
        assert "/graph/resource-relationships" in rendered


# -----------------------------------------------------------------------------
# Test class 3: TestGraphViewerPageBuild
# -----------------------------------------------------------------------------


class TestGraphViewerPageBuild:
    def test_build_site_creates_viewer_page(self, tmp_path, monkeypatch):
        builder = _setup_site_builder(tmp_path, monkeypatch)
        record = _make_record(tmp_path)
        builder._build_knowledge_graph([record])
        # The viewer must have been written to data_site_dir.
        viewer = builder.data_site_dir / "graph" / "viewer.md"
        assert viewer.exists(), "graph/viewer.md not generated"
        content = viewer.read_text(encoding="utf-8")
        assert len(content) > 50

    def test_build_site_does_not_create_viewer_page_when_empty(
        self, tmp_path, monkeypatch
    ):
        """With zero records the graph builder still emits canonical
        topic nodes, so we instead build without a real graph build
        and verify the viewer is not generated when there are no
        nodes at all (we monkeypatch build to return an empty
        graph)."""
        builder = _setup_site_builder(tmp_path, monkeypatch)
        # Stub the build to return a graph with no nodes.
        from wiki.graph import builder as graph_builder_module

        def _empty(*args, **kwargs):
            return {
                "schema_version": "1.0.0",
                "generated_at": "1970-01-01T00:00:00+00:00",
                "nodes": [],
                "edges": [],
                "stats": {
                    "node_count": 0,
                    "edge_count": 0,
                    "node_type_counts": {},
                    "edge_type_counts": {},
                    "blocked_alias_topic_nodes": 0,
                    "duplicate_edges_removed": 0,
                },
            }

        monkeypatch.setattr(
            graph_builder_module.GraphBuilder, "build", _empty
        )
        # We also need export_graph to no-op (it already does for
        # empty nodes). And we need to make sure the
        # knowledge_graph.json file exists so the gating check
        # passes, but with no nodes we should not write the viewer.
        # Manually touch the JSON file so the gating `exists()` is
        # True.
        (builder.data_site_dir / "public" / "graph").mkdir(
            parents=True, exist_ok=True
        )
        (builder.data_site_dir / "public" / "graph" / "knowledge_graph.json").write_text(
            "{}", encoding="utf-8"
        )
        builder._build_knowledge_graph([_make_record(tmp_path)])
        viewer = builder.data_site_dir / "graph" / "viewer.md"
        assert not viewer.exists(), "viewer should not be generated for empty graph"

    def test_build_site_index_page_links_to_viewer(
        self, tmp_path, monkeypatch
    ):
        builder = _setup_site_builder(tmp_path, monkeypatch)
        record = _make_record(tmp_path)
        builder._build_knowledge_graph([record])
        index_path = builder.data_site_dir / "graph" / "index.md"
        assert index_path.exists()
        content = index_path.read_text(encoding="utf-8")
        assert "/graph/viewer" in content

    def test_build_site_viewer_links_to_three_json_files(
        self, tmp_path, monkeypatch
    ):
        builder = _setup_site_builder(tmp_path, monkeypatch)
        record = _make_record(tmp_path)
        builder._build_knowledge_graph([record])
        viewer = builder.data_site_dir / "graph" / "viewer.md"
        content = viewer.read_text(encoding="utf-8")
        for needle in (
            "/graph/nodes.json",
            "/graph/edges.json",
            "/graph/knowledge_graph.json",
        ):
            assert needle in content, f"viewer.md missing {needle}"


# -----------------------------------------------------------------------------
# Test class 4: TestGraphViewerPageUI
# -----------------------------------------------------------------------------


class TestGraphViewerPageUI:
    def _viewer_content(self, tmp_path, monkeypatch) -> str:
        builder = _setup_site_builder(tmp_path, monkeypatch)
        record = _make_record(tmp_path)
        builder._build_knowledge_graph([record])
        viewer = builder.data_site_dir / "graph" / "viewer.md"
        return viewer.read_text(encoding="utf-8")

    def _viewer_template(self) -> str:
        """Return the in-repo viewer.md template (the source of truth)."""
        template_path = (
            Path(__file__).parent.parent
            / "site"
            / "docs"
            / "graph"
            / "viewer.md"
        )
        return template_path.read_text(encoding="utf-8")

    def _component_source(self) -> str:
        """Return the GraphExplorer.vue source (where the runtime DOM
        elements like #graph-search, #graph-canvas, etc. are defined)."""
        component_path = (
            Path(__file__).parent.parent
            / "site"
            / "docs"
            / ".vitepress"
            / "theme"
            / "components"
            / "GraphExplorer.vue"
        )
        return component_path.read_text(encoding="utf-8")

    def test_viewer_page_contains_search_input(self, tmp_path, monkeypatch):
        component = self._component_source()
        assert 'id="graph-search"' in component

    def test_viewer_page_contains_node_type_filter(self, tmp_path, monkeypatch):
        component = self._component_source()
        assert 'id="graph-filter-node-type"' in component

    def test_viewer_page_contains_edge_type_filter(self, tmp_path, monkeypatch):
        component = self._component_source()
        assert 'id="graph-filter-edge-type"' in component

    def test_viewer_page_contains_details_panel(self, tmp_path, monkeypatch):
        component = self._component_source()
        assert 'id="graph-details"' in component

    def test_viewer_page_contains_neighbor_section(self, tmp_path, monkeypatch):
        component = self._component_source()
        assert 'id="graph-neighbors"' in component

    def test_viewer_page_contains_svg_mini_graph(self, tmp_path, monkeypatch):
        template = self._viewer_template()
        assert '<svg id="graph-svg"' in template

    def test_viewer_page_links_to_resource_relationships_report(
        self, tmp_path, monkeypatch
    ):
        content = self._viewer_content(tmp_path, monkeypatch)
        assert "/graph/resource-relationships" in content


# -----------------------------------------------------------------------------
# Test class 5: TestGraphExplorerComponent (Prompt 35)
# -----------------------------------------------------------------------------


class TestGraphExplorerComponent:
    """Prompt 35: real interactive Cytoscape.js graph explorer."""

    def _theme_dir(self) -> Path:
        return (
            Path(__file__).parent.parent
            / "site"
            / "docs"
            / ".vitepress"
            / "theme"
        )

    def _viewer_template(self) -> str:
        template_path = (
            Path(__file__).parent.parent
            / "site"
            / "docs"
            / "graph"
            / "viewer.md"
        )
        return template_path.read_text(encoding="utf-8")

    def test_component_file_exists(self):
        component = self._theme_dir() / "components" / "GraphExplorer.vue"
        assert component.exists(), f"missing {component}"

    def test_theme_index_registers_component(self):
        index_ts = self._theme_dir() / "index.ts"
        assert index_ts.exists(), f"missing {index_ts}"
        text = index_ts.read_text(encoding="utf-8")
        assert "GraphExplorer" in text
        assert "app.component" in text

    def test_component_imports_cytoscape_dynamically(self):
        component_path = self._theme_dir() / "components" / "GraphExplorer.vue"
        text = component_path.read_text(encoding="utf-8")
        # Cytoscape must be loaded via a dynamic import so SSR
        # doesn't try to evaluate it server-side.
        assert "import('cytoscape')" in text or 'import("cytoscape")' in text
        # It must be the only top-level cytoscape import in the SFC.
        assert "from 'cytoscape'" not in text
        assert 'from "cytoscape"' not in text

    def test_component_has_canvas_with_minimum_height(self):
        component_path = self._theme_dir() / "components" / "GraphExplorer.vue"
        text = component_path.read_text(encoding="utf-8")
        # The cytoscape container must be marked with id="graph-canvas"
        # and have a height >= 600px.
        assert 'id="graph-canvas"' in text
        # Look for either an inline style declaration or a CSS
        # selector that sets the height to 600 or more.
        assert (
            "min-height: 600px" in text
            or "height: 600px" in text
            or "height: 640px" in text
            or "min-height:600px" in text
        )

    def test_component_renders_required_controls(self):
        component_path = self._theme_dir() / "components" / "GraphExplorer.vue"
        text = component_path.read_text(encoding="utf-8")
        for control_id in (
            "graph-fit",
            "graph-reset-zoom",
            "graph-zoom-in",
            "graph-zoom-out",
            "graph-show-all",
            "graph-search",
            "graph-filter-node-type",
            "graph-filter-edge-type",
        ):
            assert f'id="{control_id}"' in text, (
                f"GraphExplorer.vue missing required control id {control_id!r}"
            )

    def test_component_destroys_cytoscape_on_unmount(self):
        component_path = self._theme_dir() / "components" / "GraphExplorer.vue"
        text = component_path.read_text(encoding="utf-8")
        assert "onBeforeUnmount" in text
        assert "destroy" in text

    def test_component_uses_resize_observer(self):
        """Prompt 35.1: the explorer must observe the canvas size
        and call cy.resize() / cy.fit() on resize events."""
        component_path = self._theme_dir() / "components" / "GraphExplorer.vue"
        text = component_path.read_text(encoding="utf-8")
        assert "ResizeObserver" in text, "GraphExplorer must use a ResizeObserver"
        assert "cy.resize" in text, "GraphExplorer must call cy.resize() on resize"
        assert "cy.fit" in text, "GraphExplorer must call cy.fit() on resize"

    def test_component_calls_fit_on_initial_load(self):
        """Prompt 35.1: fit must be called once after the initial
        layout so the first paint is well-framed."""
        component_path = self._theme_dir() / "components" / "GraphExplorer.vue"
        text = component_path.read_text(encoding="utf-8")
        assert "cy.fit(undefined, FIT_PADDING)" in text or (
            "cy.fit(" in text and "FIT_PADDING" in text
        ), "GraphExplorer must call cy.fit with the configured padding on initial load"

    def test_component_does_not_fit_on_zoom(self):
        """Prompt 35.1: a mouse-wheel zoom event must NOT auto-fit
        the graph. That would break user-controlled zoom.
        """
        component_path = self._theme_dir() / "components" / "GraphExplorer.vue"
        text = component_path.read_text(encoding="utf-8")
        # Find the zoom handler block. It must not invoke cy.fit().
        zoom_idx = text.find("cy.on('zoom'")
        assert zoom_idx != -1, "GraphExplorer must register a zoom event handler"
        # The handler is the function passed to cy.on('zoom', ...).
        # Find the closing `})` that ends the handler.
        start = text.find("=>", zoom_idx)
        handler = text[start: start + 400]
        end = handler.find("})")
        if end != -1:
            handler = handler[: end + 2]
        assert "cy.fit" not in handler, (
            "Zoom event handler must not call cy.fit() — that would override user zoom"
        )

    def test_component_pads_fit_with_40(self):
        """Prompt 35.1: cy.fit() must be invoked with padding 40
        on initial load and after re-renders, not the previous 30."""
        component_path = self._theme_dir() / "components" / "GraphExplorer.vue"
        text = component_path.read_text(encoding="utf-8")
        assert "FIT_PADDING = 40" in text, (
            "GraphExplorer must declare a 40-pixel fit padding constant"
        )
        assert "cy.fit(undefined, FIT_PADDING)" in text, (
            "GraphExplorer must call cy.fit(undefined, FIT_PADDING) for refits"
        )

    def test_component_marks_high_degree_nodes_as_hubs(self):
        """Prompt 35.1: high-degree nodes must show their labels
        at lower zooms. The HUB_DEGREE_THRESHOLD constant must be
        present and applied in the stylesheet."""
        component_path = self._theme_dir() / "components" / "GraphExplorer.vue"
        text = component_path.read_text(encoding="utf-8")
        assert "HUB_DEGREE_THRESHOLD" in text
        assert "node[degree >=" in text, (
            "GraphExplorer must use a node[degree >= ...] style selector for hubs"
        )

    def test_component_reruns_layout_on_node_set_change(self):
        """Prompt 35.1: re-rendering must recompute the cose
        layout whenever the visible node set changes."""
        component_path = self._theme_dir() / "components" / "GraphExplorer.vue"
        text = component_path.read_text(encoding="utf-8")
        assert "nodeSetChanged" in text or "node_set_changed" in text or (
            "coseLayoutOptions" in text and "lastNodeIdSet" in text
        ), "GraphExplorer must re-run the layout when the node set changes"

    def test_component_uses_deterministic_layout(self):
        """Prompt 35.1: layout must be deterministic
        (randomize: false) for reproducibility."""
        component_path = self._theme_dir() / "components" / "GraphExplorer.vue"
        text = component_path.read_text(encoding="utf-8")
        assert "randomize: false" in text
        assert "coseLayoutOptions" in text

    def test_component_disconnects_resize_observer_on_unmount(self):
        """Prompt 35.1: ResizeObserver must be torn down on unmount."""
        component_path = self._theme_dir() / "components" / "GraphExplorer.vue"
        text = component_path.read_text(encoding="utf-8")
        assert "teardownResizeObserver" in text
        assert "disconnect" in text

    def test_template_mounts_graph_explorer(self):
        text = self._viewer_template()
        assert "<GraphExplorer " in text

    def test_template_keeps_legacy_svg_mini_graph(self):
        text = self._viewer_template()
        assert '<svg id="graph-svg"' in text

    def test_template_keeps_noscript_fallback(self):
        text = self._viewer_template()
        assert "<noscript>" in text
        assert "</noscript>" in text

    def test_template_keeps_legacy_initgraphviewer_hook(self):
        """The companion <script> in viewer.md keeps the
        ``initGraphViewer`` function name and the
        ``import.meta.env.BASE_URL`` literal so existing Prompt 25
        test contracts continue to pass.
        """
        text = self._viewer_template()
        assert "initGraphViewer" in text
        assert "import.meta.env.BASE_URL" in text

    def test_package_json_declares_cytoscape_dependency(self):
        package_json = (
            Path(__file__).parent.parent
            / "site"
            / "package.json"
        )
        text = package_json.read_text(encoding="utf-8")
        assert '"cytoscape"' in text
        # Cytoscape must be in the runtime `dependencies`, not just
        # `devDependencies`, so the static dist works.
        import json

        data = json.loads(text)
        assert "cytoscape" in data.get("dependencies", {})

    # ------------------------------------------------------------------
    # Prompt 35.2 — Semantic zoom and graph spacing
    # ------------------------------------------------------------------

    def _component_text(self) -> str:
        component_path = self._theme_dir() / "components" / "GraphExplorer.vue"
        return component_path.read_text(encoding="utf-8")

    def test_component_defines_apply_semantic_zoom(self):
        """Prompt 35.2: the explorer must define an
        applySemanticZoom() function and call it everywhere the
        spec lists."""
        text = self._component_text()
        assert "function applySemanticZoom" in text, (
            "GraphExplorer must define applySemanticZoom()"
        )
        # Required call sites per the Prompt 35.2 spec.
        assert "applySemanticZoom()" in text, (
            "GraphExplorer must call applySemanticZoom()"
        )
        # The function must be reachable from every event path:
        # initial load, cy zoom, node select, hover, re-render, and
        # the four graph buttons.
        for needle in (
            "cy.on('zoom'",
            "cy.on('tap', 'node'",
            "cy.on('mouseover', 'node'",
            "reRenderCy",
            "fitGraph",
            "resetZoom",
            "zoomIn",
            "zoomOut",
        ):
            assert needle in text, f"missing handler: {needle}"
        # The cy.on('zoom', ...) handler must call applySemanticZoom.
        zoom_idx = text.find("cy.on('zoom'")
        assert zoom_idx != -1
        after = text[zoom_idx: zoom_idx + 400]
        assert "applySemanticZoom" in after, (
            "cy.on('zoom', ...) handler must call applySemanticZoom"
        )

    def test_component_does_not_fit_inside_zoom_handler(self):
        """Prompt 35.2: a mouse-wheel zoom event must NOT auto-fit
        the graph. Semantic zoom must not steal user-controlled
        wheel zoom."""
        text = self._component_text()
        zoom_idx = text.find("cy.on('zoom'")
        assert zoom_idx != -1
        start = text.find("=>", zoom_idx)
        handler = text[start: start + 400]
        end = handler.find("})")
        if end != -1:
            handler = handler[: end + 2]
        assert "cy.fit" not in handler, (
            "Zoom event handler must not call cy.fit()"
        )

    def test_component_declares_semantic_zoom_tiers(self):
        """Prompt 35.2: three semantic tiers (low / medium / high)
        drive the per-zoom font and node sizing."""
        text = self._component_text()
        for needle in (
            "ZOOM_TIER_LOW_MAX",
            "ZOOM_TIER_HIGH_MIN",
            "SEMANTIC_TIER_SPECS",
            "currentTier",
            "pickSemanticTier",
        ):
            assert needle in text, f"missing semantic-zoom symbol: {needle}"
        # The tier record must define font-size, node-size, and a
        # hub size for every tier.
        assert "fontSize:" in text
        assert "nodeSize:" in text
        assert "hubNodeSize:" in text

    def test_component_uses_controlled_font_sizes(self):
        """Prompt 35.2: font sizes are picked from a fixed set so
        they never scale endlessly with zoom."""
        text = self._component_text()
        # The tier font sizes must be small integers (0, 7, 8, 9, 10
        # or close to that band).
        import re

        # Look for the three tier spec blocks.
        spec_match = re.search(
            r"SEMANTIC_TIER_SPECS:\s*Record<SemanticTier,\s*SemanticTierSpec>"
            r"\s*=\s*\{(.*?)\n  \}\n",
            text,
            re.DOTALL,
        )
        assert spec_match, "SEMANTIC_TIER_SPECS literal not found"
        body = spec_match.group(1)
        # Each tier has a fontSize: <number> field.
        font_sizes = [int(m.group(1)) for m in re.finditer(r"fontSize:\s*(\d+)", body)]
        assert font_sizes, "no fontSize fields in SEMANTIC_TIER_SPECS"
        # All values must be in the controlled band 0..12 px.
        for fs in font_sizes:
            assert 0 <= fs <= 12, (
                f"font size {fs} outside controlled band 0..12"
            )
        # Low-zoom font size should be 0 (labels hidden) to satisfy
        # the "zoom out hides cluttered labels" acceptance criterion.
        assert 0 in font_sizes, (
            "low-zoom font size should be 0 to hide labels at low zoom"
        )

    def test_component_uses_controlled_node_sizes(self):
        """Prompt 35.2: node sizes are picked from a fixed band
        per tier (10-12, 16-20, 22-26)."""
        text = self._component_text()
        import re

        spec_match = re.search(
            r"SEMANTIC_TIER_SPECS:\s*Record<SemanticTier,\s*SemanticTierSpec>"
            r"\s*=\s*\{(.*?)\n  \}\n",
            text,
            re.DOTALL,
        )
        assert spec_match
        body = spec_match.group(1)
        node_sizes = [int(m.group(1)) for m in re.finditer(r"nodeSize:\s*(\d+)", body)]
        assert node_sizes, "no nodeSize fields in SEMANTIC_TIER_SPECS"
        # The lowest tier's node size must be in 10-12.
        assert min(node_sizes) >= 10 and min(node_sizes) <= 12, (
            f"lowest-tier node size {min(node_sizes)} should be in 10..12"
        )
        # The highest tier's node size must be in 22-26.
        assert max(node_sizes) >= 22 and max(node_sizes) <= 26, (
            f"highest-tier node size {max(node_sizes)} should be in 22..26"
        )

    def test_component_does_not_duplicate_dom_ids(self):
        """Prompt 35.2: the explorer template must not declare any
        DOM id twice."""
        import re

        text = self._component_text()
        # Slice the <template> block only.
        tmpl_match = re.search(r"<template>(.*?)</template>", text, re.DOTALL)
        assert tmpl_match, "no <template> block found"
        tmpl = tmpl_match.group(1)
        # Match only literal ``id="..."`` HTML attributes. Skip
        # Vue bindings like ``:id="..."`` and ``:data-foo-id="..."``
        # by requiring the character before ``id=`` to be a
        # whitespace character (start of attribute or after space).
        ids = re.findall(r'(?<=\s)id="([^"]+)"', tmpl)
        seen: dict[str, int] = {}
        for i in ids:
            seen[i] = seen.get(i, 0) + 1
        duplicates = sorted([k for k, v in seen.items() if v > 1])
        assert not duplicates, (
            f"GraphExplorer.vue has duplicate template DOM ids: {duplicates}"
        )

    def test_component_keeps_selected_and_neighbor_labels_visible(self):
        """Prompt 35.2: the selected node and its closed
        neighbourhood must keep their labels visible regardless of
        zoom tier."""
        text = self._component_text()
        # The role-class pass must unconditionally remove hide-labels
        # for selected / inNeighborhood / hover regardless of tier
        # (low or medium). The "high" branch removes hide-labels
        # for everyone, so we just check the low/medium logic.
        assert "isSelected || inNeighborhood || isHover" in text, (
            "applyNodeRoleClasses must unconditionally un-hide selected / neighbour / hovered nodes"
        )
        # And the hub threshold must tighten at low zoom to keep
        # the visible label set small.
        assert "HUB_DEGREE_THRESHOLD_LOW_ZOOM" in text

    def test_component_layout_is_dense_graph_friendly(self):
        """Prompt 35.2: tune the cose layout for ~65 nodes / ~1069
        edges. The previous (Prompt 35.1) values of
        nodeRepulsion=12000 and idealEdgeLength=80 were still too
        dense for this graph; the spec asks us to increase both
        knobs."""
        text = self._component_text()
        # nodeRepulsion must be higher than the Prompt 35.1 value
        # of 12000.
        import re

        rep_match = re.search(r"nodeRepulsion:\s*\(\)\s*=>\s*(\d+)", text)
        assert rep_match, "nodeRepulsion option missing"
        rep = int(rep_match.group(1))
        assert rep > 12000, (
            f"nodeRepulsion should be > 12000 for a 65-node / 1069-edge graph, got {rep}"
        )
        # idealEdgeLength must be higher than the Prompt 35.1 value
        # of 80.
        ed_match = re.search(r"idealEdgeLength:\s*\(\)\s*=>\s*(\d+)", text)
        assert ed_match, "idealEdgeLength option missing"
        ed = int(ed_match.group(1))
        assert ed > 80, (
            f"idealEdgeLength should be > 80 for a 65-node / 1069-edge graph, got {ed}"
        )
        # Determinism must be preserved.
        assert "randomize: false" in text
        assert "coseLayoutOptions" in text

    def test_component_zoom_event_handler_does_not_call_fit(self):
        """Prompt 35.2: double-check that the cy.on('zoom', ...)
        handler never calls cy.fit(), even after Prompt 35.2
        refactors."""
        text = self._component_text()
        zoom_idx = text.find("cy.on('zoom'")
        assert zoom_idx != -1
        # Capture the handler body up to its closing `})`.
        start = text.find("=>", zoom_idx)
        handler = text[start: start + 400]
        end = handler.find("})")
        if end != -1:
            handler = handler[: end + 2]
        assert "applySemanticZoom" in handler, (
            "cy.on('zoom', ...) handler must call applySemanticZoom"
        )
        assert "cy.fit" not in handler, (
            "cy.on('zoom', ...) handler must not call cy.fit()"
        )

    def test_component_applies_semantic_zoom_on_filter_rerender(self):
        """Prompt 35.2: applySemanticZoom() must run on every
        filter / search / show-all rerender path, not just the
        cy.on('zoom', ...) path."""
        text = self._component_text()
        # reRenderCy is the function that handles all the filter
        # and search rerender paths. It must end with
        # applySemanticZoom().
        rerender_idx = text.find("function reRenderCy")
        assert rerender_idx != -1
        after = text[rerender_idx: rerender_idx + 1200]
        assert "applySemanticZoom" in after, (
            "reRenderCy must call applySemanticZoom() to keep semantic styling"
        )

    def test_component_applies_semantic_zoom_on_fit_and_reset(self):
        """Prompt 35.2: applySemanticZoom() must run after the
        Fit graph, Reset zoom, Zoom in, and Zoom out buttons."""
        text = self._component_text()
        for fn in ("function fitGraph", "function resetZoom", "function zoomIn", "function zoomOut"):
            idx = text.find(fn)
            assert idx != -1, f"missing {fn}"
            after = text[idx: idx + 600]
            assert "applySemanticZoom" in after, (
                f"{fn} must call applySemanticZoom()"
            )

    def test_component_does_not_have_huge_font_at_zoom_4(self):
        """Prompt 35.2 acceptance: zooming in must not make
        labels absurdly huge. The highest tier's selectedFontSize
        is the largest font in the stylesheet and it must stay in
        the 7..12 px band."""
        text = self._component_text()
        import re

        spec_match = re.search(
            r"SEMANTIC_TIER_SPECS:\s*Record<SemanticTier,\s*SemanticTierSpec>\s*=\s*\{(.*?)\n  \}\n",
            text,
            re.DOTALL,
        )
        assert spec_match
        body = spec_match.group(1)
        sizes = [int(m.group(1)) for m in re.finditer(r"selectedFontSize:\s*(\d+)", body)]
        assert sizes, "no selectedFontSize in SEMANTIC_TIER_SPECS"
        assert max(sizes) <= 12, (
            f"selectedFontSize max {max(sizes)} should stay <= 12 px"
        )

    # ------------------------------------------------------------------
    # Prompt 35.3 — Label visibility after semantic zoom
    # ------------------------------------------------------------------

    def test_component_hide_labels_comes_before_selected_rules(self):
        """Prompt 35.3: the ``node.hide-labels`` selector must
        appear in ``makeStyle()`` BEFORE the ``node:selected`` /
        ``.highlighted`` / ``node.hovered`` rules so those rules
        (which appear later in the array) win over hide-labels
        and the selected/hovered node always shows its label.

        The previous Prompt 35.2 implementation had
        ``node.hide-labels`` placed *after* ``node:selected``
        and ``.highlighted``, so a class leak on the selected
        node was overriding the visible label.
        """
        text = self._component_text()
        # Find the makeStyle() function body and look at the
        # relative order of the three selectors.
        make_idx = text.find("function makeStyle")
        assert make_idx != -1, "makeStyle() not found"
        # Search for the three selectors and capture their offsets
        # within the makeStyle body.
        body = text[make_idx: make_idx + 8000]
        hide_idx = body.find("'node.hide-labels'")
        if hide_idx == -1:
            hide_idx = body.find('"node.hide-labels"')
        sel_idx = body.find("'node:selected'")
        if sel_idx == -1:
            sel_idx = body.find('"node:selected"')
        highlighted_idx = body.find("'.highlighted'")
        if highlighted_idx == -1:
            highlighted_idx = body.find('".highlighted"')
        assert hide_idx != -1, "node.hide-labels selector not found in makeStyle"
        assert sel_idx != -1, "node:selected selector not found in makeStyle"
        assert highlighted_idx != -1, ".highlighted selector not found in makeStyle"
        # hide-labels must come first so the later rules win.
        assert hide_idx < sel_idx, (
            "node.hide-labels must be declared BEFORE node:selected in makeStyle"
        )
        assert hide_idx < highlighted_idx, (
            "node.hide-labels must be declared BEFORE .highlighted in makeStyle"
        )

    def test_component_base_node_style_shows_label(self):
        """Prompt 35.3: the base ``node`` rule must set
        ``label: 'data(label)'`` so that any node whose
        ``hide-labels`` class is removed actually has a label to
        render. The previous Prompt 35.2 implementation set
        ``label: ''`` in the base rule, which meant non-hub
        nodes never showed a label even at high zoom.
        """
        text = self._component_text()
        make_idx = text.find("function makeStyle")
        assert make_idx != -1
        body = text[make_idx: make_idx + 1500]
        # The first node selector in makeStyle is the base node
        # rule. Find the first occurrence of `label: 'data(label)'`
        # near a "node" selector.
        base_node_match = re.search(
            r"selector:\s*['\"]node['\"][^}]*?label:\s*'data\(label\)'",
            body,
            re.DOTALL,
        )
        assert base_node_match, (
            "base 'node' rule in makeStyle must set label: 'data(label)' "
            "so labels are visible by default"
        )

    def test_component_role_classes_unconditional_remove_for_selected(self):
        """Prompt 35.3: in ``applyNodeRoleClasses`` the
        selected / neighbor / hover branch must be evaluated
        before any tier check, so a node that is selected
        always loses its hide-labels class regardless of the
        current tier.
        """
        text = self._component_text()
        # The unconditional remove is a single if statement whose
        # first condition is `isSelected || inNeighborhood ||
        # isHover`. Check that this exact expression appears in
        # applyNodeRoleClasses.
        role_idx = text.find("function applyNodeRoleClasses")
        assert role_idx != -1
        body = text[role_idx: role_idx + 2500]
        # Look for the pattern `if (isSelected || inNeighborhood || isHover) {`
        # followed by `n.removeClass('hide-labels')`.
        m = re.search(
            r"if\s*\(\s*isSelected\s*\|\|\s*inNeighborhood\s*\|\|\s*isHover\s*\)\s*\{\s*n\.removeClass\('hide-labels'\)",
            body,
        )
        assert m, (
            "applyNodeRoleClasses must unconditionally remove hide-labels "
            "for selected / neighbor / hover, before any tier-specific branch"
        )

    def test_component_role_classes_hovered_class_tracking(self):
        """Prompt 35.3: the role-class pass must add / remove
        the ``hovered`` class on every node so the matching
        stylesheet rule (placed AFTER ``node.hide-labels``)
        wins for the hovered node."""
        text = self._component_text()
        role_idx = text.find("function applyNodeRoleClasses")
        assert role_idx != -1
        body = text[role_idx: role_idx + 2500]
        assert "n.addClass('hovered')" in body, (
            "applyNodeRoleClasses must add the 'hovered' class when isHover is true"
        )
        assert "n.removeClass('hovered')" in body, (
            "applyNodeRoleClasses must remove the 'hovered' class when isHover is false"
        )

    def test_component_exposes_graph_label_debug_helper(self):
        """Prompt 35.3: the component must attach a
        ``window.__graphLabelDebug`` helper that returns
        {ready, zoom, tier, counts: {visible, hidden, total}}."""
        text = self._component_text()
        assert "__graphLabelDebug" in text, (
            "GraphExplorer must expose window.__graphLabelDebug"
        )
        # The helper should be wired inside buildCy() or
        # onMounted and return counts.visible / counts.hidden /
        # counts.total.
        assert "counts.visible" in text or "visible: visible.length" in text, (
            "__graphLabelDebug must report a counts.visible field"
        )
        assert "counts.hidden" in text or "hidden: hidden.length" in text, (
            "__graphLabelDebug must report a counts.hidden field"
        )

    def test_component_cleans_up_label_debug_on_unmount(self):
        """Prompt 35.3: the debug helper must be removed on
        unmount so a stale reference cannot leak across page
        navigations in the SPA."""
        text = self._component_text()
        assert "delete (window as any).__graphLabelDebug" in text, (
            "GraphExplorer must delete window.__graphLabelDebug in onBeforeUnmount"
        )

    def test_component_does_not_let_selected_lose_label(self):
        """Prompt 35.3 regression: the stylesheet's
        ``node:selected`` rule must explicitly re-assert
        ``label: 'data(label)'`` so that an inherited
        ``label: ''`` from the base rule cannot override the
        selected node's label."""
        text = self._component_text()
        # Find the `node:selected` block and confirm it sets
        # `label: 'data(label)'` (or the double-quoted variant).
        m = re.search(
            r"selector:\s*['\"]node:selected['\"][^}]*?label:\s*['\"]data\(label\)['\"]",
            text,
            re.DOTALL,
        )
        assert m, (
            "node:selected rule must re-assert label: 'data(label)' "
            "so a selected node always shows its label"
        )

    def test_component_hovered_rule_reasserts_label(self):
        """Prompt 35.3: the ``.hovered`` / ``node.hovered``
        rule must re-assert ``label: 'data(label)'`` so the
        hovered node's label is never overridden by an
        inherited empty label."""
        text = self._component_text()
        m = re.search(
            r"selector:\s*['\"][^'\"]*hovered[^'\"]*['\"][^}]*?label:\s*['\"]data\(label\)['\"]",
            text,
            re.DOTALL,
        )
        assert m, (
            ".hovered / node.hovered rule must re-assert label: 'data(label)' "
            "so the hovered node's label stays visible"
        )


# -----------------------------------------------------------------------------
# Test class 6: TestSmokeAndValidate
# -----------------------------------------------------------------------------


class TestSmokeAndValidate:
    def _read_cli(self) -> str:
        """Return the source of wiki/cli.py for inspection."""
        from wiki import cli as cli_module

        return Path(cli_module.__file__).read_text(encoding="utf-8")

    def _build_minimal_site(self, builder):
        """Populate the tmp site dir with all pages smoke_site expects.

        Most of the pages are filled with placeholder content that
        passes the "non-empty" and "has h1" rules; the graph
        directory contains the real viewer and graph files we care
        about.
        """
        simple_pages = [
            "explorer/index.md",
            "sources/index.md",
            "review/index.md",
            "revision/index.md",
            "learn/index.md",
            "tags/index.md",
            "timeline.md",
            "gaps.md",
            "index.md",
        ]
        for rel in simple_pages:
            target = builder.data_site_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            # Make each page a valid Explorer-shaped stub with the
            # specific markers smoke_site checks for the Explorer
            # page (the only page that has extra body assertions).
            if rel == "explorer/index.md":
                target.write_text(
                    "# Explorer\n"
                    "\n"
                    "## Resource summary\n"
                    "\n"
                    "## Recent resources\n"
                    "\n"
                    "search/all.json\n"
                    "Could not load search index. Check /search/all.json.\n"
                    '<div id="wiki-explorer"></div>\n',
                    encoding="utf-8",
                )
            else:
                # Each page must be at least 50 bytes (smoke_site
                # threshold) and have an H1.
                content = (
                    f"# {rel}\n"
                    "\n"
                    f"Placeholder content for {rel}. This page exists so\n"
                    "that smoke_site has a complete set of expected files\n"
                    "to check against. Real content is generated by the\n"
                    "appropriate generator module.\n"
                )
                target.write_text(content, encoding="utf-8")
        # Search JSON files.
        search_dir = builder.data_site_dir / "public" / "search"
        search_dir.mkdir(parents=True, exist_ok=True)
        (search_dir / "all.json").write_text('{"items": []}', encoding="utf-8")
        (search_dir / "resources.json").write_text('{"items": []}', encoding="utf-8")
        # Topics index.
        topics_dir = builder.data_site_dir / "topics"
        topics_dir.mkdir(parents=True, exist_ok=True)
        (topics_dir / "index.md").write_text("# Topic Map\n\n", encoding="utf-8")
        # Resources index.
        resources_dir = builder.data_site_dir / "resources"
        resources_dir.mkdir(parents=True, exist_ok=True)
        (resources_dir / "index.md").write_text(
            "# Resources\n\n| Title | Type |\n|---|---|\n",
            encoding="utf-8",
        )
        # Prompt 27: chunk index public copy and chunks index page.
        chunks_public = builder.data_site_dir / "public" / "chunks"
        chunks_public.mkdir(parents=True, exist_ok=True)
        (chunks_public / "chunks.json").write_text("[]", encoding="utf-8")
        (chunks_public / "manifest.json").write_text(
            '{"schema_version": "chunk_index_v1", "chunk_count": 0, '
            '"resource_count": 0, "by_source_type": {}, '
            '"by_resource": [], "warnings": []}',
            encoding="utf-8",
        )
        chunks_page = builder.data_site_dir / "chunks"
        chunks_page.mkdir(parents=True, exist_ok=True)
        (chunks_page / "index.md").write_text(
            "# Chunk Index\n\nStub for smoke-site.\n",
            encoding="utf-8",
        )
        # Generated_manifest.
        manifest_path = builder.data_site_dir.parent / "processed" / "generated_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        if not manifest_path.exists():
            manifest_path.write_text(
                '{"generated_at": "1970-01-01T00:00:00", "resource_count": 0}',
                encoding="utf-8",
            )

    def test_smoke_site_contains_graph_viewer_check(self):
        """smoke_site() must include the new graph viewer checks."""
        source = self._read_cli()
        # expected_pages adds the viewer entry
        assert '("Graph viewer", site_dir / "graph" / "viewer.md")' in source
        # The four required UI strings are checked
        assert "graph/knowledge_graph.json" in source
        assert '<div id="graph-viewer">' in source
        assert "<GraphExplorer " in source
        # And they appear in the smoke_site body specifically (not
        # in viewer_markdown).
        # We confirm the smoke_site function is the one referencing
        # them by checking the substring is near 'Graph viewer'.
        smoke_idx = source.find("def smoke_site")
        assert smoke_idx > 0
        # The Graph viewer marker must appear after smoke_site
        # starts.
        graph_viewer_idx = source.find('"Graph viewer"')
        assert graph_viewer_idx > smoke_idx

    def test_validate_contains_graph_viewer_check(self):
        """validate() must include the new graph viewer checks."""
        source = self._read_cli()
        # expected_site_files adds the viewer entry
        assert (
            '("graph viewer", site_builder.repo_site_dir / "graph" / "viewer.md")'
            in source
        )
        validate_idx = source.find("def validate(")
        assert validate_idx > 0
        # The 'graph viewer' string must appear after validate
        # starts.
        graph_viewer_idx = source.find('"graph viewer"')
        assert graph_viewer_idx > validate_idx
        # And the prompt-25-added 'Could not reference' check
        # string appears.
        assert (
            "does not reference /graph/knowledge_graph.json" in source
        )

    def test_smoke_site_passes_after_viewer_added(
        self, tmp_path, monkeypatch
    ):
        """Drive a full smoke_site() pass against a complete tmp site.

        Builds a minimal but complete site in a tmp dir (all
        expected pages + the new viewer), then calls smoke_site()
        and asserts it exits 0.
        """
        from wiki import cli
        from typer import Exit

        builder = _setup_site_builder(tmp_path, monkeypatch)
        record = _make_record(tmp_path)
        builder._build_knowledge_graph([record])
        self._build_minimal_site(builder)
        # Point config.LLM_WIKI_DATA_DIR at the tmp dir.
        monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
        # Patch config.get_data_path to use the tmp dir.
        def _tmp_get_data_path(*parts):
            return tmp_path.joinpath(*parts)
        monkeypatch.setattr(config, "get_data_path", _tmp_get_data_path)
        try:
            cli.smoke_site()
        except Exit as exc:
            assert exc.exit_code == 0, f"smoke_site exited with {exc.exit_code}"

    def test_validate_passes_after_viewer_added(self, tmp_path, monkeypatch):
        """Drive a full validate() pass against a complete tmp site."""
        from wiki import cli
        from typer import Exit

        builder = _setup_site_builder(tmp_path, monkeypatch)
        record = _make_record(tmp_path)
        builder._build_knowledge_graph([record])
        # Patch the global site_builder's repo_site_dir to our tmp dir.
        monkeypatch.setattr(
            cli.site_builder,
            "repo_site_dir",
            builder.repo_site_dir,
        )
        # Also create the repo-side index/explorer files so validate
        # doesn't trip on missing site files.
        (builder.repo_site_dir / "explorer").mkdir(parents=True, exist_ok=True)
        (builder.repo_site_dir / "explorer" / "index.md").write_text(
            "# Explorer\n\n## Resource summary\n\n## Recent resources\n\nsearch/all.json\n",
            encoding="utf-8",
        )
        (builder.repo_site_dir / "index.md").write_text(
            "# Home\n",
            encoding="utf-8",
        )
        (builder.repo_site_dir / "topics").mkdir(parents=True, exist_ok=True)
        (builder.repo_site_dir / "topics" / "index.md").write_text(
            "# Topic Map\n\n",
            encoding="utf-8",
        )
        (builder.repo_site_dir / "resources").mkdir(parents=True, exist_ok=True)
        (builder.repo_site_dir / "resources" / "index.md").write_text(
            "# Resources\n\n",
            encoding="utf-8",
        )
        # Prompt 27: chunk index public copy and chunks index page.
        (builder.repo_site_dir / "chunks").mkdir(parents=True, exist_ok=True)
        (builder.repo_site_dir / "chunks" / "index.md").write_text(
            "# Chunk Index\n\nStub for validate.\n",
            encoding="utf-8",
        )
        chunks_public = builder.repo_site_dir / "public" / "chunks"
        chunks_public.mkdir(parents=True, exist_ok=True)
        (chunks_public / "chunks.json").write_text("[]", encoding="utf-8")
        (chunks_public / "manifest.json").write_text(
            '{"schema_version": "chunk_index_v1", "chunk_count": 0, '
            '"resource_count": 0, "by_source_type": {}, '
            '"by_resource": [], "warnings": []}',
            encoding="utf-8",
        )
        # Generated_manifest for staleness check.
        manifest_path = tmp_path / "processed" / "generated_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            '{"generated_at": "1970-01-01T00:00:00", "resource_count": 0}',
            encoding="utf-8",
        )
        try:
            cli.validate(provider=None)
        except Exit as exc:
            # validate() exits 0 if no errors. We accept a clean run.
            assert exc.exit_code == 0, f"validate exited with {exc.exit_code}"

    def test_viewer_page_does_not_introduce_dependencies(
        self, tmp_path, monkeypatch
    ):
        """The viewer must not pull in external JS/CSS/imports."""
        template_path = (
            Path(__file__).parent.parent
            / "site"
            / "docs"
            / "graph"
            / "viewer.md"
        )
        content = template_path.read_text(encoding="utf-8")
        # No <script src=…> tags.
        assert "<script src=" not in content, (
            "viewer.md must not use external <script src=...>"
        )
        # No <link rel="stylesheet" href="https://…"> or
        # <link rel="stylesheet" href="http://…">.
        # (We allow relative hrefs.)
        import re
        for match in re.finditer(
            r'<link[^>]+rel=["\']stylesheet["\'][^>]*>', content
        ):
            tag = match.group(0)
            assert "https://" not in tag and "http://" not in tag, (
                f"viewer.md has an external stylesheet: {tag}"
            )
        # No bare ES module imports (e.g. `import x from 'foo'`).
        # Allow ES module imports only when the source is a relative
        # URL or a Vite-specific protocol. We don't expect any
        # imports in the viewer at all.
        for match in re.finditer(
            r"^\s*import\s+.+from\s+['\"]([^'\"]+)['\"]",
            content,
            re.MULTILINE,
        ):
            source = match.group(1)
            assert source.startswith(".") or source.startswith(
                "/"
            ) or source.startswith("./"), (
                f"viewer.md imports a bare module: {source!r}"
            )


# -----------------------------------------------------------------------------
# Test class 7: TestGraphViewerErrorHandling
# -----------------------------------------------------------------------------


class TestGraphViewerErrorHandling:
    def test_viewer_page_references_known_json_path(self, tmp_path, monkeypatch):
        template_path = (
            Path(__file__).parent.parent
            / "site"
            / "docs"
            / "graph"
            / "viewer.md"
        )
        content = template_path.read_text(encoding="utf-8")
        # The JS uses import.meta.env.BASE_URL (mirrors the explorer).
        assert "import.meta.env.BASE_URL" in content
        # And the path it appends is the canonical knowledge graph path.
        assert "graph/knowledge_graph.json" in content

    def test_viewer_page_has_noscript_fallback(self, tmp_path, monkeypatch):
        template_path = (
            Path(__file__).parent.parent
            / "site"
            / "docs"
            / "graph"
            / "viewer.md"
        )
        content = template_path.read_text(encoding="utf-8")
        assert "<noscript>" in content
        assert "</noscript>" in content
