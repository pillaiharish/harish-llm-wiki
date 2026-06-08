"""Deterministic RAG prompt-template builder (Prompt 34 MVP closure).

The :mod:`wiki.rag_template` package converts a
:class:`wiki.context_pack.schema.ContextPack` plus a user query
into a deterministic prompt object that a future model-backed
answer generator could consume. The package is intentionally
small and pure-Python: it does not call any model, does not
import any provider, and does not require any network access.

The package is the V1 closure for the prompt-template side of
the RAG MVP. It sits between the deterministic
:class:`wiki.context_pack.ContextPack` (Prompt 33) and the
deterministic :class:`wiki.mock_answer.MockAnswer` (also
Prompt 34 MVP closure) and the deterministic
:class:`wiki.rag_eval.RagAnswerReport` (also Prompt 34 MVP
closure). All three packages are independent: each one
consumes the :class:`ContextPack` and is consumed by the
report; they share no mutable state.

Public API
----------

- :func:`build_prompt` — the on-disk entry point used by the
  CLI. Takes a :class:`ContextPack` and returns a
  :class:`RagPrompt`.
- :func:`build_prompt_from_query` — the in-memory entry point
  used by tests and by callers that already have a
  :class:`ContextPack`.
- :func:`format_readable` — the readable CLI formatter
  (Markdown).
- :func:`format_json` — the JSON CLI formatter.
- :class:`RagPrompt` — the public dataclass.
- :data:`RAG_PROMPT_SCHEMA_VERSION`, :data:`DEFAULT_TEMPLATE_NAME`,
  :data:`DEFAULT_INSTRUCTION_TEMPLATE` — the public constants.
"""

from wiki.rag_template.builder import (
    DEFAULT_INSTRUCTION_TEMPLATE,
    DEFAULT_TEMPLATE_NAME,
    RAG_PROMPT_SCHEMA_VERSION,
    RagPrompt,
    build_prompt,
    build_prompt_from_pack,
)
from wiki.rag_template.output import format_json, format_readable
from wiki.rag_template.templates import (
    TEMPLATE_NAMES,
    get_instruction_template,
    get_template,
)


__all__ = [
    "DEFAULT_INSTRUCTION_TEMPLATE",
    "DEFAULT_TEMPLATE_NAME",
    "RAG_PROMPT_SCHEMA_VERSION",
    "RagPrompt",
    "TEMPLATE_NAMES",
    "build_prompt",
    "build_prompt_from_pack",
    "format_json",
    "format_readable",
    "get_instruction_template",
    "get_template",
]
