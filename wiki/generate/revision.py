"""Generate active recall pages and flashcard exports."""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from wiki.config import config
from wiki.generate.page_utils import bullet_lines, extract_section, learn_route, md_table_cell, read_note, resource_route
from wiki.resource_utils import display_title, normalize_topic_slug, topic_matches
from wiki.schemas import ResourceRecord
from wiki.storage import Storage


QUESTION_RE = re.compile(r"^(?:[-*]|\d+[.)])\s*(?P<question>.+\?)\s*$")


class RevisionGenerator:
    """Generate revision questions, flashcards, and weak-area pages."""

    def generate(self, records: list[ResourceRecord]) -> dict[str, Any]:
        questions = self.extract_questions(records)
        flashcards = self.flashcards_from_questions(questions)
        weak_areas = self.weak_areas(records)
        return {"questions": questions, "flashcards": flashcards, "weak_areas": weak_areas}

    def extract_questions(self, records: list[ResourceRecord]) -> list[dict[str, Any]]:
        questions: list[dict[str, Any]] = []
        for record in records:
            note = read_note(record)
            section = extract_section(note, "Revision questions")
            topics = topic_matches(record, note)
            for index, line in enumerate(section.splitlines(), start=1):
                match = QUESTION_RE.match(line.strip())
                if not match:
                    continue
                question = match.group("question").strip()
                questions.append({
                    "id": f"{record.id.replace(':', '_')}-q{index:03d}",
                    "question": question,
                    "answer_hint": self._answer_hint(note),
                    "topic": topics[0] if topics else "general",
                    "resource_id": record.id,
                    "resource_title": display_title(record, mark_missing=True),
                    "resource_page": resource_route(record.id),
                    "difficulty": self._difficulty(question),
                    "source": "fallback" if record.extra.get("note_completed_by_fallback") else "resource_note",
                    "requires_human_review": bool(record.extra.get("requires_human_review")),
                })
        questions.extend(self._learn_questions())
        return questions

    def _learn_questions(self) -> list[dict[str, Any]]:
        learn_dir = config.get_data_path("processed", "learn")
        result: list[dict[str, Any]] = []
        if not learn_dir.exists():
            return result
        for path in learn_dir.glob("*.md"):
            if path.name == "index.md":
                continue
            content = Storage.read_text(path)
            title = next((line.lstrip("#").strip() for line in content.splitlines() if line.startswith("# ")), path.stem)
            result.append({
                "id": f"learn-{path.stem}-q001",
                "question": f"What are the main ideas in {title}?",
                "answer_hint": "Review the source-backed synthesis section.",
                "topic": normalize_topic_slug(path.stem),
                "resource_id": "",
                "resource_title": title,
                "resource_page": learn_route(path.stem),
                "difficulty": "medium",
                "source": "learn_page",
                "requires_human_review": False,
            })
        return result

    def flashcards_from_questions(self, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "front": item["question"],
                "back": item["answer_hint"] or "Review linked source page.",
                "topic": item["topic"],
                "source_page": item["resource_page"],
                "difficulty": item["difficulty"],
                "citations": [],
            }
            for item in questions
        ]

    def weak_areas(self, records: list[ResourceRecord]) -> list[dict[str, str]]:
        areas: list[dict[str, str]] = []
        for record in records:
            note = read_note(record)
            reasons = []
            needs = extract_section(note, "Needs verification")
            if needs and "none" not in needs.lower():
                reasons.append("Needs verification")
            if record.extra.get("note_completed_by_fallback"):
                reasons.append("Fallback-completed note")
            if record.extra.get("quality_status") == "weak":
                reasons.append("Weak generated note")
            next_topics = extract_section(note, "Suggested next learning topics")
            if "not yet in wiki" in next_topics.lower():
                reasons.append("Next topic not yet in wiki")
            if record.status.value == "failed_retryable":
                reasons.append("Failed note")
            if reasons:
                topic = (topic_matches(record, note) or ["general"])[0]
                areas.append({
                    "topic": topic,
                    "reason": "; ".join(reasons),
                    "resource": display_title(record, mark_missing=True),
                    "action": "Review source chunks and regenerate or edit the note.",
                })
        return areas

    def save(self, data: dict[str, Any]) -> Path:
        revision_dir = config.get_data_path("processed", "revision")
        revision_dir.mkdir(parents=True, exist_ok=True)
        for old in list(revision_dir.glob("*.md")) + list(revision_dir.glob("*.json")):
            old.unlink()
        public_dir = config.get_data_path("site_generated", "docs", "public", "revision")
        public_dir.mkdir(parents=True, exist_ok=True)
        Storage.write_json({"generated_at": datetime.utcnow().isoformat(), **data}, revision_dir / "revision.json")
        Storage.write_json({"items": data["flashcards"]}, revision_dir / "flashcards.json")
        Storage.write_json({"items": data["flashcards"]}, public_dir / "flashcards.json")
        Storage.write_text(self._index(data), revision_dir / "index.md")
        Storage.write_text(self._questions(data["questions"]), revision_dir / "questions.md")
        Storage.write_text(self._flashcards(data["flashcards"]), revision_dir / "flashcards.md")
        Storage.write_text(self._weak_areas(data["weak_areas"]), revision_dir / "weak-areas.md")
        Storage.write_text(self._by_topic(data["questions"]), revision_dir / "by-topic.md")
        return revision_dir

    def export(self, data: dict[str, Any], fmt: str) -> Path:
        out_dir = config.get_data_path("outputs", "revision")
        out_dir.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            path = out_dir / "flashcards.json"
            Storage.write_json({"items": data["flashcards"]}, path)
            return path
        if fmt == "csv":
            path = out_dir / "flashcards.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["front", "back", "topic", "source_page", "difficulty"])
                writer.writeheader()
                for card in data["flashcards"]:
                    writer.writerow({key: card.get(key, "") for key in writer.fieldnames or []})
            return path
        raise ValueError("format must be json or csv")

    def _answer_hint(self, note: str) -> str:
        for section in ["Source-backed summary", "First-principles explanation", "One-line memory hook"]:
            body = extract_section(note, section)
            lines = bullet_lines(body)
            if lines:
                return lines[0].lstrip("-* ").strip()[:300]
            if body:
                return body.splitlines()[0][:300]
        return "Review linked source page."

    def _difficulty(self, question: str) -> str:
        lowered = question.lower()
        if any(word in lowered for word in ["compare", "why", "how would", "tradeoff"]):
            return "hard"
        if any(word in lowered for word in ["how", "which"]):
            return "medium"
        return "easy"

    def _index(self, data: dict[str, Any]) -> str:
        return f"""# Revision

| Section | Count |
|---|---:|
| [Questions](./questions.md) | {len(data['questions'])} |
| [Flashcards](./flashcards.md) | {len(data['flashcards'])} |
| [Weak areas](./weak-areas.md) | {len(data['weak_areas'])} |

Generated: {datetime.utcnow().isoformat()}
"""

    def _questions(self, questions: list[dict[str, Any]]) -> str:
        lines = ["# Revision Questions", "", "| Question | Topic | Source | Difficulty |", "|---|---|---|---|"]
        for item in questions:
            lines.append(f"| {md_table_cell(item['question'])} | {md_table_cell(item['topic'])} | [{md_table_cell(item['resource_title'])}]({item['resource_page']}) | {md_table_cell(item['difficulty'])} |")
        return "\n".join(lines) + "\n"

    def _flashcards(self, flashcards: list[dict[str, Any]]) -> str:
        lines = ["# Flashcards", ""]
        for card in flashcards:
            lines.extend([f"## {card['front']}", "", card["back"], "", f"- Topic: {card['topic']}", f"- Difficulty: {card['difficulty']}", f"- Source: {card['source_page']}", ""])
        return "\n".join(lines) + "\n"

    def _weak_areas(self, areas: list[dict[str, str]]) -> str:
        lines = ["# Weak Areas", "", "## High priority", "", "| Topic | Reason | Related resources | Suggested next action |", "|---|---|---|---|"]
        for area in areas:
            lines.append(f"| {md_table_cell(area['topic'])} | {md_table_cell(area['reason'])} | {md_table_cell(area['resource'])} | {md_table_cell(area['action'])} |")
        if not areas:
            lines.append("| - | No weak areas detected | - | - |")
        return "\n".join(lines) + "\n"

    def _by_topic(self, questions: list[dict[str, Any]]) -> str:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for question in questions:
            grouped.setdefault(question["topic"], []).append(question)
        lines = ["# Revision By Topic", ""]
        for topic in sorted(grouped):
            lines.extend([f"## {topic}", ""])
            lines.extend(f"- {item['question']}" for item in grouped[topic])
            lines.append("")
        return "\n".join(lines) + "\n"


revision_generator = RevisionGenerator()
