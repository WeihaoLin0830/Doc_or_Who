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
import unicodedata
from collections import Counter
from typing import Optional

from backend.config import SEARCH_TOP_K, FINAL_TOP_K, RRF_K, WHOOSH_DIR
from backend.config import SEMANTIC_MIN_SCORE, MAX_CHUNKS_PER_DOC
from backend.models import SearchResult


def _strip_accents(text: str) -> str:
    """
    Elimina acentos/diacríticos: 'reunión' → 'reunion'.
    Permite buscar sin acento y encontrar términos acentuados
    (cuando el índice Whoosh tiene el mismo analizador).
    """
    nfd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfd if not unicodedata.combining(c))


# ─── Sinónimos corporativos español ─────────────────────────────
# Sólo para el fallback Or: si BM25-And no encuentra nada,
# se expande la query con estos términos para mejorar el recall.
_SYNONYMS: dict[str, list[str]] = {
    "reunion":     ["junta", "asamblea", "sesion", "meeting", "acta"],
    "acta":        ["reunion", "sesion", "asamblea", "junta", "meeting"],
    "acuerdo":     ["decision", "compromiso", "resolucion", "conclusion"],
    "informe":     ["reporte", "memoria", "nota", "resumen"],
    "contrato":    ["convenio", "pacto"],
    "proveedor":   ["suministrador", "vendedor", "partner"],
    "incidencia":  ["problema", "averia", "error", "fallo", "ticket"],
    "empleado":    ["trabajador", "personal", "colaborador"],
    "presupuesto": ["coste", "precio", "importe"],
    "servidor":    ["maquina", "sistema", "equipo", "host"],
    "proyecto":    ["iniciativa", "plan", "programa"],
    "cliente":     ["usuario", "consumidor"],
}


def _expand_with_synonyms(query: str) -> str:
    """
    Expande la query con sinónimos del diccionario corporativo.
    Usa claves normalizadas (sin acentos, minúsculas) para el matching.
    Devuelve la query original si no hay sinónimos aplicables.
    """
    words = _strip_accents(query.lower()).split()
    extra: list[str] = []
    for word in words:
        if word in _SYNONYMS:
            extra.extend(_SYNONYMS[word])
    if not extra:
        return query
    # Deduplicar manteniendo orden
    seen: set[str] = set(_strip_accents(query.lower()).split())
    unique_extra = [w for w in extra if w not in seen and not seen.add(w)]
    return query + (" " + " ".join(unique_extra) if unique_extra else "")


