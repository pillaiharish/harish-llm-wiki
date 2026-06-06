"""Shared helpers for resource metadata, topics, and generated views."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Any

from wiki.schemas import ResourceRecord, SourceType
from wiki.storage import Storage


REPLACEABLE_TITLES = {"", "untitled", "unknown resource"}


TOPIC_ALIASES: dict[str, str] = {
    "rag": "rag-retrieval",
    "retrieval": "rag-retrieval",
    "security": "ai-security",
    "ai-safety": "ai-security",
    "optimization-training": "optimizer-training",
    "training": "optimizer-training",
}

TOPIC_DEFINITIONS: dict[str, dict[str, Any]] = {
    "rag-retrieval": {
        "name": "RAG / Retrieval",
        "keywords": [
            "rag", "retrieval", "hybrid search", "bm25", "dense retrieval",
            "sparse retrieval", "cag", "chunking", "vector database",
            "embedding", "embeddings", "vector",
        ],
        "learning_path": [
            "Start with the basic retrieval mental model.",
            "Study chunking and embedding choices.",
            "Compare sparse, dense, and hybrid retrieval.",
            "Apply retrieval to a project and evaluate failure modes.",
        ],
    },
    "embeddings": {
        "name": "Embeddings",
        "keywords": ["embedding", "embeddings", "semantic search", "vector search", "sentence transformer", "hugging face embeddings"],
        "learning_path": [
            "Start with vectors as meaning-carrying representations.",
            "Study similarity search and distance metrics.",
            "Connect embedding quality to retrieval quality.",
        ],
    },
    "llm-inference": {
        "name": "LLM Inference / Serving",
        "keywords": ["vllm", "inference", "serving", "openai-compatible api", "throughput", "latency", "batching", "paged attention", "prefix caching", "gpu"],
        "learning_path": [
            "Start with what happens during inference.",
            "Then study serving engines and batching.",
            "Understand memory management and prefix caching.",
            "Finish with scaling and production serving layers.",
        ],
    },
    "vllm": {
        "name": "vLLM",
        "keywords": ["vllm", "paged attention", "continuous batching", "prefix caching"],
        "learning_path": [
            "Start with the serving problem vLLM solves.",
            "Study PagedAttention and scheduler behavior.",
            "Connect engine internals to throughput and latency.",
        ],
    },
    "llm-evals": {
        "name": "LLM Evaluation",
        "keywords": ["eval", "evals", "evaluation", "benchmark", "judge", "rubric", "lm-eval", "guidellm"],
        "learning_path": [
            "Start with what an eval measures.",
            "Then compare qualitative and automated evals.",
            "Study rubric design and failure analysis.",
            "Finish with production feedback loops.",
        ],
    },
    "agents": {
        "name": "Agents / Tooling",
        "keywords": ["agent", "agents", "tool", "tooling", "agent harness", "harness", "connector"],
        "learning_path": [
            "Start with tool-calling basics.",
            "Then understand agent loops and harnesses.",
            "Study reliability and observability.",
            "Finish with security and connector risks.",
        ],
    },
    "ai-security": {
        "name": "AI Security",
        "keywords": ["security", "attack", "exfiltration", "prompt injection", "jailbreak", "connector"],
        "learning_path": [
            "Start with the AI threat model.",
            "Study prompt injection and data exfiltration paths.",
            "Finish with connector and review mitigations.",
        ],
    },
    "optimizer-training": {
        "name": "Optimization / Training Fundamentals",
        "keywords": ["adam", "optimizer", "training", "gradient", "backprop", "loss"],
        "learning_path": [
            "Start with gradient descent intuition.",
            "Then study optimizer mechanics.",
            "Connect training dynamics to model behavior.",
        ],
    },
    "linear-algebra": {
        "name": "Linear Algebra",
        "keywords": ["linear algebra", "matrix", "matrices", "vectors", "mit 18.06"],
        "learning_path": [
            "Start with vectors and matrices.",
            "Study transformations and similarity.",
            "Connect linear algebra to embeddings and optimization.",
        ],
    },
    "transcription-asr": {
        "name": "Local Audio/Video Transcription",
        "keywords": ["transcript", "whisper", "audio", "video", "asr", "speech"],
        "learning_path": [
            "Start with audio extraction.",
            "Study ASR model choices and transcript chunking.",
            "Connect transcript chunks to cited wiki notes.",
        ],
    },
}

LEARN_DEFINITION_SLUGS = [
    "rag-retrieval",
    "embeddings",
    "llm-inference",
    "vllm",
    "llm-evals",
    "agents",
    "ai-security",
    "optimizer-training",
    "linear-algebra",
    "transcription-asr",
]


def is_replaceable_title(value: str | None) -> bool:
    """Return True if a title should be replaced by better metadata."""
    return value is None or str(value).strip().lower() in REPLACEABLE_TITLES


def display_title(record: ResourceRecord, *, mark_missing: bool = False) -> str:
    """Return the best display title for a resource."""
    if not is_replaceable_title(record.title):
        return str(record.title).strip()
    fallback = record.canonical_id or record.id
    if mark_missing:
        return f"{fallback} (needs metadata)"
    return fallback


def source_url(record: ResourceRecord) -> str:
    """Return the best source URL for a resource."""
    return record.normalized_url or record.original_url or record.extra.get("source_url") or ""


def learned_date(record: ResourceRecord) -> datetime:
    """Return the best date for chronology."""
    return record.user_consumed_at or record.processed_at or record.first_seen_at or datetime.utcnow()


def resource_page_name(resource_id: str) -> str:
    """Return the generated Markdown filename for a resource."""
    return f"{resource_id.replace(':', '_')}.md"


def dedupe_records(records: Iterable[ResourceRecord]) -> list[ResourceRecord]:
    """Dedupe records by canonical resource id while preserving first occurrence."""
    seen: set[str] = set()
    deduped: list[ResourceRecord] = []
    for record in records:
        key = record.canonical_id or record.id
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def metadata_toc(record: ResourceRecord) -> list[dict[str, Any]]:
    """Return resource TOC entries stored in metadata or extras."""
    toc = record.extra.get("toc")
    if isinstance(toc, list):
        return [entry for entry in toc if isinstance(entry, dict) and entry.get("title")]
    return []


def youtube_toc_from_chunks(record: ResourceRecord, *, limit: int = 8) -> list[dict[str, Any]]:
    """Create deterministic YouTube TOC entries from normalized chunks."""
    if not record.local_normalized_path:
        return []
    chunks_path = Path(record.local_normalized_path) / "chunks.jsonl"
    entries: list[dict[str, Any]] = []
    for index, chunk in enumerate(Storage.read_jsonl(chunks_path)):
        if index >= limit:
            break
        start = chunk.get("start_time")
        if start is None:
            continue
        timestamp = format_seconds(float(start))
        title = "Introduction" if index == 0 else f"Section {index + 1}"
        entries.append({"level": 2, "title": title, "timestamp": timestamp, "chunk_id": chunk.get("chunk_id")})
    return entries


def resource_toc(record: ResourceRecord) -> list[dict[str, Any]]:
    """Return the best TOC for a resource."""
    toc = metadata_toc(record)
    if toc:
        return toc
    chapters = record.extra.get("chapters")
    if isinstance(chapters, list) and chapters:
        return chapters
    if record.source_type == SourceType.YOUTUBE:
        return youtube_toc_from_chunks(record)
    return []


def format_seconds(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def extract_markdown_headings(content: str) -> list[dict[str, Any]]:
    """Extract h1-h3 style Markdown headings."""
    entries: list[dict[str, Any]] = []
    for line in content.splitlines():
        match = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if not match:
            continue
        entries.append({"level": len(match.group(1)), "title": match.group(2).strip()})
    return entries


def anchor_slug(text: str) -> str:
    """Convert a chunk ID or heading to a safe VitePress anchor slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[:/]+", "-", slug)
    slug = re.sub(r"[^a-z0-9\-]", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def short_citation_label(chunk_id: str) -> str:
    """Return a short human-readable label for inline citations.

    E.g. 'youtube:q5IF2PHA5SA-c0001' -> 'c0001'
         'webpage:df11644e-p0004' -> 'p0004'
         'no-dash-chunk' -> 'no-dash-chunk' (unchanged if no pattern match)
    """
    import re as _re
    match = _re.search(r'-([a-z]\d{3,})$', chunk_id)
    if match:
        return match.group(1)
    return chunk_id


def normalize_topic_slug(slug: str) -> str:
    """Map an alias topic slug to its canonical slug.

    If the slug is already canonical, it is returned unchanged.
    """
    return TOPIC_ALIASES.get(slug, slug)


def normalize_topic_list(topics: list[str]) -> list[str]:
    """Normalize a list of topic slugs to canonical slugs, deduping in order.

    Only returns slugs that exist in TOPIC_DEFINITIONS (i.e., are canonical).
    """
    seen: set[str] = set()
    result: list[str] = []
    for slug in topics:
        canonical = normalize_topic_slug(slug)
        if canonical not in seen and canonical in TOPIC_DEFINITIONS:
            seen.add(canonical)
            result.append(canonical)
    return result


def _contains_keyword(text: str, keyword: str) -> bool:
    """Return True for whole-word keyword or literal phrase matches."""
    if " " in keyword:
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _matching_topics(text: str) -> list[str]:
    """Return topics matched by keyword rules."""
    assigned: list[str] = []
    for slug, definition in TOPIC_DEFINITIONS.items():
        if any(_contains_keyword(text, keyword) for keyword in definition["keywords"]):
            assigned.append(slug)
    return assigned


def topic_matches(record: ResourceRecord, note_text: str = "") -> list[str]:
    """Assign deterministic canonical topics from title, tags, metadata, and note text.

    Returns only canonical slugs (aliases are normalized and deduped).
    """
    primary_text = " ".join(
        [
            display_title(record),
            " ".join(record.tags),
            record.description or "",
            record.notes_from_user or "",
            record.author or "",
            str(record.extra.get("subtitle") or ""),
            str(record.extra.get("site_name") or ""),
        ]
    ).lower()
    assigned = _matching_topics(primary_text)

    # Generated notes are useful as a fallback, but old/mock placeholder notes
    # contain generic terms like "retrieval", "benchmark", and "security" that
    # would otherwise over-classify every resource.
    note_sample = note_text[:5000].lower()
    if not assigned and note_sample and "mock-generated" not in note_sample and "placeholder content" not in note_sample:
        assigned = _matching_topics(note_sample)

    return normalize_topic_list(assigned)
