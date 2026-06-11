"""Generate learning timeline from resources."""

from datetime import datetime
from pathlib import Path
from collections import defaultdict

from wiki.config import config
from wiki.generate.page_utils import md_table_cell, resource_route
from wiki.resource_utils import (
    TOPIC_DEFINITIONS,
    dedupe_records,
    display_title,
    learned_date,
    resource_page_name,
    topic_matches,
)
from wiki.schemas import ResourceRecord, TimelineEntry, TimelinePeriod
from wiki.storage import Storage


def format_period_label(dt: datetime) -> str:
    """Format datetime as 'Month YYYY'."""
    return dt.strftime("%B %Y")


class TimelineGenerator:
    """Generate learning timeline from processed resources."""
    
    def generate(self, records: list[ResourceRecord]) -> list[TimelinePeriod]:
        """Generate timeline from resources.
        
        Groups resources by month/year and organizes entries.
        """
        # Collect all entries
        entries: list[TimelineEntry] = []
        
        for record in dedupe_records(records):
            # Determine date for timeline
            date = learned_date(record)
            
            note_text = ""
            if record.generated_note_path and record.generated_note_path.exists():
                note_text = Storage.read_text(record.generated_note_path)
            concepts = topic_matches(record, note_text) or record.tags
            
            entry = TimelineEntry(
                date=date,
                period_label=format_period_label(date),
                resource_id=record.id,
                resource_title=display_title(record, mark_missing=True),
                resource_type=record.source_type,
                concepts_learned=concepts,
                summary=self._summary(record)
            )
            
            entries.append(entry)
        
        # Sort by date (newest first)
        entries.sort(key=lambda e: e.date, reverse=True)
        
        # Group by period
        periods_dict = defaultdict(list)
        for entry in entries:
            periods_dict[entry.period_label].append(entry)
        
        # Create periods
        periods: list[TimelinePeriod] = []
        for period_label, period_entries in periods_dict.items():
            # Collect all concepts
            all_concepts = set()
            for entry in period_entries:
                all_concepts.update(entry.concepts_learned)
            
            period = TimelinePeriod(
                period_label=period_label,
                entries=period_entries,
                concepts_learned=sorted(list(all_concepts))
            )
            periods.append(period)
        
        # Sort periods by date (newest first)
        periods.sort(key=lambda p: datetime.strptime(p.period_label, "%B %Y"), reverse=True)
        
        return periods
    
    def save(self, periods: list[TimelinePeriod]) -> Path:
        """Save timeline to disk.
        
        Returns path to timeline file.
        """
        timeline_dir = config.get_data_path("processed", "timeline")
        timeline_dir.mkdir(parents=True, exist_ok=True)
        for old in list(timeline_dir.glob("*.md")) + list(timeline_dir.glob("*.json")):
            old.unlink()
        
        # Generate Markdown
        md_content = self._format_timeline_markdown(periods)
        md_path = timeline_dir / "timeline.md"
        Storage.write_text(md_content, md_path)
        
        # Generate JSON
        data = {
            "periods": [p.model_dump() for p in periods],
            "generated_at": datetime.utcnow().isoformat()
        }
        json_path = timeline_dir / "timeline.json"
        Storage.write_json(data, json_path)
        
        return md_path
    
    def _format_timeline_markdown(self, periods: list[TimelinePeriod]) -> str:
        """Format timeline as Markdown."""
        lines = [
            "# Learning Timeline",
            "",
            "A chronological view of what I've learned.",
            "",
        ]
        uncategorized_anchor_written = False
        
        for period in periods:
            lines.extend([
                f"## {period.period_label}",
                "",
            ])
            
            grouped = defaultdict(list)
            for entry in period.entries:
                topic = entry.concepts_learned[0] if entry.concepts_learned else "uncategorized"
                grouped[topic].append(entry)

            for topic_slug in sorted(grouped):
                if topic_slug == "uncategorized":
                    topic_name = "Needs classification"
                    lines.extend(
                        self._classification_section_lines(
                            heading=topic_name,
                            include_anchors=not uncategorized_anchor_written,
                        )
                    )
                    uncategorized_anchor_written = True
                else:
                    topic_name = TOPIC_DEFINITIONS.get(topic_slug, {}).get("name", topic_slug.title())
                    lines.extend([f"### {topic_name}", ""])
                for entry in grouped[topic_slug]:
                    lines.append(f"- [{md_table_cell(entry.resource_title)}]({resource_route(entry.resource_id)}) ({entry.resource_type.value})")
                    if entry.summary:
                        lines.append(f"  - {entry.summary}")
                lines.append("")
            
            lines.append("---")
            lines.append("")

        if not uncategorized_anchor_written:
            lines.extend(
                self._classification_section_lines(
                    heading="Needs classification",
                    include_anchors=True,
                )
            )
            lines.extend(["_No resources currently need classification._", ""])
        
        return "\n".join(lines)

    def _classification_section_lines(self, *, heading: str, include_anchors: bool) -> list[str]:
        """Return the timeline classification guidance section."""

        lines: list[str] = []
        if include_anchors:
            lines.extend(
                [
                    '<span id="needs-classification"></span>',
                    '<span id="uncategorized"></span>',
                    "",
                ]
            )
        lines.extend(
            [
                f"### {heading}",
                "",
                '<div class="timeline-classification-note">',
                "These resources are intake items missing topic or concept",
                "metadata. They are not learning categories yet.",
                'Fix them from <a href="/review/">Review</a>,',
                '<a href="/resources/">Resources</a>, or the',
                '<a href="/ingest/">Ingest workflow</a>.',
                '<a class="timeline-classification-cta" href="/ingest/#after-ingest">Fix classification metadata</a>',
                "</div>",
                "",
            ]
        )
        return lines

    def _summary(self, record: ResourceRecord) -> str:
        """Return a compact one-line timeline summary."""
        raw = record.notes_from_user or record.description or "Needs review"
        summary = " ".join(str(raw).split())
        return summary[:197] + "..." if len(summary) > 200 else summary


# Global instance
timeline_generator = TimelineGenerator()
