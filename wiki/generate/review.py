"""Generate review dashboard pages."""

from __future__ import annotations

from datetime import datetime
from html import escape
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
        lines.extend(
            [
                "",
                "## Priority review queue",
                "",
                "These items need the fastest manual pass. Reasons are shown in",
                "human-readable form first, with the raw machine signal preserved",
                "for provenance.",
                "",
                '<div class="review-priority-grid">',
            ]
        )
        queue = (
            [("High", item, "View failed notes", "/review/failed-notes") for item in data["failed"]]
            + [("High", item, "View fallback notes", "/review/fallback-notes") for item in data["fallback"]]
            + [("Medium", item, "View weak notes", "/review/weak-notes") for item in data["weak"]]
        )
        for priority, item, detail_label, detail_page in queue[:50]:
            lines.extend(self._priority_card(priority, item, detail_label, detail_page))
        if not queue:
            lines.append('<p class="review-empty-state">No priority review items.</p>')
        lines.append("</div>")
        lines.extend(["", "## Provenance", "", f"- Generated: {datetime.utcnow().isoformat()}"])
        return "\n".join(lines) + "\n"

    def _category(self, title: str, items: list[dict[str, Any]]) -> str:
        lines = [f"# {title}", "", "| Resource | Type | Provider/model | Reason | Source |", "|---|---|---|---|---|"]
        for item in items:
            provider = f"{item.get('provider') or '-'} / {item.get('model') or '-'}"
            reason = self._reason_with_provenance(item.get("reason"))
            lines.append(
                f"| [{md_table_cell(item['title'])}]({item['page']}) | {md_table_cell(item['type'])} | {md_table_cell(provider)} | "
                f"{md_table_cell(reason)} | {md_table_cell(item.get('source_url'))} |"
            )
        if not items:
            lines.append("| No items | - | - | - | - |")
        lines.extend(["", "## Provenance", "", f"- Generated: {datetime.utcnow().isoformat()}"])
        return "\n".join(lines) + "\n"

    def _priority_card(
        self,
        priority: str,
        item: dict[str, Any],
        detail_label: str,
        detail_page: str,
    ) -> list[str]:
        raw_reason = str(item.get("reason") or "")
        raw_status = str(item.get("status") or "")
        resource_id = str(item.get("id") or "")
        title = escape(str(item.get("title") or "Untitled resource"))
        page = escape(str(item.get("page") or "#"), quote=True)
        detail_href = escape(detail_page, quote=True)
        priority_class = escape(priority.lower().replace(" ", "-"), quote=True)
        reason = escape(self.humanize_reason(raw_reason))
        status = escape(self.humanize_status(raw_status))
        raw_reason_html = escape(raw_reason) if raw_reason else "none"
        raw_status_html = escape(raw_status) if raw_status else "none"
        resource_id_html = escape(resource_id) if resource_id else "unknown"
        return [
            '  <article class="review-priority-card">',
            '    <div class="review-card-header">',
            f'      <span class="review-priority-badge review-priority-{priority_class}">{escape(priority)}</span>',
            f'      <span class="wiki-chip">{status}</span>',
            "    </div>",
            f'    <h3><a href="{page}">{title}</a></h3>',
            f'    <p class="review-reason">{reason}</p>',
            '    <div class="review-card-actions">',
            f'      <a class="review-open-link" href="{page}">Open resource</a>',
            f'      <a class="review-secondary-link" href="{detail_href}">{escape(detail_label)}</a>',
            "    </div>",
            f'    <p class="review-resource-id"><span>Resource id</span><code>{resource_id_html}</code></p>',
            '    <details class="review-provenance">',
            "      <summary>Raw provenance</summary>",
            "      <dl>",
            f"        <dt>Raw reason</dt><dd><code>{raw_reason_html}</code></dd>",
            f"        <dt>Raw status</dt><dd><code>{raw_status_html}</code></dd>",
            "      </dl>",
            "    </details>",
            "  </article>",
        ]

    def _reason_with_provenance(self, reason: str | None) -> str:
        raw = str(reason or "")
        human = self.humanize_reason(raw)
        if not raw or human == raw:
            return human
        return f"{human} (raw: {raw})"

    def humanize_reason(self, reason: str | None) -> str:
        raw = str(reason or "").strip()
        if not raw:
            return "Needs review"
        labels = []
        for part in raw.replace(",", ";").split(";"):
            token = part.strip()
            if not token:
                continue
            labels.append(self._human_reason_part(token))
        return "; ".join(labels) if labels else "Needs review"

    def humanize_status(self, status: str | None) -> str:
        raw = str(status or "").strip()
        if not raw:
            return "Unknown status"
        status_map = {
            "llm_cache_hit": "LLM cache hit",
            "failed_retryable": "Failed, retryable",
            "failed_permanent": "Failed permanently",
            "needs_manual_markdown": "Needs manual Markdown",
            "processed": "Processed",
            "raw_saved": "Raw saved",
            "normalized": "Normalized",
            "duplicate_skipped": "Duplicate skipped",
        }
        return status_map.get(raw, raw.replace("_", " ").replace("-", " ").title())

    def _human_reason_part(self, reason: str) -> str:
        reason_map = {
            "quality_status=weak": "Marked weak by quality checks",
            "requires_human_review": "Requires human review",
            "fallback-completed": "Completed by deterministic fallback",
            "fallback completed": "Completed by deterministic fallback",
            "contract_completed_by_deterministic_fallback": "Contract completed by deterministic fallback",
            "note is short": "Note is short",
            "generic phrases": "Contains generic phrases",
            "weak Harish project connections": "Weak Harish project connections",
            "sparse source-backed citations": "Sparse source-backed citations",
            "failed_retryable": "Failed, retryable",
            "Citations section missing": "Citations section missing",
            "Source-backed summary has fewer than 3 citations": "Source-backed summary has fewer than 3 citations",
            "missing source chunks": "Missing source chunks",
            "chunks.jsonl missing": "Chunk index file missing",
            "stale for ollama_cloud": "Stale for Ollama Cloud",
            "needs manual Markdown": "Needs manual Markdown",
            "replaceable title": "Replaceable title",
        }
        if reason in reason_map:
            return reason_map[reason]
        return reason.replace("_", " ").replace("-", " ").strip().capitalize()


review_generator = ReviewGenerator()
