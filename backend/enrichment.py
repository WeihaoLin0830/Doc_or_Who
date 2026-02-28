from __future__ import annotations

import re
from collections import Counter

from backend.config import get_settings
from backend.types import ExtractedEntity
from backend.utils import canonicalize

STOPWORDS = {
    "de", "la", "el", "los", "las", "y", "o", "a", "en", "por", "para", "con", "del", "al",
    "the", "and", "for", "from", "this", "that", "una", "uno",
}
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\s+de\s+\w+\s+de\s+\d{4})\b", re.IGNORECASE)
AMOUNT_RE = re.compile(r"\b(?:EUR|USD|\$|€)\s?\d[\d.,]*\b|\b\d[\d.,]*\s?(?:EUR|USD|€)\b", re.IGNORECASE)
ORG_RE = re.compile(r"\b([A-ZÁÉÍÓÚÑ][\w&.-]+(?:\s+[A-ZÁÉÍÓÚÑ][\w&.-]+){0,4}\s+(?:S\.L\.|S\.A\.|Ltd\.|Inc\.|GmbH|LLC|B\.V\.))")
PERSON_RE = re.compile(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,2})\b")

_spacy_model = None


def _load_spacy():
    global _spacy_model
    if _spacy_model is not None:
        return _spacy_model
    settings = get_settings()
    if not settings.enable_spacy:
        _spacy_model = False
        return None
    try:
        import spacy

        _spacy_model = spacy.load(settings.spacy_model)
    except Exception:
        _spacy_model = False
    return _spacy_model if _spacy_model is not False else None


def reset_enrichment_cache() -> None:
    global _spacy_model
    _spacy_model = None


def infer_title(text: str, filename: str, metadata: dict[str, object]) -> str:
    metadata_title = str(metadata.get("title") or "").strip()
    if metadata_title:
        return metadata_title
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and len(stripped) <= 160:
            return stripped.lstrip("#").strip()
    return filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()


def _keyword_fallback(text: str, limit: int = 8) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"\b[\w-]{4,}\b", text)]
    filtered = [token for token in tokens if token not in STOPWORDS]
    counts = Counter(filtered)
    return [token for token, _count in counts.most_common(limit)]


def extract_tags(text: str, limit: int = 8) -> list[str]:
    try:
        import yake

        extractor = yake.KeywordExtractor(lan="en", n=2, top=limit, dedupLim=0.7)
        keywords = [keyword for keyword, _score in extractor.extract_keywords(text[:5000])]
    except Exception:
        keywords = _keyword_fallback(text, limit=limit)
    filtered: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        canonical = canonicalize(keyword)
        if not canonical or canonical in STOPWORDS:
            continue
        if len(canonical) < 4:
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        filtered.append(keyword.strip())
        if len(filtered) >= limit:
            break
    return filtered


class EntityExtractor:
    def extract(self, text: str, language: str) -> list[ExtractedEntity]:
        entities: list[ExtractedEntity] = []
        seen: set[tuple[str, str]] = set()

        def add(display_text: str, entity_type: str, confidence: float, importance: float = 0.0) -> None:
            canonical_text = canonicalize(display_text)
            if len(canonical_text) < 2:
                return
            key = (entity_type, canonical_text)
            if key in seen:
                return
            seen.add(key)
            entities.append(
                ExtractedEntity(
                    canonical_text=canonical_text,
                    display_text=display_text.strip(),
                    type=entity_type,
                    confidence=confidence,
                    importance_score=importance,
                )
            )

        for match in EMAIL_RE.findall(text):
            add(match, "email", 0.95, 0.4)
        for match in DATE_RE.findall(text):
            add(match, "date", 0.95, 0.3)
        for match in AMOUNT_RE.findall(text):
            add(match, "amount", 0.95, 0.4)
        for match in ORG_RE.findall(text):
            add(match, "organization", 0.7, 0.8)
        for match in PERSON_RE.findall(text):
            if match.lower() not in STOPWORDS and len(match.split()) <= 3:
                add(match, "person", 0.7, 0.5)

        nlp = _load_spacy()
        if nlp is not None:
            try:
                doc = nlp(text[:15000])
                for ent in doc.ents:
                    if ent.label_ in {"PER", "PERSON"}:
                        add(ent.text, "person", 0.85, 0.7)
                    elif ent.label_ in {"ORG"}:
                        add(ent.text, "organization", 0.85, 0.7)
                    elif ent.label_ in {"DATE"}:
                        add(ent.text, "date", 0.85, 0.4)
            except Exception:
                pass

        for tag in extract_tags(text):
            add(tag, "tag", 0.6, 0.2)

        return entities
