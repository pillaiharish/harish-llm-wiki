"""Mock LLM provider for testing."""

import json
from typing import Optional

from wiki.llm.base import LLMProvider
from wiki.llm.prompts import PROMPT_VERSION


class MockProvider(LLMProvider):
    """Mock LLM provider for testing.
    
    Generates deterministic placeholder notes with realistic structure.
    No network calls are made.
    """
    
    def __init__(self, temperature: float = 0.2) -> None:
        """Initialize mock provider."""
        super().__init__("mock-model", temperature)
        self.call_count = 0
    
    def generate(self, prompt: str, *, system: Optional[str] = None,
                 temperature: Optional[float] = None) -> str:
        """Generate deterministic mock content.
        
        Returns realistic placeholder content for testing.
        """
        self.call_count += 1
        
        # Extract resource info from prompt
        resource_title = self._extract_title(prompt)
        chunk_ids = self._extract_chunk_ids(prompt)
        
        # Generate deterministic mock content
        return self._generate_mock_note(resource_title, chunk_ids)
    
    def _extract_title(self, prompt: str) -> str:
        """Extract title from prompt."""
        metadata = self._extract_metadata(prompt)
        title = metadata.get("title")
        if title:
            return str(title)
        return "Untitled Resource"
    
    def _extract_chunk_ids(self, prompt: str) -> list[str]:
        """Extract real chunk IDs from the prompt."""
        chunk_ids: list[str] = []
        for line in prompt.splitlines():
            if line.startswith("CHUNK ID:") or line.startswith("### Chunk ID:"):
                chunk_id = line.split(":", 1)[1].strip()
                if chunk_id:
                    chunk_ids.append(chunk_id)
        return chunk_ids or ["chunk-001", "chunk-002", "chunk-003"]

    def _extract_metadata(self, prompt: str) -> dict:
        """Extract JSON metadata from the resource note prompt."""
        marker = "## Source Metadata"
        chunks_marker = "## Source Chunks"
        if marker not in prompt or chunks_marker not in prompt:
            return {}

        metadata_text = prompt.split(marker, 1)[1].split(chunks_marker, 1)[0].strip()
        try:
            return json.loads(metadata_text)
        except json.JSONDecodeError:
            return {}
    
    def _generate_mock_note(self, title: str, chunk_ids: list[str]) -> str:
        """Generate deterministic mock learning note."""
        # Generate mock citations
        citations = "\n".join(
            f"- Mock point from source chunk. Citation: [source: {chunk_id}]"
            for chunk_id in chunk_ids[:5]
        )
        
        return f"""# {title}

## Resource table of contents

- [00:00] Introduction [{chunk_ids[0]}]
- [03:00] Core mechanism [{chunk_ids[min(1, len(chunk_ids) - 1)]}]
- [08:00] Practical implications [{chunk_ids[min(2, len(chunk_ids) - 1)]}]

## Why this resource matters

This is a mock-generated learning note for testing the Harish LLM Wiki pipeline. 
The mock provider generates deterministic placeholder content so you can inspect 
the site layout, navigation, and structure without consuming cloud LLM tokens.

## One-line memory hook

"A resource becomes useful only when it is searchable, cited, and revisable."

## What this resource covers

- Core concepts from the source material
- Practical implementation details
- Common pitfalls and best practices
- Real-world applications

## Source-backed summary

{citations}

## First-principles explanation

### Simple intuition

At its core, this topic is about organizing knowledge so it can be retrieved 
when needed. Think of it like a personal library where every book has a detailed 
card catalog.

### Concrete example

Imagine trying to remember a specific debugging technique you learned from a 
YouTube video 6 months ago. Without proper notes and citations, you'd have to 
rewatch the entire video. With this wiki system, you can find the exact timestamp 
in seconds.

### Mechanics

The pipeline works in several stages:
1. **Ingestion** - Fetch raw content from sources
2. **Normalization** - Clean and chunk into citeable pieces
3. **Generation** - LLM creates structured learning notes
4. **Aggregation** - Build concept maps and timelines

## Concrete example / toy implementation

```python
def retrieve_then_answer(query: str, chunks: list[str]) -> str:
    relevant = search(query, chunks)
    return generate_answer(query, context=relevant)
```

## Real-system implications

In the age of information overload, **retrieval** is more valuable than 
**consumption**. This system optimizes for recall and revision.

## Common failure modes

- Not citing source chunks properly
- Mixing source-backed claims with LLM-added explanations
- Skipping the review step before publishing

## Harish project connections

Apply this same pipeline to:
- Technical documentation
- Research paper reading
- Conference talk summaries
- Online course notes

## What the resource did not cover

- Detailed performance benchmarks
- Comparison with alternative approaches
- Cost analysis for production use
- Security considerations

## LLM-added explanations

**Generated by: {self.provider_name} / {self.model}**

This section simulates explanation added by an LLM that was not explicitly 
covered in the source material. In a real note, this would:
- Fill conceptual gaps
- Provide additional context
- Connect to related topics
- Explain prerequisite knowledge

**Important**: Always verify LLM-added explanations against authoritative 
sources before relying on them for critical decisions.

## Needs verification

- Mock notes are placeholders and should be replaced with real source-specific notes before serious use.

## Recommended prerequisites

- Python basics
- LLM inference fundamentals
- GPU memory basics

## Suggested next learning topics

- Embeddings
- Vector databases
- Production deployment
- Quantization

## Revision questions

1. What is the primary goal of this resource?
2. Which source chunk supports the main claim about implementation?
3. What needs human review in this generated note?
4. How would you apply this to your own projects?
5. What are the common pitfalls mentioned?

## Citations

{citations}

## Provenance

- **Source type**: Mock (for testing)
- **Original URL**: See resource metadata
- **Local raw file**: `~/llm-wiki-data/raw/...`
- **Processed on**: 2026-05-30
- **LLM provider**: {self.provider_name}
- **LLM model**: {self.model}
- **Prompt version**: {PROMPT_VERSION}
- **Human review required**: true

---

*This is a mock-generated note for pipeline testing. Replace with real LLM-generated 
content when ready to consume cloud tokens.*
"""
    
    @property
    def provider_name(self) -> str:
        """Return provider name."""
        return "mock"
