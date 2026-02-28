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

from backend.config import SEARCH_TOP_K, FINAL_TOP_K, RRF_K, WHOOSH_DIR
from backend.models import SearchResult


def hybrid_search(
    query: str,
    doc_type: Optional[str] = None,
    language: Optional[str] = None,
    person: Optional[str] = None,
    organization: Optional[str] = None,
    top_k: int = FINAL_TOP_K,
) -> list[SearchResult]:
    """
    Búsqueda híbrida: combina BM25 + semántica con RRF.
    Soporta filtros por tipo, idioma, persona y organización.
    """
    filters = {k: v for k, v in {
        "doc_type": doc_type,
        "language": language,
        "person": person,
        "organization": organization,
    }.items() if v}

    bm25_results = _search_whoosh(query, filters=filters, top_k=SEARCH_TOP_K)
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
    if any([doc_type, language, person, organization]):
        filtered_results = hybrid_search(
            query=query,
            doc_type=doc_type,
            language=language,
            person=person,
            organization=organization,
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

    return {
        "doc_type":      [{"value": k, "count": v} for k, v in type_counter.most_common(20)],
        "language":      [{"value": k, "count": v} for k, v in lang_counter.most_common(10)],
        "persons":       [{"value": k, "count": v} for k, v in person_counter.most_common(20)],
        "organizations": [{"value": k, "count": v} for k, v in org_counter.most_common(20)],
        "keywords":      [{"value": k, "count": v} for k, v in keyword_counter.most_common(15)],
    }



# ─── BM25 con Whoosh ─────────────────────────────────────────────
def _search_whoosh(
    query: str,
    filters: dict | None = None,
    top_k: int = SEARCH_TOP_K,
) -> list[SearchResult]:
    """Búsqueda full-text con Whoosh (BM25). Aplica filtros a nivel de query."""
    from whoosh import index as whoosh_index
    from whoosh.qparser import MultifieldParser, OrGroup
    from whoosh.query import And, Term

    if not whoosh_index.exists_in(str(WHOOSH_DIR)):
        return []

    ix = whoosh_index.open_dir(str(WHOOSH_DIR))
    filters = filters or {}

    # Buscar en título, contenido, keywords, personas y organizaciones
    parser = MultifieldParser(
        ["content", "title", "keywords", "persons", "organizations"],
        schema=ix.schema,
        group=OrGroup,
    )

    try:
        parsed_query = parser.parse(query)
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
    from backend.indexer import _get_embedding_model, _get_chroma_collection

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

        # Convertir distancia coseno a score (1 = perfecto, 0 = nada)
        score = max(0, 1 - distance)

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

    # Acumular scores de BM25
    for rank, result in enumerate(bm25_results):
        scores[result.chunk_id] = scores.get(result.chunk_id, 0) + 1 / (k + rank + 1)
        if result.chunk_id not in result_map:
            result_map[result.chunk_id] = result

    # Acumular scores de semántica
    for rank, result in enumerate(semantic_results):
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
    for chunk_id in ranked_ids:
        r = result_map[chunk_id]
        r.score = scores[chunk_id]
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
