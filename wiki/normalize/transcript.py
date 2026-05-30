"""YouTube transcript normalization."""

import json
from pathlib import Path
from typing import List, Dict, Any

from wiki.config import config
from wiki.schemas import ResourceRecord, SourceType, YouTubeChunk
from wiki.storage import Storage, write_json
from wiki.normalize.chunker import chunker


class YouTubeNormalizer:
    """Normalizer for YouTube transcripts."""
    
    def normalize(self, record: ResourceRecord) -> ResourceRecord:
        """Normalize a YouTube transcript.
        
        Reads raw transcript, creates normalized Markdown and chunks.
        """
        if not record.local_raw_path:
            raise ValueError(f"No raw path for resource {record.id}")
        
        raw_dir = Path(record.local_raw_path)
        video_id = record.extra.get('video_id')
        
        if not video_id:
            raise ValueError(f"No video_id in resource {record.id}")
        
        # Read raw transcript
        transcript_path = raw_dir / "transcript.json"
        metadata_path = raw_dir / "metadata.json"
        
        transcript_entries = Storage.read_json(transcript_path)
        metadata = Storage.read_json(metadata_path)
        
        # Create normalized directory
        norm_dir = config.get_data_path("normalized", "youtube", video_id)
        norm_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate normalized Markdown
        title = metadata.get('title', 'Unknown Video')
        url = record.original_url
        channel = metadata.get('channel', 'Unknown Channel')
        
        markdown_lines = [
            f"# {title}",
            "",
            f"**Source:** [{url}]({url})",
            f"**Channel:** {channel}",
            "",
            "## Transcript",
            "",
        ]
        
        for entry in transcript_entries:
            start = entry['start']
            text = entry['text']
            timestamp = self._format_timestamp(start)
            markdown_lines.append(f"[{timestamp}] {text}")
        
        markdown_content = "\n".join(markdown_lines)
        
        # Save normalized Markdown
        md_path = norm_dir / "transcript.md"
        Storage.write_text(markdown_content, md_path)
        
        # Generate chunks
        chunks = list(chunker.chunk_youtube_transcript(
            transcript_entries, video_id, record.id
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
    
    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds as HH:MM:SS or MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"


# Global instance
youtube_normalizer = YouTubeNormalizer()
