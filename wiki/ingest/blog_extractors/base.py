"""Base types for blog extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BlogExtraction:
    """Normalized extraction result for a blog or webpage."""

    platform: str
    title: str | None = None
    subtitle: str | None = None
    author: str | None = None
    published_at: str | None = None
    description: str | None = None
    canonical_url: str | None = None
    source_url: str | None = None
    site_name: str | None = None
    content_markdown: str | None = None
    toc: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    status_code: int | None = None
    extractor: str | None = None
    requires_human_review: bool = False
    metadata_status: str = "enriched"
    metadata_failure_reason: str | None = None

    def metadata(self) -> dict[str, Any]:
        """Return JSON-serializable metadata."""
        return {
            "platform": self.platform,
            "title": self.title,
            "subtitle": self.subtitle,
            "author": self.author,
            "published": self.published_at,
            "published_at": self.published_at,
            "description": self.description,
            "canonical_url": self.canonical_url,
            "source_url": self.source_url,
            "site_name": self.site_name,
            "toc": self.toc,
            "links": self.links,
            "status_code": self.status_code,
            "extractor": self.extractor,
            "requires_human_review": self.requires_human_review,
            "metadata_status": self.metadata_status,
            "metadata_failure_reason": self.metadata_failure_reason,
        }


class BlogExtractor:
    """Base extractor interface."""

    platform = "generic"

    def extract(self, html: str, url: str, *, status_code: int | None = None) -> BlogExtraction:
        """Extract metadata and Markdown content from HTML."""
        raise NotImplementedError

