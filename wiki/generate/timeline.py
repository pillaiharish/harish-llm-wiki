"""Generate learning timeline from resources."""

from datetime import datetime
from pathlib import Path
from typing import List, Iterator
from collections import defaultdict

from wiki.config import config
from wiki.schemas import ResourceRecord, TimelineEntry, TimelinePeriod
from wiki.storage import Storage


def format_period_label(dt: datetime) -> str:
    """Format datetime as 'Month YYYY'."""
    return dt.strftime("%B %Y")


class TimelineGenerator:
    """Generate learning timeline from processed resources."""
    
    def generate(self, records: List[ResourceRecord]) -> List[TimelinePeriod]:
        """Generate timeline from resources.
        
        Groups resources by month/year and organizes entries.
        """
        # Collect all entries
        entries: List[TimelineEntry] = []
        
        for record in records:
            # Determine date for timeline
            date = None
            if record.user_consumed_at:
                date = record.user_consumed_at
            elif record.processed_at:
                date = record.processed_at
            elif record.first_seen_at:
                date = record.first_seen_at
            else:
                date = datetime.utcnow()
            
            # Extract concepts from record (simplified)
            concepts = record.tags  # Use tags as concepts for now
            
            entry = TimelineEntry(
                date=date,
                period_label=format_period_label(date),
                resource_id=record.id,
                resource_title=record.title or "Untitled",
                resource_type=record.source_type,
                concepts_learned=concepts,
                summary=record.notes_from_user or f"Learned about {record.title or 'this topic'}"
            )
            
            entries.append(entry)
        
        # Sort by date (newest first)
        entries.sort(key=lambda e: e.date, reverse=True)
        
        # Group by period
        periods_dict = defaultdict(list)
        for entry in entries:
            periods_dict[entry.period_label].append(entry)
        
        # Create periods
        periods: List[TimelinePeriod] = []
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
    
    def save(self, periods: List[TimelinePeriod]) -> Path:
        """Save timeline to disk.
        
        Returns path to timeline file.
        """
        timeline_dir = config.get_data_path("processed", "timeline")
        timeline_dir.mkdir(parents=True, exist_ok=True)
        
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
    
    def _format_timeline_markdown(self, periods: List[TimelinePeriod]) -> str:
        """Format timeline as Markdown."""
        lines = [
            "# Learning Timeline",
            "",
            "A chronological view of what I've learned.",
            "",
        ]
        
        for period in periods:
            lines.extend([
                f"## {period.period_label}",
                "",
            ])
            
            if period.concepts_learned:
                lines.append("**Concepts:** " + ", ".join(period.concepts_learned))
                lines.append("")
            
            for entry in period.entries:
                lines.append(f"### {entry.resource_title}")
                lines.append(f"- **Type:** {entry.resource_type.value}")
                lines.append(f"- **Summary:** {entry.summary}")
                if entry.concepts_learned:
                    lines.append(f"- **Concepts:** {', '.join(entry.concepts_learned)}")
                lines.append("")
            
            lines.append("---")
            lines.append("")
        
        return "\n".join(lines)


# Global instance
timeline_generator = TimelineGenerator()
