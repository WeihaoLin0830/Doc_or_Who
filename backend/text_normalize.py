from __future__ import annotations

import re
import unicodedata


def fold_text(s: str) -> str:
    """
    Unicode/case insensitive folding for lexical search.

    - NFKD splits base chars and combining marks
    - casefold handles Unicode case more robustly than lower()
    - combining marks are removed so á -> a, ü -> u
    - whitespace is normalized but not removed
    """
    if not s:
        return ""
    normalized = unicodedata.normalize("NFKD", s)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    folded = stripped.casefold()
    return re.sub(r"\s+", " ", folded).strip()


def char_ngrams(s: str, n: int = 3, max_ngrams: int = 50_000) -> list[str]:
    """
    Build character n-grams over folded text for typo/OCR-tolerant lexical search.

    Practical choices:
    - fold and normalize first
    - drop separators so spacing/OCR whitespace noise hurts less
    - keep only alphanumeric characters
    - cap output size to avoid exploding the Whoosh index on large chunks
    """
    if not s:
        return []

    folded = fold_text(s)
    compact = "".join(ch for ch in folded if ch.isalnum())
    if not compact:
        return []

    if len(compact) < n:
        return [compact]

    limit = max(n, max_ngrams)
    grams: list[str] = []
    for index in range(len(compact) - n + 1):
        grams.append(compact[index:index + n])
        if len(grams) >= limit:
            break
    return grams


def _fold_with_mapping(s: str) -> tuple[str, list[int]]:
    """
    Internal helper for approximate highlight positioning.

    Returns the folded text plus a positional map from each folded character
    to the source index in the original string.
    """
    if not s:
        return "", []

    chars: list[str] = []
    mapping: list[int] = []
    for source_index, original_char in enumerate(s):
        normalized = unicodedata.normalize("NFKD", original_char)
        stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        folded = stripped.casefold()
        for folded_char in folded:
            chars.append(folded_char)
            mapping.append(source_index)

    folded_text = "".join(chars)
    return folded_text, mapping
