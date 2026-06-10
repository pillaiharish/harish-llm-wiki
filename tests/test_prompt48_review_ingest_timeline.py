"""Prompt 48 UI/docs polish checks."""

from datetime import datetime
from pathlib import Path

from wiki.generate.learn import LearnGenerator
from wiki.generate.review import review_generator
from wiki.generate.timeline import timeline_generator
from wiki.schemas import ResourceRecord, ResourceStatus, SourceType


def _empty_review_data() -> dict[str, list[dict[str, str]]]:
    return {
        "weak": [],
        "fallback": [],
        "failed": [],
        "missing_citations": [],
        "stale": [],
        "manual": [],
        "untitled": [],
    }


def test_review_priority_queue_renders_cards_with_human_reasons():
    data = _empty_review_data()
    data["weak"].append(
        {
            "title": "Chunking Attention Notes",
            "type": "webpage",
            "status": "llm_cache_hit",
            "provider": "mock",
            "model": "mock-model",
            "page": "/resources/chunking-attention",
            "source_url": "https://example.com/chunking",
            "reason": "sparse source-backed citations; requires_human_review",
        }
    )
    data["fallback"].append(
        {
            "title": "Fallback Resource",
            "type": "youtube",
            "status": "processed",
            "provider": "mock",
            "model": "mock-model",
            "page": "/resources/fallback-resource",
            "source_url": "https://example.com/fallback",
            "reason": "contract_completed_by_deterministic_fallback",
        }
    )

    content = review_generator._index(data)

    assert "## Priority review queue" in content
    assert "review-priority-grid" in content
    assert "review-priority-card" in content
    assert "<details class=\"review-provenance\">" in content
    assert "<summary>Raw provenance</summary>" in content
    assert "| Priority | Resource | Reason | Status | Link |" not in content
    assert "Sparse source-backed citations; Requires human review" in content
    assert "Contract completed by deterministic fallback" in content
    assert "contract_completed_by_deterministic_fallback" in content
    assert "LLM cache hit" in content
    assert "View weak notes" in content
    assert "View fallback notes" in content
    assert "Resource id" in content
    assert 'href="/resources/chunking-attention"' in content


def test_review_category_tables_keep_raw_reason_provenance():
    content = review_generator._category(
        "Weak Notes",
        [
            {
                "title": "Weak Resource",
                "type": "webpage",
                "status": "processed",
                "provider": "mock",
                "model": "mock-model",
                "page": "/resources/weak-resource",
                "source_url": "https://example.com/weak",
                "reason": "fallback-completed; sparse source-backed citations",
            }
        ],
    )

    assert "Completed by deterministic fallback; Sparse source-backed citations" in content
    assert "raw: fallback-completed; sparse source-backed citations" in content


def test_timeline_renames_uncategorized_to_needs_classification():
    record = ResourceRecord(
        id="webpage:classification-gap",
        canonical_id="webpage:classification-gap",
        source_type=SourceType.WEBPAGE,
        original_url="https://example.com/classification-gap",
        title="Zyglor Maintenance Notes",
        status=ResourceStatus.PROCESSED,
        first_seen_at=datetime(2026, 6, 1),
        tags=[],
    )

    periods = timeline_generator.generate([record])
    content = timeline_generator._format_timeline_markdown(periods)

    assert '<span id="needs-classification"></span>' in content
    assert '<span id="uncategorized"></span>' in content
    assert "### Needs classification" in content
    assert "### Uncategorized" not in content
    assert "intake items missing topic or concept" in content
    assert "Fix classification metadata" in content
    assert 'href="/review/"' in content
    assert 'href="/resources/"' in content
    assert 'href="/ingest/"' in content


def test_ingest_page_exists_and_documents_token_safety():
    content = Path("site/docs/ingest/index.md").read_text(encoding="utf-8")

    assert "# Ingest & Processing" in content
    for expected in [
        "LLM_PROVIDER=mock",
        "--provider mock",
        "ollama_local",
        "ollama_cloud",
        "openai_compatible",
        "--dry-run",
        "--yes",
        "--skip-ingest",
        "--only-stale",
        ".env.example",
        "inputs/batch_urls.example.txt",
        "inputs/resources.example.yaml",
    ]:
        assert expected in content
    assert "does not accept API keys in the browser" in content
    assert "does not trigger provider calls from a page button" in content
    assert "Where API Tokens Are Enabled Or Disabled" in content
    assert "Choose Your Processing Mode" in content
    assert "Copyable Command Flow" in content
    assert "/review/" in content
    assert "/resources/" in content


def test_ingest_is_linked_from_nav_home_and_static_route_checks():
    config = Path("site/docs/.vitepress/config.ts").read_text(encoding="utf-8")
    builder = Path("wiki/site/builder.py").read_text(encoding="utf-8")
    verifier = Path("scripts/verify_site_static_routes.py").read_text(encoding="utf-8")

    assert "{ text: 'Ingest', link: '/ingest/' }" in config
    assert "[Ingest and processing guide](/ingest/)" in builder
    assert '"/ingest/"' in verifier


def test_learn_example_excerpt_closes_truncated_code_fence():
    generator = LearnGenerator()
    excerpt = generator._safe_markdown_excerpt("```python\n" + ("print('x')\n" * 200), 120)

    assert excerpt.count("```") == 2
    assert excerpt.endswith("```")
