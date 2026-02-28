from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models import (
    ChunkEmbeddingRecord,
    ChunkEntityRecord,
    ChunkRecord,
    DocumentRecord,
    EdgeRecord,
    EntityRecord,
    PageRankScoreRecord,
)
from backend.types import ChunkPayload, ExtractedEntity
from backend.utils import canonicalize, guess_mime, json_dumps, json_loads, normalize_relative_path, sha256_file, stable_id, utcnow_text

SEARCHABLE_STATUSES = {"processed", "skipped"}


def document_id_for_path(path: Path) -> str:
    settings = get_settings()
    relative = normalize_relative_path(path, settings.root_dir)
    return stable_id("document", relative)


def chunk_id_for(doc_id: str, chunk: ChunkPayload) -> str:
    value = f"{doc_id}:{chunk.chunk_index}:{chunk.char_start}:{chunk.char_end}"
    return stable_id("chunk", value)


def entity_id_for(entity_type: str, canonical_text: str) -> str:
    return stable_id("entity", f"{entity_type}:{canonical_text}")


def edge_id_for(src_type: str, src_id: str, dst_type: str, dst_id: str, edge_type: str) -> str:
    return stable_id("edge", f"{src_type}:{src_id}:{dst_type}:{dst_id}:{edge_type}")


def scan_file_metadata(path: Path, source_type: str, filename_override: str | None = None) -> dict[str, Any]:
    stat = path.stat()
    return {
        "doc_id": document_id_for_path(path),
        "path": str(path.resolve()),
        "filename": filename_override or path.name,
        "ext": path.suffix.lower(),
        "mime": guess_mime(path),
        "size_bytes": stat.st_size,
        "mtime_epoch": stat.st_mtime,
        "sha256": sha256_file(path),
        "source_type": source_type,
        "status": "discovered",
        "error": None,
        "metadata_json": "{}",
        "is_deleted": 0,
    }


def upsert_scanned_document(session: Session, payload: dict[str, Any]) -> tuple[DocumentRecord, bool]:
    document = session.get(DocumentRecord, payload["doc_id"])
    changed = True
    if document is None:
        document = DocumentRecord(
            doc_id=payload["doc_id"],
            path=payload["path"],
            filename=payload["filename"],
            ext=payload["ext"],
            mime=payload["mime"],
            size_bytes=payload["size_bytes"],
            mtime_epoch=payload["mtime_epoch"],
            sha256=payload["sha256"],
            source_type=payload["source_type"],
            status=payload["status"],
            error=payload["error"],
            metadata_json=payload["metadata_json"],
            is_deleted=payload["is_deleted"],
            created_at=utcnow_text(),
            updated_at=utcnow_text(),
        )
        session.add(document)
    else:
        changed = not (
            document.sha256 == payload["sha256"]
            and document.mtime_epoch == payload["mtime_epoch"]
            and document.is_deleted == 0
        )
        document.path = payload["path"]
        document.filename = payload["filename"]
        document.ext = payload["ext"]
        document.mime = payload["mime"]
        document.size_bytes = payload["size_bytes"]
        document.mtime_epoch = payload["mtime_epoch"]
        document.sha256 = payload["sha256"]
        document.source_type = payload["source_type"]
        document.is_deleted = 0
        document.updated_at = utcnow_text()
    session.flush()
    return document, changed


def mark_document_status(
    session: Session,
    doc_id: str,
    *,
    status: str,
    error: str | None = None,
    title: str | None = None,
    author: str | None = None,
    language: str | None = None,
    metadata: dict[str, object] | None = None,
    is_deleted: int | None = None,
) -> DocumentRecord:
    document = session.get(DocumentRecord, doc_id)
    if document is None:
        raise ValueError(f"Unknown document id: {doc_id}")
    document.status = status
    document.error = error
    if title is not None:
        document.title = title
    if author is not None:
        document.author = author
    if language is not None:
        document.language = language
    if metadata is not None:
        document.metadata_json = json_dumps(metadata)
    if is_deleted is not None:
        document.is_deleted = is_deleted
    document.updated_at = utcnow_text()
    session.flush()
    return document


def delete_document_artifacts(session: Session, doc_id: str) -> None:
    session.execute(delete(ChunkRecord).where(ChunkRecord.doc_id == doc_id))
    session.flush()


