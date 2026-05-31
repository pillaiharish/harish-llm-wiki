"""Medium public webpage extractor."""

from __future__ import annotations

from wiki.config import config
from wiki.ingest.blog_extractors.base import BlogExtraction
from wiki.ingest.blog_extractors.generic import GenericWebpageExtractor


class MediumExtractor(GenericWebpageExtractor):
    """Public-only Medium extractor.

    This does not bypass paywalls or login walls. If the public fetch does not
    expose substantial article content, the caller should request manual Markdown.
    """

    platform = "medium"

    def extract(self, html: str, url: str, *, status_code: int | None = None) -> BlogExtraction:
        result = super().extract(html, url, status_code=status_code)
        result.platform = self.platform
        result.extractor = self.platform
        content = result.content_markdown or ""
        blocked_markers = [
            "sign in",
            "member-only",
            "get unlimited access",
            "open in app",
        ]
        inaccessible = len(content.split()) < 200 or any(marker in content.lower() for marker in blocked_markers)
        if inaccessible:
            result.requires_human_review = True
            result.metadata_status = "needs_manual_markdown"
            result.metadata_failure_reason = (
                "Medium article may be behind a paywall or require login. "
                f"Paste/export Markdown into: {config.get_data_path('inbox', 'markdown', 'medium')}"
            )
        return result

