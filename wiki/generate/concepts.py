"""Extract and aggregate concepts from resources."""

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from wiki.config import config
from wiki.resource_utils import display_title
from wiki.schemas import Concept, ConceptResourceRef, ResourceRecord
from wiki.storage import Storage


class ConceptExtractor:
    """Extract and aggregate concepts from generated notes."""
    
    def __init__(self) -> None:
        """Initialize concept extractor."""
        self.concepts: Dict[str, Concept] = {}
    
    def slugify(self, name: str) -> str:
        """Convert concept name to slug."""
        # Lowercase, replace spaces with hyphens, remove special chars
        slug = name.lower().strip()
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[\s]+', '-', slug)
        slug = re.sub(r'-+', '-', slug)
        return slug.strip('-')
    
    def extract_from_note(self, record: ResourceRecord, note_content: str) -> List[Concept]:
        """Extract concepts from a note's content.
        
        For now, this is a simple keyword-based extraction.
        In a full implementation, this would use the LLM.
        """
        concepts_found: List[Concept] = []
        
        concept_names = self._extract_concept_names(note_content)
        fallback_definitions = {
            "Embeddings": "Vector representations used for similarity and retrieval.",
            "RAG": "Retrieval-Augmented Generation: adding retrieved context before generation.",
            "Chunking": "Splitting source material into citeable retrieval units.",
            "Tokenization": "Converting text into model-readable tokens.",
            "Vector Database": "Storage optimized for vector similarity search.",
            "LLM": "Large Language Model.",
            "Transformer": "Neural network architecture built around attention.",
            "Attention": "Mechanism for weighting relevant parts of context.",
            "Inference": "Running a trained model to produce outputs.",
            "Fine-tuning": "Adapting a pre-trained model with additional training.",
            "Prompt Engineering": "Designing model inputs to shape outputs.",
            "Cosine Similarity": "Similarity measure commonly used with vectors.",
            "Retrieval": "Fetching source material relevant to a query.",
            "Context Window": "The amount of text a model can consider at once.",
        }

        for name in concept_names:
            definition = fallback_definitions.get(
                name,
                "Mentioned in generated notes. Needs source review before becoming a stable definition.",
            )
            if name.lower() in note_content.lower():
                slug = self.slugify(name)
                
                concept = Concept(
                    name=name,
                    slug=slug,
                    definition=definition,
                    mental_model=(
                        "Review the linked resources for the concrete explanation. "
                        "This concept page is an index until source-backed synthesis is added."
                    ),
                    why_relevant=(
                        f"{name} appears in Harish's learning notes and may be useful "
                        "for revision or project work."
                    ),
                    llm_added_clarification=(
                        "Needs review: this page was assembled from generated notes and keyword extraction."
                    ),
                    practical_implementation=(
                        "Use the linked resources to extract a source-backed implementation note."
                    ),
                    resources=[
                        ConceptResourceRef(
                            resource_id=record.id,
                            resource_title=display_title(record, mark_missing=True),
                            coverage_quality="needs_review",
                            learned_at=record.processed_at or datetime.utcnow()
                        )
                    ]
                )
                
                concepts_found.append(concept)
        
        return concepts_found

    def _extract_concept_names(self, note_content: str) -> List[str]:
        """Extract concept candidates from note sections and conservative keyword matches."""
        names: list[str] = []
        for section_name in ["Related concepts", "What this resource covers"]:
            section = self._extract_section(note_content, section_name)
            for line in section.splitlines():
                stripped = line.strip()
                if not stripped.startswith("-"):
                    continue
                candidate = stripped.lstrip("-").strip()
                candidate = re.sub(r"\[[^\]]+\]", "", candidate).strip()
                candidate = candidate.split(":")[0].strip(" `*")
                if 2 <= len(candidate) <= 60:
                    names.append(candidate)

        keyword_names = [
            "Embeddings", "RAG", "Chunking", "Tokenization", "Vector Database",
            "LLM", "Transformer", "Attention", "Inference", "Fine-tuning",
            "Prompt Engineering", "Cosine Similarity", "Retrieval", "Context Window",
        ]
        lowered = note_content.lower()
        for name in keyword_names:
            if name.lower() in lowered:
                names.append(name)

        seen = set()
        unique = []
        for name in names:
            key = name.lower()
            if key not in seen:
                seen.add(key)
                unique.append(name)
        return unique[:20]

    def _extract_section(self, content: str, heading: str) -> str:
        """Extract section body by Markdown heading."""
        lines = content.splitlines()
        target = heading.lower()
        start = None
        level = None
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("#"):
                continue
            text = stripped.lstrip("#").strip().lower()
            if text == target:
                start = index + 1
                level = len(stripped) - len(stripped.lstrip("#"))
                break
        if start is None or level is None:
            return ""
        end = len(lines)
        for index in range(start, len(lines)):
            stripped = lines[index].strip()
            if stripped.startswith("#"):
                next_level = len(stripped) - len(stripped.lstrip("#"))
                if next_level <= level:
                    end = index
                    break
        return "\n".join(lines[start:end])
    
    def aggregate(self, records: List[ResourceRecord]) -> Dict[str, Concept]:
        """Aggregate concepts from all resources.
        
        Returns a dictionary mapping slugs to merged concepts.
        """
        for record in records:
            if not record.generated_note_path:
                continue
            
            # Read note content
            try:
                content = Storage.read_text(record.generated_note_path)
            except Exception:
                continue
            
            # Extract concepts
            concepts = self.extract_from_note(record, content)
            
            # Merge into global concept dictionary
            for concept in concepts:
                if concept.slug in self.concepts:
                    # Merge resources
                    existing = self.concepts[concept.slug]
                    existing_resources = {r.resource_id for r in existing.resources}
                    
                    for ref in concept.resources:
                        if ref.resource_id not in existing_resources:
                            existing.resources.append(ref)
                    
                    existing.updated_at = datetime.utcnow()
                else:
                    self.concepts[concept.slug] = concept
        
        return self.concepts
    
    def save(self) -> Path:
        """Save concepts to disk.
        
        Returns path to concepts directory.
        """
        concepts_dir = config.get_data_path("processed", "concepts")
        concepts_dir.mkdir(parents=True, exist_ok=True)
        for old in list(concepts_dir.glob("*.md")) + list(concepts_dir.glob("*.json")):
            old.unlink()
        
        for slug, concept in self.concepts.items():
            # Save as Markdown
            md_content = self._format_concept_markdown(concept)
            md_path = concepts_dir / f"{slug}.md"
            Storage.write_text(md_content, md_path)
            
            # Save as JSON
            json_path = concepts_dir / f"{slug}.json"
            Storage.write_json(concept.model_dump(), json_path)
        
        return concepts_dir
    
    def _format_concept_markdown(self, concept: Concept) -> str:
        """Format a concept as Markdown."""
        lines = [
            f"# {concept.name}",
            "",
            "## Definition",
            "",
            concept.definition,
            "",
            "## Mental Model",
            "",
            concept.mental_model,
            "",
            "## Why Harish Should Care",
            "",
            concept.why_relevant,
            "",
            "## Learned From",
            "",
        ]
        
        for ref in concept.resources:
            lines.append(f"- [{ref.resource_title}](../resources/{ref.resource_id.replace(':', '_')})")
        
        if concept.revision_questions:
            lines.extend([
                "",
                "## Revision Questions",
                "",
            ])
            for q in concept.revision_questions:
                lines.append(f"- {q}")
        
        lines.extend([
            "",
            "## Needs Review",
            "",
            concept.llm_added_clarification,
            "",
            "## Provenance",
            "",
            f"- Generated: {concept.generated_at.isoformat()}",
        ])
        
        return "\n".join(lines)


# Global instance
concept_extractor = ConceptExtractor()
