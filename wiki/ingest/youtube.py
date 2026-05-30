"""YouTube video ingestion using youtube-transcript-api."""

import re
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse, parse_qs

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    YT_API_AVAILABLE = True
except ImportError:
    YT_API_AVAILABLE = False

from wiki.config import config
from wiki.schemas import ResourceRecord
from wiki.storage import Storage, write_json

logger = logging.getLogger(__name__)


def extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from URL."""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class YouTubeIngestor:
    """Ingestor for YouTube videos."""
    
    def __init__(self) -> None:
        """Initialize the YouTube ingestor."""
        if not YT_API_AVAILABLE:
            raise ImportError(
                "youtube-transcript-api is required. "
                "Install with: pip install youtube-transcript-api"
            )
        self.ytt_api = YouTubeTranscriptApi()
    
    def fetch_transcript(self, video_id: str) -> tuple[List[Dict[str, Any]], str]:
        """Fetch transcript for a YouTube video.
        
        Uses the youtube-transcript-api v1.x instance-based API.
        Tries English first, then falls back to first available language.
        
        Returns:
            Tuple of (transcript_entries, language_code)
            transcript_entries is a list of dicts with 'text', 'start', 'duration' keys
        """
        # Try direct fetch with English first (most common case)
        try:
            transcript_data = self.ytt_api.fetch(video_id, languages=['en'])
            entries = [
                {
                    "text": snippet.text,
                    "start": snippet.start,
                    "duration": snippet.duration,
                }
                for snippet in transcript_data
            ]
            return entries, "en"
        except Exception:
            pass
        
        # Try listing available transcripts and picking one
        try:
            transcript_list = self.ytt_api.list(video_id)
            
            # Try to find English transcript
            try:
                transcript = transcript_list.find_transcript(['en'])
            except Exception:
                # Fall back to first available transcript
                available = list(transcript_list)
                if not available:
                    raise RuntimeError(
                        f"No transcripts available for video {video_id}"
                    )
                transcript = available[0]
            
            # Fetch the selected transcript
            fetched = transcript.fetch()
            entries = [
                {
                    "text": snippet.text,
                    "start": snippet.start,
                    "duration": snippet.duration,
                }
                for snippet in fetched
            ]
            return entries, transcript.language_code
        
        except Exception as e:
            raise RuntimeError(f"Failed to fetch transcript for {video_id}: {e}")
    
    def ingest(self, record: ResourceRecord) -> ResourceRecord:
        """Ingest a YouTube video.
        
        Downloads transcript, saves raw files.
        Creates directory only after successful fetch.
        """
        video_id = extract_video_id(record.original_url)
        if not video_id:
            raise ValueError(f"Could not extract video ID from URL: {record.original_url}")
        
        # Update record with video ID
        record.extra['video_id'] = video_id
        
        # Fetch transcript FIRST (before creating directories)
        try:
            transcript_entries, language = self.fetch_transcript(video_id)
        except Exception as e:
            record.failure_reason = str(e)
            logger.error(f"Failed to fetch transcript for {video_id}: {e}")
            raise
        
        # Now create directory for this video (only after successful fetch)
        raw_dir = config.get_data_path("raw", "youtube", video_id)
        raw_dir.mkdir(parents=True, exist_ok=True)
        
        # Build metadata
        metadata = {
            "video_id": video_id,
            "url": record.original_url,
            "canonical_id": record.canonical_id,
            "language": language,
            "entry_count": len(transcript_entries),
            "first_seen_at": record.first_seen_at.isoformat() if record.first_seen_at else None,
        }
        
        if record.title:
            metadata["title"] = record.title
        
        # Save metadata
        write_json(metadata, "raw", "youtube", video_id, "metadata.json")
        
        # Save transcript as JSON
        write_json(transcript_entries, "raw", "youtube", video_id, "transcript.json")
        
        # Generate VTT format
        vtt_content = self._generate_vtt(transcript_entries)
        vtt_path = raw_dir / "transcript.vtt"
        Storage.write_text(vtt_content, vtt_path)
        
        # Update record
        record.local_raw_path = raw_dir
        
        return record
    
    def _generate_vtt(self, entries: List[Dict[str, Any]]) -> str:
        """Generate WebVTT format from transcript entries."""
        lines = ["WEBVTT", ""]
        
        for i, entry in enumerate(entries):
            start = entry['start']
            duration = entry.get('duration', 0)
            end = start + duration
            text = entry['text']
            
            start_vtt = self._format_vtt_timestamp(start)
            end_vtt = self._format_vtt_timestamp(end)
            
            lines.append(str(i + 1))
            lines.append(f"{start_vtt} --> {end_vtt}")
            lines.append(text)
            lines.append("")
        
        return "\n".join(lines)
    
    def _format_vtt_timestamp(self, seconds: float) -> str:
        """Format seconds as VTT timestamp (HH:MM:SS.mmm)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


# Global instance
youtube_ingestor = YouTubeIngestor()