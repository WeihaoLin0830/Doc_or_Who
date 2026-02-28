from __future__ import annotations

from backend.enrichment import EntityExtractor, extract_tags


def test_entity_extractor_canonicalizes_and_finds_core_entities(isolated_environment):
    extractor = EntityExtractor()
    entities = extractor.extract(
        "Pedro Suarez from NovaTech Solutions S.L. emailed legal@novatech.com on 2025-01-15 about EUR 5000.",
        "en",
    )
    types = {(entity.type, entity.canonical_text) for entity in entities}

    assert ("person", "pedro suarez") in types
    assert ("organization", "novatech solutions s.l.") in types
    assert ("email", "legal@novatech.com") in types
    assert ("date", "2025-01-15") in types


def test_tags_filter_stopwords(isolated_environment):
    tags = extract_tags("The Aurora budget review discusses sensors, supplier delivery, and logistics.")
    canonical = {tag.lower() for tag in tags}
    assert "aurora budget" in canonical or "budget review" in canonical or "supplier delivery" in canonical
    assert "the" not in canonical
