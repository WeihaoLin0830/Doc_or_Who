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
