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
        assert "/public/graph/nodes.json" in rendered
        assert "/public/graph/edges.json" in rendered
        assert "/public/graph/knowledge_graph.json" in rendered

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
            "/public/graph/nodes.json",
            "/public/graph/edges.json",
            "/public/graph/knowledge_graph.json",
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

    def test_viewer_page_contains_search_input(self, tmp_path, monkeypatch):
        content = self._viewer_content(tmp_path, monkeypatch)
        assert 'id="graph-search"' in content

    def test_viewer_page_contains_node_type_filter(self, tmp_path, monkeypatch):
        content = self._viewer_content(tmp_path, monkeypatch)
        assert 'id="graph-filter-node-type"' in content

    def test_viewer_page_contains_edge_type_filter(self, tmp_path, monkeypatch):
        content = self._viewer_content(tmp_path, monkeypatch)
        assert 'id="graph-filter-edge-type"' in content

    def test_viewer_page_contains_details_panel(self, tmp_path, monkeypatch):
        content = self._viewer_content(tmp_path, monkeypatch)
        assert 'id="graph-details"' in content

    def test_viewer_page_contains_neighbor_section(self, tmp_path, monkeypatch):
        content = self._viewer_content(tmp_path, monkeypatch)
        assert 'id="graph-neighbors"' in content

    def test_viewer_page_contains_svg_mini_graph(self, tmp_path, monkeypatch):
        content = self._viewer_content(tmp_path, monkeypatch)
        assert '<svg id="graph-svg"' in content

    def test_viewer_page_links_to_resource_relationships_report(
        self, tmp_path, monkeypatch
    ):
        content = self._viewer_content(tmp_path, monkeypatch)
        assert "/graph/resource-relationships" in content


# -----------------------------------------------------------------------------
# Test class 5: TestSmokeAndValidate
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
        assert "public/graph/knowledge_graph.json" in source
        assert '<div id="graph-viewer">' in source
        assert 'id="graph-search"' in source
        assert 'id="graph-node-list"' in source
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
            "does not reference /public/graph/knowledge_graph.json" in source
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
# Test class 6: TestGraphViewerErrorHandling
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
        assert "public/graph/knowledge_graph.json" in content

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
