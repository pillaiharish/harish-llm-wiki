"""Generate review dashboard pages."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from wiki.config import config
from wiki.generate.page_utils import citation_count, extract_section, md_table_cell, read_note, resource_route
from wiki.llm.prompts import PROMPT_VERSION
from wiki.resource_utils import display_title
from wiki.schemas import ResourceRecord, ResourceStatus
from wiki.storage import Storage


GENERIC_PHRASES = ["mock-generated", "placeholder content", "learned about this topic"]


class ReviewGenerator:
    """Generate deterministic review pages from registry and notes."""

    def generate(self, records: list[ResourceRecord]) -> dict[str, list[dict[str, Any]]]:
        data = {"weak": [], "fallback": [], "failed": [], "missing_citations": [], "stale": [], "manual": [], "untitled": []}
        for record in records:
            note = read_note(record)
            title = display_title(record, mark_missing=True)
            base = {
                "id": record.id,
                "title": title,
                "type": record.source_type.value,
                "status": record.status.value,
                "provider": record.llm_provider or "",
                "model": record.llm_model or "",
                "page": resource_route(record.id),
                "source_url": record.original_url,
            }
            weak_reasons = self.weak_reasons(record, note)
            if weak_reasons:
                data["weak"].append({**base, "reason": "; ".join(weak_reasons)})
            if record.extra.get("note_completed_by_fallback"):
                data["fallback"].append({**base, "reason": ", ".join(record.extra.get("quality_issues") or ["fallback completed"])})
            if record.status == ResourceStatus.FAILED_RETRYABLE or record.extra.get("note_generation_success") is False:
                debug = config.get_data_path("debug", "failed_notes", record.id.replace(":", "_"))
                data["failed"].append({**base, "reason": record.failure_reason or "failed_retryable", "debug_path": str(debug)})
            citation_reasons = self.missing_citation_reasons(record, note)
            if citation_reasons:
                data["missing_citations"].append({**base, "reason": "; ".join(citation_reasons)})
            if self.is_stale_for_ollama(record):
                data["stale"].append({**base, "reason": "stale for ollama_cloud"})
            if record.status == ResourceStatus.NEEDS_MANUAL_MARKDOWN:
                data["manual"].append({**base, "reason": record.failure_reason or "needs manual Markdown"})
            if title.endswith("(needs metadata)"):
                data["untitled"].append({**base, "reason": "replaceable title"})
        return data

    def weak_reasons(self, record: ResourceRecord, note: str) -> list[str]:
        reasons: list[str] = []
        if record.extra.get("quality_status") == "weak":
            reasons.append("quality_status=weak")
        if record.extra.get("requires_human_review"):
            reasons.append("requires_human_review")
        if record.extra.get("note_completed_by_fallback"):
            reasons.append("fallback-completed")
        if note and len(note.split()) < 250:
            reasons.append("note is short")
        lowered = note.lower()
        if any(phrase in lowered for phrase in GENERIC_PHRASES):
            reasons.append("generic phrases")
        project = extract_section(note, "Harish project connections")
        if note and (not project or "requires human review" in project.lower()):
            reasons.append("weak Harish project connections")
        if note and citation_count(extract_section(note, "Source-backed summary")) < 3:
            reasons.append("sparse source-backed citations")
        return reasons

    def missing_citation_reasons(self, record: ResourceRecord, note: str) -> list[str]:
        if not note:
            return []
        reasons: list[str] = []
        citations = extract_section(note, "Citations")
        summary = extract_section(note, "Source-backed summary")
        if not citations:
            reasons.append("Citations section missing")
        if citation_count(summary) < 3:
            reasons.append("Source-backed summary has fewer than 3 citations")
        if "[missing source chunk:" in note:
            reasons.append("missing source chunks")
        if record.local_normalized_path:
            chunks_path = Path(record.local_normalized_path) / "chunks.jsonl"
            if not chunks_path.exists():
                reasons.append("chunks.jsonl missing")
        return reasons

    def is_stale_for_ollama(self, record: ResourceRecord) -> bool:
        target_model = config.OLLAMA_CLOUD_MODEL or ""
        if record.status == ResourceStatus.FAILED_RETRYABLE:
            return True
        if not record.generated_note_path or not Path(record.generated_note_path).exists():
            return True
        if record.prompt_version != PROMPT_VERSION:
            return True
        if record.llm_provider and record.llm_provider != "ollama_cloud":
            return True
        if target_model and record.llm_model and record.llm_model != target_model:
            return True
        return False

    def save(self, data: dict[str, list[dict[str, Any]]]) -> Path:
        review_dir = config.get_data_path("processed", "review")
        review_dir.mkdir(parents=True, exist_ok=True)
        for old in list(review_dir.glob("*.md")) + list(review_dir.glob("*.json")):
            old.unlink()
        Storage.write_json({"generated_at": datetime.utcnow().isoformat(), **data}, review_dir / "review.json")
        Storage.write_text(self._index(data), review_dir / "index.md")
        Storage.write_text(self._category("Weak Notes", data["weak"]), review_dir / "weak-notes.md")
        Storage.write_text(self._category("Fallback Notes", data["fallback"]), review_dir / "fallback-notes.md")
        Storage.write_text(self._category("Failed Notes", data["failed"]), review_dir / "failed-notes.md")
        Storage.write_text(self._category("Missing Citations", data["missing_citations"]), review_dir / "missing-citations.md")
        Storage.write_text(self._category("Stale Notes", data["stale"]), review_dir / "stale-notes.md")
        return review_dir

    def _index(self, data: dict[str, list[dict[str, Any]]]) -> str:
        summary = {
            "Weak notes": len(data["weak"]),
            "Fallback-completed notes": len(data["fallback"]),
            "Failed notes": len(data["failed"]),
            "Missing citations": len(data["missing_citations"]),
            "Missing source chunks": sum("missing source chunks" in item.get("reason", "") for item in data["missing_citations"]),
            "Stale for Ollama Cloud": len(data["stale"]),
            "Needs manual Markdown": len(data["manual"]),
            "Untitled resources": len(data["untitled"]),
        }
        lines = ["# Review Dashboard", "", "## Summary", "", "| Category | Count |", "|---|---:|"]
        lines.extend(f"| {key} | {value} |" for key, value in summary.items())
        lines.extend(["", "## Priority review queue", "", "| Priority | Resource | Reason | Status | Link |", "|---|---|---|---|---|"])
        queue = [("High", item) for item in data["failed"]] + [("High", item) for item in data["fallback"]] + [("Medium", item) for item in data["weak"]]
        for priority, item in queue[:50]:
            lines.append(
                f"| {priority} | {md_table_cell(item['title'])} | {md_table_cell(item.get('reason'))} | "
                f"{md_table_cell(item['status'])} | [Open]({item['page']}) |"
            )
        if not queue:
            lines.append("| - | No review items | - | - | - |")
        lines.extend(["", "## Provenance", "", f"- Generated: {datetime.utcnow().isoformat()}"])
        return "\n".join(lines) + "\n"

    def _category(self, title: str, items: list[dict[str, Any]]) -> str:
        lines = [f"# {title}", "", "| Resource | Type | Provider/model | Reason | Source |", "|---|---|---|---|---|"]
        for item in items:
            provider = f"{item.get('provider') or '-'} / {item.get('model') or '-'}"
            lines.append(
                f"| [{md_table_cell(item['title'])}]({item['page']}) | {md_table_cell(item['type'])} | {md_table_cell(provider)} | "
                f"{md_table_cell(item.get('reason'))} | {md_table_cell(item.get('source_url'))} |"
            )
        if not items:
            lines.append("| No items | - | - | - | - |")
        lines.extend(["", "## Provenance", "", f"- Generated: {datetime.utcnow().isoformat()}"])
        return "\n".join(lines) + "\n"


review_generator = ReviewGenerator()
