"""Tests for platform-specific blog extraction."""

from pathlib import Path

from wiki.config import config
from wiki.ingest.blog_router import get_blog_extractor
from wiki.ingest.blog_extractors.generic import GenericWebpageExtractor
from wiki.ingest.blog_extractors.huggingface import HuggingFaceBlogExtractor
from wiki.ingest.blog_extractors.medium import MediumExtractor
from wiki.normalize.webpage import WebpageNormalizer
from wiki.schemas import ResourceRecord, SourceType
from wiki.storage import Storage


HF_HTML = """<!doctype html>
<html>
<head>
  <title>Getting Started With Embeddings - Hugging Face</title>
  <meta property="og:title" content="Getting Started With Embeddings - Hugging Face" />
  <meta property="og:description" content="Learn how to use embeddings with datasets." />
  <meta name="author" content="Omar Espejel" />
  <meta property="article:published_time" content="2022-06-23T00:00:00.000Z" />
  <link rel="canonical" href="https://huggingface.co/blog/getting-started-with-embeddings" />
</head>
<body>
<main>
  <article>
    <h1>Getting Started With Embeddings</h1>
    <p>Learn how to use embeddings with datasets.</p>
    <h2>Understanding embeddings</h2>
    <p>Embeddings are vector representations used for search.</p>
    <h2>What are embeddings for?</h2>
    <p>They help compare semantic similarity.</p>
    <h2>Getting started with embeddings</h2>
    <h3>1. Embedding a dataset</h3>
    <p>Load a dataset and map it through a model.</p>
    <pre><code>from datasets import load_dataset
dataset = load_dataset("squad")</code></pre>
    <h3>2. Host embeddings for free on the Hugging Face Hub</h3>
    <p>Push embeddings to the Hub.</p>
    <h3>3. Get the most similar Frequently Asked Questions to a query</h3>
    <p>Use nearest neighbors for retrieval.</p>
    <h2>Additional resources to keep learning</h2>
    <p><a href="https://github.com/huggingface/notebooks">Notebook</a></p>
  </article>
</main>
</body>
</html>
"""


def test_blog_router_detects_huggingface_blog():
    extractor = get_blog_extractor("https://huggingface.co/blog/getting-started-with-embeddings")
    assert isinstance(extractor, HuggingFaceBlogExtractor)


def test_blog_router_detects_medium():
    assert isinstance(get_blog_extractor("https://medium.com/@user/post"), MediumExtractor)
    assert isinstance(get_blog_extractor("https://towardsdatascience.medium.com/post"), MediumExtractor)


def test_blog_router_falls_back_to_generic():
    assert isinstance(get_blog_extractor("https://example.com/blog/post"), GenericWebpageExtractor)


def test_huggingface_extractor_metadata_and_toc():
    result = HuggingFaceBlogExtractor().extract(
        HF_HTML,
        "https://huggingface.co/blog/getting-started-with-embeddings",
        status_code=200,
    )

    assert result.title == "Getting Started With Embeddings"
    assert result.author == "Omar Espejel"
    assert result.published_at == "2022-06-23"
    assert result.site_name == "Hugging Face"
    assert result.source_url == "https://huggingface.co/blog/getting-started-with-embeddings"
    toc_titles = [entry["title"] for entry in result.toc]
    assert "Understanding embeddings" in toc_titles
    assert "1. Embedding a dataset" in toc_titles
    assert "3. Get the most similar Frequently Asked Questions to a query" in toc_titles


def test_huggingface_extractor_preserves_code_and_important_links():
    result = HuggingFaceBlogExtractor().extract(
        HF_HTML,
        "https://huggingface.co/blog/getting-started-with-embeddings",
    )

    assert "```" in result.content_markdown
    assert "load_dataset" in result.content_markdown
    assert any(link["url"] == "https://github.com/huggingface/notebooks" for link in result.links)


def test_huggingface_normalizer_creates_section_aware_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    raw_dir = tmp_path / "raw" / "webpage" / "huggingface.co" / "abc12345"
    raw_dir.mkdir(parents=True)
    extraction = HuggingFaceBlogExtractor().extract(
        HF_HTML,
        "https://huggingface.co/blog/getting-started-with-embeddings",
    )
    Storage.write_text(extraction.content_markdown, raw_dir / "extracted.md")
    record = ResourceRecord(
        id="webpage:7e46dca0acc3e5be16343595987da50cc15588cd13cbfe86a069fd9d38079216",
        source_type=SourceType.WEBPAGE,
        canonical_id="webpage:7e46dca0acc3e5be16343595987da50cc15588cd13cbfe86a069fd9d38079216",
        original_url="https://huggingface.co/blog/getting-started-with-embeddings",
        content_hash="7e46dca0acc3e5be16343595987da50cc15588cd13cbfe86a069fd9d38079216",
        local_raw_path=raw_dir,
        extra={"platform": "huggingface_blog"},
    )

    record = WebpageNormalizer().normalize(record)
    chunks = list(Storage.read_jsonl(Path(record.local_normalized_path) / "chunks.jsonl"))

    assert chunks
    assert chunks[0]["chunk_id"].startswith("huggingface:7e46dca0-c")
    assert any('section "1. Embedding a dataset"' in chunk["citation_label"] for chunk in chunks)
    assert any("code block 1" in chunk["citation_label"] for chunk in chunks)


def test_huggingface_chunk_ids_use_stable_resource_id_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    raw_dir = tmp_path / "raw" / "webpage" / "huggingface.co" / "def45678"
    raw_dir.mkdir(parents=True)
    extraction = HuggingFaceBlogExtractor().extract(
        HF_HTML,
        "https://huggingface.co/blog/getting-started-with-embeddings",
    )
    Storage.write_text(extraction.content_markdown, raw_dir / "extracted.md")
    record = ResourceRecord(
        id="webpage:7e46dca0acc3e5be16343595987da50cc15588cd13cbfe86a069fd9d38079216",
        source_type=SourceType.WEBPAGE,
        canonical_id="webpage:7e46dca0acc3e5be16343595987da50cc15588cd13cbfe86a069fd9d38079216",
        original_url="https://huggingface.co/blog/getting-started-with-embeddings",
        content_hash="different-content-hash",
        local_raw_path=raw_dir,
        extra={"platform": "huggingface_blog"},
    )

    record = WebpageNormalizer().normalize(record)
    chunks = list(Storage.read_jsonl(Path(record.local_normalized_path) / "chunks.jsonl"))

    assert chunks[0]["chunk_id"].startswith("huggingface:7e46dca0-c")


def test_medium_inaccessible_page_becomes_needs_manual_markdown():
    html = "<html><body><article><h1>Private</h1><p>Sign in to read this member-only story.</p></article></body></html>"

    result = MediumExtractor().extract(html, "https://medium.com/@user/private")

    assert result.metadata_status == "needs_manual_markdown"
    assert result.requires_human_review is True
    assert "inbox/markdown/medium" in result.metadata_failure_reason
