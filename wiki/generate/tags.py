"""Generate tags page from resources."""

import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Dict, List

from wiki.config import config
from wiki.schemas import ResourceRecord
from wiki.storage import Storage


class TagsGenerator:
    """Generate tags aggregation from resources."""
    
    def generate(self, records: List[ResourceRecord]) -> Dict[str, List[dict]]:
        """Generate tags to resources mapping.
        
        Returns a dictionary mapping tag names to lists of resource summaries.
        """
        tags: Dict[str, List[dict]] = defaultdict(list)
        
        for record in records:
            for tag in record.tags:
                tags[tag].append({
                    "id": record.id,
                    "title": record.title or "Untitled",
                    "type": record.source_type.value,
                    "date": record.user_consumed_at.isoformat() if record.user_consumed_at else None,
                })
        
        return dict(tags)
    
    def save(self, tags: Dict[str, List[dict]]) -> Path:
        """Save tags to disk."""
        tags_dir = config.get_data_path("processed", "tags")
        tags_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate Markdown
        md_content = self._format_tags_markdown(tags)
        md_path = tags_dir / "tags.md"
        Storage.write_text(md_content, md_path)
        
        # Generate JSON
        data = {
            "tags": tags,
            "generated_at": datetime.utcnow().isoformat()
        }
        json_path = tags_dir / "tags.json"
        Storage.write_json(data, json_path)
        
        return md_path
    
    def _format_tags_markdown(self, tags: Dict[str, List[dict]]) -> str:
        """Format tags as Markdown."""
        lines = [
            "# Tags",
            "",
            "Browse resources by tag.",
            "",
        ]
        
        # Sort tags alphabetically
        for tag in sorted(tags.keys()):
            resources = tags[tag]
            lines.extend([
                f"## {tag}",
                "",
            ])
            
            for res in resources:
                lines.append(f"- {res['title']} ({res['type']})")
            
            lines.append("")
        
        lines.extend([
            "## Provenance",
            "",
            f"- Generated: {datetime.utcnow().isoformat()}",
        ])
        
        return "\n".join(lines)


# Global instance
tags_generator = TagsGenerator()
