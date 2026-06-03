"""Generate deterministic chapter-style Learn pages."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from wiki.config import config
from wiki.generate.page_utils import bullet_lines, extract_section, learn_route, md_table_cell, read_note, resource_link, resource_route
from wiki.resource_utils import LEARN_DEFINITION_SLUGS, TOPIC_DEFINITIONS, dedupe_records, display_title, learned_date, topic_matches
from wiki.schemas import ResourceRecord
from wiki.storage import Storage


PROJECTS = [
    "RAGOpsBench",
    "LLM wiki",
    "DNS/security + AI projects",
    "local media transcript wiki",
    "OCR/search/document-engine project",
]


class LearnGenerator:
    """Build source-aware Learn chapter pages without LLM calls."""

    def generate(self, records: list[ResourceRecord]) -> dict[str, list[ResourceRecord]]:
        chapters: dict[str, list[ResourceRecord]] = {slug: [] for slug in LEARN_DEFINITION_SLUGS}
        for record in dedupe_records(records):
            note = read_note(record)
            matched = set(topic_matches(record, note))
            title_note = " ".join([display_title(record), " ".join(record.tags), note[:5000]]).lower()
            for slug in LEARN_DEFINITION_SLUGS:
                definition = TOPIC_DEFINITIONS[slug]
                if slug in matched or any(keyword in title_note for keyword in definition["keywords"]):
                    chapters[slug].append(record)
        return {slug: dedupe_records(items) for slug, items in chapters.items()}

    def save(self, chapters: dict[str, list[ResourceRecord]]) -> Path:
        learn_dir = config.get_data_path("processed", "learn")
        learn_dir.mkdir(parents=True, exist_ok=True)
        for old in list(learn_dir.glob("*.md")) + list(learn_dir.glob("*.json")):
            old.unlink()
        Storage.write_text(self._format_index(chapters), learn_dir / "index.md")
        for slug in LEARN_DEFINITION_SLUGS:
            Storage.write_text(self._format_chapter(slug, chapters.get(slug, [])), learn_dir / f"{slug}.md")
        Storage.write_json(self._json_data(chapters), learn_dir / "learn.json")
        return learn_dir

    def _format_index(self, chapters: dict[str, list[ResourceRecord]]) -> str:
        lines = ["# Learn", "", "Chapter-style synthesis pages built from Harish's collected resources.", ""]
        for slug in LEARN_DEFINITION_SLUGS:
            definition = TOPIC_DEFINITIONS[slug]
            lines.append(f"- [{definition['name']}]({learn_route(slug)}) ({len(chapters.get(slug, []))} resources)")
        lines.extend(["", "## Provenance", "", f"- Generated: {datetime.utcnow().isoformat()}"])
        return "\n".join(lines) + "\n"

    def _format_chapter(self, slug: str, records: list[ResourceRecord]) -> str:
        definition = TOPIC_DEFINITIONS[slug]
        ordered = sorted(dedupe_records(records), key=learned_date)
        lines = [
            f"# Topic: {definition['name']}",
            "",
            "## What this topic is about",
            "",
            self._topic_intro(definition["name"]),
            "",
            "## Why Harish should care",
            "",
        ]
        lines.extend(f"- Connects to {project}." for project in PROJECTS)
        lines.extend(["", "## Prerequisites", ""])
        for prereq in self._prerequisites(slug):
            linked = self._learn_link_for_prereq(prereq)
            lines.append(f"- {linked}")
        lines.extend(["", "## Learning path", ""])
        for index, step in enumerate(definition["learning_path"], start=1):
            lines.append(f"{index}. {step}")
        lines.extend(["", "## Source-backed synthesis", ""])
        synthesis = self._source_backed_synthesis(ordered)
        lines.extend(synthesis or ["- Needs more source-backed material before this chapter is complete."])
        lines.extend(["", "## Examples / toy implementation", ""])
        lines.extend(self._examples(ordered))
        lines.extend(["", "## Gaps and weak evidence", ""])
        gaps = self._gaps(ordered)
        lines.extend(gaps or ["- No weak evidence recorded yet."])
        lines.extend(["", "## Next learning steps", ""])
        lines.extend(self._next_steps(ordered))
        lines.extend(["", "## Related resources", "", "| Date | Resource | Type | Status |", "|---|---|---|---|"])
        for record in ordered:
            title = display_title(record, mark_missing=True)
            lines.append(
                f"| {learned_date(record).date().isoformat()} | {resource_link(record, title)} | "
                f"{md_table_cell(record.source_type.value)} | {md_table_cell(record.status.value)} |"
            )
        if not ordered:
            lines.append("| - | Needs more resources | - | - |")
        lines.extend(["", "## Provenance", "", f"- Generated: {datetime.utcnow().isoformat()}"])
        return "\n".join(lines) + "\n"

    def _topic_intro(self, name: str) -> str:
        return f"{name} is a learning chapter synthesized from existing wiki resources. Claims are only promoted when they can be traced to cited resource notes."

    def _prerequisites(self, slug: str) -> list[str]:
        defaults = {
            "rag-retrieval": ["Embeddings", "Chunking", "Evaluation"],
            "embeddings": ["Vectors", "Cosine similarity", "Python basics"],
            "llm-inference": ["Transformer basics", "GPU memory", "Batching"],
            "vllm": ["LLM inference", "KV cache", "Batching"],
            "llm-evals": ["Prompting", "Metrics", "Failure analysis"],
            "agents": ["Tool calling", "APIs", "Evaluation"],
            "ai-security": ["Threat modeling", "Prompt injection", "Connectors"],
            "optimizer-training": ["Gradients", "Loss functions", "Linear algebra"],
            "linear-algebra": ["Vectors", "Matrices", "Systems of equations"],
            "transcription-asr": ["Audio basics", "ffmpeg", "Transcript chunking"],
        }
        return defaults.get(slug, ["Source-backed notes"])

    def _learn_link_for_prereq(self, prereq: str) -> str:
        key = prereq.lower()
        for slug in LEARN_DEFINITION_SLUGS:
            if key in TOPIC_DEFINITIONS[slug]["name"].lower():
                return f"[{prereq}]({learn_route(slug)})"
        return f"{prereq} (not yet in wiki)"

    def _source_backed_synthesis(self, records: list[ResourceRecord]) -> list[str]:
        lines: list[str] = []
        for record in records:
            note = read_note(record)
            summary = extract_section(note, "Source-backed summary")
            for bullet in bullet_lines(summary):
                if "c000" in bullet or "p000" in bullet or "-t" in bullet or "<!--" in bullet:
                    title = display_title(record, mark_missing=True)
                    lines.append(f"{bullet} Source: {resource_link(record, title)}")
                if len(lines) >= 12:
                    return lines
        return lines

    def _examples(self, records: list[ResourceRecord]) -> list[str]:
        for record in records:
            example = extract_section(read_note(record), "Concrete example / toy implementation")
            if example:
                title = display_title(record, mark_missing=True)
                return [f"From {resource_link(record, title)}:", "", example[:1200]]
        return ["- Needs a source-backed example from future notes."]

    def _gaps(self, records: list[ResourceRecord]) -> list[str]:
        gaps: list[str] = []
        for record in records:
            if record.extra.get("requires_human_review") or record.extra.get("quality_status") == "weak":
                gaps.append(f"- {resource_link(record, display_title(record, mark_missing=True))}: requires review.")
            needs = extract_section(read_note(record), "Needs verification")
            if needs and "none" not in needs.lower():
                gaps.append(f"- {resource_link(record, display_title(record, mark_missing=True))}: {needs.splitlines()[0][:160]}")
        return gaps[:10]

    def _next_steps(self, records: list[ResourceRecord]) -> list[str]:
        steps: list[str] = []
        for record in records:
            section = extract_section(read_note(record), "Suggested next learning topics")
            steps.extend(bullet_lines(section))
        return steps[:8] or ["- Add more resources and regenerate this Learn chapter."]

    def _json_data(self, chapters: dict[str, list[ResourceRecord]]) -> dict[str, Any]:
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "chapters": {
                slug: {
                    "title": TOPIC_DEFINITIONS[slug]["name"],
                    "resource_ids": [record.id for record in records],
                    "resource_count": len(records),
                }
                for slug, records in chapters.items()
            },
        }


learn_generator = LearnGenerator()
