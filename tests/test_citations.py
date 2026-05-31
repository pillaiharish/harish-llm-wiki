"""Tests for citation resolution, linkification, and source chunk rendering."""

from wiki.generate.citations import (
    citation_anchor,
    linkify_citations,
    render_source_chunks_section,
    short_citation_label,
    strip_source_chunks_section,
)
from wiki.schemas import YouTubeChunk, WebpageChunk, SourceType


def _yt_chunk(chunk_id: str = "youtube:abc123-c0001", start: float = 0, end: float = 30) -> YouTubeChunk:
    return YouTubeChunk(
        resource_id="youtube:abc123",
        chunk_id=chunk_id,
        source_type=SourceType.YOUTUBE,
        text="This is a test chunk about vLLM serving.",
        citation_label="00:00-00:30",
        start_time=start,
        end_time=end,
        url="https://youtube.com/watch?v=abc123&t=0",
    )


def _web_chunk(chunk_id: str = "webpage:abc-p0004") -> WebpageChunk:
    return WebpageChunk(
        resource_id="webpage:abc",
        chunk_id=chunk_id,
        source_type=SourceType.WEBPAGE,
        text="This is a test chunk about paged attention.",
        citation_label='section "LLM Engine", paragraph 4',
        section_heading="LLM Engine",
        paragraph_index=4,
        url="https://example.com/vllm",
    )


def test_citation_anchor_stable_slug():
    assert citation_anchor("youtube:q5IF2PHA5SA-c0001") == "youtube-q5if2pha5sa-c0001"
    assert citation_anchor("webpage:df11644e8c-p0004") == "webpage-df11644e8c-p0004"
    assert citation_anchor("markdown:abc123-p0002") == "markdown-abc123-p0002"
    assert citation_anchor("Simple-ID-123") == "simple-id-123"


def test_short_citation_label():
    assert short_citation_label("youtube:q5IF2PHA5SA-c0001") == "c0001"
    assert short_citation_label("webpage:df11644e8c-p0004") == "p0004"
    assert short_citation_label("no-dash-chunk") == "no-dash-chunk"


def test_linkify_citations_converts_tokens_to_links():
    chunk_map = {
        "youtube:abc123-c0001": _yt_chunk(),
        "webpage:abc-p0004": _web_chunk(),
    }
    md = "vLLM uses paged attention [youtube:abc123-c0001] for memory management [webpage:abc-p0004]."
    processed, cited, missing = linkify_citations(md, chunk_map)

    assert "[c0001](#youtube-abc123-c0001)" in processed
    assert "[p0004](#webpage-abc-p0004)" in processed
    assert "<!-- youtube:abc123-c0001 -->" in processed
    assert "<!-- webpage:abc-p0004 -->" in processed
    assert "youtube:abc123-c0001" in cited
    assert "webpage:abc-p0004" in cited
    assert not missing


def test_linkify_citations_converts_source_prefixed_tokens():
    chunk_map = {"webpage:abc-p0004": _web_chunk()}
    md = "vLLM uses paged attention [source: webpage:abc-p0004]."

    processed, cited, missing = linkify_citations(md, chunk_map)

    assert "[p0004](#webpage-abc-p0004)" in processed
    assert "<!-- webpage:abc-p0004 -->" in processed
    assert "webpage:abc-p0004" in cited
    assert not missing


def test_linkify_citations_preserves_non_citation_text():
    chunk_map = {"youtube:abc123-c0001": _yt_chunk()}
    md = "Some regular text without citations."
    processed, cited, missing = linkify_citations(md, chunk_map)
    assert processed == md
    assert not cited


def test_linkify_citations_ignores_code_blocks():
    chunk_map = {"youtube:abc123-c0001": _yt_chunk()}
    md = "Some text [youtube:abc123-c0001]\n\n```python\nprint('[youtube:abc123-c0001]')\n```\n"
    processed, cited, missing = linkify_citations(md, chunk_map)

    assert "[c0001](#youtube-abc123-c0001)" in processed
    assert "[youtube:abc123-c0001]" in processed
    assert "print('[youtube:abc123-c0001]')" in processed
    assert len(cited) == 1


def test_linkify_citations_detects_missing_ids():
    chunk_map = {"youtube:abc123-c0001": _yt_chunk()}
    md = "See [youtube:abc123-c0001] and [youtube:abc123-c9999]."
    processed, cited, missing = linkify_citations(md, chunk_map)

    assert "[c0001](#youtube-abc123-c0001)" in processed
    assert "[missing source chunk: youtube:abc123-c9999]" in processed
    assert "youtube:abc123-c9999" in missing


def test_render_source_chunks_youtube_timestamp_links():
    chunk = _yt_chunk()
    chunk_map = {"youtube:abc123-c0001": chunk}
    result = render_source_chunks_section(chunk_map, {"youtube:abc123-c0001"}, "https://youtube.com/watch?v=abc123")

    assert '<a id="youtube-abc123-c0001"></a>' in result
    assert "<details>" in result
    assert "</details>" in result
    assert "https://youtube.com/watch?v=abc123&t=0" in result
    assert "youtube" in result.lower()


def test_render_source_chunks_webpage_heading_labels():
    chunk = _web_chunk()
    chunk_map = {"webpage:abc-p0004": chunk}
    result = render_source_chunks_section(chunk_map, {"webpage:abc-p0004"}, "https://example.com/vllm")

    assert '<a id="webpage-abc-p0004"></a>' in result
    assert "<details>" in result
    assert "https://example.com/vllm" in result
    assert 'LLM Engine' in result


def test_render_source_chunks_no_cited_ids():
    chunk_map = {"youtube:abc123-c0001": _yt_chunk()}
    result = render_source_chunks_section(chunk_map, set(), "")
    assert "No source chunks were cited" in result


def test_strip_source_chunks_removes_existing_section():
    original = "# Title\n\n## Source chunks\n\n<a id=\"anchor\"></a>\n\n<details>\n<summary>chunk</summary>\n\ncontent\n\n</details>\n\n## Next section\n\nContent here."
    result = strip_source_chunks_section(original)
    assert "## Source chunks" not in result
    assert "## Next section" in result
    assert "Content here." in result


def test_strip_source_chunks_idempotent():
    original = "# Title\n\n## Source chunks\n\n<a id=\"anchor\"></a>\n\n<details>\n<summary>chunk</summary>\n\ncontent\n\n</details>\n\n## Provenance\n\nSomething."
    result = strip_source_chunks_section(original)
    result2 = strip_source_chunks_section(result)
    assert result == result2
