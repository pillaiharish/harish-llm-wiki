"""Public schema for the RAG prompt-template builder (Prompt 34 MVP closure).

This module defines the on-the-wire shape of a deterministic
RAG prompt object. A prompt object is the structured input a
future model-backed answer generator could consume. The MVP
closure intentionally does **not** include a model call: the
package only builds the prompt object from a
:class:`wiki.context_pack.schema.ContextPack` plus a user
query, an instruction template, and a set of citation rules.

The dataclass is frozen so the prompt is immutable and the
``to_dict()`` projection is the contract for the JSON CLI
output and the static report page. The schema is intentionally
small: it carries the minimum metadata a downstream consumer
(model or otherwise) would need to know what to answer, what
context to quote, and how to cite the sources.

The schema has one dataclass:

- :class:`RagPrompt` — the prompt envelope. It carries the
  system message, the user message, the structured
  :class:`wiki.context_pack.schema.ContextPack` (forwarded
  verbatim for downstream consumers that want to read the
  context programmatically), the template name, the citation
  rule string, the merged used-chars total, and the chunk
  count. The ``schema_version`` field is always the first
  key of the JSON projection.

The module has no project imports. The dataclass is a plain
frozen Python type that can be unit-tested without any of the
retrieval, context-pack, or model-provider modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# =============================================================================
# Constants
# =============================================================================


#: Schema version string for the RAG prompt object. Bumped
#: only when the public JSON shape changes in a breaking way.
#: The CLI emits this string as the ``schema_version`` field
#: of the JSON output and the first line of the readable
#: report.
RAG_PROMPT_SCHEMA_VERSION: str = "rag_prompt_v1"

#: Default template name used when the caller does not specify
#: one. The MVP closure ships with one built-in template
#: (:data:`DEFAULT_INSTRUCTION_TEMPLATE`); the ``template_name``
#: field of the prompt is always this value for the default
#: build path.
DEFAULT_TEMPLATE_NAME: str = "grounded_citations"

#: Default instruction template embedded in the system message
#: when the caller does not pass a custom one. The template is
#: deliberately short and explicitly tells the future consumer
#: (a) to ground every claim in the provided context, (b) to
#: cite each claim with the provided citation labels, and (c)
#: to refuse when the context does not support the claim.
DEFAULT_INSTRUCTION_TEMPLATE: str = (
    "You are a careful, citation-first assistant. "
    "Use ONLY the provided context chunks to answer the user's question. "
    "Every factual claim MUST end with a citation label of the form [cite:N] "
    "matching the citation labels in the context. "
    "If the provided context does not support an answer, reply exactly: "
    "I don't know based on the provided context. "
    "Do not invent facts. Do not introduce information from outside the context."
)

#: Stable string used to label the prompt as no-LLM /
#: mock-friendly. Downstream consumers can use this label to
#: reject the prompt in real-model code paths.
MOCK_TAG: str = "no-llm-template"

#: Stable prefix used in the citation-rule reminder that is
#: appended to the user message. The reminder is purely
#: advisory; the rule itself lives in the system message and
#: the JSON envelope.
CITATION_RULE_REMINDER_PREFIX: str = "Citation rules:"

#: Hard cap on the size of the system message. The MVP
#: closure does not enforce this in the builder, but the
#: field is exposed so the eval and report code can warn when
#: the cap is exceeded.
MAX_SYSTEM_CHARS: int = 8000


# =============================================================================
# Prompt envelope
# =============================================================================


@dataclass(frozen=True)
class RagPrompt:
    """The deterministic RAG prompt object.

    Fields
    ------
    schema_version:
        The :data:`RAG_PROMPT_SCHEMA_VERSION` string. Always
        the first field of the JSON projection.
    template_name:
        The template name (see
        :data:`wiki.rag_template.templates.TEMPLATE_NAMES`).
    query:
        The user query. Stored verbatim.
    instruction_template:
        The instruction template embedded in the system
        message. Stored verbatim.
    system_message:
        The full system message. The message is the
        ``instruction_template`` plus a small fixed
        no-LLM/grounded-only banner.
    user_message:
        The full user message. The message contains the query,
        a citation-rule reminder, the inlined context chunk
        excerpts with their citation labels, and the
        deduplicated source list.
    context_pack:
        The :class:`wiki.context_pack.schema.ContextPack` that
        was used to build the prompt. Stored as a dict
        (``to_dict()`` projection) so the prompt is JSON
        serializable. The field is exposed for downstream
        consumers that want to read the context
        programmatically.
    citation_rule:
        The citation rule string. The MVP closure always uses
        the same rule: "every factual claim ends with [cite:N]".
    used_chars:
        The total number of characters consumed by the
        ``chunks[].text`` fields of the context pack.
        Mirrors :attr:`ContextPack.used_chars`.
    total_chunks:
        The number of chunks in the prompt. Mirrors
        :attr:`ContextPack.total_chunks`.
    total_sources:
        The number of unique sources in the prompt. Mirrors
        the number of :class:`ContextSource` records in the
        context pack.
    mock_tag:
        A small stable string (:data:`MOCK_TAG`) the
        downstream consumer can use to detect that the prompt
        was built by the no-LLM MVP closure.
    is_mock:
        ``True``. The field exists for symmetry with future
        non-mock providers and to make the no-LLM intent
        explicit in the JSON output.
    """

    schema_version: str
    template_name: str
    query: str
    instruction_template: str
    system_message: str
    user_message: str
    context_pack: dict = field(default_factory=dict)
    citation_rule: str = "every factual claim ends with [cite:N]"
    used_chars: int = 0
    total_chunks: int = 0
    total_sources: int = 0
    mock_tag: str = MOCK_TAG
    is_mock: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Project to a dict in stable field order.

        The top-level key order is fixed and matches the
        spec: ``schema_version`` is the first key, followed
        by the template metadata, the messages, the context
        pack dict, the totals, and the mock/no-LLM tags.
        """
        return {
            "schema_version": self.schema_version,
            "template_name": self.template_name,
            "query": self.query,
            "instruction_template": self.instruction_template,
            "system_message": self.system_message,
            "user_message": self.user_message,
            "context_pack": dict(self.context_pack),
            "citation_rule": self.citation_rule,
            "used_chars": int(self.used_chars),
            "total_chunks": int(self.total_chunks),
            "total_sources": int(self.total_sources),
            "mock_tag": self.mock_tag,
            "is_mock": bool(self.is_mock),
        }


__all__ = [
    "CITATION_RULE_REMINDER_PREFIX",
    "DEFAULT_INSTRUCTION_TEMPLATE",
    "DEFAULT_TEMPLATE_NAME",
    "MAX_SYSTEM_CHARS",
    "MOCK_TAG",
    "RAG_PROMPT_SCHEMA_VERSION",
    "RagPrompt",
]
