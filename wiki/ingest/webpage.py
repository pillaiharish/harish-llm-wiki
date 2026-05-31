"""Webpage/blog ingestion with layered extraction strategy."""

import re
import time
import logging
from typing import Dict, Any
from urllib.parse import urlparse

import httpx

from wiki.config import config
from wiki.schemas import ResourceRecord, ResourceStatus
from wiki.storage import Storage, write_json

logger = logging.getLogger(__name__)

# Optional extraction libraries
try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False

try:
    from readability import Document as ReadabilityDocument
    READABILITY_AVAILABLE = True
except ImportError:
    READABILITY_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BEAUTIFULSOUP_AVAILABLE = True
except ImportError:
    BEAUTIFULSOUP_AVAILABLE = False


def sanitize_html(html: str) -> str:
    """Remove NULL bytes and control characters from HTML.
    
    readability-lxml crashes on NULL bytes and certain control characters.
    This function strips them before extraction.
    """
    if not html:
        return html
    # Remove NULL bytes
    html = html.replace('\x00', '')
    # Remove other control characters except \t, \n, \r
    html = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', '', html)
    # Remove invalid XML characters
    html = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', html)
    return html


class WebpageIngestor:
    """Ingestor for public webpages and blogs.
    
    Uses layered extraction strategy:
    1. httpx fetch
    2. trafilatura extraction (if available)
    3. readability-lxml fallback
    4. BeautifulSoup fallback
    5. Save raw HTML always when fetch succeeds
    """
    
    def __init__(self, timeout: int = 30, delay: float = 1.0) -> None:
        """Initialize the webpage ingestor."""
        self.timeout = timeout
        self.delay = delay
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                'User-Agent': (
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                # Keep this as identity so raw.html is reproducible decoded text.
                # Some environments do not have brotli support, which can turn
                # `response.text` into compressed-looking garbage.
                'Accept-Encoding': 'identity',
                'DNT': '1',
                'Connection': 'keep-alive',
            }
        )
    
    def fetch(self, url: str) -> tuple[str, int]:
        """Fetch a webpage.
        
        Returns:
            Tuple of (html_content, status_code)
        """
        try:
            response = self.client.get(url, follow_redirects=True)
            response.raise_for_status()
            
            # Small delay to be polite
            time.sleep(self.delay)
            
            html = response.text
            if not self._looks_like_html(html):
                raise RuntimeError(f"Fetched content for {url} does not look like decoded HTML")
            return html, response.status_code
            
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"HTTP error {e.response.status_code} for {url}: {e}")
        except httpx.RequestError as e:
            raise RuntimeError(f"Request failed for {url}: {e}")

    def _looks_like_html(self, html: str) -> bool:
        """Return True when fetched text looks like decoded HTML."""
        sample = html.strip().lower()[:1000]
        return sample.startswith("<!doctype") or sample.startswith("<html") or "<head" in sample
    
    def extract(self, html: str, url: str) -> Dict[str, Any]:
        """Extract content from HTML using available extractors.
        
        Sanitizes HTML before extraction to avoid crashes from
        NULL bytes and control characters.
        """
        # Sanitize HTML first
        html = sanitize_html(html)
        
        result = {
            'title': None,
            'content': None,
            'author': None,
            'published': None,
            'extractor': None,
            'requires_human_review': False
        }
        
        # Try trafilatura first (best quality)
        if TRAFILATURA_AVAILABLE:
            try:
                extracted = trafilatura.extract(
                    html,
                    url=url,
                    output_format='markdown',
                    include_comments=False,
                    include_tables=True
                )
                
                if extracted and len(extracted.strip()) > 100:
                    result['content'] = extracted
                    result['extractor'] = 'trafilatura'
                    
                    try:
                        metadata = trafilatura.extract_metadata(html, url=url)
                        if metadata:
                            result['title'] = getattr(metadata, 'title', None)
                            result['author'] = getattr(metadata, 'author', None)
                            result['published'] = getattr(metadata, 'date', None)
                    except Exception:
                        pass
                    
                    return result
            except Exception as e:
                logger.warning(f"trafilatura extraction failed for {url}: {e}")
        
        # Try readability-lxml
        if READABILITY_AVAILABLE:
            try:
                doc = ReadabilityDocument(html)
                content_html = doc.summary()
                
                if content_html and len(content_html.strip()) > 100:
                    # Convert to text/markdown
                    if BEAUTIFULSOUP_AVAILABLE:
                        soup = BeautifulSoup(content_html, 'html.parser')
                        result['content'] = soup.get_text(separator='\n\n', strip=True)
                    else:
                        result['content'] = content_html
                    
                    result['title'] = doc.title()
                    result['extractor'] = 'readability-lxml'
                    result['requires_human_review'] = True
                    
                    return result
            except Exception as e:
                logger.warning(f"readability-lxml extraction failed for {url}: {e}")
        
        # Fallback to BeautifulSoup
        if BEAUTIFULSOUP_AVAILABLE:
            try:
                soup = BeautifulSoup(html, 'html.parser')
                
                # Remove script and style elements
                for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                    tag.decompose()
                
                # Try to find main content
                main = soup.find('main') or soup.find('article') or soup.find('div', class_='content')
                
                if main:
                    text = main.get_text(separator='\n\n', strip=True)
                else:
                    text = soup.get_text(separator='\n\n', strip=True)
                
                if text and len(text) > 100:
                    result['content'] = text
                    result['title'] = soup.title.string if soup.title else None
                    result['extractor'] = 'beautifulsoup'
                    result['requires_human_review'] = True
                    
                    return result
            except Exception as e:
                logger.warning(f"BeautifulSoup extraction failed for {url}: {e}")
        
        # Last resort: return empty content with raw HTML flag
        result['content'] = None
        result['extractor'] = None
        result['requires_human_review'] = True
        
        return result
    
    def ingest(self, record: ResourceRecord) -> ResourceRecord:
        """Ingest a webpage.
        
        Fetches HTML, extracts content, saves raw files.
        Creates directory only after successful fetch.
        """
        url = record.original_url
        
        # Parse domain for storage path
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Fetch the page FIRST
        try:
            html, status_code = self.fetch(url)
        except Exception as e:
            record.failure_reason = str(e)
            logger.error(f"Failed to fetch {url}: {e}")
            raise
        
        # Compute content hash for deduplication (before creating dirs)
        import hashlib
        content_hash = hashlib.sha256(html.encode('utf-8')).hexdigest()
        record.content_hash = content_hash
        
        # NOW create directory using content hash
        raw_dir = config.get_data_path("raw", "webpage", domain, content_hash[:8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract content
        extraction = self.extract(html, url)
        
        # Build metadata
        metadata = {
            "url": url,
            "canonical_id": record.canonical_id,
            "domain": domain,
            "status_code": status_code,
            "content_hash": content_hash,
            "extractor": extraction['extractor'],
            "requires_human_review": extraction['requires_human_review'],
            "title": extraction['title'],
            "author": extraction['author'],
            "published": extraction['published'],
        }
        
        # Update record
        if extraction['title']:
            record.title = extraction['title']
        if extraction['author']:
            record.author = extraction['author']
        
        # Save files
        write_json(metadata, "raw", "webpage", domain, content_hash[:8], "metadata.json")
        Storage.write_text(html, raw_dir / "raw.html")
        record.local_raw_path = raw_dir
        
        if extraction['content']:
            Storage.write_text(extraction['content'], raw_dir / "extracted.md")
        
        # Enrich metadata from OpenGraph/meta tags if title is missing
        if not record.title:
            try:
                from wiki.enrich.metadata import webpage_metadata_enricher
                record = webpage_metadata_enricher.enrich(record)
                if record.title:
                    logger.info(f"Enriched webpage metadata from OG/meta tags: {record.title[:60]}")
            except Exception as e:
                logger.warning(f"Metadata enrichment failed for {url}: {e}")
        
        # Special handling for Medium
        if 'medium.com' in domain:
            if extraction['requires_human_review'] or not extraction['content']:
                record.status = ResourceStatus.NEEDS_MANUAL_MARKDOWN
                record.failure_reason = (
                    "Medium article may be behind paywall or require login. "
                    f"Please manually export to: {config.get_data_path('inbox', 'markdown', 'medium')}"
                )
                logger.warning(f"Medium article may need manual markdown: {url}")
        
        return record
    
    def __del__(self) -> None:
        """Cleanup HTTP client."""
        if hasattr(self, 'client'):
            try:
                self.client.close()
            except Exception:
                pass


# Global instance
webpage_ingestor = WebpageIngestor()
