"""Metadata enrichment for resources.

Fetches and stores metadata (title, author, description, etc.) for
YouTube videos using yt-dlp and for webpages using OpenGraph/meta tags.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from wiki.config import config
from wiki.schemas import ResourceRecord
from wiki.storage import Storage

logger = logging.getLogger(__name__)


def _is_missing_text(value: Optional[str]) -> bool:
    """Return True for empty placeholder metadata values."""
    return value is None or not str(value).strip() or str(value).strip().lower() == "untitled"


class YouTubeMetadataEnricher:
    """Enrich YouTube resources with video metadata using yt-dlp.
    
    Fetches title, channel, description, duration, thumbnail, upload date
    without downloading any video/audio.
    """
    
    def __init__(self) -> None:
        """Initialize the YouTube metadata enricher."""
        self._ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,
        }
        self._ytdl_available: Optional[bool] = None
        self._ytdl = None
    
    def _get_ytdl(self):
        """Lazily import and create yt-dlp instance."""
        if self._ytdl_available is None:
            try:
                from yt_dlp import YoutubeDL
                self._ytdl = YoutubeDL(self._ydl_opts)
                self._ytdl_available = True
            except ImportError:
                self._ytdl_available = False
                logger.warning("yt-dlp not available. Install with: pip install yt-dlp")
        return self._ytdl if self._ytdl_available else None
    
    def enrich(self, record: ResourceRecord, force: bool = False) -> ResourceRecord:
        """Enrich a YouTube resource with metadata.
        
        Skips if metadata.json already has a title (unless force=True).
        """
        video_id = record.extra.get('video_id')
        if not video_id:
            # Try to extract from canonical_id
            if record.canonical_id.startswith('youtube:'):
                video_id = record.canonical_id.split(':', 1)[1]
            else:
                video_id = _extract_video_id_from_url(record.original_url)
        
        if not video_id:
            logger.warning(f"Cannot extract video ID for {record.id}")
            record.extra['metadata_status'] = 'failed_retryable'
            record.extra['metadata_failure_reason'] = 'Cannot extract video ID'
            return record
        
        # Check if metadata already enriched
        raw_dir = config.get_data_path("raw", "youtube", video_id)
        metadata_path = raw_dir / "metadata.json"
        
        if metadata_path.exists() and not force:
            try:
                existing = Storage.read_json(metadata_path)
                if existing.get('title'):
                    logger.info(f"Metadata already enriched for {video_id}, skipping (use --force to re-fetch)")
                    # Still update the record from existing metadata
                    record = self._update_record_from_metadata(record, existing)
                    record.extra['metadata_status'] = 'enriched'
                    record.extra.pop('metadata_failure_reason', None)
                    return record
            except Exception:
                pass
        
        # Fetch metadata using yt-dlp
        ytdl = self._get_ytdl()
        if ytdl is None:
            logger.warning(f"yt-dlp not available, skipping metadata enrichment for {video_id}")
            record.extra['metadata_status'] = 'failed_retryable'
            record.extra['metadata_failure_reason'] = 'yt-dlp not available'
            return record
        
        try:
            info = ytdl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=False,
            )
        except Exception as e:
            logger.error(f"Failed to fetch metadata for {video_id}: {e}")
            record.extra['metadata_status'] = 'failed_retryable'
            record.extra['metadata_failure_reason'] = str(e)
            return record
        
        if info is None:
            logger.error(f"No metadata returned for {video_id}")
            record.extra['metadata_status'] = 'failed_retryable'
            record.extra['metadata_failure_reason'] = 'No metadata returned'
            return record
        
        # Build metadata dict
        description = info.get('description', '') or ''
        if len(description) > 500:
            description = description[:500] + '...'
        
        metadata = {
            "video_id": video_id,
            "url": record.original_url,
            "webpage_url": info.get('webpage_url') or f"https://www.youtube.com/watch?v={video_id}",
            "canonical_id": record.canonical_id,
            "title": info.get('title'),
            "channel": info.get('channel') or info.get('uploader'),
            "channel_url": info.get('channel_url') or info.get('uploader_url'),
            "upload_date": info.get('upload_date'),
            "duration": info.get('duration'),
            "thumbnail": info.get('thumbnail'),
            "description": description,
            "language": info.get('language'),
            "entry_count": record.extra.get('entry_count'),
            "first_seen_at": record.first_seen_at.isoformat() if record.first_seen_at else None,
            "metadata_enriched_at": datetime.utcnow().isoformat(),
            "metadata_source": "yt-dlp",
        }
        
        # Preserve transcript info if it exists
        if metadata_path.exists():
            try:
                existing = Storage.read_json(metadata_path)
                metadata['language'] = metadata.get('language') or existing.get('language')
                metadata['entry_count'] = metadata.get('entry_count') or existing.get('entry_count')
            except Exception:
                pass
        
        # Save metadata
        raw_dir.mkdir(parents=True, exist_ok=True)
        Storage.write_json(metadata, metadata_path)
        
        # Update the record
        record = self._update_record_from_metadata(record, metadata)
        record.extra['metadata_status'] = 'enriched'
        record.extra.pop('metadata_failure_reason', None)
        
        logger.info(f"Enriched metadata for {video_id}: {metadata.get('title', 'No title')}")
        
        return record
    
    def _update_record_from_metadata(self, record: ResourceRecord, metadata: Dict[str, Any]) -> ResourceRecord:
        """Update a ResourceRecord from metadata dict."""
        if metadata.get('title') and _is_missing_text(record.title):
            record.title = metadata['title']
        if metadata.get('channel') and _is_missing_text(record.author):
            record.author = metadata['channel']
        if metadata.get('upload_date') and not record.published_at:
            try:
                # yt-dlp returns upload_date as YYYYMMDD string
                date_str = metadata['upload_date']
                if date_str and len(date_str) == 8:
                    record.published_at = datetime.strptime(date_str, '%Y%m%d')
            except (ValueError, TypeError):
                pass
        if metadata.get('description') and _is_missing_text(record.description):
            record.description = metadata['description']
        
        # Store extra fields
        for key in ['duration', 'thumbnail', 'channel_url', 'video_length']:
            if key in metadata and metadata[key] is not None:
                record.extra[key] = metadata[key]
        
        if metadata.get('metadata_enriched_at'):
            record.extra['metadata_enriched_at'] = metadata.get('metadata_enriched_at')
        
        return record


class WebpageMetadataEnricher:
    """Enrich webpage resources with metadata from OpenGraph/Twitter/meta tags.
    
    Reads the already-fetched raw HTML and extracts structured metadata.
    """
    
    def enrich(self, record: ResourceRecord, force: bool = False) -> ResourceRecord:
        """Enrich a webpage resource with metadata from HTML.
        
        Reads the raw HTML file and extracts title, author, description,
        published date from OpenGraph, Twitter Card, and meta tags.
        """
        if not record.local_raw_path:
            logger.warning(f"No raw path for {record.id}, skipping metadata enrichment")
            record.extra['metadata_status'] = 'failed_retryable'
            record.extra['metadata_failure_reason'] = 'No raw path'
            return record
        
        # Find raw HTML file
        raw_dir = Path(record.local_raw_path)
        html_path = raw_dir / "raw.html"
        
        if not html_path.exists():
            logger.warning(f"No raw HTML found for {record.id}")
            record.extra['metadata_status'] = 'failed_retryable'
            record.extra['metadata_failure_reason'] = 'No raw HTML found'
            return record
        
        # Check if metadata already enriched
        metadata_path = raw_dir / "metadata.json"
        if metadata_path.exists() and not force:
            try:
                existing = Storage.read_json(metadata_path)
                if existing.get('title'):
                    logger.info(f"Metadata already enriched for {record.id}, skipping (use --force to re-fetch)")
                    record = self._update_record_from_metadata(record, existing)
                    record.extra['metadata_status'] = 'enriched'
                    record.extra.pop('metadata_failure_reason', None)
                    return record
            except Exception:
                pass
        
        # Read and parse HTML - re-fetch if local copy is unusable
        html = None
        try:
            html = Storage.read_text(html_path)
            # Check if it's actually parseable HTML
            # A real HTML file starts with <!DOCTYPE or <html or <HTML
            html_lower = html.strip().lower()[:500]
            if html_lower.startswith('<!doctype') or html_lower.startswith('<html') or '<head' in html_lower:
                pass  # Looks like valid HTML
            else:
                logger.warning(f"Local HTML for {record.id} appears binary/compressed, re-fetching...")
                html = None
        except Exception:
            pass
        
        if html is None:
            # Re-fetch the webpage
            try:
                from wiki.ingest.webpage import WebpageIngestor
                ingestor = WebpageIngestor()
                fetched_html, status_code = ingestor.fetch(record.original_url)
                html = fetched_html
                # Save the re-fetched HTML
                Storage.write_text(html, html_path)
                logger.info(f"Re-fetched webpage for {record.id} (status: {status_code})")
            except Exception as e:
                logger.error(f"Failed to re-fetch webpage for {record.id}: {e}")
                record.extra['metadata_status'] = 'failed_retryable'
                record.extra['metadata_failure_reason'] = str(e)
                return record
        
        # Extract metadata
        metadata = self._extract_metadata(html, record.original_url)
        
        # Merge with existing metadata
        if metadata_path.exists():
            try:
                existing = Storage.read_json(metadata_path)
                # Keep existing values that are not None
                for key in existing:
                    if key not in metadata or metadata[key] is None:
                        metadata[key] = existing[key]
            except Exception:
                pass
        
        # Add enrichment timestamp
        metadata['metadata_enriched_at'] = datetime.utcnow().isoformat()
        metadata['metadata_source'] = metadata.get('metadata_source', 'opengraph')
        
        # Save metadata
        Storage.write_json(metadata, metadata_path)
        
        # Update record
        record = self._update_record_from_metadata(record, metadata)
        record.extra['metadata_status'] = 'enriched' if metadata.get('title') else 'partial'
        if metadata.get('title'):
            record.extra.pop('metadata_failure_reason', None)
        
        logger.info(f"Enriched metadata for {record.id}: {metadata.get('title', 'No title')}")
        
        return record
    
    def _extract_metadata(self, html: str, url: str) -> Dict[str, Any]:
        """Extract metadata from HTML using OpenGraph, Twitter Card, and meta tags."""
        
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return {'title': None, 'author': None, 'description': None, 'published': None}
        
        soup = BeautifulSoup(html, 'html.parser')
        from urllib.parse import urlparse
        
        title = None
        author = None
        description = None
        published = None
        image = None
        site_name = None
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # 1. OpenGraph tags (highest priority)
        og_tags = {
            'title': self._get_meta_content(soup, 'og:title'),
            'description': self._get_meta_content(soup, 'og:description'),
            'image': self._get_meta_content(soup, 'og:image'),
            'site_name': self._get_meta_content(soup, 'og:site_name'),
            'type': self._get_meta_content(soup, 'og:type'),
        }
        
        # OpenGraph article:published_time
        published_time = self._get_meta_content(soup, 'article:published_time')
        if published_time:
            published = published_time
        
        # 2. Twitter Card tags
        twitter_title = self._get_meta_content(soup, 'twitter:title')
        twitter_description = self._get_meta_content(soup, 'twitter:description')
        twitter_image = self._get_meta_content(soup, 'twitter:image')
        
        # 3. Standard HTML tags (fallback)
        html_title = None
        if soup.title and soup.title.string:
            html_title = soup.title.string.strip()
        
        meta_description = self._get_meta_content(soup, 'description', attr='name')
        meta_author = self._get_meta_content(soup, 'author', attr='name')
        
        # Also check <meta name="description"> without property
        if not meta_description:
            for tag in soup.find_all('meta'):
                if tag.get('name', '').lower() == 'description' and tag.get('content'):
                    meta_description = tag['content'].strip()
                    break
        
        # Also check <meta name="author">
        if not meta_author:
            for tag in soup.find_all('meta'):
                if tag.get('name', '').lower() == 'author' and tag.get('content'):
                    meta_author = tag['content'].strip()
                    break
        
        # Also check <link rel="author">
        if not meta_author:
            link_author = soup.find('link', rel='author')
            if link_author and link_author.get('href'):
                meta_author = link_author['href']
        
        # 4. First <h1> as title fallback
        h1_title = None
        h1 = soup.find('h1')
        if h1:
            h1_title = h1.get_text(strip=True)
        
        # Priority: OpenGraph > Twitter > HTML meta > h1
        title = og_tags.get('title') or twitter_title or html_title or h1_title
        description = og_tags.get('description') or twitter_description or meta_description
        author = meta_author or og_tags.get('site_name')
        image = og_tags.get('image') or twitter_image
        site_name = og_tags.get('site_name')
        
        # Clean up title (remove site name suffix like " | Medium" etc.)
        if title:
            title = title.strip()
            # Remove common suffixes
            for separator in [' - Medium', ' | Medium', ' — Medium', ' - YouTube', ' | YouTube']:
                if title.endswith(separator):
                    title = title[:-len(separator)].strip()
        
        return {
            'title': title,
            'author': author,
            'description': description,
            'published': published,
            'image': image,
            'site_name': site_name,
            'domain': domain,
            'canonical_url': self._canonical_url(soup, url),
            'og_type': og_tags.get('type'),
            'url': url,
        }
    
    def _get_meta_content(self, soup, property_name: str, attr: str = 'property') -> Optional[str]:
        """Get content from a meta tag by property or name attribute."""
        # Try property attribute first (OG tags)
        tag = soup.find('meta', attrs={attr: property_name})
        if tag and tag.get('content'):
            return tag['content'].strip()
        
        # Try name attribute (some sites use name instead of property)
        if attr != 'name':
            tag = soup.find('meta', attrs={'name': property_name})
            if tag and tag.get('content'):
                return tag['content'].strip()
        
        return None

    def _canonical_url(self, soup, fallback_url: str) -> str:
        """Extract canonical URL from HTML with fallback."""
        link = soup.find('link', rel='canonical')
        if link and link.get('href'):
            return link['href'].strip()
        return fallback_url
    
    def _update_record_from_metadata(self, record: ResourceRecord, metadata: Dict[str, Any]) -> ResourceRecord:
        """Update a ResourceRecord from metadata dict."""
        if metadata.get('title') and _is_missing_text(record.title):
            record.title = metadata['title']
        if metadata.get('author') and _is_missing_text(record.author):
            record.author = metadata['author']
        if metadata.get('published') and not record.published_at:
            if isinstance(metadata['published'], str):
                try:
                    # Try multiple date formats
                    clean_date = metadata['published'].replace('Z', '+00:00')
                    try:
                        record.published_at = datetime.fromisoformat(clean_date)
                    except ValueError:
                        pass
                    for fmt in ['%Y-%m-%d', '%Y%m%d', '%Y-%m-%dT%H:%M:%S', '%a, %d %b %Y %H:%M:%S']:
                        try:
                            record.published_at = datetime.strptime(metadata['published'][:19], fmt)
                            break
                        except ValueError:
                            continue
                except (ValueError, TypeError):
                    pass
            elif isinstance(metadata['published'], datetime):
                record.published_at = metadata['published']
        if metadata.get('description') and _is_missing_text(record.description):
            record.description = metadata['description'][:500]
        if metadata.get('metadata_enriched_at'):
            record.extra['metadata_enriched_at'] = metadata.get('metadata_enriched_at')
        if metadata.get('site_name'):
            record.extra['site_name'] = metadata.get('site_name')
        if metadata.get('domain'):
            record.extra['domain'] = metadata.get('domain')
        if metadata.get('canonical_url'):
            record.normalized_url = record.normalized_url or metadata.get('canonical_url')
        
        return record


def _extract_video_id_from_url(url: str) -> Optional[str]:
    """Extract YouTube video ID from URL."""
    import re
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


# Global instances
youtube_metadata_enricher = YouTubeMetadataEnricher()
webpage_metadata_enricher = WebpageMetadataEnricher()
