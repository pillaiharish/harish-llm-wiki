"""Webpage normalization."""

import json
from pathlib import Path

from wiki.config import config
from wiki.schemas import ResourceRecord, SourceType, WebpageChunk
from wiki.storage import Storage
from wiki.normalize.chunker import chunker


class WebpageNormalizer:
    """Normalizer for webpage content."""
    
    def normalize(self, record: ResourceRecord) -> ResourceRecord:
        """Normalize a webpage.
        
        Reads extracted Markdown, creates normalized chunks.
        """
        if not record.local_raw_path:
            raise ValueError(f"No raw path for resource {record.id}")
        
        raw_dir = Path(record.local_raw_path)
        
        # Read extracted Markdown
        md_path = raw_dir / "extracted.md"
        if not md_path.exists():
            # Fall back to raw HTML converted to text
            html_path = raw_dir / "raw.html"
            if html_path.exists():
                from bs4 import BeautifulSoup
                html = Storage.read_text(html_path)
                soup = BeautifulSoup(html, 'html.parser')
                content = soup.get_text(separator='\n\n', strip=True)
            else:
                raise FileNotFoundError(f"No content found for {record.id}")
        else:
            content = Storage.read_text(md_path)
        
        # Compute hash for normalized directory
        content_hash = record.content_hash
        if not content_hash:
            import hashlib
            content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        
        # Create normalized directory
        norm_dir = config.get_data_path("normalized", "webpage", content_hash[:8])
        norm_dir.mkdir(parents=True, exist_ok=True)
        
        # Save normalized Markdown
        md_path = norm_dir / "article.md"
        Storage.write_text(content, md_path)
        
        # Generate chunks
        if record.extra.get("platform") == "huggingface_blog":
            chunks = self._chunk_huggingface_blog(content, record)
        else:
            chunks = list(chunker.chunk_text(
                content, record.id, SourceType.WEBPAGE, url=record.original_url
            ))
        
        # Save chunks as JSONL
        chunks_data = [chunk.model_dump() for chunk in chunks]
        chunks_path = norm_dir / "chunks.jsonl"
        
        with open(chunks_path, 'w', encoding='utf-8') as f:
            for chunk_data in chunks_data:
                f.write(json.dumps(chunk_data, ensure_ascii=False) + '\n')
        
        # Update record
        record.local_normalized_path = norm_dir
        
        return record

    def _chunk_huggingface_blog(self, content: str, record: ResourceRecord) -> list[WebpageChunk]:
        """Create section-aware chunks for Hugging Face blog pages."""
        sections = chunker._split_into_sections(content)
        stable_id = record.id.split(":", 1)[1] if ":" in record.id else record.id
        prefix = f"huggingface:{stable_id[:8]}"
        chunks: list[WebpageChunk] = []
        chunk_index = 1
        for section_heading, section_text in sections:
            if not section_text.strip():
                continue
            blocks = [block.strip() for block in section_text.split("\n\n") if block.strip()]
            paragraph_buffer: list[str] = []
            paragraph_start = 1
            code_index = 1
            paragraph_index = 1
            for block in blocks:
                if block.startswith("```"):
                    if paragraph_buffer:
                        chunks.append(self._create_hf_paragraph_chunk(
                            prefix, chunk_index, record, section_heading, paragraph_buffer, paragraph_start, paragraph_index - 1
                        ))
                        chunk_index += 1
                        paragraph_buffer = []
                    chunks.append(WebpageChunk(
                        resource_id=record.id,
                        chunk_id=f"{prefix}-c{chunk_index:04d}",
                        source_type=SourceType.WEBPAGE,
                        text=block,
                        section_heading=section_heading,
                        paragraph_index=paragraph_index,
                        citation_label=f'section "{section_heading or "Untitled"}", code block {code_index}',
                        url=record.original_url,
                    ))
                    chunk_index += 1
                    code_index += 1
                    continue
                if not paragraph_buffer:
                    paragraph_start = paragraph_index
                paragraph_buffer.append(block)
                if len(" ".join(paragraph_buffer).split()) >= chunker.TARGET_WORDS_PER_CHUNK:
                    chunks.append(self._create_hf_paragraph_chunk(
                        prefix, chunk_index, record, section_heading, paragraph_buffer, paragraph_start, paragraph_index
                    ))
                    chunk_index += 1
                    paragraph_buffer = []
                paragraph_index += 1
            if paragraph_buffer:
                chunks.append(self._create_hf_paragraph_chunk(
                    prefix, chunk_index, record, section_heading, paragraph_buffer, paragraph_start, paragraph_index - 1
                ))
                chunk_index += 1
        return chunks

    def _create_hf_paragraph_chunk(
        self,
        prefix: str,
        chunk_index: int,
        record: ResourceRecord,
        section_heading: str | None,
        paragraphs: list[str],
        start: int,
        end: int,
    ) -> WebpageChunk:
        """Create a Hugging Face paragraph chunk."""
        para_label = f"paragraphs {start}-{end}" if start != end else f"paragraph {start}"
        return WebpageChunk(
            resource_id=record.id,
            chunk_id=f"{prefix}-c{chunk_index:04d}",
            source_type=SourceType.WEBPAGE,
            text="\n\n".join(paragraphs),
            section_heading=section_heading,
            paragraph_index=start,
            citation_label=f'section "{section_heading or "Untitled"}", {para_label}',
            url=record.original_url,
        )


# Global instance
webpage_normalizer = WebpageNormalizer()
