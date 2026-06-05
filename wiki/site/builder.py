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
