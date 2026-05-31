"""Markdown normalization."""

import json
from pathlib import Path

from wiki.config import config
from wiki.schemas import ResourceRecord, SourceType
from wiki.storage import Storage
from wiki.normalize.chunker import chunker


class MarkdownNormalizer:
    """Normalizer for Markdown files."""
    
    def normalize(self, record: ResourceRecord) -> ResourceRecord:
        """Normalize a Markdown file.
        
        Reads source Markdown, creates normalized chunks.
        """
        if not record.local_raw_path:
            raise ValueError(f"No raw path for resource {record.id}")
        
        raw_dir = Path(record.local_raw_path)
        
        # Read source Markdown
        md_path = raw_dir / "source.md"
        if not md_path.exists():
            raise FileNotFoundError(f"No source.md found for {record.id}")
        
        content = Storage.read_text(md_path)
        
        # Compute hash for normalized directory
        content_hash = record.content_hash
        if not content_hash:
            import hashlib
            content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        
        # Create normalized directory
        norm_dir = config.get_data_path("normalized", "markdown", content_hash[:8])
        norm_dir.mkdir(parents=True, exist_ok=True)
        
        # Save normalized Markdown (copy)
        norm_md_path = norm_dir / "article.md"
        Storage.write_text(content, norm_md_path)
        
        # Generate chunks
        file_path = str(norm_md_path)
        source_type = record.source_type if record.source_type == SourceType.MEDIUM_MARKDOWN else SourceType.MARKDOWN
        chunks = list(chunker.chunk_text(
            content, record.id, source_type,
            url=record.normalized_url, file_path=file_path
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


# Global instance
markdown_normalizer = MarkdownNormalizer()