def persist_document_chunks(
    session: Session,
    document: DocumentRecord,
    chunks: list[ChunkPayload],
    chunk_entities: dict[int, list[ExtractedEntity]],
    vectors: np.ndarray,
    provider_name: str,
    model_name: str,
) -> None:
    delete_document_artifacts(session, document.doc_id)
    entity_cache: dict[tuple[str, str], EntityRecord] = {}

    for chunk_payload, vector in zip(chunks, vectors, strict=True):
        chunk_id = chunk_id_for(document.doc_id, chunk_payload)
        entities_for_chunk = chunk_entities.get(chunk_payload.chunk_index, [])
        entity_texts = sorted({entity.display_text for entity in entities_for_chunk if entity.type != "tag"})
        tag_texts = sorted({entity.display_text for entity in entities_for_chunk if entity.type == "tag"})
        chunk_record = ChunkRecord(
            chunk_id=chunk_id,
            doc_id=document.doc_id,
            chunk_index=chunk_payload.chunk_index,
            text=chunk_payload.text,
            token_count=chunk_payload.token_count,
            char_start=chunk_payload.char_start,
            char_end=chunk_payload.char_end,
            section_title=chunk_payload.section_title,
            entity_texts=", ".join(entity_texts),
            tag_texts=", ".join(tag_texts),
            bm25_indexed=1,
            created_at=utcnow_text(),
            updated_at=utcnow_text(),
        )
        session.add(chunk_record)
        session.flush()
        session.add(
            ChunkEmbeddingRecord(
                chunk_id=chunk_id,
                provider=provider_name,
                model_name=model_name,
                dim=int(vector.shape[0]),
                vector_blob=np.asarray(vector, dtype=np.float32).tobytes(),
                created_at=utcnow_text(),
            )
        )

        for entity in entities_for_chunk:
            key = (entity.type, entity.canonical_text)
            entity_record = entity_cache.get(key)
            if entity_record is None:
                entity_record = session.scalar(
                    select(EntityRecord).where(
                        and_(EntityRecord.type == entity.type, EntityRecord.canonical_text == entity.canonical_text)
                    )
                )
                if entity_record is None:
                    entity_record = EntityRecord(
                        entity_id=entity_id_for(entity.type, entity.canonical_text),
                        canonical_text=entity.canonical_text,
                        display_text=entity.display_text,
                        type=entity.type,
                        importance_score=entity.importance_score,
                    )
                    session.add(entity_record)
                    session.flush()
                else:
                    entity_record.display_text = entity.display_text
                    entity_record.importance_score = max(entity_record.importance_score, entity.importance_score)
                entity_cache[key] = entity_record
            session.add(
                ChunkEntityRecord(
                    chunk_id=chunk_id,
                    entity_id=entity_record.entity_id,
                    confidence=entity.confidence,
                )
            )
    document.updated_at = utcnow_text()
    session.flush()


def mark_missing_documents_deleted(session: Session, source_type: str, seen_paths: set[str]) -> list[str]:
    documents = session.scalars(
        select(DocumentRecord).where(DocumentRecord.source_type == source_type, DocumentRecord.is_deleted == 0)
    ).all()
    deleted_ids: list[str] = []
    for document in documents:
        if document.path not in seen_paths:
            delete_document_artifacts(session, document.doc_id)
            document.is_deleted = 1
            document.status = "deleted"
            document.updated_at = utcnow_text()
            deleted_ids.append(document.doc_id)
    session.flush()
    return deleted_ids


def iter_active_chunk_embeddings(session: Session) -> list[tuple[str, str, np.ndarray]]:
    rows = session.execute(
        select(ChunkEmbeddingRecord.chunk_id, ChunkRecord.doc_id, ChunkEmbeddingRecord.vector_blob)
        .join(ChunkRecord, ChunkEmbeddingRecord.chunk_id == ChunkRecord.chunk_id)
        .join(DocumentRecord, DocumentRecord.doc_id == ChunkRecord.doc_id)
        .where(DocumentRecord.is_deleted == 0, DocumentRecord.status.in_(SEARCHABLE_STATUSES))
        .order_by(ChunkRecord.doc_id, ChunkRecord.chunk_index)
    ).all()
    return [
        (chunk_id, doc_id, np.frombuffer(vector_blob, dtype=np.float32))
        for chunk_id, doc_id, vector_blob in rows
    ]


def get_document_detail(session: Session, doc_id: str) -> dict[str, Any] | None:
    document = session.get(DocumentRecord, doc_id)
    if document is None:
        return None
    chunks = session.scalars(
        select(ChunkRecord).where(ChunkRecord.doc_id == doc_id).order_by(ChunkRecord.chunk_index)
    ).all()
    return {
        "document": document,
        "chunks": chunks,
    }


def list_documents(session: Session) -> list[DocumentRecord]:
    return session.scalars(
        select(DocumentRecord).where(DocumentRecord.is_deleted == 0).order_by(DocumentRecord.updated_at.desc())
    ).all()