def _is_entity_query(query: str) -> bool:
    """
    Returns True when the query looks like a named entity (person/org),
    in which case semantic search should be skipped.

    Heuristics (all must fit):
    - 1–4 tokens
    - Every token starts with a capital letter (proper name pattern)
    - No question words / conceptual vocabulary that suggests a semantic query

    Additionally, if a matching entity exists in the graph, we confirm it.
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
    # All words capitalized (proper name signal)
    if all(w[0].isupper() for w in words):
        return True
    # Check against known graph entities
    try:
        from backend.graph import search_entities
        hits = search_entities(query, top_k=1)
        if hits and hits[0]["name"].lower() == query.lower():
            return True
    except Exception:
        pass
    return False


def hybrid_search(
    query: str,
    doc_type: Optional[str] = None,
    language: Optional[str] = None,
    person: Optional[str] = None,
    organization: Optional[str] = None,
    date: Optional[str] = None,
    top_k: int = FINAL_TOP_K,
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

    bm25_results = _search_whoosh(query, filters=filters, top_k=SEARCH_TOP_K)

    # Skip semantic search for entity name queries — names have no vector meaning
    if _is_entity_query(query):
        semantic_results: list[SearchResult] = []
    else:
        semantic_results = _search_chroma(query, filters=filters, top_k=SEARCH_TOP_K)

    fused = _reciprocal_rank_fusion(bm25_results, semantic_results, k=RRF_K)

    for result in fused:
        result.highlight = _generate_highlight(result.text, query)

    return fused[:top_k]


def hybrid_search_with_facets(
    query: str,
    doc_type: Optional[str] = None,
    language: Optional[str] = None,
    person: Optional[str] = None,
    organization: Optional[str] = None,
    date: Optional[str] = None,
    top_k: int = FINAL_TOP_K,
) -> dict:
    """
    Búsqueda híbrida que devuelve resultados + facets dinámicos.
    Los facets se calculan sobre los resultados SIN filtrar para
    mostrar qué opciones están disponibles en el universo de la query.
    """
    # Resultados sin filtros para calcular facets (hasta 50)
    all_results = hybrid_search(query=query, top_k=max(top_k, 50))
    facets = _compute_facets(all_results)

    # Resultados CON filtros aplicados
    if any([doc_type, language, person, organization, date]):
        filtered_results = hybrid_search(
            query=query,
            doc_type=doc_type,
            language=language,
            person=person,
            organization=organization,
            date=date,
            top_k=top_k,
        )
    else:
        filtered_results = all_results[:top_k]

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



# ─── BM25 con Whoosh ─────────────────────────────────────────────
def _search_whoosh(
    query: str,
    filters: dict | None = None,
    top_k: int = SEARCH_TOP_K,
) -> list[SearchResult]:
    """Búsqueda full-text con Whoosh (BM25). Aplica filtros a nivel de query."""
    from whoosh import index as whoosh_index
    from whoosh.qparser import MultifieldParser, OrGroup, AndGroup
    from whoosh.query import And, Term

    if not whoosh_index.exists_in(str(WHOOSH_DIR)):
        return []

    ix = whoosh_index.open_dir(str(WHOOSH_DIR))
    filters = filters or {}

    # AndGroup: "juan carlos" exige AMBOS términos (más preciso que Or).
    # Para queries de una sola palabra And y Or son equivalentes.
    parser = MultifieldParser(
        ["content", "title", "keywords", "persons", "organizations"],
        schema=ix.schema,
        group=AndGroup,
    )

    # Normalizar acentos en la query para que coincida con el analizador del índice.
    # Así "reunion" encuentra "reunión" y viceversa sin importar cómo tipea el usuario.
    normalized_query = _strip_accents(query)

    try:
        parsed_query = parser.parse(normalized_query)
    except Exception:
        return []

    # Construir filtros como query terms (se aplican ANTES de la búsqueda)
    filter_queries = []
    if filters.get("doc_type"):
        filter_queries.append(Term("doc_type", filters["doc_type"]))
    if filters.get("language"):
        filter_queries.append(Term("language", filters["language"]))

    # Combinar query principal con filtros
    if filter_queries:
        parsed_query = And([parsed_query] + filter_queries)

    results: list[SearchResult] = []

    with ix.searcher() as searcher:
        # Pedir más resultados para luego aplicar filtros soft (persona/org)
        hits = searcher.search(parsed_query, limit=top_k * 3)

        # Si And-query da 0 resultados, reintentamos con Or + sinónimos (fallback de precisión)
        if len(hits) == 0:
            or_parser = MultifieldParser(
                ["content", "title", "keywords", "persons", "organizations"],
                schema=ix.schema,
                group=OrGroup,
            )
            try:
                expanded_query = _expand_with_synonyms(normalized_query)
                or_query = or_parser.parse(expanded_query)
                if filter_queries:
                    or_query = And([or_query] + filter_queries)
                hits = searcher.search(or_query, limit=top_k * 3)
            except Exception:
                pass

        for hit in hits:
            # Filtro soft para persons/organizations (contienen substring)
            if filters.get("person"):
                persons_text = hit.get("persons", "").lower()
                if filters["person"].lower() not in persons_text:
                    continue
            if filters.get("organization"):
                orgs_text = hit.get("organizations", "").lower()
                if filters["organization"].lower() not in orgs_text:
                    continue
            # Filtro soft por fecha: normaliza cada fecha almacenada a ISO
            # y verifica prefijo ("2025-01" debe coincidir con "2025-01-10")
            if filters.get("date"):
                filter_date = filters["date"]
                stored_iso = [
                    _normalize_date_to_iso(d)
                    for d in _split_meta(hit.get("dates", ""))
                ]
                if not any(d and d.startswith(filter_date) for d in stored_iso):
                    continue

            results.append(SearchResult(
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
            ))

            if len(results) >= top_k:
                break

    return results


# ─── Semántica con ChromaDB ──────────────────────────────────────
def _search_chroma(
    query: str,
    filters: dict | None = None,
    top_k: int = SEARCH_TOP_K,
) -> list[SearchResult]:
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
        return []

    results: list[SearchResult] = []

    if not chroma_results["ids"] or not chroma_results["ids"][0]:
        return results

    for i, chunk_id in enumerate(chroma_results["ids"][0]):
        meta = chroma_results["metadatas"][0][i]
        text = chroma_results["documents"][0][i]
        distance = chroma_results["distances"][0][i]

        # Filtro soft para persons/organizations
        if filters.get("person"):
            persons_text = meta.get("persons", "").lower()
            if filters["person"].lower() not in persons_text:
                continue
        if filters.get("organization"):
            orgs_text = meta.get("organizations", "").lower()
            if filters["organization"].lower() not in orgs_text:
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

        results.append(SearchResult(
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
        ))

        if len(results) >= top_k:
            break

    return results


# ─── Reciprocal Rank Fusion ──────────────────────────────────────
def _reciprocal_rank_fusion(
    bm25_results: list[SearchResult],
    semantic_results: list[SearchResult],
    k: int = RRF_K,
) -> list[SearchResult]:
    """
    Combina dos listas de resultados usando Reciprocal Rank Fusion.
    Formula: score_rrf(d) = Σ 1 / (k + rank_i(d))
    """
    scores: dict[str, float] = {}
    result_map: dict[str, SearchResult] = {}
    bm25_ranks: dict[str, int] = {}     # chunk_id → posición 1-based en lista BM25
    semantic_ranks: dict[str, int] = {}  # chunk_id → posición 1-based en lista semántica

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
        r.score_detail = {
            "sources": sources,
            "bm25_rank": bm25_ranks.get(chunk_id),
            "semantic_rank": semantic_ranks.get(chunk_id),
        }
        results.append(r)

    return results


# ─── Highlight ───────────────────────────────────────────────────
def _generate_highlight(text: str, query: str, context_chars: int = 200) -> str:
    """
    Genera un snippet del texto con los términos de búsqueda resaltados.
    Busca la primera aparición de cualquier término y extrae contexto.
    """
    if not text:
        return ""

    query_terms = [t.lower() for t in query.split() if len(t) > 2]

    if not query_terms:
        return text[:context_chars] + ("..." if len(text) > context_chars else "")

    text_lower = text.lower()

    # Encontrar la posición de la primera aparición
    best_pos = len(text)
    for term in query_terms:
        pos = text_lower.find(term)
        if 0 <= pos < best_pos:
            best_pos = pos

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
