"""Tests for generated-note contract repair retries."""

from pathlib import Path
from typing import Optional

import pytest

from wiki.config import config
from wiki.generate.notes import NoteGenerator
from wiki.llm.base import LLMProvider
from wiki.llm.prompts import PROMPT_VERSION
from wiki.schemas import ResourceRecord, ResourceStatus, SourceType, WebpageChunk
from wiki.storage import Storage


class SequenceProvider(LLMProvider):
    """Provider that returns fixed responses for repair tests."""

    @property
    def provider_name(self) -> str:
        return "sequence"

    def __init__(self, responses: list[str]) -> None:
        super().__init__("sequence-model")
        self.responses = responses
        self.prompts: list[str] = []

    def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


def _chunk() -> WebpageChunk:
    return WebpageChunk(
        resource_id="webpage:test",
        chunk_id="webpage:test-p001",
        source_type=SourceType.WEBPAGE,
        text="vLLM uses paged attention to manage KV cache memory.",
        citation_label="section LLM Engine, paragraph 1",
        section_heading="LLM Engine",
        paragraph_index=1,
        url="https://example.com/vllm",
    )


def _valid_note(title: str = "vLLM Note") -> str:
    chunk_id = "webpage:test-p001"
    return f"""# {title}

## Resource table of contents

- LLM Engine [source: {chunk_id}]

## Why this resource matters

It explains a concrete serving-system mechanism.

## One-line memory hook

Paged attention makes KV cache memory manageable.

## Source-backed summary

- vLLM uses paged attention for KV cache management. [source: {chunk_id}]

## First-principles explanation

Tokens need reusable memory during inference.

## Concrete example / toy implementation

```python
blocks = allocate_kv_blocks(tokens)
```

## Real-system implications

Serving systems can batch more requests.

## Common failure modes

- Memory fragmentation needs careful handling.

## What the resource did not cover

- Deployment cost details.

## LLM-added explanations

This is a conceptual bridge, not a source claim.

## Needs verification

None.

## Revision questions

1. Why does KV cache memory matter?

## Harish project connections

This helps with LLM inference notes.

## Recommended prerequisites

- Python basics
- LLM inference fundamentals

## Suggested next learning topics

- PagedAttention
- Continuous batching

## Citations

- [source: {chunk_id}] section LLM Engine, paragraph 1

## Provenance

- Source type: webpage
- Source URL: https://example.com/vllm
- LLM provider: sequence
- LLM model: sequence-model
- Prompt version: {PROMPT_VERSION}
"""


def _record(tmp_path: Path) -> ResourceRecord:
    norm_dir = tmp_path / "normalized" / "webpage_test"
    norm_dir.mkdir(parents=True)
    Storage.write_jsonl((_chunk().model_dump(),), norm_dir / "chunks.jsonl")
    return ResourceRecord(
        id="webpage:test",
        source_type=SourceType.WEBPAGE,
        canonical_id="webpage:test",
        original_url="https://example.com/vllm",
        title="vLLM Note",
        local_normalized_path=norm_dir,
    )


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_WIKI_DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "LLM_NOTE_REPAIR_RETRIES", 1)
    return tmp_path


def test_initial_invalid_note_triggers_repair_and_saves_valid_note(data_dir):
    provider = SequenceProvider(["not markdown", _valid_note()])
    record = _record(data_dir)

    note_path = NoteGenerator(provider).generate(record)

    assert note_path.exists()
    assert provider.prompts[1].startswith("You generated a note that failed")
    assert "CHUNK ID: webpage:test-p001" in provider.prompts[1]
    assert record.status == ResourceStatus.LLM_NOTE_GENERATED
    assert record.extra["note_repaired"] is True
    assert record.extra["repair_attempts"] == 1
    assert "vLLM uses paged attention" in note_path.read_text()


def test_repair_failure_saves_debug_artifacts_and_marks_review(data_dir):
    provider = SequenceProvider(["not markdown", "# Still Bad\n\nNo contract."])
    record = _record(data_dir)

    with pytest.raises(RuntimeError, match="Generated note failed contract"):
        NoteGenerator(provider).generate(record)

    assert record.status == ResourceStatus.FAILED_RETRYABLE
    assert record.extra["requires_human_review"] is True
    assert record.extra["note_contract_errors"]

    debug_path = Path(record.extra["failed_note_debug_path"])
    assert (debug_path / "initial_output.md").exists()
    assert (debug_path / "repaired_output.md").exists()
    assert (debug_path / "validator_errors.json").exists()
    prompt_context = Storage.read_json(debug_path / "prompt_context.json")
    assert prompt_context["chunks"][0]["chunk_id"] == "webpage:test-p001"
    assert "CHUNK ID: webpage:test-p001" in prompt_context["chunks_prompt"]