def fetch_chunk_payloads(session: Session, chunk_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    chunk_ids = list(chunk_ids)
    if not chunk_ids:
        return {}
    rows = session.execute(
        select(ChunkRecord, DocumentRecord)
        .join(DocumentRecord, ChunkRecord.doc_id == DocumentRecord.doc_id)
        .where(ChunkRecord.chunk_id.in_(chunk_ids))
    ).all()
    entity_rows = session.execute(
        select(ChunkEntityRecord.chunk_id, EntityRecord.display_text, EntityRecord.canonical_text, EntityRecord.type, ChunkEntityRecord.confidence)
        .join(EntityRecord, EntityRecord.entity_id == ChunkEntityRecord.entity_id)
        .where(ChunkEntityRecord.chunk_id.in_(chunk_ids))
    ).all()
    entities_by_chunk: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk_id, display_text, canonical_text, entity_type, confidence in entity_rows:
        entities_by_chunk[chunk_id].append(
            {
                "display_text": display_text,
                "canonical_text": canonical_text,
                "type": entity_type,
                "confidence": confidence,
            }
        )
    payloads: dict[str, dict[str, Any]] = {}
    for chunk, document in rows:
        payloads[chunk.chunk_id] = {
            "chunk_id": chunk.chunk_id,
            "doc_id": document.doc_id,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "section_title": chunk.section_title,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "entity_texts": chunk.entity_texts,
            "tag_texts": chunk.tag_texts,
            "document": document,
            "entities": entities_by_chunk.get(chunk.chunk_id, []),
        }
    return payloads


def filtered_chunk_ids(session: Session, chunk_ids: list[str], filters: dict[str, str | None]) -> set[str]:
    if not chunk_ids:
        return set()
    query = (
        select(ChunkRecord.chunk_id)
        .join(DocumentRecord, ChunkRecord.doc_id == DocumentRecord.doc_id)
        .where(ChunkRecord.chunk_id.in_(chunk_ids), DocumentRecord.is_deleted == 0, DocumentRecord.status.in_(SEARCHABLE_STATUSES))
    )
    if filters.get("ext"):
        query = query.where(DocumentRecord.ext == filters["ext"])
    if filters.get("language"):
        query = query.where(DocumentRecord.language == filters["language"])
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    if date_from:
        from_dt = parse_date_to_epoch(date_from)
        if from_dt is not None:
            query = query.where(DocumentRecord.mtime_epoch >= from_dt)
    if date_to:
        to_dt = parse_date_to_epoch(date_to, end_of_day=True)
        if to_dt is not None:
            query = query.where(DocumentRecord.mtime_epoch <= to_dt)
    if filters.get("entity"):
        query = query.join(ChunkEntityRecord, ChunkEntityRecord.chunk_id == ChunkRecord.chunk_id).join(
            EntityRecord, EntityRecord.entity_id == ChunkEntityRecord.entity_id
        ).where(EntityRecord.canonical_text == canonicalize(filters["entity"] or ""))
    if filters.get("tag"):
        query = query.join(ChunkEntityRecord, ChunkEntityRecord.chunk_id == ChunkRecord.chunk_id).join(
            EntityRecord, EntityRecord.entity_id == ChunkEntityRecord.entity_id
        ).where(EntityRecord.type == "tag", EntityRecord.canonical_text == canonicalize(filters["tag"] or ""))
    return set(session.scalars(query).all())


def parse_date_to_epoch(value: str, end_of_day: bool = False) -> float | None:
    from backend.utils import parse_date_string

    parsed = parse_date_string(value)
    if parsed is None:
        return None
    if end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed.timestamp()


def clear_edges_and_pagerank(session: Session) -> None:
    session.execute(delete(EdgeRecord))
    session.execute(delete(PageRankScoreRecord))
    session.flush()


def persist_edges(session: Session, edges: list[dict[str, Any]]) -> None:
    session.execute(delete(EdgeRecord))
    for edge in edges:
        session.add(EdgeRecord(**edge))
    session.flush()


def persist_pagerank(session: Session, pagerank_rows: list[dict[str, Any]]) -> None:
    session.execute(delete(PageRankScoreRecord))
    for row in pagerank_rows:
        session.add(PageRankScoreRecord(**row))
    session.flush()


def max_pagerank(session: Session, node_type: str = "chunk") -> float:
    value = session.scalar(select(func.max(PageRankScoreRecord.pagerank)).where(PageRankScoreRecord.node_type == node_type))
    return float(value or 0.0)


def get_status_counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(DocumentRecord.status, func.count()).where(DocumentRecord.is_deleted == 0).group_by(DocumentRecord.status)
    ).all()
    return {status: count for status, count in rows}


def metadata_for_document(document: DocumentRecord) -> dict[str, object]:
    payload = json_loads(document.metadata_json)
    payload.setdefault("path", document.path)
    payload.setdefault("filename", document.filename)
    payload.setdefault("ext", document.ext)
    payload.setdefault("mime", document.mime)
    return payload
