"""Generate deterministic topic map pages."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from wiki.config import config
from wiki.resource_utils import (
    TOPIC_DEFINITIONS,
    dedupe_records,
    display_title,
    learned_date,
    resource_page_name,
    topic_matches,
)
from wiki.schemas import ResourceRecord
from wiki.storage import Storage


class TopicGenerator:
    """Generate topic index and topic pages from registry metadata."""

    def generate(self, records: list[ResourceRecord]) -> dict[str, list[ResourceRecord]]:
        """Assign resources to topics."""
        topics: dict[str, list[ResourceRecord]] = {slug: [] for slug in TOPIC_DEFINITIONS}
        for record in dedupe_records(records):
            note_text = ""
            if record.generated_note_path and record.generated_note_path.exists():
                note_text = Storage.read_text(record.generated_note_path)
            for slug in topic_matches(record, note_text):
                if slug in topics:
                    topics[slug].append(record)
        return {slug: dedupe_records(items) for slug, items in topics.items() if items}

    def save(self, topics: dict[str, list[ResourceRecord]]) -> Path:
        """Save topic pages under processed/topics."""
        topics_dir = config.get_data_path("processed", "topics")
        topics_dir.mkdir(parents=True, exist_ok=True)
        for old_file in topics_dir.glob("*.md"):
            old_file.unlink()
        for old_file in topics_dir.glob("*.json"):
            old_file.unlink()

        Storage.write_text(self._format_index(topics), topics_dir / "index.md")
        Storage.write_json(self._json_data(topics), topics_dir / "topics.json")

        for slug, records in topics.items():
            Storage.write_text(self._format_topic(slug, records), topics_dir / f"{slug}.md")
        return topics_dir

    def _format_index(self, topics: dict[str, list[ResourceRecord]]) -> str:
        lines = ["# Topic Map", "", "Browse the wiki as a curriculum.", ""]
        for slug in TOPIC_DEFINITIONS:
            if slug not in topics:
                continue
            definition = TOPIC_DEFINITIONS[slug]
            lines.append(f"- [{definition['name']}](./{slug}.md) ({len(topics[slug])} resources)")
        lines.extend(["", "## Provenance", "", f"- Generated: {datetime.utcnow().isoformat()}"])
        return "\n".join(lines)

    def _format_topic(self, slug: str, records: list[ResourceRecord]) -> str:
        definition = TOPIC_DEFINITIONS[slug]
        ordered = sorted(records, key=learned_date)
        lines = [
            f"# Topic: {definition['name']}",
            "",
            "## Learning path",
            "",
        ]
        for index, step in enumerate(definition["learning_path"], start=1):
            lines.append(f"{index}. {step}")
        lines.extend([
            "",
            "## Resources in chronological order",
            "",
            "| Date learned | Resource | Type | Why useful | Status |",
            "|---|---|---|---|---|",
        ])
        for record in ordered:
            date = learned_date(record).strftime("%Y-%m-%d")
            title = display_title(record, mark_missing=True)
            link = f"[{title}](../resources/{resource_page_name(record.id)})"
            why = record.notes_from_user or record.description or "Needs review"
            lines.append(
                f"| {date} | {link} | {record.source_type.value} | "
                f"{self._table_value(why[:100])} | {record.status.value} |"
            )
        lines.extend([
            "",
            "## Source-backed concepts",
            "",
            "_Use linked resource pages for cited notes._",
            "",
            "## Gaps / needs review",
            "",
        ])
        for record in ordered:
            if display_title(record, mark_missing=True).endswith("(needs metadata)"):
                lines.append(f"- {record.id}: needs metadata")
        if lines[-1] == "":
            lines.append("- None recorded.")
        lines.extend([
            "",
            "## Suggested next resources",
            "",
            "_Add candidate resources here after review._",
            "",
            "## Provenance",
            "",
            f"- Generated: {datetime.utcnow().isoformat()}",
        ])
        return "\n".join(lines)

    def _json_data(self, topics: dict[str, list[ResourceRecord]]) -> dict[str, Any]:
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "topics": {
                slug: [
                    {
                        "id": record.id,
                        "title": display_title(record, mark_missing=True),
                        "type": record.source_type.value,
                        "date": learned_date(record).isoformat(),
                    }
                    for record in records
                ]
                for slug, records in topics.items()
            },
        }

    def _table_value(self, value: str) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")


topic_generator = TopicGenerator()

