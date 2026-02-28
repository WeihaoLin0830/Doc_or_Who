"""
searcher.py — Búsqueda híbrida con fusión BM25 + semántica (RRF).

Flujo:
1. Query → BM25 (Whoosh) → top K resultados léxicos
2. Query → embedding (ChromaDB) → top K resultados semánticos
3. Reciprocal Rank Fusion → lista final combinada
"""

from __future__ import annotations

import re
from typing import Optional

from backend.config import SEARCH_TOP_K, FINAL_TOP_K, RRF_K, WHOOSH_DIR
from backend.models import SearchResult


def hybrid_search(
    query: str,
    doc_type: Optional[str] = None,
    top_k: int = FINAL_TOP_K,
) -> list[SearchResult]:
    """
    Búsqueda híbrida: combina BM25 + semántica con RRF.
    Opcionalmente filtra por tipo de documento.
    """
    # 1. Búsqueda BM25 (léxica)
    bm25_results = _search_whoosh(query, doc_type=doc_type, top_k=SEARCH_TOP_K)

    # 2. Búsqueda semántica (embeddings)
    semantic_results = _search_chroma(query, doc_type=doc_type, top_k=SEARCH_TOP_K)

    # 3. Fusión con Reciprocal Rank Fusion
    fused = _reciprocal_rank_fusion(bm25_results, semantic_results, k=RRF_K)

    # 4. Añadir highlights
    for result in fused:
        result.highlight = _generate_highlight(result.text, query)

    return fused[:top_k]


# ─── BM25 con Whoosh ─────────────────────────────────────────────
def _search_whoosh(
    query: str,
    doc_type: Optional[str] = None,
    top_k: int = SEARCH_TOP_K,
) -> list[SearchResult]:
    """Búsqueda full-text con Whoosh (BM25)."""
    from whoosh import index as whoosh_index
    from whoosh.qparser import MultifieldParser, OrGroup

    if not whoosh_index.exists_in(str(WHOOSH_DIR)):
        return []

    ix = whoosh_index.open_dir(str(WHOOSH_DIR))

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

    results: list[SearchResult] = []

    with ix.searcher() as searcher:
        hits = searcher.search(parsed_query, limit=top_k)

        for hit in hits:
            # Filtrar por tipo si se especificó
            if doc_type and hit.get("doc_type", "") != doc_type:
                continue

            results.append(SearchResult(
                chunk_id=hit["chunk_id"],
                doc_id=hit["doc_id"],
                text=hit.get("content", ""),  # Whoosh no almacena content, usaremos chroma
                score=hit.score,
                title=hit.get("title", ""),
                doc_type=hit.get("doc_type", ""),
                filename=hit.get("filename", ""),
                section=hit.get("section", ""),
                persons=_split_meta(hit.get("persons", "")),
                organizations=_split_meta(hit.get("organizations", "")),
                keywords=_split_meta(hit.get("keywords", "")),
                dates=_split_meta(hit.get("dates", "")),
            ))

    return results


# ─── Semántica con ChromaDB ──────────────────────────────────────
def _search_chroma(
    query: str,
    doc_type: Optional[str] = None,
    top_k: int = SEARCH_TOP_K,
) -> list[SearchResult]:
    """Búsqueda semántica con ChromaDB (cosine similarity)."""
    from backend.indexer import _get_embedding_model, _get_chroma_collection

    model = _get_embedding_model()
    collection = _get_chroma_collection()

    query_embedding = model.encode(query).tolist()

    # Construir filtro de metadatos
    where = None
    if doc_type:
        where = {"doc_type": doc_type}

    try:
        chroma_results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
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
            persons=_split_meta(meta.get("persons", "")),
            organizations=_split_meta(meta.get("organizations", "")),
            keywords=_split_meta(meta.get("keywords", "")),
            dates=_split_meta(meta.get("dates", "")),
        ))

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
