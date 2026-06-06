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

        self._copy_generated_section("public")

        # Build gaps page
        self._build_gaps()

        # Sync to repo site directory
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
            "| [/public/graph/nodes.json](/public/graph/nodes.json) | All graph nodes |",
            "| [/public/graph/edges.json](/public/graph/edges.json) | All graph edges |",
            "| [/public/graph/knowledge_graph.json](/public/graph/knowledge_graph.json) | Combined bundle with stats |",
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
