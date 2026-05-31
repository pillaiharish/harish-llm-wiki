"""Tests for internal topic/concept link resolution."""

import pytest

from wiki.generate.learning_links import (
    resolve_section_links,
    linkify_prerequisites,
    linkify_next_topics,
    resolve_learning_links,
)


def test_resolve_existing_topic_links():
    topic_slugs = {"rag", "llm-inference", "llm-evals", "agents"}
    result = resolve_section_links("- RAG\n- Embeddings\n- GPU memory basics", topic_slugs, set())
    lines = result.strip().splitlines()
    assert "[RAG / Retrieval](/topics/rag.html)" in lines[0]
    # "Embeddings" is an alias that maps to RAG topic
    assert "[RAG / Retrieval](/topics/rag.html)" in lines[1]
    assert "GPU memory basics — not yet in wiki" in lines[2]


def test_resolve_existing_concept_links():
    concept_slugs = {"embeddings", "rag"}
    result = resolve_section_links("- Embeddings\n- Vector databases", set(), concept_slugs)
    assert "[Embeddings](/concepts/embeddings.html)" in result
    assert "Vector databases — not yet in wiki" in result


def test_mark_missing_as_not_yet_in_wiki():
    topic_slugs = set()
    result = resolve_section_links("- Python basics\n- Quantum computing", topic_slugs, set())
    assert "Python basics — not yet in wiki" in result
    assert "Quantum computing — not yet in wiki" in result


def test_linkify_prerequisites_section():
    md = """# Title

## Recommended prerequisites

- RAG
- GPU memory basics
- Python basics

## Other section

Some content.
"""
    topic_slugs = {"rag"}
    result = linkify_prerequisites(md, topic_slugs, set())
    assert "[RAG / Retrieval](/topics/rag.html)" in result
    assert "GPU memory basics — not yet in wiki" in result
    assert "## Other section" in result


def test_linkify_next_topics_section():
    md = """# Title

## Suggested next learning topics

- PagedAttention
- Continuous batching
- Vector databases

## Provenance

Some content.
"""
    topic_slugs = {"llm-inference"}
    result = linkify_next_topics(md, topic_slugs, set())
    assert "[LLM Inference / Serving](/topics/llm-inference.html)" in result or "PagedAttention" in result
    assert "## Provenance" in result


def test_no_change_if_no_sections():
    md = "# Title\n\nJust some content without the special sections.\n"
    result = resolve_learning_links(md)
    assert result == md


def test_resolve_upgrades_previously_unlinked():
    md = """# Title

## Recommended prerequisites

- RAG — not yet in wiki

## Other

Content.
"""
    topic_slugs = {"rag"}
    result = linkify_prerequisites(md, topic_slugs, set())
    assert "[RAG / Retrieval](/topics/rag.html)" in result
    # The "not yet in wiki" should be replaced with a real link
    lines_with_rag = [l for l in result.splitlines() if "RAG" in l]
    assert any("](/topics/rag.html)" in l for l in lines_with_rag)


def test_resolve_skips_already_linked_items():
    md = """# Title

## Recommended prerequisites

- [RAG / Retrieval](/topics/rag.html)
- Python basics

## Other

Content.
"""
    topic_slugs = {"rag"}
    result = linkify_prerequisites(md, topic_slugs, set())
    assert "[RAG / Retrieval](/topics/rag.html)" in result
    assert "Python basics — not yet in wiki" in result