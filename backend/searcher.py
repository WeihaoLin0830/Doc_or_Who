from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import desc, select

from backend.config import get_settings
from backend.db import session_scope
from backend.embeddings import get_embedding_provider
from backend.enrichment import EntityExtractor
from backend.fts import fetch_facets, fetch_facets_for_document_ids, search_keyword_candidates
from backend.models import ChunkRecord, DocumentRecord, PageRankScoreRecord
from backend.pagerank import normalize_pagerank
from backend.repositories import fetch_chunk_payloads, filtered_chunk_ids, max_pagerank
from backend.schemas import ChunkSnippet, DocumentSearchResult, SearchResponse
from backend.types import SearchParams
from backend.vector import get_vector_index


def _generate_highlight(text: str, query: str, context_chars: int = 220) -> str:
    lower_text = text.lower()
    terms = [token for token in re.findall(r"\b[\w-]{2,}\b", query.lower()) if len(token) > 1]
    if not terms:
        return text[:context_chars]
    position = min((lower_text.find(term) for term in terms if lower_text.find(term) >= 0), default=0)
    start = max(0, position - context_chars // 3)
    end = min(len(text), start + context_chars)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    for term in terms:
        snippet = re.sub(rf"(?i)\b({re.escape(term)})\b", r"<mark>\1</mark>", snippet)
    return snippet


def _min_max(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    minimum = min(scores.values())
    maximum = max(scores.values())
    if maximum == minimum:
        return {key: 1.0 for key in scores}
    return {key: (value - minimum) / (maximum - minimum) for key, value in scores.items()}


def combine_weighted_score(keyword_score: float, semantic_score: float, pagerank_score: float) -> float:
    settings = get_settings()
    return (
        settings.keyword_weight * keyword_score
        + settings.semantic_weight * semantic_score
        + settings.pagerank_weight * pagerank_score
    )


class SearchService:
    def __init__(self) -> None:
        self.entity_extractor = EntityExtractor()

    def search(self, params: SearchParams) -> SearchResponse:
        settings = get_settings()
        ext = params.ext if not params.ext or params.ext.startswith(".") else f".{params.ext}"
        query = params.query.strip()
        params = SearchParams(
            query=query,
            ext=ext,
            language=params.language,
            date_from=params.date_from,
            date_to=params.date_to,
            entity=params.entity,
            tag=params.tag,
            top_k=params.top_k,
            debug=params.debug,
        )
        with session_scope() as session:
            keyword_candidates: list[dict[str, object]] = []
            vector_hits = []
            if params.query:
                keyword_candidates = search_keyword_candidates(session, params, limit=settings.search_top_k * 5)
                if params.entity or params.tag:
                    allowed_ids = filtered_chunk_ids(
                        session,
                        [candidate["chunk_id"] for candidate in keyword_candidates],
                        {
                            "ext": params.ext,
                            "language": params.language,
                            "date_from": params.date_from,
                            "date_to": params.date_to,
                            "entity": params.entity,
                            "tag": params.tag,
                        },
                    )
                    keyword_candidates = [candidate for candidate in keyword_candidates if candidate["chunk_id"] in allowed_ids]

                provider = get_embedding_provider()
                query_vector = provider.embed([params.query])[0]
                vector_hits = get_vector_index().search(
                    query_vector,
                    top_k=settings.search_top_k,
                    overfetch=settings.search_top_k * settings.semantic_overfetch_multiplier,
                )
                vector_ids = [hit.chunk_id for hit in vector_hits]
                allowed_vector_ids = filtered_chunk_ids(
                    session,
                    vector_ids,
                    {
                        "ext": params.ext,
                        "language": params.language,
                        "date_from": params.date_from,
                        "date_to": params.date_to,
                        "entity": params.entity,
                        "tag": params.tag,
                    },
                )
                vector_hits = [hit for hit in vector_hits if hit.chunk_id in allowed_vector_ids][: settings.search_top_k]

            candidate_ids = {candidate["chunk_id"] for candidate in keyword_candidates} | {hit.chunk_id for hit in vector_hits}
            if not params.query:
                browse_query = (
                    select(PageRankScoreRecord.node_id)
                    .where(PageRankScoreRecord.node_type == "chunk")
                    .order_by(desc(PageRankScoreRecord.pagerank))
                )
                pagerank_order = session.scalars(browse_query).all()
                if pagerank_order:
                    candidate_ids = set(
                        filtered_chunk_ids(
                            session,
                            pagerank_order[: settings.search_top_k * 10],
                            {
                                "ext": params.ext,
                                "language": params.language,
                                "date_from": params.date_from,
                                "date_to": params.date_to,
                                "entity": params.entity,
                                "tag": params.tag,
                            },
                        )
                    )
                if not candidate_ids:
                    fallback_chunk_ids = session.scalars(
                        select(ChunkRecord.chunk_id)
                        .join(DocumentRecord, DocumentRecord.doc_id == ChunkRecord.doc_id)
                        .where(DocumentRecord.is_deleted == 0, DocumentRecord.status.in_(("processed", "skipped")))
                        .order_by(DocumentRecord.updated_at.desc(), ChunkRecord.chunk_index)
                        .limit(settings.search_top_k * 10)
                    ).all()
                    candidate_ids = set(
                        filtered_chunk_ids(
                            session,
                            list(fallback_chunk_ids),
                            {
                                "ext": params.ext,
                                "language": params.language,
                                "date_from": params.date_from,
                                "date_to": params.date_to,
                                "entity": params.entity,
                                "tag": params.tag,
                            },
                        )
                    )
            payloads = fetch_chunk_payloads(session, candidate_ids)
            pagerank_rows = session.execute(
                select(PageRankScoreRecord.node_id, PageRankScoreRecord.pagerank).where(
                    PageRankScoreRecord.node_type == "chunk", PageRankScoreRecord.node_id.in_(candidate_ids)
                )
            ).all()
            pagerank_map = {node_id: score for node_id, score in pagerank_rows}
            pagerank_max = max_pagerank(session, "chunk")

            keyword_raw = {candidate["chunk_id"]: float(-float(candidate["bm25_score"])) for candidate in keyword_candidates}
            keyword_normalized = _min_max(keyword_raw)
            semantic_normalized = {
                hit.chunk_id: max(0.0, min(1.0, (hit.similarity + 1.0) / 2.0))
                for hit in vector_hits
            }
            keyword_map = {candidate["chunk_id"]: candidate for candidate in keyword_candidates}
            semantic_map = {hit.chunk_id: hit for hit in vector_hits}
            query_terms = set(re.findall(r"\b[\w-]{2,}\b", params.query.lower()))
            query_entities = {
                entity.canonical_text: entity.display_text
                for entity in self.entity_extractor.extract(params.query, params.language or "unknown")
            } if params.query else {}

            grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
            for chunk_id, payload in payloads.items():
                document = payload["document"]
                keyword_score = keyword_normalized.get(chunk_id, 0.0)
                semantic_score = semantic_normalized.get(chunk_id, 0.0)
                pagerank_score = normalize_pagerank(pagerank_map.get(chunk_id, 0.0), pagerank_max)
                final_score = combine_weighted_score(keyword_score, semantic_score, pagerank_score)
                highlight = str(keyword_map.get(chunk_id, {}).get("snippet") or _generate_highlight(payload["text"], params.query))
                chunk_entities = payload["entities"]
                matched_terms = sorted(query_terms.intersection({term.lower() for term in re.findall(r"\b[\w-]{2,}\b", payload["text"]) }))
                matched_entities = sorted(
                    {
                        entity["display_text"]
                        for entity in chunk_entities
                        if entity["canonical_text"] in query_entities
                    }
                )
                retrieval_modes: list[str] = []
                if chunk_id in keyword_map:
                    retrieval_modes.append("keyword")
                if chunk_id in semantic_map:
                    retrieval_modes.append("semantic")
                grouped[payload["doc_id"]].append(
                    {
                        "chunk_id": chunk_id,
                        "document": document,
                        "text": payload["text"],
                        "section_title": payload["section_title"],
                        "highlight": highlight,
                        "char_start": payload["char_start"],
                        "char_end": payload["char_end"],
                        "keyword_score": keyword_score,
                        "semantic_score": semantic_score,
                        "pagerank_score": pagerank_score,
                        "score": final_score,
                        "matched_terms": matched_terms,
                        "matched_entities": matched_entities,
                        "retrieval_modes": retrieval_modes,
                    }
                )

            document_results: list[DocumentSearchResult] = []
            for doc_id, chunk_rows in grouped.items():
                chunk_rows.sort(key=lambda row: float(row["score"]), reverse=True)
                best = chunk_rows[0]
                document = best["document"]
                snippets = [
                    ChunkSnippet(
                        chunk_id=row["chunk_id"],
                        section_title=row["section_title"],
                        text=row["text"],
                        highlight=row["highlight"],
                        keyword_score=float(row["keyword_score"]),
                        semantic_score=float(row["semantic_score"]),
                        pagerank_score=float(row["pagerank_score"]),
                        score=float(row["score"]),
                        char_start=int(row["char_start"]),
                        char_end=int(row["char_end"]),
                    )
                    for row in chunk_rows[:3]
                ]
                document_results.append(
                    DocumentSearchResult(
                        doc_id=doc_id,
                        filename=document.filename,
                        title=document.title,
                        ext=document.ext,
                        language=document.language,
                        status=document.status,
                        score=float(best["score"]),
                        best_chunk_id=str(best["chunk_id"]),
                        matched_terms=list(best["matched_terms"]),
                        matched_entities=list(best["matched_entities"]),
                        keyword_score=float(best["keyword_score"]),
                        semantic_score=float(best["semantic_score"]),
                        pagerank_score=float(best["pagerank_score"]),
                        ranking_breakdown={
                            "keyword": float(best["keyword_score"]),
                            "semantic": float(best["semantic_score"]),
                            "pagerank": float(best["pagerank_score"]),
                            "final": float(best["score"]),
                        },
                        retrieval_modes=list(best["retrieval_modes"]),
                        why_this_result=_explain(best),
                        snippets=snippets,
                    )
                )
            document_results.sort(key=lambda result: result.score, reverse=True)
            facet_document_ids = {result.doc_id for result in document_results}
            facets = fetch_facets_for_document_ids(session, facet_document_ids) if facet_document_ids else fetch_facets(session, params)
            debug = None
            if params.debug:
                debug = {
                    "keyword_candidates": len(keyword_candidates),
                    "semantic_candidates": len(vector_hits),
                    "merged_candidates": len(candidate_ids),
                    "weights": {
                        "keyword": settings.keyword_weight,
                        "semantic": settings.semantic_weight,
                        "pagerank": settings.pagerank_weight,
                    },
                }
            return SearchResponse(
                query=params.query,
                filters={
                    "ext": params.ext,
                    "language": params.language,
                    "date_from": params.date_from,
                    "date_to": params.date_to,
                    "entity": params.entity,
                    "tag": params.tag,
                },
                results=document_results[: params.top_k],
                facets=facets,
                debug=debug,
            )


def _explain(row: dict[str, object]) -> str:
    matched_terms = ", ".join(row["matched_terms"]) if row["matched_terms"] else "no exact terms"
    matched_entities = ", ".join(row["matched_entities"]) if row["matched_entities"] else "no entity overlap"
    return (
        f"Matched terms: {matched_terms}; semantic score {float(row['semantic_score']):.2f}; "
        f"PageRank contribution {float(row['pagerank_score']):.2f}; entities: {matched_entities}."
    )
