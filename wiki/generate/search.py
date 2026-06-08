"""Generate static search indexes, Explorer, and Sources pages."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from wiki.config import config
from wiki.generate.page_utils import citation_count, extract_section, md_table_cell, read_note, resource_route
from wiki.resource_utils import display_title, source_url, topic_matches
from wiki.schemas import ResourceRecord
from wiki.storage import Storage


class SearchIndexGenerator:
    """Generate static JSON indexes and browse pages."""

    def generate(self, records: list[ResourceRecord]) -> dict[str, Any]:
        resource_items = [self._resource_item(record) for record in records]
        concepts = self._markdown_items(config.get_data_path("processed", "concepts"), "concept", "/concepts/")
        topics = self._markdown_items(config.get_data_path("processed", "topics"), "topic", "/topics/")
        learn = self._markdown_items(config.get_data_path("processed", "learn"), "learn", "/learn/")
        citations = self._citation_items(records)
        return {
            "resources": resource_items,
            "concepts": concepts,
            "topics": topics,
            "learn": learn,
            "citations": citations,
            "all": resource_items + concepts + topics + learn,
        }

    def save(self, indexes: dict[str, Any]) -> Path:
        processed_dir = config.get_data_path("processed", "search")
        processed_dir.mkdir(parents=True, exist_ok=True)
        public_dir = config.get_data_path("site_generated", "docs", "public", "search")
        public_dir.mkdir(parents=True, exist_ok=True)
        for name in ["resources", "concepts", "topics", "learn", "citations", "all"]:
            payload = {"generated_at": datetime.utcnow().isoformat(), "items": indexes.get(name, [])}
            Storage.write_json(payload, processed_dir / f"{name}.json")
            Storage.write_json(payload, public_dir / f"{name}.json")
        docs_dir = config.get_data_path("site_generated", "docs")
        Storage.write_text(self._explorer(indexes["all"]), docs_dir / "explorer" / "index.md")
        Storage.write_text(self._sources(indexes["resources"]), docs_dir / "sources" / "index.md")
        return processed_dir

    def _resource_item(self, record: ResourceRecord) -> dict[str, Any]:
        note = read_note(record)
        topics = topic_matches(record, note)
        review_status = "needs_review" if record.extra.get("requires_human_review") or record.extra.get("quality_status") == "weak" else "ok"
        stale = record.prompt_version is None
        return {
            "id": record.id,
            "title": display_title(record, mark_missing=True),
            "type": record.source_type.value,
            "summary": self._summary(record, note),
            "tags": record.tags,
            "topics": topics,
            "source_url": source_url(record),
            "local_page": resource_route(record.id),
            "provider": record.llm_provider or "",
            "model": record.llm_model or "",
            "prompt_version": record.prompt_version or "",
            "requires_human_review": bool(record.extra.get("requires_human_review")),
            "review_status": review_status,
            "stale_status": "stale" if stale else "current",
            "created_at": record.first_seen_at.isoformat() if record.first_seen_at else "",
            "updated_at": record.updated_at.isoformat() if record.updated_at else "",
        }

    def _summary(self, record: ResourceRecord, note: str) -> str:
        section = extract_section(note, "One-line memory hook") or extract_section(note, "Why this resource matters")
        return (section or record.description or "").replace("\n", " ")[:300]

    def _markdown_items(self, directory: Path, item_type: str, page_prefix: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if not directory.exists():
            return items
        for path in sorted(directory.glob("*.md")):
            if path.name == "index.md":
                continue
            content = Storage.read_text(path)
            title = next((line.lstrip("#").strip() for line in content.splitlines() if line.startswith("# ")), path.stem)
            items.append({
                "id": f"{item_type}:{path.stem}",
                "title": title,
                "type": item_type,
                "summary": content[:300].replace("\n", " "),
                "tags": [],
                "topics": [path.stem] if item_type in {"topic", "learn"} else [],
                "source_url": "",
                "local_page": f"{page_prefix}{path.stem}",
                "provider": "",
                "model": "",
                "prompt_version": "",
                "requires_human_review": False,
                "review_status": "ok",
                "stale_status": "current",
                "created_at": "",
                "updated_at": "",
            })
        return items

    def _citation_items(self, records: list[ResourceRecord]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for record in records:
            note = read_note(record)
            if not note or not record.local_normalized_path:
                continue
            items.append({
                "id": record.id,
                "title": display_title(record, mark_missing=True),
                "type": record.source_type.value,
                "citation_count": citation_count(note),
                "source_url": source_url(record),
                "local_page": resource_route(record.id),
            })
        return items

    def _explorer(self, items: list[dict[str, Any]]) -> str:
        normalized = [self._normalize_explorer_item(item) for item in items[:200]]
        rows = "\n".join(
            f"| [{md_table_cell(item['title'])}]({item['local_page']}) | {md_table_cell(item['type'])} | "
            f"{md_table_cell(', '.join(item.get('topics') or []) or '-')} | {md_table_cell(item.get('provider') or '-')} | "
            f"{md_table_cell(item.get('review_status') or '-')} | {md_table_cell(item.get('stale_status') or '-')} |"
            for item in normalized
        )
        # Prompt 36: the interactive explorer is a Vue component
        # (``<SearchExplorer />``) registered globally by the
        # VitePress theme. We deliberately do NOT embed raw
        # ``<script>`` or ``<style>`` blocks in this Markdown
        # file because VitePress/Vue would warn at dev/build
        # time and strip the side-effect tags.
        #
        # The expected shape (per the spec) is:
        #
        #   <ClientOnly>
        #     <SearchExplorer />
        #   </ClientOnly>
        #
        # ``<ClientOnly>`` ensures the component only renders on
        # the client (it depends on ``fetch`` + ``window``) and
        # suppresses SSR/hydration mismatches. The ``SearchExplorer``
        # component itself handles the ``/search/all.json`` fetch
        # and a deterministic error fallback, so we never emit an
        # inline ``<script>fetch(...)`` block here.
        #
        # We still keep a ``<div id="wiki-explorer">`` wrapper
        # inside the ClientOnly block so older smoke / validate
        # checks that look for that marker continue to pass.
        return f"""# Explorer

