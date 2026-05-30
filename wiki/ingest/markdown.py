"""Markdown file ingestion."""

import re
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

import yaml

from wiki.config import config
from wiki.schemas import ResourceRecord
from wiki.storage import Storage, write_json


class MarkdownIngestor:
    """Ingestor for manually saved Markdown files."""
    
    def parse_frontmatter(self, content: str) -> Tuple[Dict[str, Any], str]:
        """Parse YAML frontmatter from Markdown content.
        
        Returns:
            Tuple of (frontmatter_dict, body_content)
        """
        # Check for frontmatter
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    body = parts[2].strip()
                    return frontmatter, body
                except yaml.YAMLError:
                    pass
        
        # No frontmatter found
        return {}, content
    
    def ingest(self, file_path: Path, record: ResourceRecord,
               original_url: Optional[str] = None) -> ResourceRecord:
        """Ingest a Markdown file.
        
        Reads file, parses frontmatter, computes content hash.
        """
        # Read file
        content = Storage.read_text(file_path)
        
        # Parse frontmatter
        frontmatter, body = self.parse_frontmatter(content)
        
        # Compute content hash
        import hashlib
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        record.content_hash = content_hash
        
        # Update canonical_id with content hash
        record.canonical_id = f"markdown:{content_hash}"
        record.id = record.canonical_id
        
        # Extract metadata from frontmatter
        if 'title' in frontmatter:
            record.title = frontmatter['title']
        
        if 'author' in frontmatter:
            record.author = frontmatter['author']
        
        if 'original_url' in frontmatter:
            record.normalized_url = frontmatter['original_url']
        
        if original_url:
            record.normalized_url = original_url
        
        if 'user_read_at' in frontmatter:
            from datetime import datetime
            try:
                record.user_consumed_at = datetime.fromisoformat(frontmatter['user_read_at'])
            except ValueError:
                pass
        
        if 'tags' in frontmatter:
            record.tags = frontmatter['tags']
        
        # Create directory
        raw_dir = config.get_data_path("raw", "markdown", content_hash[:8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        
        # Build metadata
        metadata = {
            "original_file": str(file_path),
            "content_hash": content_hash,
            "canonical_id": record.canonical_id,
            "original_url": original_url or frontmatter.get('original_url'),
            "has_frontmatter": bool(frontmatter),
            "frontmatter_keys": list(frontmatter.keys()) if frontmatter else [],
        }
        
        # Save files
        write_json(metadata, "raw", "markdown", content_hash[:8], "metadata.json")
        Storage.write_text(content, raw_dir / "source.md")
        
        record.local_raw_path = raw_dir
        
        return record
    
    def ingest_from_content(self, content: str, record: ResourceRecord,
                           original_url: Optional[str] = None) -> ResourceRecord:
        """Ingest Markdown from string content.
        
        Used when importing content from other sources.
        """
        # Parse frontmatter
        frontmatter, body = self.parse_frontmatter(content)
        
        # Compute content hash
        import hashlib
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        record.content_hash = content_hash
        
        # Update canonical_id with content hash
        record.canonical_id = f"markdown:{content_hash}"
        record.id = record.canonical_id
        
        # Extract metadata from frontmatter
        if 'title' in frontmatter:
            record.title = frontmatter['title']
        
        if 'author' in frontmatter:
            record.author = frontmatter['author']
        
        if original_url:
            record.normalized_url = original_url
        
        if 'tags' in frontmatter:
            record.tags = frontmatter['tags']
        
        # Create directory
        raw_dir = config.get_data_path("raw", "markdown", content_hash[:8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        
        # Build metadata
        metadata = {
            "content_hash": content_hash,
            "canonical_id": record.canonical_id,
            "original_url": original_url or frontmatter.get('original_url'),
            "has_frontmatter": bool(frontmatter),
        }
        
        # Save files
        write_json(metadata, "raw", "markdown", content_hash[:8], "metadata.json")
        Storage.write_text(content, raw_dir / "source.md")
        
        record.local_raw_path = raw_dir
        
        return record


# Global instance
markdown_ingestor = MarkdownIngestor()
