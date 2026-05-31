"""Generate learning notes from chunks using LLM."""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Iterator, Any

from wiki.config import config
from wiki.resource_utils import display_title, resource_toc
from wiki.schemas import ResourceRecord, ResourceStatus, YouTubeChunk, WebpageChunk, MarkdownChunk
from wiki.storage import Storage
from wiki.llm.base import LLMProvider
from wiki.llm.prompts import (
    build_note_repair_prompt,
    build_resource_note_prompt,
    format_chunks_for_prompt,
    SYSTEM_PROMPT,
    PROMPT_VERSION,
)
from wiki.generate.citations import (
    load_chunk_map,
    linkify_citations,
    render_source_chunks_section,
    strip_source_chunks_section,
)
from wiki.generate.learning_links import resolve_learning_links


def load_chunks(norm_dir: Path) -> Iterator[YouTubeChunk | WebpageChunk | MarkdownChunk]:
    """Load chunks from a normalized directory."""
    chunks_path = norm_dir / "chunks.jsonl"
    if not chunks_path.exists():
        return
    
    with open(chunks_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            
            # Determine chunk type based on source_type
            source_type = data.get('source_type')
            if source_type == 'youtube':
                yield YouTubeChunk.model_validate(data)
            elif source_type == 'webpage':
                yield WebpageChunk.model_validate(data)
            elif source_type == 'markdown':
                yield MarkdownChunk.model_validate(data)


def compute_chunks_hash(chunks: List[Any]) -> str:
    """Compute hash of chunks for caching."""
    content = json.dumps([c.model_dump() for c in chunks], sort_keys=True)
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


REQUIRED_NOTE_SECTIONS = [
    "Resource table of contents",
    "Why this resource matters",
    "One-line memory hook",
    "Source-backed summary",
    "First-principles explanation",
    "Concrete example / toy implementation",
    "Real-system implications",
    "Common failure modes",
    "What the resource did not cover",
    "LLM-added explanations",
    "Needs verification",
    "Revision questions",
    "Harish project connections",
    "Recommended prerequisites",
    "Suggested next learning topics",
    "Citations",
    "Provenance",
]


def _has_markdown_heading(content: str, heading: str) -> bool:
    """Return True if the Markdown content contains a heading with this text."""
    target = heading.lower()
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        text = stripped.lstrip("#").strip().lower()
        if text == target:
            return True
    return False


def _extract_section(content: str, heading: str) -> str:
    """Extract a Markdown section body by heading text."""
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

    return "\n".join(lines[start:end]).strip()


def _safe_resource_id(resource_id: str) -> str:
    """Return a filesystem-safe resource id."""
    return resource_id.replace(":", "_").replace("/", "_")


def validate_generated_note_contract(
    content: str,
    chunks: List[Any],
    *,
    provider: str,
    model: str,
    prompt_version: str,
) -> list[str]:
    """Validate the generated Markdown follows the wiki note contract."""
    issues: list[str] = []

    if not content.lstrip().startswith("# "):
        issues.append("note must start with a level-1 title")

    for section in REQUIRED_NOTE_SECTIONS:
        if not _has_markdown_heading(content, section):
            issues.append(f"missing section: {section}")

    chunk_ids = [str(chunk.chunk_id) for chunk in chunks]
    for section in ["Source-backed summary", "Citations"]:
        body = _extract_section(content, section)
        if body and chunk_ids and not any(chunk_id in body for chunk_id in chunk_ids):
            issues.append(f"{section} must cite source chunk IDs")

    summary_body = _extract_section(content, "Source-backed summary")
    for line in summary_body.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        if chunk_ids and not any(chunk_id in stripped for chunk_id in chunk_ids):
            issues.append("every Source-backed summary bullet must cite a source chunk ID")
            break

    summary = _extract_section(content, "Source-backed summary").lower()
    generic_phrases = ["learned about this topic", "core concepts from the source material"]
    if any(phrase in summary for phrase in generic_phrases):
        issues.append("Source-backed summary is too generic")

    provenance = _extract_section(content, "Provenance")
    provenance_lower = provenance.lower()
    required_provenance = [
        provider.lower(),
        model.lower(),
        prompt_version.lower(),
    ]
    for value in required_provenance:
        if value and value not in provenance_lower:
            issues.append(f"provenance missing value: {value}")

    return issues


class NoteGenerator:
    """Generate learning notes from chunks using LLM."""
    
    def __init__(self, provider: LLMProvider) -> None:
        """Initialize with an LLM provider."""
        self.provider = provider
    
    def should_regenerate(self, record: ResourceRecord, chunks_hash: str) -> bool:
        """Check if note should be regenerated.
        
        Returns True if:
        - No existing note
        - Source chunks changed
        - Prompt version changed
        - Model changed
        """
        if not record.generated_note_path:
            return True
        
        if not record.generated_note_path.exists():
            return True
        
        # Check hashes
        if record.source_chunks_hash != chunks_hash:
            return True
        
        if record.prompt_version != PROMPT_VERSION:
            return True
        
        if record.llm_model != self.provider.model:
            return True
        
        return False
    
    def generate(self, record: ResourceRecord) -> Path:
        """Generate learning note for a resource.
        
        Returns path to generated note.
        """
        if not record.local_normalized_path:
            raise ValueError(f"Resource {record.id} has no normalized path")
        
        norm_dir = Path(record.local_normalized_path)
        
        # Load chunks
        chunks = list(load_chunks(norm_dir))
        if not chunks:
            raise ValueError(f"No chunks found for {record.id}")
        
        # Compute chunks hash
        chunks_hash = compute_chunks_hash(chunks)
        
        # Check if we can use cache
        if not self.should_regenerate(record, chunks_hash):
            print(f"  Cache hit for {record.id}")
            record.status = ResourceStatus.LLM_CACHE_HIT
            return record.generated_note_path
        
        # Build metadata for prompt
        metadata = {
            "source_type": record.source_type.value,
            "title": display_title(record, mark_missing=True),
            "author": record.author or "Unknown",
            "url": record.original_url,
            "subtitle": record.extra.get("subtitle"),
            "published_at": record.published_at.isoformat() if record.published_at else None,
            "toc": resource_toc(record),
            "chunk_count": len(chunks),
        }
        
        # Build prompt
        prompt = build_resource_note_prompt(
            chunks, metadata, 
            self.provider.provider_name,
            self.provider.model
        )
        
        # Compute prompt hash
        prompt_hash = self.provider.compute_prompt_hash(prompt, SYSTEM_PROMPT)
        
        # Generate note
        print(f"  Generating note for {record.id}...")
        record.extra.pop("note_repaired", None)
        record.extra.pop("repair_attempts", None)
        content = self.provider.generate(prompt, system=SYSTEM_PROMPT)
        
        if not content:
            raise RuntimeError(f"Empty response from LLM for {record.id}")

        contract_issues = validate_generated_note_contract(
            content,
            chunks,
            provider=self.provider.provider_name,
            model=self.provider.model,
            prompt_version=PROMPT_VERSION,
        )
        if contract_issues:
            content = self._repair_or_fail(
                record=record,
                metadata=metadata,
                chunks=chunks,
                initial_output=content,
                initial_errors=contract_issues,
                prompt_hash=prompt_hash,
            )

        # Post-processing: linkify citations, resolve learning links
        norm_dir = Path(record.local_normalized_path)
        chunk_map = load_chunk_map(norm_dir)
        content, cited_ids, _missing = linkify_citations(content, chunk_map)
        content = resolve_learning_links(content)
        content = strip_source_chunks_section(content)
        source_url = record.original_url or ""
        content += render_source_chunks_section(chunk_map, cited_ids, source_url=source_url)

        note_path = self._save_valid_note(
            record=record,
            content=content,
            prompt_hash=prompt_hash,
            chunks_hash=chunks_hash,
            chunk_count=len(chunks),
        )
        return note_path

    def _repair_or_fail(
        self,
        *,
        record: ResourceRecord,
        metadata: dict[str, Any],
        chunks: List[Any],
        initial_output: str,
        initial_errors: list[str],
        prompt_hash: str,
    ) -> str:
        """Try to repair invalid note output or save debug artifacts."""
        print("  ✗ Initial note failed contract")
        repair_attempts = max(0, config.LLM_NOTE_REPAIR_RETRIES)
        repaired_output = ""
        repaired_errors = initial_errors

        for attempt in range(1, repair_attempts + 1):
            print(f"  ↻ Attempting repair {attempt}/{repair_attempts}")
            repair_prompt = build_note_repair_prompt(
                resource_title=metadata["title"],
                chunks=chunks,
                validator_errors=repaired_errors,
                invalid_output=repaired_output or initial_output,
            )
            repaired_output = self.provider.generate(repair_prompt, system=SYSTEM_PROMPT)
            if not repaired_output:
                repaired_errors = ["empty repaired response from LLM"]
                continue

            repaired_errors = validate_generated_note_contract(
                repaired_output,
                chunks,
                provider=self.provider.provider_name,
                model=self.provider.model,
                prompt_version=PROMPT_VERSION,
            )
            if not repaired_errors:
                print("  ✓ Repaired note passed contract")
                record.extra["note_repaired"] = True
                record.extra["repair_attempts"] = attempt
                record.extra["requires_human_review"] = False
                record.extra.pop("note_contract_errors", None)
                record.extra.pop("failed_note_debug_path", None)
                return repaired_output

        print("  ✗ Repair failed")
        debug_path = self._save_failed_debug(
            record=record,
            initial_output=initial_output,
            repaired_output=repaired_output,
            validator_errors=repaired_errors,
            prompt_context={
                "resource_id": record.id,
                "metadata": metadata,
                "prompt_hash": prompt_hash,
                "prompt_version": PROMPT_VERSION,
                "llm_provider": self.provider.provider_name,
                "llm_model": self.provider.model,
                "chunks": [
                    {
                        "chunk_id": str(chunk.chunk_id),
                        "citation_label": getattr(chunk, "citation_label_formatted", None) or chunk.citation_label,
                        "source_type": chunk.source_type.value,
                    }
                    for chunk in chunks
                ],
                "chunks_prompt": format_chunks_for_prompt(chunks),
            },
        )
        print(f"  Debug saved to: {debug_path}")
        record.status = ResourceStatus.FAILED_RETRYABLE
        record.failure_reason = "Generated note failed contract after repair"
        record.extra["requires_human_review"] = True
        record.extra["note_contract_errors"] = repaired_errors
        record.extra["failed_note_debug_path"] = str(debug_path)
        raise RuntimeError(
            f"Generated note failed contract for {record.id}: "
            + "; ".join(repaired_errors)
        )

    def _save_valid_note(
        self,
        *,
        record: ResourceRecord,
        content: str,
        prompt_hash: str,
        chunks_hash: str,
        chunk_count: int,
    ) -> Path:
        """Save a validated note and update record metadata."""
        output_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()

        proc_dir = config.get_data_path("processed", "resources")
        proc_dir.mkdir(parents=True, exist_ok=True)

        note_path = proc_dir / f"{_safe_resource_id(record.id)}.md"
        Storage.write_text(content, note_path)

        note_data = {
            "resource_id": record.id,
            "generated_at": datetime.utcnow().isoformat(),
            "llm_provider": self.provider.provider_name,
            "llm_model": self.provider.model,
            "prompt_version": PROMPT_VERSION,
            "prompt_hash": prompt_hash,
            "source_chunks_hash": chunks_hash,
            "generated_output_hash": output_hash,
            "chunk_count": chunk_count,
            "note_repaired": bool(record.extra.get("note_repaired")),
            "repair_attempts": record.extra.get("repair_attempts", 0),
        }

        json_path = proc_dir / f"{_safe_resource_id(record.id)}.json"
        Storage.write_json(note_data, json_path)

        record.generated_note_path = note_path
        record.prompt_hash = prompt_hash
        record.source_chunks_hash = chunks_hash
        record.generated_output_hash = output_hash
        record.llm_provider = self.provider.provider_name
        record.llm_model = self.provider.model
        record.prompt_version = PROMPT_VERSION
        record.status = ResourceStatus.LLM_NOTE_GENERATED
        record.failure_reason = None

        return note_path

    def _save_failed_debug(
        self,
        *,
        record: ResourceRecord,
        initial_output: str,
        repaired_output: str,
        validator_errors: list[str],
        prompt_context: dict[str, Any],
    ) -> Path:
        """Save failed LLM outputs outside Git for human debugging."""
        debug_dir = config.get_data_path("debug", "failed_notes", _safe_resource_id(record.id))
        debug_dir.mkdir(parents=True, exist_ok=True)
        Storage.write_text(initial_output, debug_dir / "initial_output.md")
        Storage.write_text(repaired_output, debug_dir / "repaired_output.md")
        Storage.write_json({"errors": validator_errors}, debug_dir / "validator_errors.json")
        Storage.write_json(prompt_context, debug_dir / "prompt_context.json")
        return debug_dir


# Global instance (initialized with provider when needed)
note_generator: NoteGenerator | None = None


def get_note_generator(provider: LLMProvider) -> NoteGenerator:
    """Get or create the note generator."""
    global note_generator
    if note_generator is None or note_generator.provider != provider:
        note_generator = NoteGenerator(provider)
    return note_generator
