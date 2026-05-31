"""Generate static search indexes, Explorer, and Sources pages."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from wiki.config import config
from wiki.generate.page_utils import citation_count, extract_section, read_note, table_value
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
            "local_page": f"/resources/{record.id.replace(':', '_')}",
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
                "local_page": f"/resources/{record.id.replace(':', '_')}",
            })
        return items

    def _explorer(self, items: list[dict[str, Any]]) -> str:
        rows = "\n".join(
            f"| [{table_value(item['title'])}]({item['local_page']}) | {item['type']} | "
            f"{', '.join(item.get('topics') or []) or '-'} | {item.get('provider') or '-'} | "
            f"{item.get('review_status', '-')} | {item.get('stale_status', '-')} |"
            for item in items[:200]
        )
        data = json.dumps(items)
        return f"""# Explorer

Search and filter the static wiki without a backend.

<noscript>
<p><strong>JavaScript is disabled.</strong> The interactive search below requires JavaScript. Use the static table further down instead.</p>
</noscript>

<div id="wiki-explorer">
  <input id="q" placeholder="Search" />
  <select id="type"><option value="">All types</option></select>
  <select id="topic"><option value="">All topics</option></select>
  <select id="provider"><option value="">All providers</option></select>
  <select id="review"><option value="">All review states</option></select>
  <select id="stale"><option value="">All stale states</option></select>
  <div id="results"><p>Loading...</p></div>
  <noscript><p>The interactive search requires JavaScript. See the static table below.</p></noscript>
</div>

<script>
try {{
const items = {data};
const fields = ['type','provider','review','stale'];
function uniq(values) {{ return [...new Set(values.filter(Boolean))].sort(); }}
function fill(id, values) {{
  const el = document.getElementById(id);
  uniq(values).forEach(v => {{ const o=document.createElement('option'); o.value=v; o.textContent=v; el.appendChild(o); }});
}}
fill('type', items.map(i => i.type));
fill('topic', items.flatMap(i => i.topics || []));
fill('provider', items.map(i => i.provider));
fill('review', items.map(i => i.review_status));
fill('stale', items.map(i => i.stale_status));
function render() {{
  const q = document.getElementById('q').value.toLowerCase();
  const type = document.getElementById('type').value;
  const topic = document.getElementById('topic').value;
  const provider = document.getElementById('provider').value;
  const review = document.getElementById('review').value;
  const stale = document.getElementById('stale').value;
  const filtered = items.filter(i =>
    (!q || (i.title + ' ' + i.summary).toLowerCase().includes(q)) &&
    (!type || i.type === type) &&
    (!topic || (i.topics || []).includes(topic)) &&
    (!provider || i.provider === provider) &&
    (!review || i.review_status === review) &&
    (!stale || i.stale_status === stale)
  );
  document.getElementById('results').innerHTML = filtered.slice(0, 100).map(i => `<p><a href="${{i.local_page}}">${{i.title}}</a> <code>${{i.type}}</code></p>`).join('');
}}
['q','type','topic','provider','review','stale'].forEach(id => document.getElementById(id).addEventListener('input', render));
render();
}} catch(e) {{
  document.getElementById('results').innerHTML = '<p>Could not initialize Explorer. Check that search data is available at /search/all.json.</p>';
}}
</script>

## Static table fallback

| Title | Type | Topic | Provider | Review | Stale |
|---|---|---|---|---|---|
{rows or '| No items | - | - | - | - | - |'}
"""

    def _sources(self, resources: list[dict[str, Any]]) -> str:
        lines = ["# Sources", "", "| Source URL | Resource | Type | Provider/model |", "|---|---|---|---|"]
        for item in resources:
            lines.append(
                f"| {table_value(item.get('source_url'))} | [{table_value(item['title'])}]({item['local_page']}) | "
                f"{item['type']} | {item.get('provider') or '-'} / {item.get('model') or '-'} |"
            )
        return "\n".join(lines) + "\n"


search_index_generator = SearchIndexGenerator()
