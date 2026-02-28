from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.models import ChunkEntityRecord, ChunkRecord, DocumentRecord, EntityRecord
from backend.repositories import parse_date_to_epoch
from backend.schemas import FacetBucket, SearchFacets
from backend.types import SearchParams
from backend.utils import canonicalize


def _normalize_ext(ext: str | None) -> str | None:
    if not ext:
        return None
    return ext if ext.startswith(".") else f".{ext}"


def build_match_query(query: str) -> str:
    tokens = [token for token in canonicalize(query).split() if len(token) > 1]
    return " OR ".join(f"{token}*" for token in tokens)


def search_keyword_candidates(session: Session, params: SearchParams, limit: int = 50) -> list[dict[str, object]]:
    match_query = build_match_query(params.query)
    if not match_query:
        return []
    where_clauses = [
        "d.is_deleted = 0",
        "d.status IN ('processed', 'skipped')",
    ]
    query_params: dict[str, object] = {"match_query": match_query, "limit": limit}
    if params.ext:
        where_clauses.append("d.ext = :ext")
        query_params["ext"] = _normalize_ext(params.ext)
    if params.language:
        where_clauses.append("d.language = :language")
        query_params["language"] = params.language
    if params.date_from:
        epoch = parse_date_to_epoch(params.date_from)
        if epoch is not None:
            where_clauses.append("d.mtime_epoch >= :date_from_epoch")
            query_params["date_from_epoch"] = epoch
    if params.date_to:
        epoch = parse_date_to_epoch(params.date_to, end_of_day=True)
        if epoch is not None:
            where_clauses.append("d.mtime_epoch <= :date_to_epoch")
            query_params["date_to_epoch"] = epoch
    sql = text(
        f"""
        SELECT
            c.chunk_id AS chunk_id,
            bm25(chunks_fts) AS bm25_score,
            snippet(chunks_fts, 3, '<mark>', '</mark>', '...', 24) AS snippet
        FROM chunks_fts
        JOIN chunks c ON c.rowid = chunks_fts.rowid
        JOIN documents d ON d.doc_id = c.doc_id
        WHERE chunks_fts MATCH :match_query AND {' AND '.join(where_clauses)}
        ORDER BY bm25(chunks_fts)
        LIMIT :limit
        """
    )
    rows = session.execute(sql, query_params).mappings().all()
    return [dict(row) for row in rows]


def _filtered_document_ids(session: Session, params: SearchParams | dict[str, str | None]) -> set[str]:
    ext = params.ext if isinstance(params, SearchParams) else params.get("ext")
    language = params.language if isinstance(params, SearchParams) else params.get("language")
    date_from = params.date_from if isinstance(params, SearchParams) else params.get("date_from")
    date_to = params.date_to if isinstance(params, SearchParams) else params.get("date_to")
    entity = params.entity if isinstance(params, SearchParams) else params.get("entity")
    tag = params.tag if isinstance(params, SearchParams) else params.get("tag")

    query = select(DocumentRecord.doc_id).where(DocumentRecord.is_deleted == 0)
    if ext:
        query = query.where(DocumentRecord.ext == _normalize_ext(ext))
    if language:
        query = query.where(DocumentRecord.language == language)
    if date_from:
        epoch = parse_date_to_epoch(date_from)
        if epoch is not None:
            query = query.where(DocumentRecord.mtime_epoch >= epoch)
    if date_to:
        epoch = parse_date_to_epoch(date_to, end_of_day=True)
        if epoch is not None:
            query = query.where(DocumentRecord.mtime_epoch <= epoch)
    if entity or tag:
        query = query.join(ChunkRecord, ChunkRecord.doc_id == DocumentRecord.doc_id)
        query = query.join(ChunkEntityRecord, ChunkEntityRecord.chunk_id == ChunkRecord.chunk_id)
        query = query.join(EntityRecord, EntityRecord.entity_id == ChunkEntityRecord.entity_id)
        if entity:
            query = query.where(EntityRecord.canonical_text == canonicalize(entity))
        if tag:
            query = query.where(EntityRecord.type == "tag", EntityRecord.canonical_text == canonicalize(tag))
    return set(session.scalars(query.distinct()).all())


def fetch_facets(session: Session, params: SearchParams | dict[str, str | None]) -> SearchFacets:
    document_ids = _filtered_document_ids(session, params)
    return fetch_facets_for_document_ids(session, document_ids)


def fetch_facets_for_document_ids(session: Session, document_ids: set[str]) -> SearchFacets:
    if not document_ids:
        return SearchFacets()

    ext_rows = session.execute(
        select(DocumentRecord.ext, func.count()).where(DocumentRecord.doc_id.in_(document_ids)).group_by(DocumentRecord.ext)
    ).all()
    language_rows = session.execute(
        select(DocumentRecord.language, func.count())
        .where(DocumentRecord.doc_id.in_(document_ids))
        .group_by(DocumentRecord.language)
    ).all()
    status_rows = session.execute(
        select(DocumentRecord.status, func.count())
        .where(DocumentRecord.doc_id.in_(document_ids))
        .group_by(DocumentRecord.status)
    ).all()
    tag_rows = session.execute(
        select(EntityRecord.display_text, func.count(func.distinct(ChunkRecord.doc_id)))
        .join(ChunkEntityRecord, ChunkEntityRecord.entity_id == EntityRecord.entity_id)
        .join(ChunkRecord, ChunkRecord.chunk_id == ChunkEntityRecord.chunk_id)
        .where(ChunkRecord.doc_id.in_(document_ids), EntityRecord.type == "tag")
        .group_by(EntityRecord.display_text)
        .order_by(func.count(func.distinct(ChunkRecord.doc_id)).desc())
        .limit(10)
    ).all()

    entities_by_type: dict[str, list[FacetBucket]] = defaultdict(list)
    entity_rows = session.execute(
        select(EntityRecord.type, EntityRecord.display_text, func.count(func.distinct(ChunkRecord.doc_id)).label("doc_count"))
        .join(ChunkEntityRecord, ChunkEntityRecord.entity_id == EntityRecord.entity_id)
        .join(ChunkRecord, ChunkRecord.chunk_id == ChunkEntityRecord.chunk_id)
        .where(ChunkRecord.doc_id.in_(document_ids), EntityRecord.type != "tag")
        .group_by(EntityRecord.type, EntityRecord.display_text)
        .order_by(func.count(func.distinct(ChunkRecord.doc_id)).desc())
    ).all()
    per_type_count: dict[str, int] = defaultdict(int)
    for entity_type, display_text, doc_count in entity_rows:
        if per_type_count[entity_type] >= 10:
            continue
        entities_by_type[entity_type].append(FacetBucket(value=display_text, count=doc_count))
        per_type_count[entity_type] += 1

    return SearchFacets(
        ext=[FacetBucket(value=value or "unknown", count=count) for value, count in ext_rows],
        language=[FacetBucket(value=value or "unknown", count=count) for value, count in language_rows],
        status=[FacetBucket(value=value or "unknown", count=count) for value, count in status_rows],
        tags=[FacetBucket(value=value, count=count) for value, count in tag_rows],
        entities_by_type=dict(entities_by_type),
    )
