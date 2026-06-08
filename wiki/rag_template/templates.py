"""Built-in prompt templates for the RAG prompt builder (Prompt 34 MVP closure).

The MVP closure ships with a single, deterministic instruction
template (:data:`DEFAULT_INSTRUCTION_TEMPLATE`). The
:func:`get_template` and :func:`get_instruction_template`
helpers expose the template by name and let the CLI print a
list of available templates for debugging.

The templates are intentionally short and rigid: the MVP
closure only needs to demonstrate the prompt shape, not to
negotiate with a model. New templates can be added in a
follow-up prompt without breaking the public schema.
"""

from __future__ import annotations

from typing import Mapping

from wiki.rag_template.schema import DEFAULT_INSTRUCTION_TEMPLATE


#: The set of template names the MVP closure ships with.
TEMPLATE_NAMES: tuple[str, ...] = ("grounded_citations",)


_BUILTIN_TEMPLATES: Mapping[str, str] = {
    "grounded_citations": DEFAULT_INSTRUCTION_TEMPLATE,
}


def get_template(name: str) -> str:
    """Return the instruction template for the given name.

    The MVP closure only knows about the
    ``grounded_citations`` template. Unknown names raise
    :class:`ValueError` so the CLI can surface the error
    instead of silently falling back.
    """
    if name not in _BUILTIN_TEMPLATES:
        raise ValueError(
            f"unknown template name: {name!r} "
            f"(available: {list(_BUILTIN_TEMPLATES)})"
        )
    return _BUILTIN_TEMPLATES[name]


def get_instruction_template(name: str) -> str:
    """Return the instruction template for the given name.

    The function is a thin alias for :func:`get_template`. It
    exists for symmetry with future templates that might
    carry more than just an instruction string (e.g. a
    JSON-formatted config).
    """
    return get_template(name)


__all__ = [
    "TEMPLATE_NAMES",
    "get_instruction_template",
    "get_template",
]
