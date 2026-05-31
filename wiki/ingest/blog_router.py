"""Route public webpages to platform-specific blog extractors."""

from __future__ import annotations

from urllib.parse import urlparse

from wiki.ingest.blog_extractors.base import BlogExtractor
from wiki.ingest.blog_extractors.generic import GenericWebpageExtractor
from wiki.ingest.blog_extractors.huggingface import HuggingFaceBlogExtractor
from wiki.ingest.blog_extractors.medium import MediumExtractor


def get_blog_extractor(url: str) -> BlogExtractor:
    """Return the best extractor for a URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    path = parsed.path or ""

    if domain == "huggingface.co" and path.startswith("/blog/"):
        return HuggingFaceBlogExtractor()
    if domain == "medium.com" or domain.endswith(".medium.com"):
        return MediumExtractor()
    return GenericWebpageExtractor()

