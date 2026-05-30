"""Generate gaps report from resources."""

from datetime import datetime
from pathlib import Path
from typing import List

from wiki.config import config
from wiki.schemas import ResourceRecord, KnowledgeGap, GapsReport
from wiki.storage import Storage


class GapsGenerator:
    """Generate knowledge gaps report."""
    
    def generate(self, records: List[ResourceRecord]) -> GapsReport:
        """Generate gaps report from processed resources."""
        report = GapsReport()
        
        for record in records:
            # Check for resources needing human review
            if record.status.value == "needs_manual_markdown":
                gap = KnowledgeGap(
                    concept_name=record.title or record.id,
                    gap_type="needs_manual_markdown",
                    mentioned_in=[record.id],
                    problem_description=record.failure_reason or "Requires manual Markdown import",
                    suggested_action=f"Export to {config.get_data_path('inbox', 'markdown', 'medium')}"
                )
                report.needs_verification.append(gap)
            
            # Check for missing metadata
            if not record.title:
                report.resources_missing_metadata.append(
                    f"{record.id}: Missing title"
                )
            
            if not record.author:
                report.resources_missing_metadata.append(
                    f"{record.id}: Missing author"
                )
            
            # Check for failed resources
            if record.status.value == "failed_retryable":
                gap = KnowledgeGap(
                    concept_name=record.title or record.id,
                    gap_type="failed_retryable",
                    mentioned_in=[record.id],
                    problem_description=record.failure_reason or "Processing failed",
                    suggested_action="Retry with process-new"
                )
                report.needs_verification.append(gap)
            
            # Check for resources with weak examples
            # This would require analyzing the generated notes
            # For now, we use a placeholder
            
        return report
    
    def save(self, report: GapsReport) -> Path:
        """Save gaps report to disk."""
        gaps_dir = config.get_data_path("processed", "gaps")
        gaps_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate Markdown
        md_content = self._format_gaps_markdown(report)
        md_path = gaps_dir / "gaps.md"
        Storage.write_text(md_content, md_path)
        
        # Generate JSON
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
        
        # Needs verification
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
        
        # Resources with missing metadata
        if report.resources_missing_metadata:
            lines.extend([
                "## Resources Missing Metadata",
                "",
            ])
            for item in report.resources_missing_metadata:
                lines.append(f"- {item}")
            lines.append("")
        
        # Add placeholder sections for other gap types
        lines.extend([
            "## Weak Examples",
            "",
            "_To be populated based on analysis of generated notes._",
            "",
            "## Missing Project Connections",
            "",
            "_To be populated based on analysis of generated notes._",
            "",
            "## Provenance",
            "",
            f"- Generated: {report.generated_at.isoformat()}",
        ])
        
        return "\n".join(lines)


# Global instance
gaps_generator = GapsGenerator()
