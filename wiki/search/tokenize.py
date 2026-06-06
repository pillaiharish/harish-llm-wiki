"""Deterministic, dependency-free tokenizer for the BM25 backend.

The tokenizer is the single most important determinism contract in
the BM25 backend: index time and query time **must** call the same
function with the same byte semantics. The function is therefore:

- pure (no I/O, no globals beyond a frozen stopword set);
- deterministic (``str.lower()`` + the same regex everywhere);
- dependency-free (no ``regex`` package, no ``nltk``).

Tokenization pipeline
---------------------

1. ``str.lower()`` – Unicode-aware lowercasing.
2. ``[^\w\s]+`` -> " " – strip punctuation and symbols.
3. ``.split()`` – collapse whitespace and split.
4. Drop tokens shorter than 2 characters (e.g. ``"I"``, ``"a"``).
5. Drop tokens that are in the bundled English stopword list.
6. Drop pure-numeric tokens (configurable; default keeps them
   so queries like ``"rag 2024"`` still match).

The stopword list is a small, sorted, frozen set bundled in
``wiki/search/data/stopwords_en.txt``. Keeping it bundled (not
downloaded at runtime) is part of the determinism contract.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import FrozenSet


# =============================================================================
# Constants
# =============================================================================


#: Default minimum token length (drop "I", "a", "s", "1" etc.).
DEFAULT_MIN_TOKEN_LENGTH: int = 2

#: Path to the bundled English stopword list. Sorted, one per line,
#: lowercase, no duplicates.
_STOPWORDS_PATH = (
    Path(__file__).resolve().parent / "data" / "stopwords_en.txt"
)

#: Punctuation/symbol regex used to strip non-word, non-whitespace
#: characters. ``\w`` is Unicode-aware under ``re.UNICODE`` (the
#: default in Python 3).
_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)

#: Whitespace splitter. We use ``.split()`` directly, not a regex,
#: because it already handles Unicode whitespace and repeated runs.
_WHITESPACE_RE = re.compile(r"\s+", re.UNICODE)


# =============================================================================
# Stopwords
# =============================================================================


def _load_stopwords() -> FrozenSet[str]:
    """Load the bundled stopword list as a frozen set.

    The function reads ``wiki/search/data/stopwords_en.txt`` once
    and freezes the result. It tolerates a missing file by
    returning an empty set, but the canonical build always has the
    file present.
    """
    if not _STOPWORDS_PATH.exists():
        return frozenset()
    words: set[str] = set()
    with _STOPWORDS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            words.add(line.lower())
    return frozenset(sorted(words))


#: Frozen stopword set. Loaded once at module import.
STOPWORDS: FrozenSet[str] = _load_stopwords()


# =============================================================================
# Public API
# =============================================================================


def tokenize(
    text: str,
    *,
    min_length: int = DEFAULT_MIN_TOKEN_LENGTH,
    drop_stopwords: bool = True,
    drop_numeric: bool = False,
) -> list[str]:
    """Tokenize ``text`` into a deterministic list of normalized tokens.

    Parameters
    ----------
    text:
        The input string. May be empty (returns ``[]``).
    min_length:
        Drop tokens shorter than this many characters. Default is
        ``2`` (drops ``"I"``, ``"a"``, ``"s"``).
    drop_stopwords:
        When ``True`` (default), drop tokens in :data:`STOPWORDS`.
    drop_numeric:
        When ``True``, drop tokens that are pure digits. Default
        is ``False`` (keeps them) so queries like ``"rag 2024"``
        and ``"vllm 0.6"`` still match.

    Returns
    -------
    list[str]
        The token list, in the order they appeared in ``text``.

    Notes
    -----
    - Same input bytes -> same token list. The function does not
      consult any external state beyond the bundled stopword list
      and the ``min_length`` / ``drop_stopwords`` / ``drop_numeric``
      flags.
    - The tokenizer is intentionally simple: lowercasing, ASCII
      punctuation stripping, whitespace split, stopword removal.
      It is good enough for the English-language LLM-wiki content
      and avoids the determinism hazards of language-specific
      stemmers or lemmatizers.
    """
    if not text:
        return []
    # 1. Lowercase (Unicode-aware via str.lower()).
    lowered = text.lower()
    # 2. Replace any non-word, non-whitespace char with a space.
    cleaned = _PUNCT_RE.sub(" ", lowered)
    # 3. Split on whitespace and drop empties.
    raw_tokens = _WHITESPACE_RE.split(cleaned.strip())
    if not raw_tokens:
        return []
    out: list[str] = []
    for tok in raw_tokens:
        if len(tok) < min_length:
            continue
        if drop_stopwords and tok in STOPWORDS:
            continue
        if drop_numeric and tok.isdigit():
            continue
        out.append(tok)
    return out


def token_count(text: str, **kwargs) -> int:
    """Return the number of tokens in ``text`` after tokenization."""
    return len(tokenize(text, **kwargs))


__all__ = [
    "DEFAULT_MIN_TOKEN_LENGTH",
    "STOPWORDS",
    "tokenize",
    "token_count",
]
