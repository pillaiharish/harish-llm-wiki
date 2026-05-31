"""Generate learning notes from chunks using LLM."""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Iterator, Any

from wiki.config import config
from wiki.schemas import ResourceRecord, ResourceStatus, YouTubeChunk, WebpageChunk, MarkdownChunk
from wiki.storage import Storage
from wiki.llm.base import LLMProvider
from wiki.llm.prompts import build_resource_note_prompt, SYSTEM_PROMPT, PROMPT_VERSION


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
    "Why this resource matters",
    "One-line memory hook",
    "Source-backed summary",
    "What this resource covers",
    "First-principles explanation",
    "Source-backed notes",
    "Timeline of ideas",
    "Examples",
    "Missing pieces from the resource",
    "LLM-added explanations",
    "Needs verification",
    "Related concepts",
    "Revision questions",
    "Harish project connection",
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
    for section in ["Source-backed summary", "Source-backed notes", "Citations"]:
        body = _extract_section(content, section)
        if body and chunk_ids and not any(chunk_id in body for chunk_id in chunk_ids):
            issues.append(f"{section} must cite source chunk IDs")

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
            "title": record.title or "Unknown",
            "author": record.author or "Unknown",
            "url": record.original_url,
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
            raise RuntimeError(
                f"Generated note failed contract for {record.id}: "
                + "; ".join(contract_issues)
            )
        
        # Compute output hash
        output_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        
        # Create processed directory
        proc_dir = config.get_data_path("processed", "resources")
        proc_dir.mkdir(parents=True, exist_ok=True)
        
        # Save note as Markdown
        note_filename = f"{record.id.replace(':', '_')}.md"
        note_path = proc_dir / note_filename
        Storage.write_text(content, note_path)
        
        # Save metadata as JSON
        note_data = {
            "resource_id": record.id,
            "generated_at": datetime.utcnow().isoformat(),
            "llm_provider": self.provider.provider_name,
            "llm_model": self.provider.model,
            "prompt_version": PROMPT_VERSION,
            "prompt_hash": prompt_hash,
            "source_chunks_hash": chunks_hash,
            "generated_output_hash": output_hash,
            "chunk_count": len(chunks),
        }
        
        json_path = proc_dir / f"{record.id.replace(':', '_')}.json"
        Storage.write_json(note_data, json_path)
        
        # Update record
        record.generated_note_path = note_path
        record.prompt_hash = prompt_hash
        record.source_chunks_hash = chunks_hash
        record.generated_output_hash = output_hash
        record.llm_provider = self.provider.provider_name
        record.llm_model = self.provider.model
        record.prompt_version = PROMPT_VERSION
        record.status = ResourceStatus.LLM_NOTE_GENERATED
        
        return note_path


# Global instance (initialized with provider when needed)
note_generator: NoteGenerator | None = None


def get_note_generator(provider: LLMProvider) -> NoteGenerator:
    """Get or create the note generator."""
    global note_generator
    if note_generator is None or note_generator.provider != provider:
        note_generator = NoteGenerator(provider)
    return note_generator
