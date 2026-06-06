"""Generate tags page from resources, topic assignments, and metadata."""

from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Dict, List

from wiki.config import config
from wiki.generate.page_utils import extract_section, md_table_cell, read_note, resource_route
from wiki.resource_utils import TOPIC_DEFINITIONS, dedupe_records, display_title, learned_date, topic_matches
from wiki.schemas import ResourceRecord
from wiki.storage import Storage


class TagsGenerator:
    """Generate tags aggregation from resources, topics, and metadata."""

    def generate(self, records: List[ResourceRecord]) -> Dict[str, List[dict]]:
        """Generate tags to resources mapping.

        Tags come from:
        - record.tags (explicit user tags)
        - source_type (youtube, webpage, local_transcript, etc.)
        - topic assignments from topic_matches()
        - platform from record.extra (huggingface_blog, medium, etc.)
        - concept names from generated notes
        """
        tags: Dict[str, List[dict]] = defaultdict(list)

        for record in dedupe_records(records):
            note = read_note(record)
            seen_ids = set()
            resource_entry = {
                "id": record.id,
                "title": display_title(record, mark_missing=True),
                "type": record.source_type.value,
                "date": learned_date(record).isoformat(),
            }

            tag_sources = [
                ("user", record.tags),
                ("type", [record.source_type.value]),
                ("topic", topic_matches(record, note)),
                ("platform", [record.extra.get("platform")] if record.extra.get("platform") else []),
            ]

            concept_names = self._extract_concept_names(note)
            if concept_names:
                tag_sources.append(("concept", concept_names))

            for source, items in tag_sources:
                for item in items:
                    if not item:
                        continue
                    tag = item.lower().strip()
                    if not tag:
                        continue
                    if (tag, record.id) in seen_ids:
                        continue
                    seen_ids.add((tag, record.id))
                    if resource_entry not in tags[tag]:
                        tags[tag].append(resource_entry)

        return dict(tags)

    def _extract_concept_names(self, note: str) -> List[str]:
        section = extract_section(note, "Related concepts")
        if not section:
            section = extract_section(note, "What this resource covers")
        if not section:
            return []
        names = []
        for line in section.splitlines():
            stripped = line.strip()
            if stripped.startswith(("-", "*")):
                name = stripped.lstrip("-*").strip()
                name = name.split(":")[0].strip("`* ")
                if 2 <= len(name) <= 60:
                    names.append(name)
        return names

    def save(self, tags: Dict[str, List[dict]]) -> Path:
        """Save tags to disk."""
        tags_dir = config.get_data_path("processed", "tags")
        tags_dir.mkdir(parents=True, exist_ok=True)
        for old in list(tags_dir.glob("*.md")) + list(tags_dir.glob("*.json")):
            old.unlink()

        md_content = self._format_tags_markdown(tags)
        md_path = tags_dir / "tags.md"
        Storage.write_text(md_content, md_path)

        data = {
            "tags": tags,
            "generated_at": datetime.utcnow().isoformat(),
            "tag_count": len(tags),
        }
        json_path = tags_dir / "tags.json"
        Storage.write_json(data, json_path)

        return md_path

    def _format_tags_markdown(self, tags: Dict[str, List[dict]]) -> str:
        """Format tags as Markdown with summary table."""
        lines = [
            "# Tags",
            "",
            "Browse resources by tag.",
            "",
            "## Summary",
            "",
            "| Tag | Count |",
            "|---|---:|",
        ]

        for tag in sorted(tags.keys()):
            count = len(tags[tag])
            lines.append(f"| {md_table_cell(tag)} | {count} |")

        lines.extend([""])

        for tag in sorted(tags.keys()):
            resources = tags[tag]
            lines.extend([
                f"## {tag}",
                "",
            ])

            for res in resources:
                lines.append(f"- [{md_table_cell(res['title'])}]({resource_route(res['id'])}) ({md_table_cell(res['type'])})")

            lines.append("")

        lines.extend([
            "## Provenance",
            "",
            f"- Generated: {datetime.utcnow().isoformat()}",
        ])

        return "\n".join(lines)


# Global instance
tags_generator = TagsGenerator()