Search and filter the static wiki without a backend. The interactive
search below loads ``/search/all.json`` via ``fetch`` (inside the
``<SearchExplorer />`` Vue component) and never makes external
network calls. The view is fully static and deterministic.

If the search index cannot be loaded, the component surfaces a
deterministic fallback message: **Could not load search index. Check
/search/all.json.**

<ClientOnly>
  <div id="wiki-explorer">
    <SearchExplorer />
  </div>
</ClientOnly>

## Resource summary

| Count | Value |
|---|---:|
| Indexed items | {len(items)} |
| Recent resources shown | {min(len(items), 200)} |

## Recent resources

| Title | Type | Topic | Provider | Review | Stale |
|---|---|---|---|---|---|
{rows or '| No items | - | - | - | - | - |'}
"""

    @staticmethod
    def _normalize_explorer_item(item: Any) -> dict[str, Any]:
        """Normalize a single Explorer item to a known schema.

        Different code paths feed ``_explorer()`` (resource records,
        concept/topic/learn markdown items, citation items, …) and
        they can disagree on the exact field names. To keep the
        generated Markdown stable we coerce every item to a fixed
        shape. Missing or ``None`` fields fall back to safe defaults
        so a partial item never raises ``KeyError``.
        """
        if not isinstance(item, dict):
            item = {}

        def _coerce_str(value: Any) -> str:
            if value is None:
                return ""
            return str(value)

        title = (
            item.get("title")
            or item.get("name")
            or item.get("label")
            or item.get("resource_title")
            or item.get("text")
            or item.get("id")
            or "(untitled)"
        )
        item_type = (
            item.get("type")
            or item.get("source_type")
            or item.get("kind")
            or item.get("category")
            or item.get("resource")
            or ""
        )
        local_page = (
            item.get("local_page")
            or item.get("path")
            or item.get("href")
            or item.get("url")
            or "#"
        )
        topics_value = item.get("topics")
        if topics_value is None:
            topics_value = item.get("topic")
        if isinstance(topics_value, str):
            topics_list: list[str] = [topics_value] if topics_value else []
        elif isinstance(topics_value, (list, tuple, set)):
            topics_list = [_coerce_str(t) for t in topics_value if t is not None]
        else:
            topics_list = []

        return {
            "id": _coerce_str(item.get("id")),
            "title": _coerce_str(title) or "(untitled)",
            "type": _coerce_str(item_type),
            "summary": _coerce_str(item.get("summary")),
            "tags": list(item.get("tags") or []) if isinstance(item.get("tags"), (list, tuple, set)) else [],
            "topics": topics_list,
            "source_url": _coerce_str(item.get("source_url")),
            "local_page": _coerce_str(local_page) or "#",
            "provider": _coerce_str(item.get("provider")),
            "model": _coerce_str(item.get("model")),
            "prompt_version": _coerce_str(item.get("prompt_version")),
            "requires_human_review": bool(item.get("requires_human_review", False)),
            "review_status": _coerce_str(item.get("review_status") or "ok"),
            "stale_status": _coerce_str(item.get("stale_status") or "current"),
            "created_at": _coerce_str(item.get("created_at")),
            "updated_at": _coerce_str(item.get("updated_at")),
        }

    def _sources(self, resources: list[dict[str, Any]]) -> str:
        lines = ["# Sources", "", "| Source URL | Resource | Type | Provider/model |", "|---|---|---|---|"]
        for item in resources:
            lines.append(
                f"| {md_table_cell(item.get('source_url'))} | [{md_table_cell(item['title'])}]({item['local_page']}) | "
                f"{md_table_cell(item['type'])} | {md_table_cell(item.get('provider') or '-')} / {md_table_cell(item.get('model') or '-')} |"
            )
        return "\n".join(lines) + "\n"


search_index_generator = SearchIndexGenerator()
