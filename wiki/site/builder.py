"""Build VitePress site from generated content."""

import shutil
import json
from pathlib import Path
from typing import List, Iterator

from wiki.config import config
from wiki.schemas import ResourceRecord, ResourceStatus
from wiki.storage import Storage


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
        
        for record in records:
            title = record.title or record.id
            status = record.status.value
            date = record.user_consumed_at.strftime("%Y-%m-%d") if record.user_consumed_at else "N/A"
            
            # Create individual resource page if note exists
            if record.generated_note_path and record.generated_note_path.exists():
                resource_filename = f"{record.id.replace(':', '_')}.md"
                resource_path = resources_dir / resource_filename
                
                # Copy note content
                note_content = Storage.read_text(record.generated_note_path)
                Storage.write_text(note_content, resource_path)
                
                link = f"[{title}](./{resource_filename})"
            else:
                link = title
            
            index_lines.append(f"| {link} | {record.source_type.value} | {status} | {date} |")
        
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
                index_lines.append(f"- [{name}](./{concept_file.name})")
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
    
    def _build_gaps(self) -> None:
        """Build the gaps page."""
        gaps_source = config.get_data_path("processed", "gaps", "gaps.md")
        
        if gaps_source.exists():
            content = Storage.read_text(gaps_source)
        else:
            content = "# Knowledge Gaps\n\n_No gaps identified yet._\n"
        
        gaps_path = self.data_site_dir / "gaps.md"
        Storage.write_text(content, gaps_path)
    
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


# Global instance
site_builder = SiteBuilder()
