"""Extract and aggregate concepts from resources."""

import json
import re
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set

from wiki.config import config
from wiki.schemas import Concept, ConceptResourceRef, ResourceRecord, ResourceStatus
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
        
        # Look for concept mentions in different sections
        # This is a simplified extraction - real implementation would use LLM
        
        # Common LLM/AI concepts to extract
        concept_keywords = [
            ("Embeddings", "Dense vector representations of text"),
            ("RAG", "Retrieval-Augmented Generation"),
            ("Chunking", "Breaking text into segments"),
            ("Tokenization", "Splitting text into tokens"),
            ("Vector Database", "Database optimized for vector similarity search"),
            ("LLM", "Large Language Model"),
            ("Transformer", "Neural network architecture"),
            ("Attention", "Mechanism for focusing on relevant parts"),
            ("Inference", "Running a model to generate predictions"),
            ("Fine-tuning", "Adapting a pre-trained model to specific tasks"),
            ("Prompt Engineering", "Crafting effective prompts for LLMs"),
            ("Cosine Similarity", "Measure of vector similarity"),
            ("Retrieval", "Fetching relevant documents"),
            ("Context Window", "Maximum tokens a model can process"),
        ]
        
        for name, definition in concept_keywords:
            # Check if concept is mentioned in the note
            if name.lower() in note_content.lower():
                slug = self.slugify(name)
                
                concept = Concept(
                    name=name,
                    slug=slug,
                    definition=definition,
                    mental_model=f"{name} is a fundamental concept in modern AI.",
                    why_relevant=f"Understanding {name} is essential for building AI applications.",
                    llm_added_clarification=f"This is a placeholder clarification for {name}. Replace with LLM-generated content.",
                    practical_implementation=f"Practical implementation of {name} concepts.",
                    resources=[
                        ConceptResourceRef(
                            resource_id=record.id,
                            resource_title=record.title or "Unknown",
                            coverage_quality="partial",
                            learned_at=record.processed_at or datetime.utcnow()
                        )
                    ]
                )
                
                concepts_found.append(concept)
        
        return concepts_found
    
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
            "## Provenance",
            "",
            f"- Generated: {concept.generated_at.isoformat()}",
        ])
        
        return "\n".join(lines)


# Global instance
concept_extractor = ConceptExtractor()
