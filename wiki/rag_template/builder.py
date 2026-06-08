"""Prompt builder for the RAG prompt-template package (Prompt 34 MVP closure).

The builder converts a :class:`wiki.context_pack.schema.ContextPack`
plus a user query into a :class:`wiki.rag_template.schema.RagPrompt`.
The function is pure: it does not call any model, does not
import any provider, and does not require any network access.

The builder exposes two entry points:

- :func:`build_prompt` — the on-disk entry point used by the
  CLI. Reads the BM25 and vector indexes from the data dir,
  builds a :class:`ContextPack`, and delegates to
  :func:`build_prompt_from_pack`.
- :func:`build_prompt_from_pack` — the in-memory entry point
  used by tests and by callers that already have a
  :class:`ContextPack`.

The builder is deterministic: same query + same pack + same
template = same prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from wiki.config import config
from wiki.context_pack.schema import ContextPack
from wiki.rag_template.schema import (
    CITATION_RULE_REMINDER_PREFIX,
    DEFAULT_INSTRUCTION_TEMPLATE,
    DEFAULT_TEMPLATE_NAME,
    MOCK_TAG,
    RAG_PROMPT_SCHEMA_VERSION,
    RagPrompt,
)
from wiki.rag_template.templates import get_instruction_template
from wiki.retrieval.schema import ALLOWED_MODES, DEFAULT_MODE


#: Citation rule string the MVP closure always uses.
DEFAULT_CITATION_RULE: str = "every factual claim ends with [cite:N]"


def build_prompt_from_pack(
    pack: ContextPack,
    *,
    query: Optional[str] = None,
    template_name: str = DEFAULT_TEMPLATE_NAME,
    instruction_template: Optional[str] = None,
) -> RagPrompt:
    """Build a :class:`RagPrompt` from a pre-computed :class:`ContextPack`.

    The function is pure: it does not call any model, does not
    import any provider, and does not require any network
    access. The prompt is fully derived from the
    :class:`ContextPack` (which is itself deterministic).

    Parameters
    ----------
    pack:
        The :class:`ContextPack` to embed in the prompt.
    query:
        The user query. When omitted, the pack's
        :attr:`ContextPack.query` is used.
    template_name:
        The template name. The MVP closure only knows about
        the ``grounded_citations`` template. Unknown names
        raise :class:`ValueError`.
    instruction_template:
        Optional override for the instruction template. When
        ``None``, the template is looked up by name via
        :func:`wiki.rag_template.templates.get_instruction_template`.
    """
    if pack is None:
        raise ValueError("pack is required")

    template = get_instruction_template(template_name)
    if instruction_template is not None:
        template = str(instruction_template)

    effective_query = str(query) if query is not None else str(pack.query)
    if not effective_query.strip():
        # An empty query would produce a useless prompt. We
        # fall back to the pack's query so the CLI never
        # produces a blank user message.
        effective_query = str(pack.query)

    system_message = _build_system_message(template)
    user_message = _build_user_message(pack, effective_query)

    return RagPrompt(
        schema_version=RAG_PROMPT_SCHEMA_VERSION,
        template_name=str(template_name),
        query=effective_query,
        instruction_template=str(template),
        system_message=system_message,
        user_message=user_message,
        context_pack=pack.to_dict(),
        citation_rule=DEFAULT_CITATION_RULE,
        used_chars=int(pack.used_chars),
        total_chunks=int(pack.total_chunks),
        total_sources=len(list(pack.sources or [])),
        mock_tag=MOCK_TAG,
        is_mock=True,
    )


def build_prompt(
    query: str,
    *,
    mode: str = DEFAULT_MODE,
    limit: int = 10,
    max_chars: int = 0,
    source_types: Optional[list[str]] = None,
    resource_id: Optional[str] = None,
    template_name: str = DEFAULT_TEMPLATE_NAME,
    instruction_template: Optional[str] = None,
    bm25_weight: float = 0.55,
    vector_weight: float = 0.45,
    index_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> RagPrompt:
    """Build a :class:`RagPrompt` over the on-disk indexes.

    The on-disk entry point used by the CLI. Reads the BM25
    and vector indexes from the data dir, builds a
    :class:`ContextPack`, and delegates to
    :func:`build_prompt_from_pack`.

    Parameters
    ----------
    query:
        The user query. Must be non-empty.
    mode:
        Retrieval mode (``bm25``, ``vector``, ``hybrid``,
        ``graph-lite``). Defaults to ``hybrid``.
    limit:
        Maximum number of retrieval results.
    max_chars:
        Per-chunk char budget. ``0`` disables trimming.
    source_types:
        Optional list of source types to filter by.
    resource_id:
        Optional single resource id to filter by.
    template_name:
        The template name (default: ``grounded_citations``).
    instruction_template:
        Optional override for the instruction template.
    bm25_weight:
        Weight on the BM25 contribution. Forwarded to the
        upstream router.
    vector_weight:
        Weight on the vector contribution. Forwarded to the
        upstream router.
    index_dir:
        Optional override for the BM25/vector index dir.
    data_dir:
        Optional override for the wiki data dir.

    Raises
    ------
    ValueError
        If the query is empty or the mode is invalid.
    FileNotFoundError
        If the BM25 or vector index is missing for a mode
        that requires it.
    """
    if not query or not str(query).strip():
        raise ValueError("query is empty")
    if mode not in ALLOWED_MODES:
        raise ValueError(
            f"invalid mode: {mode!r} (allowed: {sorted(ALLOWED_MODES)})"
        )

    base = Path(data_dir) if data_dir is not None else config.LLM_WIKI_DATA_DIR

    # Local import to avoid an import cycle when the package
    # is imported during tests.
    from wiki.context_pack import build_context_pack

    pack = build_context_pack(
        str(query),
        mode=mode,
        limit=limit,
        max_chars=max_chars,
        source_types=source_types,
        resource_id=resource_id,
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
        index_dir=index_dir,
        data_dir=base,
    )

    return build_prompt_from_pack(
        pack,
        query=str(query),
        template_name=template_name,
        instruction_template=instruction_template,
    )


# =============================================================================
# Helpers
# =============================================================================


def _build_system_message(instruction_template: str) -> str:
    """Build the system message from the instruction template.

    The system message embeds the instruction template plus a
    small no-LLM banner. The banner is intentionally stable
    so downstream consumers can detect MVP-closure prompts
    by string match if they want to.
    """
    parts: list[str] = []
    parts.append("[MOCK / NO-LLM PROMPT — not generated by any model]")
    parts.append("")
    parts.append(str(instruction_template).rstrip())
    return "\n".join(parts).rstrip() + "\n"


def _build_user_message(pack: ContextPack, query: str) -> str:
    """Build the user message from the pack and the query.

    The user message has a fixed structure:

    1. The query, restated in a Markdown heading.
    2. A citation-rule reminder.
    3. A ``## Context`` block with one subsection per chunk,
       each labeled with its citation label.
    4. A ``## Sources`` block with one bullet per source.
    """
    lines: list[str] = []
    lines.append("## Question")
    lines.append("")
    lines.append(str(query).rstrip())
    lines.append("")
    lines.append("## " + CITATION_RULE_REMINDER_PREFIX.replace(":", ""))
    lines.append("")
    lines.append(
        "Every factual claim in your answer must end with a citation "
        "label of the form [cite:N] where N is the 1-based rank of "
        "the chunk in the Context section."
    )
    lines.append("")
    lines.append("## Context")
    lines.append("")
    if not pack.chunks:
        lines.append("_No context chunks were retrieved for this query._")
        lines.append("")
    else:
        for chunk in pack.chunks:
            lines.append(f"### {chunk.citation_label}")
            lines.append("")
            lines.append(
                f"Resource: `{chunk.resource_id}`"
                + (f" — {chunk.title}" if chunk.title else "")
            )
            lines.append(f"Source type: `{chunk.source_type or 'unknown'}`")
            lines.append(f"Score: {chunk.score:.6f}")
            lines.append(f"Chunk id: `{chunk.chunk_id}`")
            lines.append("")
            lines.append("```")
            lines.append(chunk.text or "")
            lines.append("```")
            lines.append("")
    lines.append("## Sources")
    lines.append("")
    if not pack.sources:
        lines.append("_No sources._")
        lines.append("")
    else:
        for source in pack.sources:
            lines.append(
                f"- {source.citation_label} "
                f"`{source.resource_id}`"
                + (f" — {source.title}" if source.title else "")
                + f" ({source.source_type or 'unknown'})"
            )
            for cid in source.chunk_ids:
                lines.append(f"    - chunk: `{cid}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "DEFAULT_CITATION_RULE",
    "build_prompt",
    "build_prompt_from_pack",
]
