"""Deduplication logic for resources."""

import re
import hashlib
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from typing import Optional, List

from wiki.schemas import SourceType, ResourceIdentity


def extract_youtube_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from various URL formats.
    
    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - With optional timestamp (&t=XXXs)
    """
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def extract_youtube_timestamp(url: str) -> Optional[int]:
    """Extract timestamp from YouTube URL (in seconds)."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    
    # Check for t or start parameter
    for param in ['t', 'start']:
        if param in query:
            value = query[param][0]
            # Handle formats like "670s" or just "670"
            value = value.rstrip('s')
            try:
                return int(value)
            except ValueError:
                continue
    
    return None


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication.
    
    - Lowercase scheme and domain
    - Remove trailing slash where safe
    - Remove tracking parameters
    - Strip fragments unless meaningful
    """
    parsed = urlparse(url)
    
    # Lowercase scheme and netloc
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    
    # Remove www. prefix for consistency
    if netloc.startswith('www.'):
        netloc = netloc[4:]
    
    # Parse query parameters
    query_dict = parse_qs(parsed.query)
    
    # Remove tracking parameters
    tracking_params = [
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
        'fbclid', 'gclid', 'ref', 'utm_id'
    ]
    
    for param in tracking_params:
        query_dict.pop(param, None)
    
    # Rebuild query string
    query = urlencode(query_dict, doseq=True) if query_dict else ''
    
    # Normalize path (remove trailing slash)
    path = parsed.path.rstrip('/') if parsed.path != '/' else parsed.path
    
    # Rebuild URL without fragment (unless it's a hash anchor for content)
    fragment = ''
    
    normalized = urlunparse((scheme, netloc, path, parsed.params, query, fragment))
    return normalized


def compute_content_hash(content: bytes) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content).hexdigest()


def compute_string_hash(text: str) -> str:
    """Compute SHA256 hash of a string."""
    return compute_content_hash(text.encode('utf-8'))


class Deduplicator:
    """Deduplication logic for resources."""
    
    @staticmethod
    def canonicalize_youtube(url: str) -> Optional[ResourceIdentity]:
        """Canonicalize a YouTube URL.
        
        Returns ResourceIdentity with canonical_id like "youtube:VIDEO_ID"
        """
        video_id = extract_youtube_video_id(url)
        if not video_id:
            return None
        
        timestamp = extract_youtube_timestamp(url)
        normalized = normalize_url(url)
        
        return ResourceIdentity(
            source_type=SourceType.YOUTUBE,
            canonical_id=f"youtube:{video_id}",
            original_url=url,
            normalized_url=normalized,
            video_id=video_id,
            start_time_seconds=timestamp,
            important_timestamps=[timestamp] if timestamp else []
        )
    
    @staticmethod
    def canonicalize_webpage(url: str) -> ResourceIdentity:
        """Canonicalize a webpage URL.
        
        Returns ResourceIdentity with canonical_id like "webpage:HASH"
        """
        normalized = normalize_url(url)
        content_hash = compute_string_hash(normalized)
        
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        
        return ResourceIdentity(
            source_type=SourceType.WEBPAGE,
            canonical_id=f"webpage:{content_hash}",
            original_url=url,
            normalized_url=normalized,
            domain=domain
        )
    
    @staticmethod
    def canonicalize_markdown(content: str, original_url: Optional[str] = None) -> ResourceIdentity:
        """Canonicalize a Markdown file.
        
        Returns ResourceIdentity with canonical_id like "markdown:HASH"
        """
        content_hash = compute_string_hash(content)
        
        return ResourceIdentity(
            source_type=SourceType.MARKDOWN,
            canonical_id=f"markdown:{content_hash}",
            original_url=original_url or "",
            normalized_url=original_url,
            content_hash=content_hash
        )
    
    @staticmethod
    def detect_source_type(url: str) -> SourceType:
        """Detect the source type from a URL."""
        if extract_youtube_video_id(url):
            return SourceType.YOUTUBE
        return SourceType.WEBPAGE
    
    @staticmethod
    def canonicalize(url: str, content: Optional[str] = None) -> Optional[ResourceIdentity]:
        """Canonicalize any URL.
        
        Auto-detects source type and applies appropriate canonicalization.
        """
        source_type = Deduplicator.detect_source_type(url)
        
        if source_type == SourceType.YOUTUBE:
            return Deduplicator.canonicalize_youtube(url)
        elif source_type == SourceType.WEBPAGE:
            return Deduplicator.canonicalize_webpage(url)
        
        return None
    
    @staticmethod
    def merge_timestamps(existing: List[int], new: Optional[int]) -> List[int]:
        """Merge timestamps, removing duplicates."""
        if new is None:
            return existing
        
        timestamps = set(existing)
        timestamps.add(new)
        return sorted(list(timestamps))


# Global deduplicator instance
deduplicator = Deduplicator()
