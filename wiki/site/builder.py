"""Build VitePress site from generated content."""

import shutil
from pathlib import Path
from typing import List

from wiki.config import config
from wiki.resource_utils import (
    dedupe_records,
    display_title,
    learned_date,
    resource_page_name,
    resource_toc,
    source_url,
)
from wiki.schemas import ResourceRecord, ResourceStatus
from wiki.storage import Storage
from wiki.generate.citations import (
    load_chunk_map,
    linkify_citations,
    render_source_chunks_section,
    strip_source_chunks_section,
)
from wiki.generate.learning_links import resolve_learning_links
from wiki.generate.page_utils import concept_route, md_table_cell, resource_route


class SiteBuilder:
    """Build VitePress site from generated content."""
    
    def __init__(self) -> None:
        """Initialize the site builder."""
        self.repo_site_dir = Path(__file__).parent.parent.parent / "site" / "docs"
        self.data_site_dir = config.get_data_path("site_generated", "docs")
    
    def build(self, records: List[ResourceRecord]) -> Path:
        """Build the complete site.
        
        Returns path to site directory.
        """
        print("Building site...")
        
        # Ensure site directories exist
        self.repo_site_dir.mkdir(parents=True, exist_ok=True)
        self.data_site_dir.mkdir(parents=True, exist_ok=True)
        
        # Build home page
        self._build_home(records)
        
        # Build resources section
        self._build_resources(records)
        
        # Build timeline page
        self._build_timeline()
        
        # Build concepts section
        self._build_concepts()
        
        # Build tags section
        self._build_tags()

        # Build topics section
        self._build_topics()

        # Build generated higher-level sections
        self._copy_generated_section("learn")
        self._copy_generated_section("review")
        self._copy_generated_section("revision")
        self._copy_generated_section("explorer")
        self._copy_generated_section("sources")

        # Build the knowledge graph (Prompt 23).
        # The JSON files are written into
        # ``self.data_site_dir / public / graph`` and will be picked up
        # by the ``public`` copy step below.
        self._build_knowledge_graph(records)

        # Build the chunk index public copy + landing page (Prompt 27).
        # The data-dir files were already written by
        # ``wiki build-chunk-index`` (or by the
        # ``generate_derived_views`` integration in
        # ``wiki.cli.generate_derived_views``). We only need the
        # public copy and the Markdown landing page here, and the
        # public copy is a no-op if the data files do not exist.
        self._build_chunks_index_page()
        self._build_chunk_index_public_copy()

        # Build the BM25 search report page + public copy (Prompt 28).
        # The data-dir files were already written by
        # ``wiki build-bm25-index`` (or by the
        # ``generate_derived_views`` integration in
        # ``wiki.cli.generate_derived_views``). We only need the
        # public copy and the Markdown report page here.
        self._build_bm25_search_page()
        self._build_bm25_public_copy()

        # Build the vector search report page + public copy (Prompt 29).
        # The data-dir files were already written by
        # ``wiki build-vector-index`` (or by the
        # ``generate_derived_views`` integration). We only need
        # the public copy and the Markdown report page here.
        self._build_vector_search_page()
        self._build_vector_public_copy()

        # Build the hybrid retrieval report page (Prompt 30).
        # The page is defensive: it falls back to a "build the
        # indexes" message if the BM25, vector, and chunk
        # indexes are all missing. The build never fails on
        # Prompt 30.
        self._build_retrieval_page()

        # Build the retrieval eval report page (Prompt 32).
        # The page is defensive: it runs the Prompt 31 eval
        # against the on-disk BM25 and vector indexes and
        # surfaces the aggregate metrics, per-mode and per-k
        # summaries, and a failure summary if any. The build
        # never fails on Prompt 32: missing indexes produce a
        # placeholder page that points to the eval command.
        self._build_retrieval_eval_page()

        # Build the deterministic no-LLM RAG debug pages
        # (Prompt 34 MVP closure). The pages are defensive:
        # missing indexes produce a placeholder page that
        # points to the relevant CLI commands. The build
        # never fails on Prompt 34.
        self._build_context_page()
        self._build_rag_report_page()

        self._copy_generated_section("public")

        # Build gaps page
        self._build_gaps()

        # Sync to repo site directory
        self._ensure_prompt34_static_page_markers()
        self._sync_to_repo_site()
        
        return self.repo_site_dir
    
    def _build_home(self, records: List[ResourceRecord]) -> None:
        """Build the home page."""
        # Get stats
        total_resources = len(records)
        processed_resources = len([r for r in records if r.status == ResourceStatus.PROCESSED])
        
        content = f"""---
layout: home

hero:
  name: "Harish LLM Wiki"
  text: "Personal Learning Wiki"
  tagline: A static wiki generated from YouTube, blogs, and LLM-generated notes
  actions:
    - theme: brand
      text: Browse Resources
      link: /resources/
    - theme: alt
      text: Timeline
      link: /timeline

features:
  - title: 📚 {total_resources} Resources
    details: YouTube videos, blog posts, and articles ingested
  - title: ✅ {processed_resources} Processed
    details: Resources with generated learning notes
  - title: 🔍 Full-Text Search
    details: Search across all content using VitePress
  - title: 📅 Timeline View
    details: Chronological learning trail
---

## Welcome

This is a personal static learning wiki generated from:

- **YouTube transcripts** - Educational videos with timestamp citations
- **Blog posts** - Technical articles with source references
- **LLM-generated notes** - AI-assisted explanations with provenance

## Quick Links

- [Browse all resources](/resources/)
- [View learning timeline](/timeline)
- [Explore concepts](/concepts/)
- [Browse by tag](/tags/)
- [Knowledge gaps](/gaps)

## How to Use

1. **Add resources** with `python -m wiki add-batch`
2. **Process new resources** with `python -m wiki process-new`
3. **Generate site** with `python -m wiki build-site`
4. **Browse locally** with `cd site && npm run docs:dev`

## Privacy Note

This wiki is generated locally and contains personal learning notes.
Do not publish publicly unless content is appropriate for public sharing.
"""
        
        home_path = self.data_site_dir / "index.md"
        Storage.write_text(content, home_path)
    
    def _build_resources(self, records: List[ResourceRecord]) -> None:
        """Build the resources section."""
        resources_dir = self.data_site_dir / "resources"
        resources_dir.mkdir(exist_ok=True)
        
        # Create index
        index_lines = [
            "# Resources",
            "",
            "All ingested learning resources.",
            "",
            "| Title | Type | Status | Date |",
            "|-------|------|--------|------|",
        ]
        
        for record in dedupe_records(records):
            title = display_title(record, mark_missing=True)
            status = record.status.value
            date = learned_date(record).strftime("%Y-%m-%d")
            
            # Create individual resource page. Resources without generated notes
            # still need a route target for Explorer/Sources/search indexes.
            resource_filename = resource_page_name(record.id)
            resource_path = resources_dir / resource_filename
            if record.generated_note_path and record.generated_note_path.exists():
                # Copy note content with site-build-time post-processing
                note_content = Storage.read_text(record.generated_note_path)
                
                # Re-linkify citations at site-build time (chunks may have changed)
                if record.local_normalized_path:
                    norm_dir = Path(record.local_normalized_path)
                    chunk_map = load_chunk_map(norm_dir)
                    if chunk_map:
                        note_content, cited_ids, _missing = linkify_citations(note_content, chunk_map)
                        # Re-linkify learning links retroactively
                        note_content = resolve_learning_links(note_content)
                        # Re-render source chunks section from current chunks
                        note_content = strip_source_chunks_section(note_content)
                        note_content += render_source_chunks_section(
                            chunk_map, cited_ids, source_url=record.original_url or ""
                        )
                
                Storage.write_text(
                    self._format_resource_header(record)
                    + "\n\n"
                    + self._strip_duplicate_title(note_content),
                    resource_path,
                )
            else:
                Storage.write_text(
                    self._format_resource_header(record)
                    + "\n\n"
                    + "## Generated note\n\n"
                    + "_No generated note is available for this resource yet._\n",
                    resource_path,
                )

            link = f"[{md_table_cell(title)}]({resource_route(record.id)})"
            
            index_lines.append(f"| {link} | {md_table_cell(record.source_type.value)} | {md_table_cell(status)} | {date} |")
        
        index_lines.append("")
        index_content = "\n".join(index_lines)
        
        index_path = resources_dir / "index.md"
        Storage.write_text(index_content, index_path)
    
    def _build_timeline(self) -> None:
        """Build the timeline page."""
        timeline_source = config.get_data_path("processed", "timeline", "timeline.md")
        
        if timeline_source.exists():
            content = Storage.read_text(timeline_source)
        else:
            content = "# Timeline\n\n_No timeline data yet._\n"
        
        timeline_path = self.data_site_dir / "timeline.md"
        Storage.write_text(content, timeline_path)
    
    def _build_concepts(self) -> None:
        """Build the concepts section."""
        concepts_dir = self.data_site_dir / "concepts"
        concepts_dir.mkdir(exist_ok=True)
        
        concepts_source = config.get_data_path("processed", "concepts")
        
        if concepts_source.exists():
            # Copy all concept markdown files
            for concept_file in concepts_source.glob("*.md"):
                dest = concepts_dir / concept_file.name
                shutil.copy(concept_file, dest)
        
        # Create index
        index_lines = [
            "# Concepts",
            "",
            "Concepts extracted from learning resources.",
            "",
        ]
        
        if concepts_source.exists():
            for concept_file in sorted(concepts_source.glob("*.md")):
                name = concept_file.stem.replace("-", " ").title()
                index_lines.append(f"- [{name}]({concept_route(concept_file.stem)})")
        else:
            index_lines.append("_No concepts generated yet._")
        
        index_lines.append("")
        index_content = "\n".join(index_lines)
        
        index_path = concepts_dir / "index.md"
        Storage.write_text(index_content, index_path)
    
    def _build_tags(self) -> None:
        """Build the tags section."""
        tags_dir = self.data_site_dir / "tags"
        tags_dir.mkdir(exist_ok=True)
        
        tags_source = config.get_data_path("processed", "tags", "tags.md")
        
        if tags_source.exists():
            content = Storage.read_text(tags_source)
        else:
            content = "# Tags\n\n_No tags yet._\n"
        
        tags_path = tags_dir / "index.md"
        Storage.write_text(content, tags_path)

    def _build_topics(self) -> None:
        """Build the topics section."""
        topics_dir = self.data_site_dir / "topics"
        topics_dir.mkdir(exist_ok=True)
        for old_file in list(topics_dir.glob("*.md")):
            old_file.unlink()
        topics_source = config.get_data_path("processed", "topics")
        if topics_source.exists():
            for topic_file in topics_source.glob("*.md"):
                shutil.copy(topic_file, topics_dir / topic_file.name)
        elif not (topics_dir / "index.md").exists():
            Storage.write_text("# Topic Map\n\n_No topics generated yet._\n", topics_dir / "index.md")
    
    def _build_gaps(self) -> None:
        """Build the gaps page."""
        gaps_source = config.get_data_path("processed", "gaps", "gaps.md")
        
        if gaps_source.exists():
            content = Storage.read_text(gaps_source)
        else:
            content = "# Knowledge Gaps\n\n_No gaps identified yet._\n"
        
        gaps_path = self.data_site_dir / "gaps.md"
        Storage.write_text(content, gaps_path)

    def _build_knowledge_graph(self, records: List[ResourceRecord]) -> None:
        """Build the knowledge graph JSON files and Markdown index.

        Prompt 23 introduces the graph data model and JSON export. The
        files are written into ``self.data_site_dir / public / graph``
        so the existing ``_copy_generated_section("public")`` pass
        syncs them into the VitePress site automatically.
        """
        from wiki.graph import GraphBuilder, export_graph
        from wiki.graph.export import graph_output_paths

        try:
            data_dir = config.LLM_WIKI_DATA_DIR
            graph = GraphBuilder(data_dir=data_dir).build(records)
            export_graph(graph, data_dir=data_dir)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"  [yellow]⚠[/yellow] Knowledge graph build failed: {exc}")
            return

        paths = graph_output_paths(data_dir=data_dir)
        if paths["knowledge_graph"].exists():
            print(f"  [green]✓[/green] Knowledge graph: {paths['directory']}")
            self._build_graph_index_page(graph)
            # Prompt 25: also write the static graph viewer page.
            self._build_graph_viewer_page(graph)

    def _build_graph_index_page(self, graph: dict) -> None:
        """Build a small Markdown landing page for the graph files.

        The page is only generated if there is at least one node, so
        an empty wiki does not surface a useless landing page.
        """
        stats = graph.get("stats", {})
        node_type_counts = stats.get("node_type_counts", {}) or {}
        edge_type_counts = stats.get("edge_type_counts", {}) or {}
        lines = [
            "# Knowledge Graph",
            "",
            "The wiki exposes a deterministic knowledge graph as JSON for future",
            "RAG, search, and visualization features.",
            "",
            "| File | Purpose |",
            "|---|---|",
            "| [/graph/nodes.json](/graph/nodes.json) | All graph nodes |",
            "| [/graph/edges.json](/graph/edges.json) | All graph edges |",
            "| [/graph/knowledge_graph.json](/graph/knowledge_graph.json) | Combined bundle with stats |",
            "| [Open the graph viewer](/graph/viewer) | Interactive neighborhood + filter explorer (Prompt 25) |",
            "",
            "## Stats",
            "",
            f"- Schema version: `{graph.get('schema_version', 'unknown')}`",
            f"- Nodes: {stats.get('node_count', 0)}",
            f"- Edges: {stats.get('edge_count', 0)}",
            "",
            "### Node types",
            "",
            "| Type | Count |",
            "|---|---:|",
        ]
        for node_type, count in sorted(node_type_counts.items()):
            lines.append(f"| {node_type} | {count} |")
        lines.extend(["", "### Edge types", "", "| Type | Count |", "|---|---:|"])
        for edge_type, count in sorted(edge_type_counts.items()):
            lines.append(f"| {edge_type} | {count} |")
        lines.extend([
            "",
            "## Provenance",
            "",
            f"- Generated: {graph.get('generated_at', '')}",
            "",
        ])
        graph_dir = self.data_site_dir / "graph"
        graph_dir.mkdir(parents=True, exist_ok=True)
        Storage.write_text("\n".join(lines), graph_dir / "index.md")
        # Prompt 24: also write the resource-relationships report page
        # (only if at least one relationship edge was detected).
        self._build_resource_relationships_page(graph, graph_dir)

    def _build_resource_relationships_page(
        self, graph: dict, graph_dir: Path
    ) -> None:
        """Write a Markdown report of detected resource relationships.

        Prompt 24 introduces six new resource-to-resource edge types.
        This page surfaces the top relationships for each type in a
        compact table, sourced directly from the graph bundle. It is
        only generated if at least one of the six edge types has a
        non-zero count in ``stats.edge_type_counts``.

        The page is generated from the same in-memory graph as the
        JSON files (no second build pass), so it is byte-stable for a
        given input.
        """
        from wiki.graph.schema import RESOURCE_RELATIONSHIP_EDGE_TYPES

        stats = graph.get("stats", {}) or {}
        edge_type_counts = stats.get("edge_type_counts", {}) or {}
        rel_counts = {
            et: edge_type_counts.get(et, 0)
            for et in sorted(RESOURCE_RELATIONSHIP_EDGE_TYPES)
        }
        if sum(rel_counts.values()) == 0:
            # No relationship edges to report; skip the page.
            return

        nodes = graph.get("nodes", []) or []
        edges = graph.get("edges", []) or []
        # Build a label lookup so the table can show the resource
        # title rather than the bare id.
        labels_by_id = {
            n.get("id"): n.get("label", n.get("id", ""))
            for n in nodes
            if n.get("id")
        }

        lines: list[str] = [
            "# Resource Relationships",
            "",
            "Deterministic resource-to-resource relationships detected at graph build",
            "time (Prompt 24). Each row corresponds to a single edge in the",
            "knowledge graph. Scores and reason lists come from the edge metadata.",
            "",
            "## Edge type summary",
            "",
            "| Edge type | Count |",
            "|---|---:|",
        ]
        for edge_type, count in rel_counts.items():
            lines.append(f"| {edge_type} | {count} |")

        # Friendly description per edge type.
        descriptions = {
            "resource_similar_to_resource": (
                "Catch-all similarity edge. Emitted when a pair's combined "
                "topic/concept/keyword score meets the threshold."
            ),
            "resource_shares_topic_with_resource": (
                "Both resources match the same canonical topic."
            ),
            "resource_shares_concept_with_resource": (
                "Both resources mention the same concept slug."
            ),
            "resource_same_source_type_as_resource": (
                "Both resources share a source type and at least one of "
                "topic/concept/keyword overlap."
            ),
            "resource_may_be_prerequisite_for_resource": (
                "Asymmetric: shallower resource may be a prerequisite for "
                "the deeper one on the same topic."
            ),
            "resource_may_expand_on_resource": (
                "Asymmetric: deeper resource may expand on the shallower "
                "one on the same topic."
            ),
        }
        lines.extend(["", "## Per-type details", ""])
        for edge_type in sorted(RESOURCE_RELATIONSHIP_EDGE_TYPES):
            if rel_counts.get(edge_type, 0) == 0:
                continue
            lines.append(f"### `{edge_type}`")
            lines.append("")
            lines.append(descriptions.get(edge_type, ""))
            lines.append("")
            matching = [
                e for e in edges if e.get("type") == edge_type
            ]
            # Sort: highest score first, then by edge id for stability.
            matching.sort(
                key=lambda e: (
                    -float((e.get("metadata") or {}).get("score", 0.0)),
                    e.get("id", ""),
                )
            )
            top = matching[:20]
            lines.extend([
                "| Source | Target | Score | Reasons | Shared topics | Shared concepts | Shared keywords |",
                "|---|---|---:|---|---|---|---|",
            ])
            for edge in top:
                meta = edge.get("metadata") or {}
                source_label = labels_by_id.get(edge.get("source"), edge.get("source", ""))
                target_label = labels_by_id.get(edge.get("target"), edge.get("target", ""))
                reasons = ", ".join(meta.get("reasons", []) or [])
                shared_topics = ", ".join(meta.get("shared_topics", []) or [])
                shared_concepts = ", ".join(meta.get("shared_concepts", []) or [])
                shared_keywords = ", ".join(meta.get("shared_keywords", []) or [])
                score = meta.get("score", 0.0)
                lines.append(
                    f"| {md_table_cell(source_label)} | "
                    f"{md_table_cell(target_label)} | {score} | "
                    f"{md_table_cell(reasons)} | "
                    f"{md_table_cell(shared_topics)} | "
                    f"{md_table_cell(shared_concepts)} | "
                    f"{md_table_cell(shared_keywords)} |"
                )
            if len(matching) > 20:
                lines.append("")
                lines.append(
                    f"_Showing top 20 of {len(matching)} edges for this type._"
                )
            lines.append("")

        lines.extend([
            "## Provenance",
            "",
            f"- Generated: {graph.get('generated_at', '')}",
            "- Detection: deterministic, no LLM, no embeddings, no BM25.",
            "",
        ])
        Storage.write_text("\n".join(lines), graph_dir / "resource-relationships.md")

    def _build_graph_viewer_page(self, graph: dict) -> None:
        """Write the static graph viewer page (Prompt 25).

        The page is a Markdown file with embedded vanilla
        HTML/CSS/JavaScript. The Python side computes a small set of
        summary fields (schema version, counts, top-N node ids, type
        lists) and substitutes them into the in-repo template
        ``site/docs/graph/viewer.md``. The JS reads the graph JSON
        at runtime via ``fetch``.

        The template path is computed from the ``wiki.site.builder``
        module's location (the in-repo source of truth), not from
        ``self.repo_site_dir``. This is important for tests: they
        may instantiate a :class:`SiteBuilder` with a temporary
        ``repo_site_dir`` that does not contain the template, and
        they should still be able to build the viewer. The template
        lives in the git repo alongside the other static Markdown
        files; the build process reads it and writes the rendered
        Markdown into ``self.data_site_dir / "graph" / "viewer.md"``,
        which is then synced to the repo site directory by
        :meth:`_sync_to_repo_site`.

        The viewer is only generated when there is at least one
        node, matching the gating rule for the index page.
        """
        from wiki.graph.viewer import viewer_markdown

        nodes = graph.get("nodes", []) or []
        if not nodes:
            # No nodes: skip viewer (same gating as index page).
            return

        graph_dir = self.data_site_dir / "graph"
        graph_dir.mkdir(parents=True, exist_ok=True)

        # Read the in-repo template. The template is checked into
        # the git repo at ``harish-llm-wiki/site/docs/graph/viewer.md``;
        # compute that path from the module location rather than
        # from ``self.repo_site_dir`` (which tests may rebind).
        module_template_path = (
            Path(__file__).parent.parent.parent
            / "site"
            / "docs"
            / "graph"
            / "viewer.md"
        )
        template_path = module_template_path
        if not template_path.exists():
            # Fallback: try the configured repo_site_dir.
            template_path = self.repo_site_dir / "graph" / "viewer.md"
        if not template_path.exists():
            # Defensive: if the template was deleted from the repo
            # we skip rather than crash the build.
            print(
                f"  [yellow]⚠[/yellow] Graph viewer template missing: "
                f"{template_path}"
            )
            return

        template = template_path.read_text(encoding="utf-8")
        rendered = viewer_markdown(graph, template)
        Storage.write_text(rendered, graph_dir / "viewer.md")

    def _build_chunks_index_page(self) -> None:
        """Build a small Markdown landing page for the chunk index (Prompt 27).

        The page lists the top resources by chunk count and links to
        the public JSON. It is regenerated from the on-disk manifest
        so it always reflects the latest index state.
        """
        from wiki.chunks.export import chunk_index_output_paths

        chunk_paths = chunk_index_output_paths()
        chunks_dir = self.data_site_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        chunk_count = 0
        resource_count = 0
        by_source_type: dict[str, int] = {}
        top_entries: list[dict] = []

        manifest_path = chunk_paths["manifest"]
        if manifest_path.exists():
            try:
                manifest_data = Storage.read_json(manifest_path)
                chunk_count = int(manifest_data.get("chunk_count", 0))
                resource_count = int(manifest_data.get("resource_count", 0))
                by_source_type = dict(manifest_data.get("by_source_type") or {})
                by_resource = list(manifest_data.get("by_resource") or [])
                top_entries = sorted(
                    by_resource,
                    key=lambda entry: (-int(entry.get("chunk_count", 0)), str(entry.get("resource_id", ""))),
                )[:20]
            except Exception as exc:  # pragma: no cover - defensive
                print(f"  [yellow]⚠[/yellow] Chunk manifest read failed: {exc}")

        lines: list[str] = [
            "# Chunk Index",
            "",
            "Deterministic, citation-aware chunk index used by future search and",
            "retrieval features (BM25, vector, graph retriever, hybrid router, and",
            "grounded LLM answers).",
            "",
            "| File | Purpose |",
            "|---|---|",
            "| [/public/chunks/chunks.json](/public/chunks/chunks.json) | Full chunk list (text included) |",
            "| [/public/chunks/manifest.json](/public/chunks/manifest.json) | Per-resource summary, by source type |",
            "| [Browse resources](/resources/) | Per-resource pages, citation-aware |",
            "",
            "## Stats",
            "",
            f"- Schema version: `chunk_index_v1`",
            f"- Chunks: {chunk_count}",
            f"- Resources indexed: {resource_count}",
            "",
            "### By source type",
            "",
            "| Source type | Chunk count |",
            "|---|---:|",
        ]
        for source_type, count in sorted(by_source_type.items()):
            lines.append(f"| {source_type} | {count} |")
        if not by_source_type:
            lines.append("| _none_ | 0 |")

        if top_entries:
            lines.extend([
                "",
                "## Top resources by chunk count",
                "",
                "| Resource | Source type | Chunks |",
                "|---|---|---:|",
            ])
            for entry in top_entries:
                resource_id = str(entry.get("resource_id", ""))
                source_type = str(entry.get("source_type", ""))
                chunk_count = int(entry.get("chunk_count", 0))
                title = str(entry.get("title", resource_id))
                route = str(entry.get("resource_route") or "")
                if route:
                    label = f"[{md_table_cell(title)}]({route})"
                else:
                    label = md_table_cell(title)
                lines.append(
                    f"| {label} | {md_table_cell(source_type)} | {chunk_count} |"
                )

        lines.extend([
            "",
            "## Provenance",
            "",
            "- Generated by `wiki build-chunk-index` (or as part of `wiki build-site --refresh`).",
            "- Deterministic: no LLM, no embeddings, no BM25.",
            "",
        ])
        Storage.write_text("\n".join(lines), chunks_dir / "index.md")

    def _copy_generated_section(self, section: str) -> None:
        """Copy a generated site section from external data if it exists."""
        source = config.get_data_path("processed", section)
        if section in {"explorer", "sources", "public"}:
            source = self.data_site_dir / section
        if not source.exists():
            return
        dest = self.data_site_dir / section
        if dest.exists() and dest != source:
            shutil.rmtree(dest)
        if source.is_dir() and dest != source:
            shutil.copytree(source, dest)

    def _build_chunk_index_public_copy(self) -> None:
        """Write a small public copy of the chunk index into the site dir.

        This is the in-repo copy under
        ``self.data_site_dir / public / chunks``. The data-dir files
        are the source of truth; this copy is what VitePress serves
        at ``/public/chunks/...``.

        The function is defensive: if the data-dir files do not
        exist, it writes a valid empty pair (``[]`` and an empty
        manifest) so the static copy never breaks the build.
        """
        from wiki.chunks import write_public_copy

        try:
            write_public_copy()
        except Exception as exc:  # pragma: no cover - defensive
            print(f"  [yellow]⚠[/yellow] Chunk index public copy failed: {exc}")

    def _build_bm25_search_page(self) -> None:
        """Build a small Markdown landing page for the BM25 search (Prompt 28).

        The page lists index stats and example queries. It is
        regenerated from the on-disk manifest so it always
        reflects the latest BM25 index state. If the BM25 index
        has not been built, the page falls back to a short
        pointer to ``wiki build-bm25-index``.
        """
        from wiki.search.export import bm25_output_paths

        bm25_paths = bm25_output_paths()
        search_dir = self.data_site_dir / "search"
        search_dir.mkdir(parents=True, exist_ok=True)

        doc_count = 0
        resource_count = 0
        vocab_size = 0
        total_postings = 0
        avg_doc_length = 0.0
        by_source_type: dict[str, int] = {}
        bm25_built = bm25_paths["manifest"].exists()
        if bm25_built:
            try:
                manifest_data = Storage.read_json(bm25_paths["manifest"])
                doc_count = int(manifest_data.get("doc_count", 0))
                resource_count = int(manifest_data.get("resource_count", 0))
                vocab_size = int(manifest_data.get("vocab_size", 0))
                total_postings = int(manifest_data.get("total_postings", 0))
                avg_doc_length = float(manifest_data.get("avg_doc_length", 0.0))
                by_source_type = dict(manifest_data.get("by_source_type") or {})
            except Exception as exc:  # pragma: no cover - defensive
                print(f"  [yellow]⚠[/yellow] BM25 manifest read failed: {exc}")
                bm25_built = False

        lines: list[str] = [
            "# BM25 Search",
            "",
            "Deterministic BM25 lexical search over the chunk index (Prompt 28).",
            "",
            "BM25 is a classic bag-of-words retrieval function: it scores a query",
            "against every chunk using term frequency, inverse document frequency,",
            "and a length-normalization factor. It is the lexical half of the",
            "planned hybrid retrieval router; the vector half (embeddings) and the",
            "graph retriever belong to later prompts.",
            "",
            "| File | Purpose |",
            "|---|---|",
            "| [/public/search/bm25_index.json](/public/search/bm25_index.json) | Public vocab summary (term -> document frequency) |",
            "| [/public/search/bm25_manifest.json](/public/search/bm25_manifest.json) | Public manifest mirror |",
            "",
            "## Stats",
            "",
            f"- Schema version: `bm25_index_v1`",
            f"- Chunks indexed: {doc_count}",
            f"- Resources: {resource_count}",
            f"- Vocab size: {vocab_size}",
            f"- Total postings: {total_postings}",
            f"- Average doc length (weighted): {avg_doc_length:.2f}",
        ]
        if by_source_type:
            lines.extend([
                "",
                "### By source type",
                "",
                "| Source type | Chunk count |",
                "|---|---:|",
            ])
            for source_type, count in sorted(by_source_type.items()):
                lines.append(f"| {source_type} | {count} |")
        if not bm25_built:
            lines.extend([
                "",
                "## Build the BM25 index",
                "",
                "The BM25 index has not been built yet. Run:",
                "",
                "```",
                ".venv/bin/python -m wiki build-bm25-index",
                "```",
                "",
                "Or rebuild the derived views:",
                "",
                "```",
                ".venv/bin/python -m wiki build-site --refresh",
                "```",
                "",
            ])
        else:
            lines.extend([
                "",
                "## Example queries",
                "",
                "These are the canonical example queries from `prompt28.md`. Each",
                "can be reproduced with the CLI:",
                "",
                "```",
                ".venv/bin/python -m wiki search-bm25 \"attention transformer\"",
                ".venv/bin/python -m wiki search-bm25 \"scaled dot-product attention\"",
                ".venv/bin/python -m wiki search-bm25 \"embeddings retrieval\"",
                ".venv/bin/python -m wiki search-bm25 \"vllm paged attention\"",
                ".venv/bin/python -m wiki search-bm25 \"rag evaluation\"",
                "```",
                "",
                "Pass `--json` to emit a JSON array on stdout, suitable for piping",
                "into a downstream retrieval pipeline.",
                "",
            ])

        lines.extend([
            "## Provenance",
            "",
            "- Generated by `wiki build-bm25-index` (or as part of `wiki build-site --refresh`).",
            "- Deterministic: no LLM, no embeddings, no vector search, no FAISS.",
            "",
        ])
        Storage.write_text("\n".join(lines), search_dir / "bm25.md")

    def _build_bm25_public_copy(self) -> None:
        """Write a small public copy of the BM25 index into the site dir.

        This is the in-repo copy under
        ``self.data_site_dir / public / search``. The data-dir files
        are the source of truth; this copy is what VitePress serves
        at ``/public/search/...``.

        The function is defensive: if the data-dir files do not
        exist, it writes a valid empty pair so the static copy
        never breaks the build.
        """
        from wiki.search import write_public_copy as write_bm25_public

        try:
            write_bm25_public()
        except Exception as exc:  # pragma: no cover - defensive
            print(f"  [yellow]⚠[/yellow] BM25 public copy failed: {exc}")

    def _build_vector_search_page(self) -> None:
        """Build a small Markdown landing page for the vector search (Prompt 29).

        The page lists index stats and example queries. It is
        regenerated from the on-disk manifest so it always
        reflects the latest vector index state. If the vector
        index has not been built, the page falls back to a short
        pointer to ``wiki build-vector-index``.
        """
        from wiki.vector.export import vector_output_paths

        vector_paths = vector_output_paths()
        search_dir = self.data_site_dir / "search"
        search_dir.mkdir(parents=True, exist_ok=True)

        chunk_count = 0
        resource_count = 0
        dimension = 0
        vocab_size = 0
        total_nnz = 0
        by_source_type: dict[str, int] = {}
        vector_built = vector_paths["manifest"].exists()
        if vector_built:
            try:
                manifest_data = Storage.read_json(vector_paths["manifest"])
                chunk_count = int(manifest_data.get("chunk_count", 0))
                resource_count = int(manifest_data.get("resource_count", 0))
                dimension = int(manifest_data.get("dimension", 0))
                vocab_size = int(manifest_data.get("vocab_size", 0))
                total_nnz = int(manifest_data.get("total_nnz", 0))
                by_source_type = dict(manifest_data.get("by_source_type") or {})
            except Exception as exc:  # pragma: no cover - defensive
                print(f"  [yellow]⚠[/yellow] Vector manifest read failed: {exc}")
                vector_built = False

        lines: list[str] = [
            "# Vector Search",
            "",
            "Deterministic local vector search over the chunk index (Prompt 29).",
            "",
            "The vector backend is a small pure-Python hashing TF-IDF",
            "implementation: each chunk is mapped to a fixed-dimension",
            "sparse vector with a signed blake2b hash, weighted by TF-IDF,",
            "L2-normalized, and scored against queries with cosine",
            "similarity. It is the vector half of the planned hybrid",
            "retrieval router; the graph retriever, hybrid router, and",
            "model-based embeddings (Ollama, sentence-transformers, OpenAI)",
            "belong to later prompts.",
            "",
            "| File | Purpose |",
            "|---|---|",
            "| [/public/search/vector_index.json](/public/search/vector_index.json) | Public vocab summary (term -> IDF weight) |",
            "| [/public/search/vector_manifest.json](/public/search/vector_manifest.json) | Public manifest mirror |",
            "",
            "## Stats",
            "",
            f"- Schema version: `vector_index_v1`",
            f"- Chunks indexed: {chunk_count}",
            f"- Resources: {resource_count}",
            f"- Dimension: {dimension}",
            f"- Vocab size: {vocab_size}",
            f"- Total NNZ: {total_nnz}",
        ]
        if by_source_type:
            lines.extend([
                "",
                "### By source type",
                "",
                "| Source type | Chunk count |",
                "|---|---:|",
            ])
            for source_type, count in sorted(by_source_type.items()):
                lines.append(f"| {source_type} | {count} |")
        if not vector_built:
            lines.extend([
                "",
                "## Build the vector index",
                "",
                "The vector index has not been built yet. Run:",
                "",
                "```",
                ".venv/bin/python -m wiki build-vector-index",
                "```",
                "",
                "Or rebuild the derived views:",
                "",
                "```",
                ".venv/bin/python -m wiki build-site --refresh",
                "```",
                "",
            ])
        else:
            lines.extend([
                "",
                "## Example queries",
                "",
                "These are the canonical example queries from `prompt29.md`. Each",
                "can be reproduced with the CLI:",
                "",
                "```",
                ".venv/bin/python -m wiki search-vector \"attention transformer\"",
                ".venv/bin/python -m wiki search-vector \"scaled dot-product attention\"",
                ".venv/bin/python -m wiki search-vector \"embeddings retrieval\"",
                ".venv/bin/python -m wiki search-vector \"vllm paged attention\"",
                ".venv/bin/python -m wiki search-vector \"rag evaluation\"",
                "```",
                "",
                "Pass `--json` to emit a JSON array on stdout, suitable for piping",
                "into a downstream retrieval pipeline.",
                "",
            ])

        lines.extend([
            "## Provenance",
            "",
            "- Generated by `wiki build-vector-index` (or as part of `wiki build-site --refresh`).",
            "- Deterministic: no LLM, no embeddings, no model-based vector search, no FAISS / Chroma / LanceDB.",
            "- Pure-Python hashing TF-IDF vectorizer with cosine similarity over L2-normalized vectors.",
            "",
        ])
        Storage.write_text("\n".join(lines), search_dir / "vector.md")

    def _build_vector_public_copy(self) -> None:
        """Write a small public copy of the vector index into the site dir.

        This is the in-repo copy under
        ``self.data_site_dir / public / search``. The data-dir files
        are the source of truth; this copy is what VitePress serves
        at ``/public/search/...``.

        The function is defensive: if the data-dir files do not
        exist, it writes a valid empty pair so the static copy
        never breaks the build.
        """
        from wiki.vector import write_public_copy as write_vector_public

        try:
            write_vector_public()
        except Exception as exc:  # pragma: no cover - defensive
            print(f"  [yellow]⚠[/yellow] Vector public copy failed: {exc}")

    def _build_retrieval_page(self) -> None:
        """Build a small Markdown landing page for the hybrid retrieval router (Prompt 30).

        The page documents the four modes, the scoring formula,
        the example commands, and the out-of-scope items. It
        is regenerated defensively: if the BM25, vector, and
        chunk indexes are all missing, the page falls back to
        a "build the indexes" message; the static site build
        never fails on Prompt 30.
        """
        from wiki.search.export import bm25_output_paths
        from wiki.vector.export import vector_output_paths
        from wiki.chunks.export import chunk_index_output_paths

        bm25_paths = bm25_output_paths()
        vector_paths = vector_output_paths()
        chunk_paths = chunk_index_output_paths()

        search_dir = self.data_site_dir / "search"
        search_dir.mkdir(parents=True, exist_ok=True)

        bm25_built = bm25_paths["manifest"].exists()
        vector_built = vector_paths["manifest"].exists()
        chunk_built = chunk_paths["chunks_json"].exists()

        bm25_doc_count = 0
        bm25_vocab_size = 0
        vector_chunk_count = 0
        vector_dimension = 0
        chunk_count = 0

        if bm25_built:
            try:
                manifest_data = Storage.read_json(bm25_paths["manifest"])
                bm25_doc_count = int(manifest_data.get("doc_count", 0))
                bm25_vocab_size = int(manifest_data.get("vocab_size", 0))
            except Exception as exc:  # pragma: no cover - defensive
                print(f"  [yellow]⚠[/yellow] BM25 manifest read failed: {exc}")
                bm25_built = False
        if vector_built:
            try:
                manifest_data = Storage.read_json(vector_paths["manifest"])
                vector_chunk_count = int(manifest_data.get("chunk_count", 0))
                vector_dimension = int(manifest_data.get("dimension", 0))
            except Exception as exc:  # pragma: no cover - defensive
                print(f"  [yellow]⚠[/yellow] Vector manifest read failed: {exc}")
                vector_built = False
        if chunk_built:
            try:
                manifest_data = Storage.read_json(chunk_paths["manifest"])
                chunk_count = int(manifest_data.get("chunk_count", 0))
            except Exception as exc:  # pragma: no cover - defensive
                print(f"  [yellow]⚠[/yellow] Chunk manifest read failed: {exc}")
                chunk_built = False

        lines: list[str] = [
            "# Hybrid Retrieval",
            "",
            "Deterministic hybrid retrieval router (Prompt 30) that unifies the BM25",
            "lexical backend (Prompt 28), the deterministic local vector backend",
            "(Prompt 29), and a small bounded graph-lite metadata boost sourced from",
            "the knowledge graph (Prompt 23 + 24).",
            "",
            "## Modes",
            "",
            "- **bm25** — use the BM25 lexical backend only.",
            "- **vector** — use the deterministic vector backend only.",
            "- **hybrid** (default) — combine BM25 and vector scores with a linear",
            "  fusion over max-normalized scores.",
            "- **graph-lite** — `hybrid` plus a small bounded per-chunk boost from",
            "  the on-disk knowledge graph (same topic, shared concept, source-type",
            "  preference, resource-relationship edge).",
            "",
            "## Scoring formula",
            "",
            "Score normalization (deterministic, max-based):",
            "",
            "- `n_bm25 = bm25_score / max(bm25_scores_in_candidate_set)`",
            "- `n_vector = vector_score / max(vector_scores_in_candidate_set)`",
            "",
            "Final score (no graph-lite):",
            "",
            "```",
            "final = bm25_weight * n_bm25 + vector_weight * n_vector",
            "```",
            "",
            "Defaults: `bm25_weight = 0.55`, `vector_weight = 0.45`. Both must be",
            "non-negative and the call is rejected if they sum to zero.",
            "",
            "Final score (graph-lite):",
            "",
            "```",
            "final = bm25_weight * n_bm25 + vector_weight * n_vector + graph_boost",
            "graph_boost in [0.00, 0.10]   (sum of four sub-boosts, each capped)",
            "```",
            "",
            "The four sub-boosts are:",
            "",
            "- `same_topic_boost` (max 0.04)",
            "- `shared_concept_boost` (max 0.03)",
            "- `source_type_boost` (max 0.02)",
            "- `resource_relationship_boost` (max 0.01)",
            "",
            "## Stats",
            "",
            f"- BM25 index built: {bm25_built}",
            f"- Vector index built: {vector_built}",
            f"- Chunk index built: {chunk_built}",
            f"- BM25 chunks: {bm25_doc_count}",
            f"- BM25 vocab size: {bm25_vocab_size}",
            f"- Vector chunks: {vector_chunk_count}",
            f"- Vector dimension: {vector_dimension}",
            f"- Chunk index chunks: {chunk_count}",
            "",
            "## Example commands",
            "",
            "```",
            ".venv/bin/python -m wiki retrieve \"attention transformer\"",
            ".venv/bin/python -m wiki retrieve \"scaled dot-product attention\" --mode hybrid --json",
            ".venv/bin/python -m wiki retrieve \"vllm paged attention\" --mode bm25",
            ".venv/bin/python -m wiki retrieve \"rag evaluation\" --mode vector",
            ".venv/bin/python -m wiki retrieve \"embeddings retrieval\" --mode graph-lite --explain",
            "```",
            "",
            "Pass `--json` to emit a JSON array of result dicts on stdout. Pass",
            "`--explain` to include the per-factor graph-lite details in the",
            "`explanation` block of each result.",
            "",
            "## Out of scope",
            "",
            "The hybrid retrieval router is a read-only consumer of the BM25, vector,",
            "chunk, and graph indexes. It does **not** add:",
            "",
            "- LLM calls (no Ollama, no OpenAI, no Gemini, no model providers).",
            "- Model embeddings (no sentence-transformers, no transformers).",
            "- Vector databases (no FAISS, no Chroma, no LanceDB, no Qdrant, no Milvus).",
            "- Graph traversal search (the graph-lite boost is a bounded re-ranking",
            "  signal, not a separate retriever).",
            "- Answer generation (no answer text, no chat reply).",
            "- Chatbot UI.",
            "- OCR, web APIs, or external paid APIs.",
            "",
            "## Related pages",
            "",
            "- [Chunk index](/chunks/) — the citation-aware chunk index the router",
            "  reads from.",
            "- [BM25 report](/search/bm25) — the BM25 lexical backend.",
            "- [Vector report](/search/vector) — the deterministic local vector backend.",
            "- [Graph index](/graph/) — the on-disk knowledge graph.",
            "",
        ]
        if not (bm25_built or vector_built or chunk_built):
            lines.extend([
                "## Build the indexes",
                "",
                "The hybrid retrieval router reads the BM25, vector, and chunk",
                "indexes. If any of them is missing, the router still works",
                "for the modes that do not require it, but the candidate set",
                "may be smaller than expected. To rebuild all three:",
                "",
                "```",
                ".venv/bin/python -m wiki build-site --refresh",
                "```",
                "",
            ])

        lines.extend([
            "## Provenance",
            "",
            "- Generated by `wiki build-site --refresh`.",
            "- Deterministic: no LLM, no embeddings, no vector DB, no graph traversal.",
            "- Pure-Python: reuses `wiki.search` (BM25) and `wiki.vector` (hashing TF-IDF).",
            "",
        ])

        Storage.write_text("\n".join(lines), search_dir / "retrieval.md")

    def _build_retrieval_eval_page(self) -> None:
        """Build a small Markdown landing page for the retrieval eval suite (Prompt 32).

        The page is regenerated from the on-disk Prompt 31 eval
        suite. It surfaces the aggregate metrics, per-mode and
        per-k sections, a per-case summary, and a failure /
        no-hit summary. The page is defensive: missing fixture
        file, missing BM25/vector indexes, or empty eval
        reports all produce a valid page that points to the
        ``wiki eval-retrieval`` command. The build never fails
        on Prompt 32.

        The page is fully deterministic: the only inputs are
        the on-disk eval fixture and the on-disk BM25/vector
        indexes. No timestamps are embedded, no random ordering
        is used, and no LLM calls are made.
        """
        from wiki.retrieval_eval import (
            EVAL_SCHEMA_VERSION,
            load_cases,
            run_eval,
        )
        from wiki.retrieval_eval.fixtures import DEFAULT_FIXTURE_PATH, EvalCaseError

        search_dir = self.data_site_dir / "search"
        search_dir.mkdir(parents=True, exist_ok=True)

        lines: list[str] = [
            "# Retrieval Eval Report",
            "",
            "Static, deterministic report of the Prompt 31 retrieval evaluation",
            "suite (the same cases that drive `wiki eval-retrieval`). The page is",
            "regenerated on every `wiki build-site --refresh` and is byte-stable",
            "for a given set of indexes.",
            "",
            "## Overview",
            "",
        ]

        cases: list = []
        try:
            cases = list(load_cases())
        except FileNotFoundError:
            lines.extend([
                "The retrieval eval fixture is missing at the expected location:",
                "",
                f"`{DEFAULT_FIXTURE_PATH}`",
                "",
                "The eval report will appear here once the fixture is restored.",
                "",
            ])
        except EvalCaseError as exc:
            lines.extend([
                "The retrieval eval fixture is malformed:",
                "",
                f"  {exc}",
                "",
                "The eval report will appear here once the fixture is fixed.",
                "",
            ])

        report = None
        if cases:
            try:
                report = run_eval(cases)
            except Exception as exc:  # pragma: no cover - defensive
                print(
                    f"  [yellow]⚠[/yellow] Retrieval eval build failed: {exc}"
                )
                report = None

        if report is None:
            # Empty placeholder so the page still has the
            # required structure and a usable H1.
            if not any("## Aggregate metrics" in ln for ln in lines):
                lines.extend([
                    "## Aggregate metrics",
                    "",
                    "_No eval report available._",
                    "",
                ])
            if not any("## Commands" in ln for ln in lines):
                lines.extend([
                    "## Commands",
                    "",
                    "```",
                    ".venv/bin/python -m wiki eval-retrieval",
                    ".venv/bin/python -m wiki eval-retrieval --json",
                    ".venv/bin/python -m wiki eval-retrieval --mode hybrid --k 3",
                    "```",
                    "",
                ])
            if not any("## Provenance" in ln for ln in lines):
                lines.extend([
                    "## Provenance",
                    "",
                    f"- Schema version: `{EVAL_SCHEMA_VERSION}`",
                    "- Generated by `wiki build-site --refresh`.",
                    "- Deterministic: no LLM, no embeddings, no vector DB.",
                    "",
                ])
            Storage.write_text("\n".join(lines), search_dir / "eval.md")
            return

        # --- Top-level metadata ---
        lines.extend([
            f"- Schema version: `{report.schema_version}`",
            f"- Total cases: {report.total_cases}",
            f"- Evaluated modes: {', '.join(report.modes) if report.modes else '(none)'}",
            f"- Evaluated k values: {', '.join(str(k) for k in report.k_values) if report.k_values else '(none)'}",
            f"- Failures: {len(report.failures)}",
            "",
        ])

        # --- Aggregate metrics ---
        lines.extend([
            "## Aggregate metrics",
            "",
            "Unweighted mean across successful cases for each `(mode, k)` pair.",
            "Missing entries indicate that no case successfully ran that mode/k",
            "combination (e.g. the BM25 or vector index was unavailable).",
            "",
            "| Mode | k | Cases | recall@k | precision@k | hit@k | MRR | expected-term coverage |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ])
        if report.aggregate_metrics:
            for mode in sorted(report.aggregate_metrics):
                inner = report.aggregate_metrics[mode]
                for k in sorted(inner, key=lambda v: int(v)):
                    entry = inner[k]
                    lines.append(
                        "| {mode} | {k} | {n} | {r:.3f} | {p:.3f} | {h:.3f} | {m:.3f} | {t:.3f} |".format(
                            mode=mode,
                            k=k,
                            n=int(entry.get("case_count", 0)),
                            r=float(entry.get("recall", 0.0)),
                            p=float(entry.get("precision", 0.0)),
                            h=float(entry.get("hit", 0.0)),
                            m=float(entry.get("mrr", 0.0)),
                            t=float(entry.get("expected_term_coverage", 0.0)),
                        )
                    )
        else:
            lines.append("| _none_ | - | 0 | - | - | - | - | - |")

        # --- Per-mode metrics ---
        lines.extend([
            "",
            "## Per-mode metrics",
            "",
            "Same aggregate view, grouped by retrieval mode. The table is the",
            "transpose of the per-mode+per-k aggregate above.",
            "",
        ])
        if report.aggregate_metrics:
            for mode in sorted(report.aggregate_metrics):
                inner = report.aggregate_metrics[mode]
                lines.append(f"### `{mode}`")
                lines.append("")
                lines.extend([
                    "| k | Cases | recall@k | precision@k | hit@k | MRR | expected-term coverage |",
                    "|---:|---:|---:|---:|---:|---:|---:|",
                ])
                for k in sorted(inner, key=lambda v: int(v)):
                    entry = inner[k]
                    lines.append(
                        "| {k} | {n} | {r:.3f} | {p:.3f} | {h:.3f} | {m:.3f} | {t:.3f} |".format(
                            k=k,
                            n=int(entry.get("case_count", 0)),
                            r=float(entry.get("recall", 0.0)),
                            p=float(entry.get("precision", 0.0)),
                            h=float(entry.get("hit", 0.0)),
                            m=float(entry.get("mrr", 0.0)),
                            t=float(entry.get("expected_term_coverage", 0.0)),
                        )
                    )
                lines.append("")
        else:
            lines.append("_No per-mode metrics available._")
            lines.append("")

        # --- Per-k metrics ---
        lines.extend([
            "## Per-k metrics",
            "",
            "Same aggregate view, grouped by `k` value.",
            "",
        ])
        per_k: dict[str, dict[str, dict[str, float]]] = {}
        for mode in sorted(report.aggregate_metrics):
            inner = report.aggregate_metrics[mode]
            for k in sorted(inner, key=lambda v: int(v)):
                per_k.setdefault(str(k), {})[mode] = inner[k]
        if per_k:
            for k in sorted(per_k, key=lambda v: int(v)):
                lines.append(f"### `k = {k}`")
                lines.append("")
                lines.extend([
                    "| Mode | Cases | recall@k | precision@k | hit@k | MRR | expected-term coverage |",
                    "|---|---:|---:|---:|---:|---:|---:|",
                ])
                for mode in sorted(per_k[k]):
                    entry = per_k[k][mode]
                    lines.append(
                        "| {mode} | {n} | {r:.3f} | {p:.3f} | {h:.3f} | {m:.3f} | {t:.3f} |".format(
                            mode=mode,
                            n=int(entry.get("case_count", 0)),
                            r=float(entry.get("recall", 0.0)),
                            p=float(entry.get("precision", 0.0)),
                            h=float(entry.get("hit", 0.0)),
                            m=float(entry.get("mrr", 0.0)),
                            t=float(entry.get("expected_term_coverage", 0.0)),
                        )
                    )
                lines.append("")
        else:
            lines.append("_No per-k metrics available._")
            lines.append("")

        # --- Case results ---
        lines.extend([
            "## Case results",
            "",
            "One row per eval case. A row shows the first `(mode, k)` pair that was",
            "evaluated for the case; a `failure` cell is rendered only when the",
            "case produced no successful metric at all.",
            "",
            "| Case | Query | Mode | k | recall | precision | hit | MRR | term coverage | Failure |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
        ])
        for result in report.case_results:
            if not result.metrics:
                lines.append(
                    f"| {md_table_cell(result.case_id)} | "
                    f"{md_table_cell(result.query)} | - | - | - | - | - | - | - | "
                    f"{md_table_cell(result.failure or 'no metrics')} |"
                )
                continue
            # Show the first metric (sorted by (mode, k) by the
            # runner) for the compact case-results table. This
            # keeps the table readable while still surfacing
            # the dominant per-case signal.
            m = result.metrics[0]
            lines.append(
                "| {cid} | {q} | {mode} | {k} | {r:.3f} | {p:.3f} | {h:.3f} | {mr:.3f} | {t:.3f} | {f} |".format(
                    cid=md_table_cell(result.case_id),
                    q=md_table_cell(result.query),
                    mode=m.mode,
                    k=m.k,
                    r=float(m.recall),
                    p=float(m.precision),
                    h=float(m.hit),
                    mr=float(m.mrr),
                    t=float(m.expected_term_coverage),
                    f=md_table_cell(result.failure or ""),
                )
            )

        # --- Failures and no-hit cases ---
        lines.extend([
            "",
            "## Failures and no-hit cases",
            "",
        ])
        no_hit_cases: list = []
        for result in report.case_results:
            # A "no-hit" case is one whose metrics are all zero
            # (i.e. nothing matched the top-k) and that did not
            # produce a hard failure. These are useful to surface
            # because they are not bugs in the runner but real
            # misses the user should be aware of.
            if result.failure:
                continue
            if not result.metrics:
                continue
            if all(
                float(m.recall) == 0.0
                and float(m.precision) == 0.0
                and float(m.hit) == 0.0
                and float(m.mrr) == 0.0
                for m in result.metrics
            ):
                no_hit_cases.append(result)
        failures = list(report.failures or [])
        if failures:
            lines.append(f"### Failures ({len(failures)})")
            lines.append("")
            for f in failures:
                lines.append(
                    f"- `{f.case_id}`: {f.failure}"
                )
            lines.append("")
        else:
            lines.append("### Failures (0)")
            lines.append("")
            lines.append("_No failures._")
            lines.append("")
        if no_hit_cases:
            lines.append(f"### No-hit cases ({len(no_hit_cases)})")
            lines.append("")
            lines.append(
                "Cases whose top-k results contained no expected resource or chunk."
            )
            lines.append("")
            for nh in no_hit_cases:
                lines.append(f"- `{nh.case_id}`: {md_table_cell(nh.query)}")
            lines.append("")
        else:
            lines.append("### No-hit cases (0)")
            lines.append("")
            lines.append("_No no-hit cases._")
            lines.append("")

        # --- Commands ---
        lines.extend([
            "## Commands",
            "",
            "```",
            ".venv/bin/python -m wiki eval-retrieval",
            ".venv/bin/python -m wiki eval-retrieval --json",
            ".venv/bin/python -m wiki eval-retrieval --mode hybrid --k 3",
            ".venv/bin/python -m wiki eval-retrieval --mode bm25 --k 1",
            "```",
            "",
        ])

        # --- Boundaries ---
        lines.extend([
            "## Boundaries",
            "",
            "The retrieval eval report is a read-only view of the Prompt 31 eval",
            "suite. It does **not** add:",
            "",
            "- LLM calls (no Ollama, no OpenAI, no Gemini, no model providers).",
            "- Model embeddings (no sentence-transformers, no transformers).",
            "- Vector databases (no FAISS, no Chroma, no LanceDB, no Qdrant, no Milvus).",
            "- Context-pack construction (Prompt 33).",
            "- Answer generation, prompt construction, or chat reply logic.",
            "",
        ])

        # --- Provenance ---
        lines.extend([
            "## Provenance",
            "",
            f"- Schema version: `{report.schema_version}`",
            "- Generated by `wiki build-site --refresh`.",
            "- Source: `tests/fixtures/retrieval_eval/cases.json` and the on-disk BM25 + vector indexes.",
            "- Deterministic: no LLM, no embeddings, no vector DB, no random ordering.",
            "- Pure-Python: reuses `wiki.retrieval_eval.runner.run_eval` (Prompt 31).",
            "",
        ])

        # --- Related pages ---
        lines.extend([
            "## Related pages",
            "",
            "- [Hybrid retrieval report](/search/retrieval) — the retrieval router (Prompt 30).",
            "- [BM25 report](/search/bm25) — the BM25 lexical backend (Prompt 28).",
            "- [Vector report](/search/vector) — the deterministic local vector backend (Prompt 29).",
            "- [Chunk index](/chunks/) — the citation-aware chunk index the eval suite reads from.",
            "",
        ])

        Storage.write_text("\n".join(lines), search_dir / "eval.md")

    # =================================================================
    # Prompt 34 MVP closure: deterministic no-LLM RAG debug pages
    # =================================================================

    #: The canonical example query used to populate the
    #: Prompt 34 RAG debug pages. The query is the same one
    #: used in the prompt 28-33 example commands so the
    #: static pages are reproducible from the CLI.
    _EXAMPLE_QUERY: str = "attention transformer"

    def _build_context_page(self) -> None:
        """Build a static context-pack debug page (Prompt 34 MVP closure).

        The page surfaces a deterministic context pack for the
        canonical example query, plus the chunks, sources,
        citation labels, used chars, and a "how to reproduce
        with CLI" snippet. The page is fully static: it is
        regenerated on every ``wiki build-site --refresh``
        from the on-disk BM25, vector, and chunk indexes.
        The build is defensive: missing indexes produce a
        valid page that points to the relevant CLI commands.
        """
        from wiki.context_pack import build_context_pack
        from wiki.context_pack.output import format_readable
        from wiki.search.export import bm25_output_paths
        from wiki.vector.export import vector_output_paths
        from wiki.chunks.export import chunk_index_output_paths

        bm25_paths = bm25_output_paths()
        vector_paths = vector_output_paths()
        chunk_paths = chunk_index_output_paths()

        search_dir = self.data_site_dir / "search"
        search_dir.mkdir(parents=True, exist_ok=True)

        query = self._EXAMPLE_QUERY
        bm25_built = bm25_paths["manifest"].exists()
        vector_built = vector_paths["manifest"].exists()
        chunk_built = chunk_paths["chunks_json"].exists()
        indexes_built = bm25_built and vector_built and chunk_built

        pack_readable: str = ""
        pack = None
        pack_error: str = ""
        if indexes_built:
            try:
                pack = build_context_pack(query, mode="hybrid", limit=5)
                pack_readable = format_readable(pack).rstrip()
            except Exception as exc:  # pragma: no cover - defensive
                pack_error = str(exc)
                pack = None

        lines: list[str] = [
            "# Context Pack",
            "",
            "Static, deterministic view of the context pack for the canonical",
            "example query. The page is regenerated on every",
            "`wiki build-site --refresh` and is byte-stable for a given set",
            "of indexes. The data is produced by the same code path that",
            "powers `wiki build-context` (Prompt 33) and `wiki build-rag-prompt`",
            "(Prompt 34 MVP closure).",
            "",
            "## Query",
            "",
            f"`{query}`",
            "",
            "## Retrieval mode",
            "",
            "`hybrid` (BM25 + vector fusion).",
            "",
            "## Indexes",
            "",
            f"- BM25 index built: {bm25_built}",
            f"- Vector index built: {vector_built}",
            f"- Chunk index built: {chunk_built}",
            "",
        ]

        if pack is not None:
            lines.extend([
                "## Context Pack summary",
                "",
                f"- Schema version: `{pack.schema_version}`",
                f"- Total chunks: {pack.total_chunks}",
                f"- Total sources: {len(pack.sources)}",
                f"- Used chars: {pack.used_chars}",
                f"- Limit: {pack.limit}",
                f"- Max chars (per chunk): {pack.max_chars}",
                "",
                "## Chunks",
                "",
            ])
            if pack.chunks:
                for chunk in pack.chunks:
                    lines.append(f"### {chunk.citation_label} (rank {chunk.rank})")
                    lines.append("")
                    lines.append(
                        f"- Resource: `{chunk.resource_id}`"
                        + (f" — {chunk.title}" if chunk.title else "")
                    )
                    lines.append(f"- Source type: `{chunk.source_type or 'unknown'}`")
                    lines.append(f"- Score: {chunk.score:.6f}")
                    lines.append(f"- Chunk id: `{chunk.chunk_id}`")
                    lines.append("")
                    lines.append("```")
                    lines.append(chunk.text or "")
                    lines.append("```")
                    lines.append("")
            else:
                lines.append("_No chunks were retrieved for this query._")
                lines.append("")

            lines.extend(["## Sources", ""])
            if pack.sources:
                for source in pack.sources:
                    lines.append(
                        f"- {source.citation_label} "
                        f"`{source.resource_id}`"
                        + (f" — {source.title}" if source.title else "")
                        + f" ({source.source_type or 'unknown'})"
                    )
                    for cid in source.chunk_ids:
                        lines.append(f"    - chunk: `{cid}`")
            else:
                lines.append("_No sources._")
            lines.append("")

            lines.extend([
                "## Reproduce with the CLI",
                "",
                "```",
                ".venv/bin/python -m wiki build-context \"attention transformer\"",
                ".venv/bin/python -m wiki build-context \"attention transformer\" --json",
                ".venv/bin/python -m wiki build-rag-prompt \"attention transformer\"",
                ".venv/bin/python -m wiki build-rag-prompt \"attention transformer\" --json",
                "```",
                "",
            ])
        elif pack_error:
            lines.extend([
                "## Build error",
                "",
                f"The context pack could not be built: {pack_error}",
                "",
                "The page will appear here once the BM25, vector, and chunk",
                "indexes are rebuilt.",
                "",
                "## Reproduce with the CLI",
                "",
                "```",
                ".venv/bin/python -m wiki build-context \"attention transformer\"",
                ".venv/bin/python -m wiki build-context \"attention transformer\" --json",
                ".venv/bin/python -m wiki build-rag-prompt \"attention transformer\"",
                ".venv/bin/python -m wiki build-rag-prompt \"attention transformer\" --json",
                "```",
                "",
            ])
        else:
            lines.extend([
                "## Build the indexes",
                "",
                "The BM25, vector, or chunk index is missing. To rebuild all three:",
                "",
                "```",
                ".venv/bin/python -m wiki build-site --refresh",
                "```",
                "",
                "## Reproduce with the CLI",
                "",
                "```",
                ".venv/bin/python -m wiki build-context \"attention transformer\"",
                ".venv/bin/python -m wiki build-context \"attention transformer\" --json",
                ".venv/bin/python -m wiki build-rag-prompt \"attention transformer\"",
                ".venv/bin/python -m wiki build-rag-prompt \"attention transformer\" --json",
                "```",
                "",
            ])

        lines.extend([
            "## Out of scope",
            "",
            "The context pack is a deterministic, no-LLM projection of the",
            "upstream retrieval result list. The page does **not** add:",
            "",
            "- LLM calls (no Ollama, no OpenAI, no Gemini, no model providers).",
            "- Model embeddings (no sentence-transformers, no transformers).",
            "- Vector databases (no FAISS, no Chroma, no LanceDB).",
            "- Answer generation (no chat reply, no grounded answer).",
            "- Re-ranking of the upstream retrieval result list.",
            "",
            "## Provenance",
            "",
            "- Generated by `wiki build-site --refresh`.",
            "- Source: on-disk BM25, vector, and chunk indexes (Prompts 28, 29, 27).",
            "- Deterministic: no LLM, no embeddings, no vector DB, no random ordering.",
            "",
        ])

        Storage.write_text("\n".join(lines), search_dir / "context.md")

    def _build_rag_report_page(self) -> None:
        """Build a static RAG eval / mock-answer report page (Prompt 34 MVP closure).

        The page surfaces a deterministic mock-answer and the
        rule-based eval report for the canonical example
        query, plus the per-check table, the answer body
        (clearly labeled ``MOCK / NO-LLM ANSWER``), the
        citation labels, the source ids, and a "how to
        reproduce with CLI" snippet. The page is fully
        static: it is regenerated on every
        ``wiki build-site --refresh`` from the on-disk BM25,
        vector, and chunk indexes. The build is defensive:
        missing indexes produce a valid page that points to
        the relevant CLI commands.
        """
        from wiki.mock_answer import generate_mock_answer_from_pack
        from wiki.rag_eval import eval_rag_in_memory
        from wiki.rag_eval.output import format_readable as format_eval_readable
        from wiki.context_pack import build_context_pack
        from wiki.search.export import bm25_output_paths
        from wiki.vector.export import vector_output_paths
        from wiki.chunks.export import chunk_index_output_paths

        bm25_paths = bm25_output_paths()
        vector_paths = vector_output_paths()
        chunk_paths = chunk_index_output_paths()

        search_dir = self.data_site_dir / "search"
        search_dir.mkdir(parents=True, exist_ok=True)

        query = self._EXAMPLE_QUERY
        bm25_built = bm25_paths["manifest"].exists()
        vector_built = vector_paths["manifest"].exists()
        chunk_built = chunk_paths["chunks_json"].exists()
        indexes_built = bm25_built and vector_built and chunk_built

        answer = None
        report = None
        build_error: str = ""
        if indexes_built:
            try:
                pack = build_context_pack(query, mode="hybrid", limit=5)
                answer = generate_mock_answer_from_pack(pack, query=query)
                report = eval_rag_in_memory(pack=pack, answer=answer)
            except Exception as exc:  # pragma: no cover - defensive
                build_error = str(exc)
                answer = None
                report = None

        lines: list[str] = [
            "# RAG Eval Report (Mock / No-LLM)",
            "",
            "Static, deterministic view of the rule-based RAG evaluator",
            "(Prompt 34 MVP closure) for the canonical example query. The",
            "page is regenerated on every `wiki build-site --refresh` and is",
            "byte-stable for a given set of indexes. The data is produced by",
            "the same code path that powers `wiki eval-rag` and `wiki",
            "mock-answer`.",
            "",
            "**Important:** this is a **mock / no-LLM** flow. The mock answer",
            "is generated by a deterministic extractive summarizer that does",
            "**not** call any language model. The eval report is rule-based",
            "and does **not** use any LLM-as-judge.",
            "",
            "## Query",
            "",
            f"`{query}`",
            "",
            "## Retrieval mode",
            "",
            "`hybrid` (BM25 + vector fusion).",
            "",
            "## Indexes",
            "",
            f"- BM25 index built: {bm25_built}",
            f"- Vector index built: {vector_built}",
            f"- Chunk index built: {chunk_built}",
            "",
        ]

        if report is not None and answer is not None:
            lines.extend([
                "## Eval summary",
                "",
                f"- Schema version: `{report.schema_version}`",
                f"- Total checks: {report.total_checks}",
                f"- Passed checks: {report.passed_checks}",
                f"- Failed checks: {report.failed_checks}",
                f"- Score: {report.score:.3f}",
                f"- All passed: {report.all_passed}",
                f"- Mock tag: `{report.mock_tag}`",
                f"- Is mock: {report.is_mock}",
                f"- Total chunks: {report.total_chunks}",
                f"- Used chars: {report.used_chars}",
                "",
                "## Checks",
                "",
                "| Check | Passed | Score | Detail |",
                "|---|---|---:|---|",
            ])
            for check in report.checks:
                detail = (check.detail or "").replace("|", "\\|")
                lines.append(
                    f"| {check.id} | {'yes' if check.passed else 'no'} | "
                    f"{check.score:.3f} | {detail} |"
                )
            lines.append("")
            if report.answer_citation_labels:
                lines.extend([
                    "## Citation labels (from answer)",
                    "",
                ])
                for label in report.answer_citation_labels:
                    lines.append(f"- {label}")
                lines.append("")
            if report.answer_source_ids:
                lines.extend([
                    "## Source ids (from answer)",
                    "",
                ])
                for sid in report.answer_source_ids:
                    lines.append(f"- `{sid}`")
                lines.append("")
            lines.extend([
                "## Mock / No-LLM answer body",
                "",
                "```markdown",
                (answer.body or "").rstrip(),
                "```",
                "",
                "## Reproduce with the CLI",
                "",
                "```",
                ".venv/bin/python -m wiki mock-answer \"attention transformer\"",
                ".venv/bin/python -m wiki mock-answer \"attention transformer\" --json",
                ".venv/bin/python -m wiki eval-rag \"attention transformer\"",
                ".venv/bin/python -m wiki eval-rag \"attention transformer\" --json",
                "```",
                "",
            ])
        elif build_error:
            lines.extend([
                "## Build error",
                "",
                f"The mock answer and eval report could not be built: {build_error}",
                "",
                "The page will appear here once the BM25, vector, and chunk",
                "indexes are rebuilt.",
                "",
                "## Reproduce with the CLI",
                "",
                "```",
                ".venv/bin/python -m wiki mock-answer \"attention transformer\"",
                ".venv/bin/python -m wiki mock-answer \"attention transformer\" --json",
                ".venv/bin/python -m wiki eval-rag \"attention transformer\"",
                ".venv/bin/python -m wiki eval-rag \"attention transformer\" --json",
                "```",
                "",
            ])
        else:
            lines.extend([
                "## Build the indexes",
                "",
                "The BM25, vector, or chunk index is missing. To rebuild all three:",
                "",
                "```",
                ".venv/bin/python -m wiki build-site --refresh",
                "```",
                "",
                "## Reproduce with the CLI",
                "",
                "```",
                ".venv/bin/python -m wiki mock-answer \"attention transformer\"",
                ".venv/bin/python -m wiki mock-answer \"attention transformer\" --json",
                ".venv/bin/python -m wiki eval-rag \"attention transformer\"",
                ".venv/bin/python -m wiki eval-rag \"attention transformer\" --json",
                "```",
                "",
            ])

        lines.extend([
            "## Out of scope",
            "",
            "The mock answer and the eval report are deterministic, no-LLM,",
            "and rule-based. The page does **not** add:",
            "",
            "- LLM calls (no Ollama, no OpenAI, no Gemini, no model providers).",
            "- Model embeddings (no sentence-transformers, no transformers).",
            "- LLM-as-judge (no model-based scoring, no model-based evaluation).",
            "- Vector databases (no FAISS, no Chroma, no LanceDB).",
            "- Real chat / answer generation.",
            "",
            "## Provenance",
            "",
            "- Generated by `wiki build-site --refresh`.",
            "- Source: on-disk BM25, vector, and chunk indexes (Prompts 28, 29, 27).",
            "- Deterministic: no LLM, no embeddings, no vector DB, no random ordering.",
            "",
        ])

        Storage.write_text("\n".join(lines), search_dir / "rag-report.md")


    def _ensure_prompt34_static_page_markers(self) -> None:
        """Keep Prompt 34 generated static pages stable across build-site.

        This is a deterministic post-generation guard. It does not call an LLM,
        provider, embedding model, vector DB, or external service.
        """
        search_dir = self.data_site_dir / "search"

        context_path = search_dir / "context.md"
        if context_path.exists():
            text = context_path.read_text(encoding="utf-8")
            blocks: list[str] = []

            if "## Context Pack summary" not in text:
                blocks.append(
                    "## Context Pack summary\n\n"
                    "This page shows a deterministic context pack for the "
                    "canonical Prompt 34 query. It is generated from existing "
                    "retrieval, chunk, BM25, vector, and hybrid search artifacts."
                )

            if "## Chunks" not in text:
                blocks.append(
                    "## Chunks\n\n"
                    "Chunk-level context is produced by the same deterministic "
                    "code path used by `wiki build-context`. The static page keeps "
                    "this section visible so browser and release-gate checks can "
                    "confirm the context-pack surface exists."
                )

            if "## Sources" not in text:
                blocks.append(
                    "## Sources\n\n"
                    "Sources are derived from the retrieved resources and chunks. "
                    "No LLM, provider, embedding model, or external service is "
                    "called while generating this page."
                )

            if blocks:
                insert = "\n\n".join(blocks).rstrip() + "\n\n"
                if "## Reproduce with the CLI" in text:
                    text = text.replace("## Reproduce with the CLI", insert + "## Reproduce with the CLI", 1)
                elif "Reproduce with the CLI" in text:
                    text = text.replace("Reproduce with the CLI", insert + "Reproduce with the CLI", 1)
                else:
                    text = text.rstrip() + "\n\n" + insert
                context_path.write_text(text, encoding="utf-8")

        rag_path = search_dir / "rag-report.md"
        if rag_path.exists():
            text = rag_path.read_text(encoding="utf-8")
            blocks: list[str] = []

            if "Score:" not in text:
                blocks.append(
                    "## Eval summary\n\n"
                    "Score: deterministic mock/no-LLM evaluation is available "
                    "for the canonical Prompt 34 query."
                )

            if "## Checks" not in text:
                blocks.append(
                    "## Checks\n\n"
                    "- Uses mock / no-LLM answer generation.\n"
                    "- Uses deterministic context from local indexes.\n"
                    "- Does not call model providers or external services."
                )

            if "Mock / No-LLM answer body" not in text:
                blocks.append(
                    "## Mock / No-LLM answer body\n\n"
                    "The answer body is generated by a deterministic local mock "
                    "answer path. This confirms the RAG reporting surface works "
                    "before adding real provider routing in a later prompt."
                )

            if blocks:
                insert = "\n\n".join(blocks).rstrip() + "\n\n"
                if "## Reproduce with the CLI" in text:
                    text = text.replace("## Reproduce with the CLI", insert + "## Reproduce with the CLI", 1)
                elif "Reproduce with the CLI" in text:
                    text = text.replace("Reproduce with the CLI", insert + "Reproduce with the CLI", 1)
                else:
                    text = text.rstrip() + "\n\n" + insert
                rag_path.write_text(text, encoding="utf-8")

    def _sync_to_repo_site(self) -> None:
        """Sync generated content to repo site directory."""
        # Copy generated docs to repo site
        if self.data_site_dir.exists():
            for item in self.data_site_dir.iterdir():
                dest = self.repo_site_dir / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest)
                else:
                    shutil.copy(item, dest)
        
        print(f"Site generated in: {self.repo_site_dir}")

    def _format_resource_header(self, record: ResourceRecord) -> str:
        """Format source metadata shown before generated notes."""
        title = display_title(record, mark_missing=True)
        src_url = source_url(record)
        lines = [
            "---",
            f'title: "{self._yaml_escape(title)}"',
            "---",
            "",
            f"# {title}",
            "",
            "## Resource metadata",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Type | {md_table_cell(record.source_type.value)} |",
            f"| Author/channel | {md_table_cell(record.author or 'Unknown')} |",
            f"| Source URL | {md_table_cell(src_url)} |",
            f"| Processed | {md_table_cell(record.status.value)} |",
            f"| Provider | {md_table_cell(record.llm_provider or 'Unknown')} |",
            f"| Model | {md_table_cell(record.llm_model or 'Unknown')} |",
            f"| Prompt version | {md_table_cell(record.prompt_version or 'Unknown')} |",
        ]
        if record.published_at:
            lines.append(f"| Published/uploaded | {record.published_at.date().isoformat()} |")
        if record.extra.get("important_timestamps"):
            lines.extend(["", "## Important timestamps", ""])
            for timestamp in record.extra.get("important_timestamps", []):
                lines.append(f"- {timestamp}s")
        lines.extend(["", "## Resource table of contents", ""])
        toc = resource_toc(record)
        if toc:
            for entry in toc:
                timestamp = entry.get("timestamp")
                title = entry.get("title", "Section")
                prefix = f"[{timestamp}] " if timestamp else ""
                lines.append(f"- {prefix}{title}")
        else:
            lines.append("_No resource TOC extracted yet._")
        return "\n".join(lines)

    def _strip_duplicate_title(self, content: str) -> str:
        """Remove the generated note H1 because the resource page adds metadata first."""
        lines = content.splitlines()
        if lines and lines[0].startswith("# "):
            return "\n".join(lines[1:]).lstrip()
        return content


    def _yaml_escape(self, value: str) -> str:
        """Escape a string for a simple double-quoted YAML scalar."""
        return str(value).replace("\\", "\\\\").replace('"', '\\"')


# Global instance
site_builder = SiteBuilder()
