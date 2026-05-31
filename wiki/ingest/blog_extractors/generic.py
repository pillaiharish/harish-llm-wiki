"""Generic public webpage extractor."""

from __future__ import annotations

from bs4 import BeautifulSoup

from wiki.ingest.blog_extractors.base import BlogExtraction, BlogExtractor


class GenericWebpageExtractor(BlogExtractor):
    """Fallback extractor for unknown public webpages."""

    platform = "generic_webpage"

    def extract(self, html: str, url: str, *, status_code: int | None = None) -> BlogExtraction:
        """Extract basic metadata and readable text."""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        title = self._meta(soup, "og:title") or self._meta(soup, "twitter:title")
        if not title and soup.title and soup.title.string:
            title = soup.title.string.strip()
        h1 = soup.find("h1")
        title = title or (h1.get_text(" ", strip=True) if h1 else None)

        description = self._meta(soup, "og:description") or self._meta(soup, "description", attr="name")
        author = self._meta(soup, "author", attr="name")
        site_name = self._meta(soup, "og:site_name")
        published = (
            self._meta(soup, "article:published_time")
            or self._meta(soup, "date", attr="name")
            or self._meta(soup, "datePublished", attr="name")
        )
        canonical_url = self._canonical(soup, url)
        toc = [
            {"level": int(heading.name[1]), "title": heading.get_text(" ", strip=True)}
            for heading in soup.find_all(["h1", "h2", "h3"])
            if heading.get_text(" ", strip=True)
        ]

        main = soup.find("main") or soup.find("article") or soup.body or soup
        content = main.get_text(separator="\n\n", strip=True)
        return BlogExtraction(
            platform=self.platform,
            title=title,
            author=author,
            published_at=published,
            description=description,
            canonical_url=canonical_url,
            source_url=url,
            site_name=site_name,
            content_markdown=content if content else None,
            toc=toc,
            status_code=status_code,
            extractor=self.platform,
            requires_human_review=True,
        )

    def _meta(self, soup: BeautifulSoup, name: str, *, attr: str = "property") -> str | None:
        tag = soup.find("meta", attrs={attr: name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
        return None

    def _canonical(self, soup: BeautifulSoup, fallback_url: str) -> str:
        link = soup.find("link", rel="canonical")
        if link and link.get("href"):
            return link["href"].strip()
        return fallback_url

