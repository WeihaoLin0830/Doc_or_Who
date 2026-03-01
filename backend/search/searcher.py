"""
searcher.py — Búsqueda híbrida con fusión BM25 + semántica (RRF).

Flujo:
1. Query → BM25 (Whoosh) → top K resultados léxicos
2. Query → embedding (ChromaDB) → top K resultados semánticos
3. Reciprocal Rank Fusion → lista final combinada
4. Facets aggregation → conteos dinámicos para filtros
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from backend.config import (
    CHAR3_MIN_COVERAGE,
    FINAL_TOP_K,
    FUSION_MODE,
    FUZZY,
    GRAPH_BOOST,
    LEXICAL_STRICT,
    MAX_CHUNKS_PER_DOC,
    RRF_K,
    SEARCH_TOP_K,
    SEMANTIC_MIN_SCORE,
    WEIGHT_LEXICAL,
    WEIGHT_SEMANTIC,
    WHOOSH_DIR,
)
from backend.models import SearchResult
from backend.search.text_normalize import _fold_with_mapping, char_ngrams, fold_text, normalize_numbers_in_text


def _folded_query(text: str) -> str:
    return fold_text(text)


# ─── Stopwords en español ───────────────────────────────────────
# Palabras funcionales que no aportan significado semántico.
# Se filtran de las queries antes de buscar y de los highlights.
_STOPWORDS: frozenset[str] = frozenset({
    # Artículos
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    # Preposiciones
    "a", "ante", "bajo", "con", "contra", "de", "desde", "en",
    "entre", "hacia", "hasta", "para", "por", "segun", "sin",
    "sobre", "tras", "durante", "mediante", "via",
    # Conjunciones
    "y", "e", "ni", "o", "u", "pero", "sino", "aunque", "si",
    "que", "como", "cuando", "donde", "pues", "ya", "porque",
    # Pronombres comunes
    "yo", "tu", "el", "ella", "nosotros", "vosotros", "ellos",
    "me", "te", "se", "nos", "os", "le", "les", "lo", "les",
    "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas",
    # Verbos auxiliares / muy comunes
    "es", "son", "era", "fue", "ser", "estar", "estar", "hay",
    "ha", "han", "he", "hemos", "fue", "sido", "tiene", "tienen",
    # Otros funcionales
    "al", "del", "no", "mas", "muy", "mas", "tan", "tanto",
    "cada", "todo", "toda", "todos", "todas", "otro", "otra",
    "sus", "su", "mi", "mis", "tu", "tus", "su", "nuestro",
})


def _strip_stopwords(query: str) -> str:
    """
    Elimina stopwords de la query. Si todos los tokens son stopwords
    (p.ej. solo "por"), devuelve la query original para no quedar vacía.
    Las stopwords se comparan en su forma plegada (sin acentos, minúsculas).
    """
    tokens = query.split()
    filtered = [t for t in tokens if fold_text(t).casefold() not in _STOPWORDS]
    # Si quedan ≥1 tokens significativos, devolver la query filtrada
    if filtered:
        return " ".join(filtered)
    # Si todo son stopwords, devolver query original (se evitará buscar solo "por")
    return ""  # Señal para que el caller retorne vacío


# ─── Sinónimos basados en corpus ────────────────────────────────
# El expansor se inicializa al arrancar el servidor (api.py startup).
# Aquí sólo importamos la referencia al objeto global.
from backend.search.synonyms import get_expander as _get_synonym_expander  # noqa: E402


def _expand_with_synonyms(query: str) -> str:
    """
    Expande la query con sinónimos inferidos del corpus.
    Delega en CorpusSynonymExpander (backend/search/synonyms.py).
    Devuelve la query original si el expansor aún no está listo o
    no encuentra términos suficientemente similares en el corpus.
    """
    return _get_synonym_expander().expand_query(query)


def _whoosh_supports_folded_fields(ix) -> bool:
    schema_names = set(ix.schema.names())
    return {"content_folded", "title_folded"}.issubset(schema_names)


def _whoosh_search_fields(ix) -> list[str]:
    if not LEXICAL_STRICT and _whoosh_supports_folded_fields(ix):
        return ["content_folded", "title_folded", "content", "title", "keywords", "persons", "organizations"]
    return ["content", "title", "keywords", "persons", "organizations"]


def _whoosh_supports_char3_field(ix) -> bool:
    return "content_char3" in set(ix.schema.names())


def _whoosh_supports_num_norm_field(ix) -> bool:
    return "content_num_norm" in set(ix.schema.names())


def _looks_noisy_query(query: str) -> bool:
    trimmed = query.strip()
    if not trimmed:
        return False

    non_alnum = sum(1 for ch in trimmed if not ch.isalnum() and not ch.isspace())
    non_alnum_ratio = non_alnum / max(len(trimmed), 1)
    if non_alnum_ratio >= 0.12:
        return True

    tokens = [token for token in fold_text(trimmed).split() if token]
    for token in tokens:
        if len(token) >= 9 and re.search(r"(.)\1{2,}", token):
            return True
        if len(token) >= 10 and re.search(r"[bcdfghjklmnpqrstvwxyz]{6,}", token):
            return True
        # OCR artifact: digits embedded inside a long alphabetic word (e.g. "t3l3trabaj0")
        # Digits in isolation (zip codes, years, prices) are NOT noisy.
        has_alpha = any(ch.isalpha() for ch in token)
        has_digit = any(ch.isdigit() for ch in token)
        if has_alpha and has_digit and len(token) >= 7:
            digit_ratio = sum(1 for ch in token if ch.isdigit()) / len(token)
            if 0 < digit_ratio <= 0.5:
                return True
    return False


def _should_use_char3_fallback(query: str, base_results_count: int) -> tuple[bool, str]:
    if FUZZY:
        return True, "env"
    if _looks_noisy_query(query):
        return True, "noisy_query"
    # NOTE: No disparar char3 solo porque base_results_count <= 2.
    # Palabras limpias no presentes en el corpus deben devolver 0 resultados,
    # no falsos positivos por trigramas comunes (p.ej. "espagueti" → "ESP32").
    # Char3 solo sirve para ruido OCR detectado por _looks_noisy_query.
    return False, "not_needed"


def _query_has_numeric_signal(query: str, normalized_numeric_query: str) -> bool:
    folded = fold_text(query)
    if re.search(r"\d", folded):
        return True
    if re.search(r"\b[a-z]+\b", folded) and normalized_numeric_query != folded:
        return True
    if re.search(r"\d+(?:[.,]\d+)*(?:[kmb])\b", folded):
        return True
    return False


def _has_folded_term_match(value: str, terms: list[str]) -> bool:
    folded_value = fold_text(value)
    return any(term and term in folded_value for term in terms)


def _approximate_lexical_matched_fields(
    hit,
    normalized_query: str,
    normalized_numeric_query: str,
    *,
    folded_mode: bool,
    fuzzy_char3: bool,
    numeric_norm: bool,
) -> list[str]:
    fields: list[str] = []
    query_terms = [term for term in normalized_query.split() if len(term) > 1]

    title_field = "title_folded" if folded_mode else "title"
    content_field = "content_folded" if folded_mode else "content"

    if _has_folded_term_match(hit.get("title", ""), query_terms):
        fields.append(title_field)
    if _has_folded_term_match(hit.get("content", ""), query_terms):
        fields.append(content_field)
    if _has_folded_term_match(hit.get("keywords", ""), query_terms):
        fields.append("keywords")
    if _has_folded_term_match(hit.get("persons", ""), query_terms):
        fields.append("persons")
    if _has_folded_term_match(hit.get("organizations", ""), query_terms):
        fields.append("organizations")

    if numeric_norm and normalized_numeric_query:
        normalized_content = normalize_numbers_in_text(
            hit.get("content", ""),
            language=hit.get("language", ""),
            include_original=True,
        )
        numeric_terms = [term for term in normalized_numeric_query.split() if term]
        if any(term in normalized_content for term in numeric_terms):
            fields.append("content_num_norm")

    if fuzzy_char3:
        fields.append("content_char3")

    # Preserve order while deduplicating
    return list(dict.fromkeys(fields))


def _is_entity_query(query: str) -> bool:
    """
    Returns True when the query looks like a named entity (person/org),
    in which case semantic search should be skipped.

    Heuristics (conservative on purpose):
    - 2–4 tokens that look like a proper name
    - No question words / conceptual vocabulary that suggests a semantic query

    Single-token queries such as "Aurora" are NOT treated as entities, because
    they are often project names or concepts where semantic search still helps.
    If the graph confirms an exact entity match, we only skip semantic search
    for person/organization names with at least two tokens.
    """
    QUESTION_WORDS = {
        "qué", "que", "cuál", "cual", "cómo", "como", "dónde", "donde",
        "cuándo", "cuando", "quién", "quien", "cuánto", "cuanto", "por",
        "cómo", "hay", "existe", "tiene", "puede", "dame", "dime",
        "busca", "muéstrame", "listar", "informe", "reporte",
    }
    words = query.strip().split()
    if not words or len(words) > 4:
        return False
    if any(w.lower() in QUESTION_WORDS for w in words):
        return False

    # Proper-name pattern: at least two tokens in title case.
    if len(words) >= 2 and all(w and w[0].isupper() and not w.isupper() for w in words):
        return True

    # Check against known graph entities
    try:
        from backend.graph import search_entities
        hits = search_entities(query, top_k=1)
        if (
            hits
            and hits[0]["name"].casefold() == query.casefold()
            and hits[0].get("type") in {"person", "organization"}
            and len(words) >= 2
        ):
            return True
    except Exception:
        pass
    return False


def _apply_graph_boost(
    query: str,
    results: list[SearchResult],
    boost: float = GRAPH_BOOST,
) -> list[SearchResult]:
    """
    Post-fusion: sube el score de resultados cuyos documentos contienen
    entidades mencionadas en la query (según el grafo de conocimiento).

    Estrategia:
      - Extrae candidatos de nombre propio de la query (1-3 tokens en título)
      - Busca cada candidato en el grafo via search_entities
      - Si el nombre coincide exactamente con una entidad conocida,
        aplica un multiplicador (1 + boost) a todos los chunks de ese doc
      - Re-ordena la lista por score final
    Solo actúa si GRAPH_BOOST > 0 y el grafo tiene entidades cargadas.
    """
    if boost <= 0 or not results:
        return results
    try:
        from backend.graph import search_entities
        from backend.search.text_normalize import fold_text as _ft

        query_folded = _ft(query)
        words = query.strip().split()

        # Generar n-gramas de 1 a 3 tokens de la query como candidatos de entidad
        candidates: list[str] = []
        for n in (1, 2, 3):
            for i in range(len(words) - n + 1):
                span = " ".join(words[i:i + n])
                # Solo spans que parecen nombre propio (al menos un token capitalizado)
                if any(w and w[0].isupper() for w in span.split()):
                    candidates.append(span)

        if not candidates:
            return results

        # doc_ids que merecen boost, con el número de entidades que coinciden
        boosted_doc_ids: dict[str, int] = {}
        for candidate in candidates:
            hits = search_entities(candidate, top_k=2)
            for h in hits:
                if _ft(h["name"]) in query_folded:
                    for doc_id in h.get("doc_ids", []):
                        boosted_doc_ids[doc_id] = boosted_doc_ids.get(doc_id, 0) + 1

        if not boosted_doc_ids:
            return results

        boosted_count = 0
        for r in results:
            hits_count = boosted_doc_ids.get(r.doc_id, 0)
            if hits_count:
                # Boost proporcional al número de entidades matched (cap 2x)
                effective_boost = min(boost * hits_count, boost * 2)
                r.score = r.score * (1 + effective_boost)
                r.explanation.setdefault("notes", []).append("graph_boost")
                boosted_count += 1

        if boosted_count:
            results.sort(key=lambda r: r.score, reverse=True)
            print(f"🕸️  Graph boost aplicado a {boosted_count} chunks (boost={boost})")

    except Exception:
        pass
    return results


def hybrid_search(
    query: str,
    doc_type: Optional[str] = None,
    language: Optional[str] = None,
    person: Optional[str] = None,
    organization: Optional[str] = None,
    date: Optional[str] = None,
    top_k: int = FINAL_TOP_K,
    debug: bool = False,
) -> list[SearchResult]:
    """
    Búsqueda híbrida: combina BM25 + semántica con RRF.
    Soporta filtros por tipo, idioma, persona, organización y fecha.

    Para queries de entidades (nombres propios) se omite la búsqueda semántica
    porque los embeddings no capturan significado en nombres propios.
    """
    filters = {k: v for k, v in {
        "doc_type": doc_type,
        "language": language,
        "person": person,
        "organization": organization,
        "date": date,
    }.items() if v}

    # Si la query entera son stopwords (ej: "por", "de", "y") devuelve vacío.
    # Evita que palabras funcionales sin significado semántico devuelvan resultados.
    if not _strip_stopwords(_folded_query(query)):
        return []

    bm25_results, whoosh_trace = _search_whoosh(
        query,
        filters=filters,
        top_k=SEARCH_TOP_K,
        return_trace=True,
    )

    # Skip semantic search for entity name queries — names have no vector meaning
    if _is_entity_query(query):
        semantic_results: list[SearchResult] = []
        chroma_trace = {"hits": 0, "skipped": True, "reason": "entity_query"}
    else:
        semantic_results, chroma_trace = _search_chroma(
            query,
            filters=filters,
            top_k=SEARCH_TOP_K,
            return_trace=True,
        )

    fused = _fuse_results(
        bm25_results,
        semantic_results,
        fusion_mode=FUSION_MODE,
        debug=debug,
        k=RRF_K,
    )

    # Boost de grafo: documentos con entidades mencionadas en la query suben
    fused = _apply_graph_boost(query, fused)

    for result in fused:
        fallback_used = result.explanation.setdefault(
            "fallback_used",
            {"fuzzy_char3": False, "numeric_norm": False},
        )
        fallback_used["fuzzy_char3"] = fallback_used["fuzzy_char3"] or whoosh_trace["fallbacks"]["fuzzy_char3"]
        fallback_used["numeric_norm"] = fallback_used["numeric_norm"] or whoosh_trace["fallbacks"]["numeric_norm"]
        result.explanation["fusion_mode"] = FUSION_MODE
        result.why_this_result = _build_why_this_result(result)
        result.highlight = _generate_highlight(result.text, query)

    print(
        "🔀 Hybrid search "
        f"fusion_mode={FUSION_MODE} whoosh_hits={whoosh_trace['hits']} "
        f"chroma_hits={chroma_trace['hits']} merged_hits={len(fused)} "
        f"fallbacks={whoosh_trace['fallbacks']} "
        f"semantic_skipped={chroma_trace.get('skipped', False)}"
    )

    return fused[:top_k]


def hybrid_search_with_facets(
    query: str,
    doc_type: Optional[str] = None,
    language: Optional[str] = None,
    person: Optional[str] = None,
    organization: Optional[str] = None,
    date: Optional[str] = None,
    top_k: int = FINAL_TOP_K,
    debug: bool = False,
) -> dict:
    """
    Búsqueda híbrida que devuelve resultados + facets dinámicos en cascada.
    Los facets se calculan siempre sobre los resultados filtrados, de modo
    que al aplicar un filtro los demás se restringen a lo que realmente existe.
    Para la primera búsqueda (sin filtros) se usa un pool amplio (top 200)
    para que los facets muestren la variedad máxima.
    """
    active_filters = any([doc_type, language, person, organization, date])

    if active_filters:
        # Resultados con los filtros activos (pool amplio para facets)
        filtered_results = hybrid_search(
            query=query,
            doc_type=doc_type,
            language=language,
            person=person,
            organization=organization,
            date=date,
            top_k=max(top_k, 200),
            debug=debug,
        )
        # Los facets se calculan sobre ESOS mismos resultados filtrados
        facets = _compute_facets(filtered_results)
        filtered_results = filtered_results[:top_k]
    else:
        # Sin filtros: pool amplio para tener todos los facets disponibles
        filtered_results = hybrid_search(query=query, top_k=max(top_k, 200), debug=debug)
        facets = _compute_facets(filtered_results)
        filtered_results = filtered_results[:top_k]

    return {
        "results": filtered_results,
        "facets": facets,
    }


def _compute_facets(results: list[SearchResult]) -> dict:
    """
    Calcula conteos de facets a partir de los resultados.
    Agrupa por doc_id para no inflar type/language por multi-chunk.
    """
    type_counter: Counter = Counter()
    lang_counter: Counter = Counter()
    person_counter: Counter = Counter()
    org_counter: Counter = Counter()
    keyword_counter: Counter = Counter()
    date_counter: Counter = Counter()

    seen_docs: set[str] = set()

    for r in results:
        if r.doc_id not in seen_docs:
            seen_docs.add(r.doc_id)
            if r.doc_type:
                type_counter[r.doc_type] += 1
            if r.language:
                lang_counter[r.language] += 1
        for p in r.persons:
            person_counter[p] += 1
        for o in r.organizations:
            org_counter[o] += 1
        for k in r.keywords:
            keyword_counter[k] += 1
        for d in r.dates:
            iso = _normalize_date_to_iso(d.strip())
            if iso:
                date_counter[iso] += 1

    return {
        "doc_type":      [{"value": k, "count": v} for k, v in type_counter.most_common(20)],
        "language":      [{"value": k, "count": v} for k, v in lang_counter.most_common(10)],
        "persons":       [{"value": k, "count": v} for k, v in person_counter.most_common(20)],
        "organizations": [{"value": k, "count": v} for k, v in org_counter.most_common(20)],
        "keywords":      [{"value": k, "count": v} for k, v in keyword_counter.most_common(15)],
        "dates":         [{"value": k, "count": v} for k, v in sorted(date_counter.items(), key=lambda x: x[0], reverse=True)[:20]],
    }


def _normalize_date_to_iso(raw: str) -> str | None:
    """
    Convierte cualquier formato de fecha a ISO para deduplicar en facets.
    Soporta: YYYY-MM-DD (ISO), DD/MM/YYYY, DD-MM-YYYY, YYYY-MM, YYYY.
    """
    import re
    raw = raw.strip()
    if not raw:
        return None
    # Ya es ISO: YYYY-MM-DD
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw):
        return raw
    # Ya es ISO: YYYY-MM
    if re.fullmatch(r'\d{4}-\d{2}', raw):
        return raw
    # Ya es ISO: YYYY
    if re.fullmatch(r'\d{4}', raw):
        return raw
    # DD/MM/YYYY o D/M/YYYY
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', raw)
    if m:
        d, mo, y = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    # DD-MM-YYYY (evitar confundir con YYYY-MM-DD ya tratado arriba)
    m = re.fullmatch(r'(\d{1,2})-(\d{1,2})-(\d{4})', raw)
    if m:
        d, mo, y = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return None


def _hit_matches_filters(hit, filters: dict) -> bool:
    if filters.get("person"):
        persons_text = fold_text(hit.get("persons", ""))
        if fold_text(filters["person"]) not in persons_text:
            return False

    if filters.get("organization"):
        orgs_text = fold_text(hit.get("organizations", ""))
        if fold_text(filters["organization"]) not in orgs_text:
            return False

    if filters.get("date"):
        filter_date = filters["date"]
        stored_iso = [
            _normalize_date_to_iso(d)
            for d in _split_meta(hit.get("dates", ""))
        ]
        if not any(d and d.startswith(filter_date) for d in stored_iso):
            return False

    return True


def _hit_to_search_result(hit) -> SearchResult:
    return SearchResult(
        chunk_id=hit["chunk_id"],
        doc_id=hit["doc_id"],
        text=hit.get("content", ""),
        score=hit.score,
        title=hit.get("title", ""),
        doc_type=hit.get("doc_type", ""),
        filename=hit.get("filename", ""),
        section=hit.get("section", ""),
        language=hit.get("language", ""),
        persons=_split_meta(hit.get("persons", "")),
        organizations=_split_meta(hit.get("organizations", "")),
        keywords=_split_meta(hit.get("keywords", "")),
        dates=_split_meta(hit.get("dates", "")),
        emails=_split_meta(hit.get("emails", "")),
        source="lexical",
        scores={"whoosh": hit.score, "chroma": None, "fused": hit.score},
    )


def _collect_whoosh_results(
    hits,
    filters: dict,
    top_k: int,
    *,
    normalized_query: str,
    normalized_numeric_query: str,
    folded_mode: bool,
    fuzzy_char3: bool = False,
    numeric_norm: bool = False,
    seen_chunk_ids: set[str] | None = None,
) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen = seen_chunk_ids if seen_chunk_ids is not None else set()

    for hit in hits:
        if hit["chunk_id"] in seen:
            continue
        if not _hit_matches_filters(hit, filters):
            continue
        result = _hit_to_search_result(hit)
        matched_fields = _approximate_lexical_matched_fields(
            hit,
            normalized_query,
            normalized_numeric_query,
            folded_mode=folded_mode,
            fuzzy_char3=fuzzy_char3,
            numeric_norm=numeric_norm,
        )
        notes: list[str] = []
        if numeric_norm:
            notes.append("Matched via numeric normalization fallback.")
        if fuzzy_char3:
            notes.append("Matched via character 3-gram fuzzy fallback.")
        if not matched_fields:
            notes.append("Matched via lexical search; fields are approximated.")
        result.explanation = {
            "matched_fields": matched_fields,
            "fallback_used": {
                "fuzzy_char3": fuzzy_char3,
                "numeric_norm": numeric_norm,
            },
            "notes": notes,
            "fusion_mode": FUSION_MODE,
        }
        result.score_detail = {
            **result.score_detail,
            "engine": "whoosh",
            "lexical_mode": "folded" if folded_mode else "raw",
        }
        results.append(result)
        seen.add(hit["chunk_id"])
        if len(results) >= top_k:
            break

    return results



# ─── BM25 con Whoosh ─────────────────────────────────────────────
def _search_whoosh(
    query: str,
    filters: dict | None = None,
    top_k: int = SEARCH_TOP_K,
    return_trace: bool = False,
) -> list[SearchResult] | tuple[list[SearchResult], dict]:
    """Búsqueda full-text con Whoosh (BM25). Aplica filtros a nivel de query."""
    from whoosh import index as whoosh_index
    from whoosh.qparser import AndGroup, MultifieldParser, OrGroup, QueryParser
    from whoosh.query import And, Term

    if not whoosh_index.exists_in(str(WHOOSH_DIR)):
        empty = []
        trace = {"hits": 0, "fallbacks": {"fuzzy_char3": False, "numeric_norm": False}, "lexical_mode": "missing"}
        return (empty, trace) if return_trace else empty

    ix = whoosh_index.open_dir(str(WHOOSH_DIR))
    filters = filters or {}
    search_fields = _whoosh_search_fields(ix)
    has_folded_fields = _whoosh_supports_folded_fields(ix)
    has_char3_field = _whoosh_supports_char3_field(ix)
    has_num_norm_field = _whoosh_supports_num_norm_field(ix)
    fieldboosts = {
        "title_folded": 2.5,
        "content_folded": 2.0,
        "title": 1.8,
        "content": 1.0,
        "keywords": 1.2,
        "persons": 1.2,
        "organizations": 1.2,
    }

    # AndGroup: "juan carlos" exige AMBOS términos (más preciso que Or).
    # Para queries de una sola palabra And y Or son equivalentes.
    parser = MultifieldParser(
        search_fields,
        schema=ix.schema,
        group=AndGroup,
        fieldboosts={field: fieldboosts[field] for field in search_fields if field in fieldboosts},
    )

    # Fold the lexical query so folded fields become robust to Unicode,
    # accents and casing. If the index is still on the old schema, we fall
    # back to raw fields and keep the original query text.
    normalized_query = _folded_query(query) if not LEXICAL_STRICT and has_folded_fields else query

    # Filter stopwords from the query so that common words like "por" don't
    # pollute the results. We strip stopwords from the folded query. If the
    # result is empty (all tokens were stopwords), bail out early.
    filtered_query = _strip_stopwords(normalized_query)
    if not filtered_query:
        empty: list[SearchResult] = []
        return (empty, trace) if return_trace else empty
    normalized_query = filtered_query

    normalized_numeric_query = normalize_numbers_in_text(
        query,
        language=None,
        include_original=False,
    )
    trace = {
        "hits": 0,
        "fallbacks": {"fuzzy_char3": False, "numeric_norm": False},
        "lexical_mode": "strict-raw" if LEXICAL_STRICT else ("folded" if has_folded_fields else "raw-fallback"),
    }

    try:
        parsed_query = parser.parse(normalized_query)
    except Exception:
        empty = []
        return (empty, trace) if return_trace else empty

    # Sinónimos como soft boost (AndMaybe): los términos expandidos NO son
    # obligatorios, pero si aparecen en un documento suben su score.
    # Esto es diferente al fallback OR (que solo actúa cuando AND da 0).
    try:
        from whoosh.query import AndMaybe
        or_boost_parser = MultifieldParser(
            search_fields,
            schema=ix.schema,
            group=OrGroup,
            fieldboosts={
                field: fieldboosts[field] * 0.35
                for field in search_fields
                if field in fieldboosts
            },
        )
        expanded_for_boost = _expand_with_synonyms(normalized_query)
        if expanded_for_boost != normalized_query:
            synonym_boost_query = or_boost_parser.parse(expanded_for_boost)
            parsed_query = AndMaybe(parsed_query, synonym_boost_query)
    except Exception:
        pass

    # Construir filtros como query terms (se aplican ANTES de la búsqueda)
    filter_queries = []
    if filters.get("doc_type"):
        filter_queries.append(Term("doc_type", filters["doc_type"]))
    if filters.get("language"):
        filter_queries.append(Term("language", filters["language"]))

    # Combinar query principal con filtros
    if filter_queries:
        parsed_query = And([parsed_query] + filter_queries)

    with ix.searcher() as searcher:
        # Pedir más resultados para luego aplicar filtros soft (persona/org)
        normal_hits = searcher.search(parsed_query, limit=top_k * 3)

        # Si And-query da 0 resultados, reintentamos con Or + sinónimos (fallback de precisión)
        if len(normal_hits) == 0:
            or_parser = MultifieldParser(
                search_fields,
                schema=ix.schema,
                group=OrGroup,
                fieldboosts={field: fieldboosts[field] for field in search_fields if field in fieldboosts},
            )
            try:
                expanded_query = _expand_with_synonyms(normalized_query)
                or_query = or_parser.parse(expanded_query)
                if filter_queries:
                    or_query = And([or_query] + filter_queries)
                normal_hits = searcher.search(or_query, limit=top_k * 3)
            except Exception:
                pass

        results = _collect_whoosh_results(
            normal_hits,
            filters,
            top_k,
            normalized_query=normalized_query,
            normalized_numeric_query=normalized_numeric_query,
            folded_mode=not LEXICAL_STRICT and has_folded_fields,
        )
        base_results_count = len(results)

        numeric_signal = _query_has_numeric_signal(query, normalized_numeric_query)
        if base_results_count <= 2 and numeric_signal and has_num_norm_field:
            trace["fallbacks"]["numeric_norm"] = True
            numeric_parser = QueryParser("content_num_norm", schema=ix.schema, group=AndGroup)
            try:
                numeric_query = numeric_parser.parse(normalized_numeric_query)
                if filter_queries:
                    numeric_query = And([numeric_query] + filter_queries)
                numeric_hits = searcher.search(numeric_query, limit=max(top_k * 3, 10))
                print(
                    "🔢 Whoosh numeric mode=num_norm "
                    f"base_hits={base_results_count} raw_hits={len(numeric_hits)} query={normalized_numeric_query!r}"
                )
                results.extend(
                    _collect_whoosh_results(
                        numeric_hits,
                        filters,
                        max(top_k - len(results), 0),
                        normalized_query=normalized_query,
                        normalized_numeric_query=normalized_numeric_query,
                        folded_mode=not LEXICAL_STRICT and has_folded_fields,
                        numeric_norm=True,
                        seen_chunk_ids={result.chunk_id for result in results},
                    )
                )
            except Exception:
                pass
        elif base_results_count <= 2 and numeric_signal and not has_num_norm_field:
            print(
                "⚠️  Whoosh numeric fallback requested but the index schema "
                "does not include content_num_norm. Rebuild lexical indexes."
            )

        current_results_count = len(results)
        use_char3, char3_reason = _should_use_char3_fallback(query, current_results_count)
        fuzzy_hits_count = 0
        if use_char3 and has_char3_field:
            trace["fallbacks"]["fuzzy_char3"] = True
            q_fold = _folded_query(query)
            q_ng = " ".join(char_ngrams(q_fold, 3))
            if q_ng:
                fuzzy_parser = QueryParser("content_char3", schema=ix.schema, group=OrGroup)
                try:
                    fuzzy_query = fuzzy_parser.parse(q_ng)
                    if filter_queries:
                        fuzzy_query = And([fuzzy_query] + filter_queries)
                    fuzzy_hits = searcher.search(fuzzy_query, limit=max(top_k * 5, 50))
                    fuzzy_hits_count = len(fuzzy_hits)

                    # ── Filtro de cobertura de trigramas ────────────────────────
                    # Solo conservar resultados donde al menos CHAR3_MIN_COVERAGE
                    # fracción de los trigramas del query aparecen en el contenido.
                    # Esto elimina falsos positivos donde solo un trigram aleatorio
                    # coincide (p.ej. "esp" de "espagueti" matcheando "ESP32").
                    query_ngrams = set(char_ngrams(q_fold, 3))
                    if query_ngrams and CHAR3_MIN_COVERAGE > 0:
                        covered_hits = []
                        for hit in fuzzy_hits:
                            # Usar el campo precomputado (trigramas separados por espacio)
                            char3_content = hit.get("content_char3", "")
                            if char3_content:
                                hit_ngrams = set(char3_content.split())
                            else:
                                hit_ngrams = set(char_ngrams(fold_text(hit.get("content", "")), 3))
                            coverage = len(query_ngrams & hit_ngrams) / len(query_ngrams)
                            if coverage >= CHAR3_MIN_COVERAGE:
                                covered_hits.append(hit)
                        hits_to_process = covered_hits
                    else:
                        hits_to_process = list(fuzzy_hits)

                    coverage_filtered = fuzzy_hits_count - len(hits_to_process)
                    print(
                        "🪶 Whoosh fuzzy mode=char3 "
                        f"reason={char3_reason} base_hits={current_results_count} "
                        f"raw_hits={fuzzy_hits_count} coverage_filtered={coverage_filtered} "
                        f"kept={len(hits_to_process)}"
                    )
                    if hits_to_process:
                        results.extend(
                            _collect_whoosh_results(
                                hits_to_process,
                                filters,
                                max(top_k - len(results), 0),
                                normalized_query=normalized_query,
                                normalized_numeric_query=normalized_numeric_query,
                                folded_mode=not LEXICAL_STRICT and has_folded_fields,
                                fuzzy_char3=True,
                                seen_chunk_ids={result.chunk_id for result in results},
                            )
                        )
                except Exception:
                    pass
        elif use_char3 and not has_char3_field:
            print(
                "⚠️  Whoosh char3 fuzzy fallback requested but the index schema "
                "does not include content_char3. Rebuild lexical indexes."
            )

    trace["hits"] = len(results)
    print(f"🔎 Whoosh lexical mode={trace['lexical_mode']} query={normalized_query!r} hits={len(results)}")

    return (results, trace) if return_trace else results


# ─── Semántica con ChromaDB ──────────────────────────────────────
def _search_chroma(
    query: str,
    filters: dict | None = None,
    top_k: int = SEARCH_TOP_K,
    return_trace: bool = False,
) -> list[SearchResult] | tuple[list[SearchResult], dict]:
    """Búsqueda semántica con ChromaDB (cosine similarity) con filtros."""
    from backend.search.indexer import _get_embedding_model, _get_chroma_collection

    model = _get_embedding_model()
    collection = _get_chroma_collection()
    filters = filters or {}

    query_embedding = model.encode(query).tolist()

    # Construir filtro de metadatos para ChromaDB
    where_clauses = []
    if filters.get("doc_type"):
        where_clauses.append({"doc_type": filters["doc_type"]})
    if filters.get("language"):
        where_clauses.append({"language": filters["language"]})

    where = None
    if len(where_clauses) == 1:
        where = where_clauses[0]
    elif len(where_clauses) > 1:
        where = {"$and": where_clauses}

    try:
        chroma_results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k * 3 if filters.get("person") or filters.get("organization") else top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        empty = []
        trace = {"hits": 0, "skipped": False}
        return (empty, trace) if return_trace else empty

    results: list[SearchResult] = []

    if not chroma_results["ids"] or not chroma_results["ids"][0]:
        trace = {"hits": 0, "skipped": False}
        return (results, trace) if return_trace else results

    for i, chunk_id in enumerate(chroma_results["ids"][0]):
        meta = chroma_results["metadatas"][0][i]
        text = chroma_results["documents"][0][i]
        distance = chroma_results["distances"][0][i]

        # Filtro soft para persons/organizations
        if filters.get("person"):
            persons_text = fold_text(meta.get("persons", ""))
            if fold_text(filters["person"]) not in persons_text:
                continue
        if filters.get("organization"):
            orgs_text = fold_text(meta.get("organizations", ""))
            if fold_text(filters["organization"]) not in orgs_text:
                continue
        # Filtro soft por fecha: normaliza cada fecha almacenada a ISO
        # y verifica prefijo ("2025-01" debe coincidir con "2025-01-10")
        if filters.get("date"):
            filter_date = filters["date"]
            stored_iso = [
                _normalize_date_to_iso(d)
                for d in _split_meta(meta.get("dates", ""))
            ]
            if not any(d and d.startswith(filter_date) for d in stored_iso):
                continue

        # Convertir distancia coseno a score (1 = perfecto, 0 = nada)
        score = max(0, 1 - distance)

        # Descartar resultados con similitud muy baja (ruido semántico)
        if score < SEMANTIC_MIN_SCORE:
            continue

        semantic_result = SearchResult(
            chunk_id=chunk_id,
            doc_id=meta.get("doc_id", ""),
            text=text,
            score=score,
            title=meta.get("title", ""),
            doc_type=meta.get("doc_type", ""),
            filename=meta.get("filename", ""),
            section=meta.get("section", ""),
            language=meta.get("language", ""),
            persons=_split_meta(meta.get("persons", "")),
            organizations=_split_meta(meta.get("organizations", "")),
            keywords=_split_meta(meta.get("keywords", "")),
            dates=_split_meta(meta.get("dates", "")),
            emails=_split_meta(meta.get("emails", "")),
            source="semantic",
            scores={"whoosh": None, "chroma": score, "fused": score},
            explanation={
                "matched_fields": [],
                "fallback_used": {"fuzzy_char3": False, "numeric_norm": False},
                "notes": ["Matched via semantic vector similarity."],
                "fusion_mode": FUSION_MODE,
            },
            score_detail={"engine": "chroma", "semantic_distance": distance},
        )
        results.append(semantic_result)

        if len(results) >= top_k:
            break

    trace = {"hits": len(results), "skipped": False}
    return (results, trace) if return_trace else results


def _merge_explanations(
    lexical: dict,
    semantic: dict,
    *,
    source: str,
    fused_score: float,
    fusion_mode: str,
    debug: bool,
) -> dict:
    matched_fields = list(
        dict.fromkeys((lexical.get("matched_fields") or []) + (semantic.get("matched_fields") or []))
    )
    fallback_used = {
        "fuzzy_char3": bool((lexical.get("fallback_used") or {}).get("fuzzy_char3")),
        "numeric_norm": bool((lexical.get("fallback_used") or {}).get("numeric_norm")),
    }
    notes = list(
        dict.fromkeys((lexical.get("notes") or []) + (semantic.get("notes") or []))
    )
    if source == "hybrid":
        notes.append("Combined lexical and semantic evidence.")
    explanation = {
        "matched_fields": matched_fields,
        "fallback_used": fallback_used,
        "notes": notes,
        "fusion_mode": fusion_mode,
    }
    if not debug:
        explanation.pop("notes", None)
        explanation["matched_fields"] = matched_fields[:5]
    return explanation


def _display_field_name(field: str) -> str:
    labels = {
        "title": "titulo",
        "title_folded": "titulo",
        "content": "contenido",
        "content_folded": "contenido",
        "keywords": "keywords",
        "persons": "personas",
        "organizations": "organizaciones",
        "content_char3": "texto aproximado",
        "content_num_norm": "numeros normalizados",
    }
    return labels.get(field, field)


def _build_why_this_result(result: SearchResult) -> str:
    explanation = result.explanation or {}
    matched_fields = [
        _display_field_name(field)
        for field in (explanation.get("matched_fields") or [])
        if field
    ]
    fallback_used = explanation.get("fallback_used") or {}
    notes: list[str] = []

    if result.source == "hybrid":
        notes.append("Coincide por texto y por similitud semantica")
    elif result.source == "lexical":
        notes.append("Coincide por texto")
    elif result.source == "semantic":
        notes.append("Coincide por similitud semantica")

    if matched_fields:
        compact_fields = ", ".join(list(dict.fromkeys(matched_fields))[:3])
        notes.append(f"campos: {compact_fields}")

    if fallback_used.get("numeric_norm"):
        notes.append("normalizacion numerica activada")
    if fallback_used.get("fuzzy_char3"):
        notes.append("tolerancia a typos/OCR activada")
    if "graph_boost" in (explanation.get("notes") or []):
        notes.append("entidad del grafo de conocimiento")

    return ". ".join(notes) + "." if notes else ""


def _normalize_score_map(score_map: dict[str, float]) -> dict[str, float]:
    if not score_map:
        return {}
    values = list(score_map.values())
    min_value = min(values)
    max_value = max(values)
    if max_value == min_value:
        return {key: 1.0 for key in score_map}
    return {
        key: (value - min_value) / (max_value - min_value)
        for key, value in score_map.items()
    }


def _fuse_results(
    bm25_results: list[SearchResult],
    semantic_results: list[SearchResult],
    *,
    fusion_mode: str,
    debug: bool,
    k: int = RRF_K,
) -> list[SearchResult]:
    if fusion_mode == "weighted":
        return _weighted_fusion(bm25_results, semantic_results, debug=debug)
    return _reciprocal_rank_fusion(bm25_results, semantic_results, k=k, debug=debug)


# ─── Reciprocal Rank Fusion ──────────────────────────────────────
def _reciprocal_rank_fusion(
    bm25_results: list[SearchResult],
    semantic_results: list[SearchResult],
    k: int = RRF_K,
    debug: bool = False,
) -> list[SearchResult]:
    """
    Combina dos listas de resultados usando Reciprocal Rank Fusion.
    Formula: score_rrf(d) = Σ 1 / (k + rank_i(d))
    """
    scores: dict[str, float] = {}
    result_map: dict[str, SearchResult] = {}
    bm25_ranks: dict[str, int] = {}     # chunk_id → posición 1-based en lista BM25
    semantic_ranks: dict[str, int] = {}  # chunk_id → posición 1-based en lista semántica
    lexical_score_map = {result.chunk_id: result.scores.get("whoosh", result.score) for result in bm25_results}
    semantic_score_map = {result.chunk_id: result.scores.get("chroma", result.score) for result in semantic_results}

    # Acumular scores de BM25
    for rank, result in enumerate(bm25_results):
        bm25_ranks[result.chunk_id] = rank + 1
        scores[result.chunk_id] = scores.get(result.chunk_id, 0) + 1 / (k + rank + 1)
        if result.chunk_id not in result_map:
            result_map[result.chunk_id] = result

    # Acumular scores de semántica
    for rank, result in enumerate(semantic_results):
        semantic_ranks[result.chunk_id] = rank + 1
        scores[result.chunk_id] = scores.get(result.chunk_id, 0) + 1 / (k + rank + 1)
        if result.chunk_id not in result_map:
            result_map[result.chunk_id] = result
        else:
            # Si ya existía por BM25 pero el texto estaba vacío, rellenar
            existing = result_map[result.chunk_id]
            if not existing.text and result.text:
                existing.text = result.text

    # Ordenar por score RRF descendente
    ranked_ids = sorted(scores, key=scores.get, reverse=True)

    results = []
    doc_chunk_count: dict[str, int] = {}
    for chunk_id in ranked_ids:
        r = result_map[chunk_id]
        # Limitar chunks por documento: evita que un doc largo acapare todos los resultados
        n = doc_chunk_count.get(r.doc_id, 0)
        if n >= MAX_CHUNKS_PER_DOC:
            continue
        doc_chunk_count[r.doc_id] = n + 1
        r.score = scores[chunk_id]
        # Explicabilidad: qué sistema(s) encontraron este resultado y en qué posición
        sources = (["bm25"] if chunk_id in bm25_ranks else []) + \
                  (["semantic"] if chunk_id in semantic_ranks else [])
        source = "hybrid" if len(sources) == 2 else ("lexical" if "bm25" in sources else "semantic")
        lexical_result = next((item for item in bm25_results if item.chunk_id == chunk_id), SearchResult(chunk_id=chunk_id, doc_id=r.doc_id, text=""))
        semantic_result = next((item for item in semantic_results if item.chunk_id == chunk_id), SearchResult(chunk_id=chunk_id, doc_id=r.doc_id, text=""))
        r.source = source
        r.scores = {
            "whoosh": lexical_score_map.get(chunk_id),
            "chroma": semantic_score_map.get(chunk_id),
            "fused": r.score,
        }
        r.explanation = _merge_explanations(
            lexical_result.explanation,
            semantic_result.explanation,
            source=source,
            fused_score=r.score,
            fusion_mode="rrf",
            debug=debug,
        )
        r.score_detail = {
            "sources": sources,
            "bm25_rank": bm25_ranks.get(chunk_id),
            "semantic_rank": semantic_ranks.get(chunk_id),
            "fusion_mode": "rrf",
        }
        results.append(r)

    return results


def _weighted_fusion(
    bm25_results: list[SearchResult],
    semantic_results: list[SearchResult],
    *,
    debug: bool = False,
) -> list[SearchResult]:
    lexical_raw = {result.chunk_id: result.scores.get("whoosh", result.score) for result in bm25_results}
    semantic_raw = {result.chunk_id: result.scores.get("chroma", result.score) for result in semantic_results}
    lexical_norm = _normalize_score_map(lexical_raw)
    semantic_norm = _normalize_score_map(semantic_raw)

    result_map: dict[str, SearchResult] = {}
    for result in bm25_results + semantic_results:
        result_map.setdefault(result.chunk_id, result)

    scores: dict[str, float] = {}
    lexical_components: dict[str, float] = {}
    semantic_components: dict[str, float] = {}
    bm25_ranks = {result.chunk_id: rank + 1 for rank, result in enumerate(bm25_results)}
    semantic_ranks = {result.chunk_id: rank + 1 for rank, result in enumerate(semantic_results)}

    for chunk_id in result_map:
        lexical_component = lexical_norm.get(chunk_id, 0.0) * WEIGHT_LEXICAL
        semantic_component = semantic_norm.get(chunk_id, 0.0) * WEIGHT_SEMANTIC
        lexical_components[chunk_id] = lexical_component
        semantic_components[chunk_id] = semantic_component
        scores[chunk_id] = lexical_component + semantic_component

    ranked_ids = sorted(scores, key=scores.get, reverse=True)
    results: list[SearchResult] = []
    doc_chunk_count: dict[str, int] = {}

    for chunk_id in ranked_ids:
        result = result_map[chunk_id]
        n = doc_chunk_count.get(result.doc_id, 0)
        if n >= MAX_CHUNKS_PER_DOC:
            continue
        doc_chunk_count[result.doc_id] = n + 1
        result.score = scores[chunk_id]
        sources = (["bm25"] if chunk_id in bm25_ranks else []) + (["semantic"] if chunk_id in semantic_ranks else [])
        source = "hybrid" if len(sources) == 2 else ("lexical" if "bm25" in sources else "semantic")
        lexical_result = next((item for item in bm25_results if item.chunk_id == chunk_id), SearchResult(chunk_id=chunk_id, doc_id=result.doc_id, text=""))
        semantic_result = next((item for item in semantic_results if item.chunk_id == chunk_id), SearchResult(chunk_id=chunk_id, doc_id=result.doc_id, text=""))
        result.source = source
        result.scores = {
            "whoosh": lexical_raw.get(chunk_id),
            "chroma": semantic_raw.get(chunk_id),
            "fused": result.score,
            "whoosh_norm": lexical_norm.get(chunk_id),
            "chroma_norm": semantic_norm.get(chunk_id),
            "whoosh_component": lexical_components.get(chunk_id, 0.0),
            "chroma_component": semantic_components.get(chunk_id, 0.0),
        }
        result.explanation = _merge_explanations(
            lexical_result.explanation,
            semantic_result.explanation,
            source=source,
            fused_score=result.score,
            fusion_mode="weighted",
            debug=debug,
        )
        result.score_detail = {
            "sources": sources,
            "bm25_rank": bm25_ranks.get(chunk_id),
            "semantic_rank": semantic_ranks.get(chunk_id),
            "fusion_mode": "weighted",
            "weights": {"lexical": WEIGHT_LEXICAL, "semantic": WEIGHT_SEMANTIC},
        }
        results.append(result)

    return results


# ─── Highlight ───────────────────────────────────────────────────
def _generate_highlight(text: str, query: str, context_chars: int = 200) -> str:
    """
    Genera un snippet del texto con los términos de búsqueda resaltados.
    Busca la primera aparición de cualquier término y extrae contexto.
    """
    if not text:
        return ""

    query_terms = [
        t.casefold() for t in query.split()
        if len(t) > 2 and fold_text(t).casefold() not in _STOPWORDS
    ]

    if not query_terms:
        return text[:context_chars] + ("..." if len(text) > context_chars else "")

    text_lower = text.casefold()

    # Encontrar la posición de la primera aparición
    best_pos = len(text)
    for term in query_terms:
        pos = text_lower.find(term)
        if 0 <= pos < best_pos:
            best_pos = pos

    if best_pos >= len(text):
        folded_text, mapping = _fold_with_mapping(text)
        folded_terms = [fold_text(term) for term in query_terms if fold_text(term)]
        for term in folded_terms:
            pos = folded_text.find(term)
            if pos >= 0:
                mapped_pos = mapping[pos] if pos < len(mapping) else 0
                if mapped_pos < best_pos:
                    best_pos = mapped_pos

        if best_pos >= len(text):
            for gram in char_ngrams(query, 3, max_ngrams=64):
                pos = folded_text.find(gram)
                if pos >= 0:
                    mapped_pos = mapping[pos] if pos < len(mapping) else 0
                    if mapped_pos < best_pos:
                        best_pos = mapped_pos
                        break

    if best_pos >= len(text):
        best_pos = 0

    # Extraer snippet alrededor de la coincidencia
    start = max(0, best_pos - context_chars // 2)
    end = min(len(text), best_pos + context_chars)
    snippet = text[start:end]

    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."

    # Marcar los términos con **bold**
    for term in query_terms:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        snippet = pattern.sub(lambda m: f"**{m.group()}**", snippet)

    return snippet


def _split_meta(value: str) -> list[str]:
    """Convierte un string 'a, b, c' en lista ['a', 'b', 'c']."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]
