"""Tests for the generated note prompt contract."""

from wiki.llm.mock import MockProvider
from wiki.llm.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_resource_note_prompt
from wiki.generate.notes import validate_generated_note_contract
from wiki.schemas import SourceType, WebpageChunk


def _chunks() -> list[WebpageChunk]:
    return [
        WebpageChunk(
            resource_id="webpage:test",
            chunk_id="chunk-001",
            source_type=SourceType.WEBPAGE,
            text="RAG retrieves relevant chunks before generation.",
            citation_label="paragraph 1",
            url="https://example.com/rag",
        )
    ]


def test_prompt_version_bumped_to_v2():
    assert PROMPT_VERSION == "harish_llm_wiki_v2"


def test_resource_prompt_uses_first_principles_contract():
    prompt = build_resource_note_prompt(
        _chunks(),
        {
            "source_type": "webpage",
            "title": "RAG Notes",
            "url": "https://example.com/rag",
            "chunk_count": 1,
        },
        "mock",
        "mock-model",
    )

    assert "### First-principles explanation" in prompt
    assert "### Source-backed summary" in prompt
    assert "### Needs verification" in prompt
    assert "### Karpathy-style explanation" not in prompt
    assert '"title": "RAG Notes"' in prompt


def test_mock_output_satisfies_note_contract():
    chunks = _chunks()
    prompt = build_resource_note_prompt(
        chunks,
        {
            "source_type": "webpage",
            "title": "RAG Notes",
            "url": "https://example.com/rag",
            "chunk_count": 1,
        },
        "mock",
        "mock-model",
    )
    content = MockProvider().generate(prompt, system=SYSTEM_PROMPT)

    issues = validate_generated_note_contract(
        content,
        chunks,
        provider="mock",
        model="mock-model",
        prompt_version=PROMPT_VERSION,
    )

    assert issues == []
    assert "# RAG Notes" in content
    assert "## First-principles explanation" in content


def test_contract_validator_rejects_missing_sections():
    issues = validate_generated_note_contract(
        "# Thin Note\n\nNo structure.",
        _chunks(),
        provider="mock",
        model="mock-model",
        prompt_version=PROMPT_VERSION,
    )

    assert "missing section: First-principles explanation" in issues
    assert "missing section: Provenance" in issues
