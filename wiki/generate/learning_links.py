"""Internal topic/concept link resolver for prerequisites and next-topic sections.

Resolves bullet list items against existing wiki topics and concepts.
Produces VitePress-compatible internal links for matches and
marks unmatched items as "not yet in wiki".
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from wiki.config import config
from wiki.resource_utils import TOPIC_DEFINITIONS


def load_existing_topic_slugs() -> set[str]:
    """Scan processed/topics/ for topic page slugs."""
    topics_dir = config.get_data_path("processed", "topics")
    slugs: set[str] = set()
    if topics_dir.exists():
        for f in topics_dir.iterdir():
            if f.suffix == ".md" and f.name != "index.md":
                slugs.add(f.stem)
    return slugs


def load_existing_concept_slugs() -> set[str]:
    """Scan processed/concepts/ for concept page slugs."""
    concepts_dir = config.get_data_path("processed", "concepts")
    slugs: set[str] = set()
    if concepts_dir.exists():
        for f in concepts_dir.iterdir():
            if f.suffix == ".json":
                slugs.add(f.stem)
    return slugs


def resolve_section_links(
    section_text: str,
    topic_slugs: set[str] | None = None,
    concept_slugs: set[str] | None = None,
) -> str:
    """Resolve bullet list items against known wiki topics and concepts.

    For each list item (starting with '- '), check if it matches a known
    topic or concept. If so, replace with an internal link.
    If not, append ' — not yet in wiki'.
    """
    if topic_slugs is None:
        topic_slugs = load_existing_topic_slugs()
    if concept_slugs is None:
        concept_slugs = load_existing_concept_slugs()

    lines = section_text.splitlines()
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("- "):
            result.append(line)
            continue

        item_text = stripped[2:].strip()
        clean_text = item_text.rstrip()

        if clean_text.endswith(" — not yet in wiki") or clean_text.endswith(" -- not yet in wiki"):
            base = clean_text.rsplit(" —", 1)[0].rsplit(" --", 1)[0].strip()
            name_lower = base.lower()
        elif clean_text.startswith("[") and "](" in clean_text:
            result.append(line)
            continue
        else:
            base = clean_text
            name_lower = base.lower()

        match = _find_match(name_lower, topic_slugs, concept_slugs)
        if match:
            kind, slug, display = match
            result.append(f"- [{display}](/{kind}/{slug}.html)")
        else:
            if base != clean_text:
                result.append(f"- {base} — not yet in wiki")
            else:
                result.append(f"- {base} — not yet in wiki")
    return "\n".join(result)


_KNOWN_ALIASES: dict[str, tuple[str, str, str]] = {
    "rag": ("topics", "rag", "RAG / Retrieval"),
    "retrieval": ("topics", "rag", "RAG / Retrieval"),
    "retrieval augmented generation": ("topics", "rag", "RAG / Retrieval"),
    "embeddings": ("topics", "rag", "RAG / Retrieval"),
    "embedding": ("topics", "rag", "RAG / Retrieval"),
    "vector database": ("topics", "rag", "RAG / Retrieval"),
    "hybrid search": ("topics", "rag", "RAG / Retrieval"),
    "chunking": ("topics", "rag", "RAG / Retrieval"),
    "llm inference": ("topics", "llm-inference", "LLM Inference / Serving"),
    "llm serving": ("topics", "llm-inference", "LLM Inference / Serving"),
    "vllm": ("topics", "llm-inference", "LLM Inference / Serving"),
    "paged attention": ("topics", "llm-inference", "LLM Inference / Serving"),
    "continuous batching": ("topics", "llm-inference", "LLM Inference / Serving"),
    "prefix caching": ("topics", "llm-inference", "LLM Inference / Serving"),
    "llm evaluation": ("topics", "llm-evals", "LLM Evaluation"),
    "llm evals": ("topics", "llm-evals", "LLM Evaluation"),
    "evals": ("topics", "llm-evals", "LLM Evaluation"),
    "evaluation": ("topics", "llm-evals", "LLM Evaluation"),
    "agents": ("topics", "agents", "Agents / Tooling"),
    "agent": ("topics", "agents", "Agents / Tooling"),
    "tool calling": ("topics", "agents", "Agents / Tooling"),
    "optimizer": ("topics", "optimizer-training", "Optimization / Training Fundamentals"),
    "adam optimizer": ("topics", "optimizer-training", "Optimization / Training Fundamentals"),
    "training": ("topics", "optimizer-training", "Optimization / Training Fundamentals"),
    "security": ("topics", "security", "Security"),
    "dns exfiltration": ("topics", "security", "Security"),
    "prompt injection": ("topics", "security", "Security"),
}


def _find_match(
    name_lower: str,
    topic_slugs: set[str],
    concept_slugs: set[str],
) -> tuple[str, str, str] | None:
    """Try to match a prerequisite/next-topic name to an existing wiki page.

    Returns (kind, slug, display) or None.
    kind is "topics" or "concepts".
    """
    if name_lower in _KNOWN_ALIASES:
        kind, slug, display = _KNOWN_ALIASES[name_lower]
        if (kind == "topics" and slug in topic_slugs) or (kind == "concepts" and slug in concept_slugs):
            return (kind, slug, display)

    for slug, definition in TOPIC_DEFINITIONS.items():
        dname = definition["name"].lower()
        if name_lower == dname or name_lower == slug:
            if slug in topic_slugs:
                return ("topics", slug, definition["name"])
        for kw in definition.get("keywords", []):
            if name_lower == kw.lower():
                if slug in topic_slugs:
                    return ("topics", slug, definition["name"])

    if name_lower in concept_slugs:
        display = name_lower.replace("-", " ").title()
        return ("concepts", name_lower, display)

    return None


def linkify_prerequisites(markdown: str, topic_slugs: set[str] | None = None, concept_slugs: set[str] | None = None) -> str:
    """Resolve internal wiki links in the Recommended prerequisites section."""
    section = _extract_section(markdown, "Recommended prerequisites")
    if not section:
        return markdown
    resolved = resolve_section_links(section, topic_slugs, concept_slugs)
    return _replace_section(markdown, "Recommended prerequisites", resolved)


def linkify_next_topics(markdown: str, topic_slugs: set[str] | None = None, concept_slugs: set[str] | None = None) -> str:
    """Resolve internal wiki links in the Suggested next learning topics section."""
    section = _extract_section(markdown, "Suggested next learning topics")
    if not section:
        return markdown
    resolved = resolve_section_links(section, topic_slugs, concept_slugs)
    return _replace_section(markdown, "Suggested next learning topics", resolved)


def resolve_learning_links(markdown: str, topic_slugs: set[str] | None = None, concept_slugs: set[str] | None = None) -> str:
    """Resolve both prerequisites and next-topics sections in one pass."""
    markdown = linkify_prerequisites(markdown, topic_slugs, concept_slugs)
    markdown = linkify_next_topics(markdown, topic_slugs, concept_slugs)
    return markdown


def _extract_section(content: str, heading: str) -> str:
    """Extract section body by heading text (case-insensitive match)."""
    lines = content.splitlines()
    start = None
    start_level = None
    target = heading.lower()

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        text = stripped.lstrip("#").strip().lower()
        if text == target:
            start = index + 1
            start_level = len(stripped) - len(stripped.lstrip("#"))
            break

    if start is None or start_level is None:
        return ""

    end = len(lines)
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if not stripped.startswith("#"):
            continue
        level = len(stripped) - len(stripped.lstrip("#"))
        if level <= start_level:
            end = index
            break

    return "\n".join(lines[start:end])


def _replace_section(content: str, heading: str, new_body: str) -> str:
    """Replace a section's body while keeping the heading."""
    lines = content.splitlines()
    start = None
    start_level = None
    target = heading.lower()
    end = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        text = stripped.lstrip("#").strip().lower()
        if text == target:
            start = index + 1
            start_level = len(stripped) - len(stripped.lstrip("#"))
            break

    if start is None or start_level is None:
        return content

    end = len(lines)
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if not stripped.startswith("#"):
            continue
        level = len(stripped) - len(stripped.lstrip("#"))
        if level <= start_level:
            end = index
            break

    before = lines[:start - 1]
    heading_line = lines[start - 1]
    after = lines[end:]
    return "\n".join(before + [heading_line, "", new_body] + after)