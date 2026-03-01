from __future__ import annotations

import re
import unicodedata

_TOKEN_RE = re.compile(r"[a-z]+|\d+(?:[.,]\d+)*(?:[kmb])?", re.IGNORECASE)
_THOUSANDS_RE = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$")
_SUFFIX_RE = re.compile(r"^(\d+(?:[.,]\d+)?)([kmb])$", re.IGNORECASE)

_NUMBER_WORDS_ES = {
    "cero": 0,
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
    "cien": 100,
}

_NUMBER_WORDS_CAT = {
    "zero": 0,
    "un": 1,
    "u": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "quatre": 4,
    "cinc": 5,
    "sis": 6,
    "set": 7,
    "vuit": 8,
    "nou": 9,
    "deu": 10,
    "onze": 11,
    "dotze": 12,
    "tretze": 13,
    "catorze": 14,
    "quinze": 15,
    "setze": 16,
    "disset": 17,
    "divuit": 18,
    "dinou": 19,
    "vint": 20,
    "trenta": 30,
    "quaranta": 40,
    "cinquanta": 50,
    "seixanta": 60,
    "setanta": 70,
    "vuitanta": 80,
    "noranta": 90,
    "cent": 100,
}

_UNITS_ES = {word: value for word, value in _NUMBER_WORDS_ES.items() if 0 <= value <= 9}
_UNITS_CAT = {word: value for word, value in _NUMBER_WORDS_CAT.items() if 0 <= value <= 9}
_TENS_ES = {word: value for word, value in _NUMBER_WORDS_ES.items() if value in {20, 30, 40, 50, 60, 70, 80, 90}}
_TENS_CAT = {word: value for word, value in _NUMBER_WORDS_CAT.items() if value in {20, 30, 40, 50, 60, 70, 80, 90}}


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


def _tokenize_folded_text(text: str) -> list[str]:
    return _TOKEN_RE.findall(fold_text(text))


def _language_number_maps(lang: str | None) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    normalized = (lang or "").strip().casefold()
    if normalized.startswith("es"):
        return _NUMBER_WORDS_ES, _UNITS_ES, _TENS_ES
    if normalized.startswith("ca") or normalized.startswith("cat"):
        return _NUMBER_WORDS_CAT, _UNITS_CAT, _TENS_CAT

    number_words = {**_NUMBER_WORDS_ES, **_NUMBER_WORDS_CAT}
    units = {**_UNITS_ES, **_UNITS_CAT}
    tens = {**_TENS_ES, **_TENS_CAT}
    return number_words, units, tens


def normalize_number_token(token: str) -> list[str]:
    """
    Normalize numeric spellings into a canonical digit form.

    Returns one or more variants. The canonical numeric token is appended when
    normalization succeeds so the lexical index can match alternate spellings.
    """
    folded = fold_text(token)
    if not folded:
        return []

    variants = [folded]

    if _THOUSANDS_RE.fullmatch(folded):
        canonical = folded.replace(".", "").replace(",", "")
        if canonical not in variants:
            variants.append(canonical)
        return variants

    suffix_match = _SUFFIX_RE.fullmatch(folded)
    if suffix_match:
        numeric_part, suffix = suffix_match.groups()
        multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[suffix.casefold()]
        try:
            value = float(numeric_part.replace(",", "."))
            canonical = str(int(value * multiplier))
        except ValueError:
            return variants
        if canonical not in variants:
            variants.append(canonical)
        return variants

    if folded.isdigit():
        return variants

    return variants


def _consume_number_words(tokens: list[str], start: int, lang: str | None) -> tuple[int, int] | None:
    number_words, units, tens = _language_number_maps(lang)
    token = tokens[start]

    if token in number_words:
        direct_value = number_words[token]
        if token in tens and start + 2 < len(tokens) and tokens[start + 1] in {"y", "i"} and tokens[start + 2] in units:
            return 3, direct_value + units[tokens[start + 2]]
        return 1, direct_value

    return None


def words_to_int_es_cat(text: str, lang: str | None) -> str:
    """
    Replace recognized ES/CAT number words with digits.

    Conservative by design: only known forms are replaced.
    """
    tokens = _tokenize_folded_text(text)
    output: list[str] = []
    index = 0

    while index < len(tokens):
        consumed = _consume_number_words(tokens, index, lang)
        if consumed:
            size, value = consumed
            output.append(str(value))
            index += size
            continue
        output.append(tokens[index])
        index += 1

    return " ".join(output)


def normalize_numbers_in_text(
    text: str,
    language: str | None,
    include_original: bool = True,
) -> str:
    """
    Build a number-normalized text stream for Whoosh.

    - number words in ES/CAT become digits
    - thousands separators collapse when they look like grouping
    - 6k / 1.5m style suffixes expand to canonical integers
    - original normalized token can be kept alongside the canonical one
    """
    tokens = _tokenize_folded_text(text)
    output: list[str] = []
    index = 0

    while index < len(tokens):
        consumed = _consume_number_words(tokens, index, language)
        if consumed:
            size, value = consumed
            original_tokens = tokens[index:index + size]
            if include_original:
                output.extend(original_tokens)
            output.append(str(value))
            index += size
            continue

        token = tokens[index]
        variants = normalize_number_token(token)
        if include_original:
            output.extend(variants[:1])
            if len(variants) > 1:
                output.extend(variants[1:])
        else:
            canonical = variants[-1] if variants else token
            output.append(canonical)
        index += 1

    return " ".join(output)


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


# ─── Stemmer español (Snowball) ──────────────────────────────────
_stemmer_cache = None


def _get_stemmer():
    """Lazy-init del SnowballStemmer para español. None si NLTK no disponible."""
    global _stemmer_cache
    if _stemmer_cache is None:
        try:
            from nltk.stem import SnowballStemmer
            _stemmer_cache = SnowballStemmer("spanish")
        except Exception:
            _stemmer_cache = False  # marca como no disponible
    return _stemmer_cache if _stemmer_cache is not False else None


def stem_es(text: str) -> str:
    """
    Aplica el stemmer Snowball español sobre texto ya plegado (fold_text).

    Cada token del texto se reduce a su raíz morfológica:
      - reuniones   → reunion
      - contratación → contrat
      - proveedores  → proveedor
      - ventas       → vent

    Esto mejora el recall en búsquedas cuando el usuario escribe una
    forma flexionada diferente a la del documento.

    Devuelve los tokens con raíz unidos por espacio.
    Si NLTK no está disponible, devuelve el texto tal cual (sin romper nada).
    """
    folded = fold_text(text)
    if not folded:
        return ""
    stemmer = _get_stemmer()
    if stemmer is None:
        return folded
    tokens = folded.split()
    return " ".join(stemmer.stem(t) for t in tokens if t)
