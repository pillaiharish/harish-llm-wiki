"""Generate gaps report from resources and generated notes."""

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from wiki.config import config
from wiki.generate.page_utils import extract_section, read_note
from wiki.resource_utils import dedupe_records, display_title, topic_matches
from wiki.schemas import ResourceRecord, KnowledgeGap, GapsReport
from wiki.storage import Storage


class GapsGenerator:
    """Generate knowledge gaps report from resources and notes."""

    def generate(self, records: List[ResourceRecord]) -> GapsReport:
        """Generate gaps report from processed resources."""
        report = GapsReport()

        for record in dedupe_records(records):
            note = read_note(record)

            # Needs manual markdown
            if record.status.value == "needs_manual_markdown":
                report.needs_verification.append(KnowledgeGap(
                    concept_name=record.title or record.id,
                    gap_type="needs_manual_markdown",
                    mentioned_in=[record.id],
                    problem_description=record.failure_reason or "Requires manual Markdown import",
                    suggested_action=f"Export to {config.get_data_path('inbox', 'markdown', 'medium')}",
                ))

            # Failed retryable
            if record.status.value == "failed_retryable":
                report.needs_verification.append(KnowledgeGap(
                    concept_name=record.title or record.id,
                    gap_type="failed_retryable",
                    mentioned_in=[record.id],
                    problem_description=record.failure_reason or "Processing failed",
                    suggested_action="Retry with process-new",
                ))

            # Missing metadata
            if not record.title:
                report.resources_missing_metadata.append(f"{record.id}: Missing title")
            if not record.author:
                report.resources_missing_metadata.append(f"{record.id}: Missing author")

            # Weak / fallback notes
            if record.extra.get("note_completed_by_fallback"):
                report.weak_examples.append(KnowledgeGap(
                    concept_name=record.title or record.id,
                    gap_type="fallback_completed",
                    mentioned_in=[record.id],
                    problem_description="Note was completed by deterministic fallback; may lack depth.",
                    suggested_action="Review and regenerate with real LLM.",
                ))
            elif record.extra.get("quality_status") == "weak":
                report.weak_examples.append(KnowledgeGap(
                    concept_name=record.title or record.id,
                    gap_type="weak_note",
                    mentioned_in=[record.id],
                    problem_description="Generated note has weak quality.",
                    suggested_action="Review and improve the note.",
                ))

            # Short notes
            if note and len(note.split()) < 250 and record.status.value == "processed" and "mock-generated" not in note.lower():
                report.weak_examples.append(KnowledgeGap(
                    concept_name=record.title or record.id,
                    gap_type="short_note",
                    mentioned_in=[record.id],
                    problem_description=f"Generated note has only {len(note.split())} words.",
                    suggested_action="Regenerate for more depth.",
                ))

            # Missing project connections
            proj_section = extract_section(note, "Harish project connections")
            if proj_section:
                lower = proj_section.lower()
                if any(marker in lower for marker in ["requires human review", "not covered", "needs review"]):
                    report.missing_project_connection.append(KnowledgeGap(
                        concept_name=record.title or record.id,
                        gap_type="missing_project_connections",
                        mentioned_in=[record.id],
                        problem_description="Harish project connections section needs review.",
                        suggested_action="Add specific project connections.",
                    ))

            # Needs verification section from notes
            needs_section = extract_section(note, "Needs verification")
            if needs_section and len(needs_section.strip()) > 5:
                items = [line.lstrip("-* ").strip() for line in needs_section.splitlines()
                          if line.strip().startswith(("-", "*")) and line.strip()]
                if items and "none" not in needs_section.lower():
                    report.weak_examples.append(KnowledgeGap(
                        concept_name=record.title or record.id,
                        gap_type="needs_verification",
                        mentioned_in=[record.id],
                        problem_description=f"Note has {len(items)} items needing verification.",
                        suggested_action="Review and verify claims.",
                    ))

        # Group missing prerequisites and next topics across all records
        prereq_accumulator: Dict[str, List[str]] = defaultdict(list)
        next_accumulator: Dict[str, List[str]] = defaultdict(list)
        for record in dedupe_records(records):
            note = read_note(record)
            prereq_section = extract_section(note, "Recommended prerequisites")
            for name in self._extract_not_yet_in_wiki(prereq_section):
                if record.id not in prereq_accumulator[name]:
                    prereq_accumulator[name].append(record.id)
            next_section = extract_section(note, "Suggested next learning topics")
            for name in self._extract_not_yet_in_wiki(next_section):
                if record.id not in next_accumulator[name]:
                    next_accumulator[name].append(record.id)

        for topic_name, resource_ids in prereq_accumulator.items():
            report.needs_verification.append(KnowledgeGap(
                concept_name=topic_name,
                gap_type="missing_prerequisite",
                mentioned_in=resource_ids,
                problem_description=f"Prerequisite '{topic_name}' is not yet in the wiki.",
                suggested_action=f"Add a resource covering {topic_name}.",
            ))

        for topic_name, resource_ids in next_accumulator.items():
            report.needs_verification.append(KnowledgeGap(
                concept_name=topic_name,
                gap_type="missing_next_topic",
                mentioned_in=resource_ids,
                problem_description=f"Next topic '{topic_name}' is not yet in the wiki.",
                suggested_action=f"Add a resource covering {topic_name}.",
            ))

        return report

    @staticmethod
    def _extract_not_yet_in_wiki(section: str) -> list[str]:
        """Extract items marked as 'not yet in wiki' from a section."""
        if not section:
            return []
        results = []
        for line in section.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("-", "*")):
                continue
            text = stripped.lstrip("-* ").strip()
            if "not yet in wiki" in text.lower():
                name = text.replace("not yet in wiki", "").strip().rstrip("—–-: ").strip()
                if name:
                    results.append(name)
        return results

    @staticmethod
    def _group_by_name(names: list[str], resource_id: str) -> dict[str, list[str]]:
        """Group duplicate topic names and track which resources mention each."""
        grouped: dict[str, list[str]] = defaultdict(list)
        for name in names:
            if resource_id not in grouped[name]:
                grouped[name].append(resource_id)
        return dict(grouped)

    def save(self, report: GapsReport) -> Path:
        """Save gaps report to disk."""
        gaps_dir = config.get_data_path("processed", "gaps")
        gaps_dir.mkdir(parents=True, exist_ok=True)
        for old in list(gaps_dir.glob("*.md")) + list(gaps_dir.glob("*.json")):
            old.unlink()

        md_content = self._format_gaps_markdown(report)
        md_path = gaps_dir / "gaps.md"
        Storage.write_text(md_content, md_path)

        json_path = gaps_dir / "gaps.json"
        Storage.write_json(report.model_dump(), json_path)

        return md_path

    def _format_gaps_markdown(self, report: GapsReport) -> str:
        """Format gaps report as Markdown."""
        lines = [
            "# Knowledge Gaps",
            "",
            "This page tracks knowledge gaps and areas needing improvement.",
            "",
        ]

        if report.needs_verification:
            lines.extend([
                "## Needs Verification",
                "",
            ])
            for gap in report.needs_verification:
                lines.extend([
                    f"### {gap.concept_name}",
                    f"**Problem:** {gap.problem_description}",
                    f"**Suggested Action:** {gap.suggested_action}",
                    "",
                ])
        else:
            lines.extend(["## Needs Verification", "", "- No gaps detected.", "", ])

        if report.resources_missing_metadata:
            lines.extend([
                "## Resources Missing Metadata",
                "",
            ])
            for item in report.resources_missing_metadata:
                lines.append(f"- {item}")
            lines.append("")

        if report.weak_examples:
            lines.extend([
                "## Weak Notes",
                "",
            ])
            for gap in report.weak_examples:
                lines.extend([
                    f"### {gap.concept_name}",
                    f"**Problem:** {gap.problem_description}",
                    f"**Suggested Action:** {gap.suggested_action}",
                    "",
                ])
        else:
            lines.extend(["## Weak Notes", "", "- No weak notes detected.", "", ])

        if report.missing_project_connection:
            lines.extend([
                "## Missing Project Connections",
                "",
            ])
            for gap in report.missing_project_connection:
                lines.extend([
                    f"### {gap.concept_name}",
                    f"**Problem:** {gap.problem_description}",
                    f"**Suggested Action:** {gap.suggested_action}",
                    "",
                ])
        else:
            lines.extend(["## Missing Project Connections", "", "- No missing project connections detected.", "", ])

        lines.extend([
            "## Provenance",
            "",
            f"- Generated: {report.generated_at.isoformat()}",
        ])

        return "\n".join(lines)


# Global instance
gaps_generator = GapsGenerator()