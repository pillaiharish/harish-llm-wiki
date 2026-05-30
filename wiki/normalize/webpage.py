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


# Global instance
webpage_normalizer = WebpageNormalizer()
