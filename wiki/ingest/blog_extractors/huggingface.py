"""Hugging Face blog extractor."""

from __future__ import annotations

import re
import json
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from wiki.ingest.blog_extractors.base import BlogExtraction, BlogExtractor


class HuggingFaceBlogExtractor(BlogExtractor):
    """Extractor for public Hugging Face blog pages."""

    platform = "huggingface_blog"

    def extract(self, html: str, url: str, *, status_code: int | None = None) -> BlogExtraction:
        """Extract Hugging Face blog metadata and article Markdown."""
        soup = BeautifulSoup(html, "html.parser")
        article = self._article_root(soup)
        json_ld = self._article_json_ld(soup)

        title = self._clean(
            self._json_text(json_ld, "headline")
            or self._json_text(json_ld, "name")
            or self._meta(soup, "og:title")
            or self._meta(soup, "twitter:title")
            or self._heading(article, "h1")
        )
        title = self._strip_suffix(title)
        subtitle = self._clean(
            self._json_text(json_ld, "description")
            or self._meta(soup, "og:description")
            or self._first_text_after_h1(article)
        )
        author = self._author(soup, article, json_ld)
        published_at = self._published(soup, article, json_ld)
        canonical_url = self._json_text(json_ld, "url") or self._canonical(soup, url)
        toc = self._toc(article)
        links = self._important_links(article, url)
        content_markdown = self._markdown(article)

        return BlogExtraction(
            platform=self.platform,
            title=title,
            subtitle=subtitle,
            author=author,
            published_at=published_at,
            description=subtitle,
            canonical_url=canonical_url,
            source_url=canonical_url or url,
            site_name="Hugging Face",
            content_markdown=content_markdown,
            toc=toc,
            links=links,
            status_code=status_code,
            extractor=self.platform,
            requires_human_review=False,
            metadata_status="enriched" if title else "partial",
        )

    def _article_root(self, soup: BeautifulSoup) -> Tag:
        """Select the actual blog article, avoiding related cards and sidebars."""
        blog_content = soup.select_one(".blog-content")
        if isinstance(blog_content, Tag):
            return blog_content

        candidates = [
            tag
            for tag in soup.find_all(["article", "main", "section", "div"])
            if isinstance(tag, Tag)
        ]
        if not candidates:
            return soup.body or soup

        def score(tag: Tag) -> tuple[int, int]:
            text = tag.get_text(" ", strip=True)
            classes = " ".join(str(value) for value in tag.get("class", []))
            content_score = 0
            if "blog-content" in classes or "prose" in classes:
                content_score += 120
            if tag.name in {"article", "main"}:
                content_score += 40
            if "Getting Started With Embeddings" in text:
                content_score += 30
            content_score += min(len(tag.find_all(["h1", "h2", "h3"])), 20) * 4
            content_score += min(len(tag.find_all("p")), 80)
            content_score += min(len(tag.find_all("pre")), 20) * 3
            if tag.find_parent(["article", "main", "section", "div"]) and len(text) > 100:
                content_score += 1
            return content_score, -len(text)

        return max(candidates, key=score)

    def _article_json_ld(self, soup: BeautifulSoup) -> dict[str, Any]:
        for script in soup.find_all("script", type="application/ld+json"):
            text = (script.string or script.get_text() or "").strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            for item in self._json_items(data):
                item_type = item.get("@type")
                item_types = item_type if isinstance(item_type, list) else [item_type]
                if any(str(value).lower() in {"article", "blogposting"} for value in item_types):
                    return item
        return {}

    def _json_items(self, data: Any) -> list[dict[str, Any]]:
        if isinstance(data, dict):
            items = [data]
            graph = data.get("@graph")
            if isinstance(graph, list):
                items.extend(item for item in graph if isinstance(item, dict))
            return items
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def _json_text(self, data: dict[str, Any], key: str) -> str | None:
        value = data.get(key)
        if isinstance(value, str):
            return value.strip()
        return None

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

    def _heading(self, root: Tag, name: str) -> str | None:
        heading = root.find(name)
        return heading.get_text(" ", strip=True) if heading else None

    def _first_text_after_h1(self, root: Tag) -> str | None:
        h1 = root.find("h1")
        if not h1:
            return None
        for node in h1.find_all_next(["p", "h2"], limit=4):
            text = node.get_text(" ", strip=True)
            if text:
                return text
        return None

    def _author(self, soup: BeautifulSoup, article: Tag, json_ld: dict[str, Any] | None = None) -> str | None:
        for value in self._json_people(json_ld or {}, "author", "creator"):
            if value:
                return value
        author = (
            self._meta(soup, "author", attr="name")
            or self._meta(soup, "article:author")
            or self._meta(soup, "twitter:creator")
        )
        if author:
            return author.lstrip("@").strip()
        for selector in ['a[href^="/"]', '[rel="author"]']:
            node = article.select_one(selector)
            if node:
                text = node.get_text(" ", strip=True)
                if text and len(text.split()) <= 4 and text.lower() not in {"blog", "hugging face"}:
                    return text
        return None

    def _json_people(self, data: dict[str, Any], *keys: str) -> list[str]:
        names: list[str] = []
        for key in keys:
            value = data.get(key)
            values = value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    names.append(item["name"].strip())
                elif isinstance(item, str):
                    names.append(item.strip())
        return [name for name in names if name]

    def _published(self, soup: BeautifulSoup, article: Tag, json_ld: dict[str, Any] | None = None) -> str | None:
        for key in ["datePublished", "dateCreated", "dateModified"]:
            value = self._json_text(json_ld or {}, key)
            if value:
                return value[:10]
        published = (
            self._meta(soup, "article:published_time")
            or self._meta(soup, "date", attr="name")
            or self._meta(soup, "datePublished", attr="name")
        )
        if published:
            return published[:10]
        time_tag = article.find("time")
        if time_tag:
            if time_tag.get("datetime"):
                return str(time_tag["datetime"])[:10]
            text = time_tag.get_text(" ", strip=True)
            match = re.search(r"\d{4}-\d{2}-\d{2}", text)
            if match:
                return match.group(0)
        text = article.get_text(" ", strip=True)
        match = re.search(
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b",
            text,
        )
        if match:
            return match.group(0)
        return None

    def _toc(self, article: Tag) -> list[dict[str, str | int]]:
        seen: set[tuple[int, str]] = set()
        toc: list[dict[str, str | int]] = []
        for heading in article.find_all(["h2", "h3"]):
            text = heading.get_text(" ", strip=True)
            if not text:
                continue
            level = int(heading.name[1])
            key = (level, text)
            if key in seen:
                continue
            seen.add(key)
            toc.append({"level": level, "title": text})
        return toc

    def _important_links(self, article: Tag, base_url: str) -> list[dict[str, str]]:
        important_domains = ["github.com", "colab.research.google.com", "huggingface.co"]
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for anchor in article.find_all("a", href=True):
            if self._has_non_content_ancestor(anchor):
                continue
            href = urljoin(base_url, anchor["href"])
            if self._skip_link(href):
                continue
            if not any(domain in href for domain in important_domains):
                continue
            if href in seen:
                continue
            seen.add(href)
            text = anchor.get_text(" ", strip=True)
            links.append({"text": text or href, "url": href})
        return links

    def _skip_link(self, href: str) -> bool:
        parsed = urlparse(href)
        if parsed.fragment:
            return True
        if parsed.netloc.endswith("huggingface.co") and parsed.path in {"/", "/blog"}:
            return True
        return any(marker in href for marker in ["/login", "/join", "/blog?", "/spaces/huggingface-projects/"])

    def _markdown(self, article: Tag) -> str:
        lines: list[str] = []
        toc_titles = [str(entry["title"]) for entry in self._toc(article)]
        for node in article.descendants:
            if not isinstance(node, Tag):
                continue
            if self._has_non_content_ancestor(node):
                continue
            if node.name in {"h1", "h2", "h3"}:
                text = node.get_text(" ", strip=True)
                if text:
                    lines.extend(["", f"{'#' * int(node.name[1])} {text}", ""])
            elif node.name == "p":
                if self._has_block_ancestor(node):
                    continue
                text = node.get_text(" ", strip=True)
                if self._looks_like_toc_paragraph(text, toc_titles):
                    continue
                if text:
                    lines.extend([text, ""])
            elif node.name in {"pre", "code"} and node.name == "pre":
                code = node.get_text("\n", strip=False).strip()
                if code:
                    lines.extend(["```", code, "```", ""])
            elif node.name in {"ul", "ol"}:
                if self._has_list_ancestor(node):
                    continue
                for item in node.find_all("li", recursive=False):
                    text = item.get_text(" ", strip=True)
                    if text:
                        lines.append(f"- {text}")
                lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _looks_like_toc_paragraph(self, text: str, toc_titles: list[str]) -> bool:
        if not text or len(text) < 120:
            return False
        matches = sum(1 for title in toc_titles if title and title in text)
        return matches >= 3

    def _has_block_ancestor(self, node: Tag) -> bool:
        parent = node.parent
        while parent is not None:
            if isinstance(parent, Tag) and parent.name in {"li", "pre", "code"}:
                return True
            parent = parent.parent
        return False

    def _has_list_ancestor(self, node: Tag) -> bool:
        parent = node.parent
        while parent is not None:
            if isinstance(parent, Tag) and parent.name in {"li", "ul", "ol"}:
                return True
            parent = parent.parent
        return False

    def _has_non_content_ancestor(self, node: Tag) -> bool:
        parent: Tag | None = node
        while parent is not None:
            if not isinstance(parent, Tag):
                break
            classes = {str(value) for value in parent.get("class", [])}
            if parent.name in {"nav", "aside", "button", "header", "footer"}:
                return True
            if {"not-prose", "sticky", "peer", "sr-only"} & classes:
                return True
            parent = parent.parent
        return False

    def _clean(self, value: str | None) -> str | None:
        if not value:
            return None
        return re.sub(r"\s+", " ", value).strip()

    def _strip_suffix(self, title: str | None) -> str | None:
        if not title:
            return None
        for suffix in [" - Hugging Face", " | Hugging Face"]:
            if title.endswith(suffix):
                return title[: -len(suffix)].strip()
        return title
