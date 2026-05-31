"""Tests for Prompt 7 view and quality-gate behavior."""

from datetime import datetime

from typer.testing import CliRunner

from wiki import cli
from wiki.cli import app, quality_gate_issues
from wiki.enrich.metadata import WebpageMetadataEnricher
from wiki.generate.timeline import timeline_generator
from wiki.generate.topics import topic_generator
from wiki.resource_utils import display_title
from wiki.schemas import ResourceRecord, ResourceStatus, SourceType


def _record(
    resource_id: str,
    title: str,
    *,
    source_type: SourceType = SourceType.WEBPAGE,
    url: str = "https://example.com",
) -> ResourceRecord:
    return ResourceRecord(
        id=resource_id,
        source_type=source_type,
        canonical_id=resource_id,
        original_url=url,
        title=title,
        status=ResourceStatus.PROCESSED,
        first_seen_at=datetime(2026, 5, 31),
    )


def test_webpage_metadata_extracts_title_subtitle_date_and_toc():
    html = """
    <html>
      <head>
        <meta property="og:title" content="Inside vLLM: Anatomy of a High-Throughput LLM Inference System" />
        <meta property="og:site_name" content="Aleksa Gordić" />
      </head>
      <body>
        <article>
          <h1>Inside vLLM: Anatomy of a High-Throughput LLM Inference System</h1>
          <h2>From paged attention, continuous batching, prefix caching, specdec, etc. to multi-GPU, multi-node dynamic serving at scale</h2>
          <p>August 29, 2025</p>
          <h2>LLM Engine &amp; Engine Core</h2>
          <h3>Scheduler</h3>
          <h2>Advanced Features - extending the core engine logic</h2>
        </article>
      </body>
    </html>
    """

    metadata = WebpageMetadataEnricher()._extract_metadata(html, "https://www.aleksagordic.com/blog/vllm")

    assert metadata["title"] == "Inside vLLM: Anatomy of a High-Throughput LLM Inference System"
    assert metadata["subtitle"].startswith("From paged attention")
    assert metadata["author"] == "Aleksa Gordić"
    assert metadata["published"] == "August 29, 2025"
    assert {"level": 2, "title": "LLM Engine & Engine Core"} in metadata["toc"]
    assert {"level": 3, "title": "Scheduler"} in metadata["toc"]


def test_registry_title_beats_stale_generated_title():
    record = _record("webpage:test", "Fresh Registry Title")
    assert display_title(record) == "Fresh Registry Title"


def test_topic_assignment_and_deduplication():
    records = [
        _record("webpage:vllm", "Inside vLLM: Anatomy of a High-Throughput LLM Inference System"),
        _record("webpage:vllm", "Inside vLLM: Anatomy of a High-Throughput LLM Inference System"),
        _record("youtube:evals", "What are LLM Evals?"),
    ]

    topics = topic_generator.generate(records)

    assert [r.id for r in topics["llm-inference"]] == ["webpage:vllm"]
    assert [r.id for r in topics["llm-evals"]] == ["youtube:evals"]


def test_timeline_groups_by_month_and_topic():
    records = [
        _record("youtube:rag", "Better RAG: Hybrid Search", source_type=SourceType.YOUTUBE),
        _record("youtube:evals", "What are LLM Evals?", source_type=SourceType.YOUTUBE),
    ]

    periods = timeline_generator.generate(records)
    content = timeline_generator._format_timeline_markdown(periods)

    assert "## May 2026" in content
    assert "### RAG / Retrieval" in content
    assert "### LLM Evaluation" in content
    assert "Better RAG: Hybrid Search" in content


def test_quality_gate_blocks_many_untitled_resources():
    records = [
        _record("webpage:1", "Untitled"),
        _record("webpage:2", "Unknown Resource"),
        _record("webpage:3", ""),
        _record("webpage:4", "Good Title"),
    ]

    issues = quality_gate_issues(records)

    assert any("replaceable titles" in issue for issue in issues)
    assert any("metadata coverage" in issue for issue in issues)


def test_test_llm_mock_command():
    result = CliRunner().invoke(app, ["test-llm", "--provider", "mock"])

    assert result.exit_code == 0
    assert "LLM provider: mock" in result.output
    assert "Model: mock-model" in result.output


def test_test_llm_ollama_cloud_with_monkeypatched_provider(monkeypatch):
    class FakeCloudProvider:
        model = "fake-model"

        def generate(self, prompt, *, temperature=None, system=None):
            return "ollama cloud works"

    monkeypatch.setattr(cli.config, "OLLAMA_CLOUD_API_KEY", "key")
    monkeypatch.setattr(cli.config, "OLLAMA_CLOUD_MODEL", "fake-model")
    monkeypatch.setattr(cli, "OllamaCloudProvider", FakeCloudProvider)

    result = CliRunner().invoke(app, ["test-llm", "--provider", "ollama_cloud"])

    assert result.exit_code == 0
    assert "LLM provider: ollama_cloud" in result.output
    assert "Response: ollama cloud works" in result.output


def test_build_site_refresh_calls_regeneration(monkeypatch):
    calls = {"regenerate": 0, "build": 0}
    records = [_record("webpage:test", "Fresh Title")]

    monkeypatch.setattr(cli.registry, "get_all", lambda: iter(records))

    def fake_regenerate(input_records):
        assert input_records == records
        calls["regenerate"] += 1

    def fake_build(input_records):
        assert input_records == records
        calls["build"] += 1
        return "/tmp/site/docs"

    monkeypatch.setattr(cli, "generate_derived_views", fake_regenerate)
    monkeypatch.setattr(cli.site_builder, "build", fake_build)

    result = CliRunner().invoke(app, ["build-site", "--refresh"])

    assert result.exit_code == 0
    assert calls == {"regenerate": 1, "build": 1}
