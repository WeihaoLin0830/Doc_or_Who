from __future__ import annotations

import time
from pathlib import Path

from backend.chunker import Chunker
from backend.cleaning import clean_text, detect_language
from backend.config import get_settings
from backend.db import bootstrap_database, session_scope
from backend.embeddings import get_embedding_provider
from backend.enrichment import EntityExtractor, infer_title
from backend.graph import GraphBuilder
from backend.indexer import rebuild_vector_index
from backend.logging import get_logger, log_event
from backend.parsers import SUPPORTED_EXTENSIONS, parse_file
from backend.pagerank import run_pagerank
from backend.repositories import (
    SEARCHABLE_STATUSES,
    mark_document_status,
    mark_missing_documents_deleted,
    metadata_for_document,
    persist_document_chunks,
    scan_file_metadata,
    upsert_scanned_document,
)
from backend.types import IngestStats

LOGGER = get_logger(__name__)


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir() or path.is_symlink():
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return files


class IngestService:
    def __init__(self) -> None:
        self.chunker = Chunker()
        self.entity_extractor = EntityExtractor()

    def ingest_directory(
        self,
        source_dir: Path,
        *,
        source_type: str = "dataset",
        rebuild_graph: bool = True,
        recompute_pagerank: bool = True,
        mark_missing: bool = True,
        filename_overrides: dict[str, str] | None = None,
    ) -> tuple[IngestStats, float]:
        bootstrap_database()
        started = time.time()
        settings = get_settings()
        files = _iter_files(source_dir)
        stats = IngestStats(total_seen=len(files))
        seen_paths: set[str] = set()

        for path in files:
            payload = scan_file_metadata(path, source_type, filename_override=(filename_overrides or {}).get(str(path.resolve())))
            seen_paths.add(payload["path"])
            with session_scope() as session:
                document, changed = upsert_scanned_document(session, payload)
                unchanged_searchable = not changed and document.status in SEARCHABLE_STATUSES
                if unchanged_searchable:
                    mark_document_status(session, document.doc_id, status="skipped", metadata=metadata_for_document(document))
                    stats.skipped += 1
                    continue
                if not changed and document.status in {"needs_ocr", "unsupported", "failed"}:
                    stats.skipped += 1
                    continue
                if payload["size_bytes"] > settings.file_size_limit_bytes:
                    mark_document_status(
                        session,
                        document.doc_id,
                        status="failed",
                        error="file exceeds size limit",
                        metadata={"path": payload["path"], "filename": payload["filename"], "size_bytes": payload["size_bytes"]},
                    )
                    stats.failed += 1
                    stats.changed = True
                    continue
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    mark_document_status(
                        session,
                        document.doc_id,
                        status="unsupported",
                        metadata={"path": payload["path"], "filename": payload["filename"], "ext": payload["ext"]},
                    )
                    stats.unsupported += 1
                    stats.changed = True
                    continue
                mark_document_status(session, document.doc_id, status="processing", metadata=metadata_for_document(document))

            try:
                self._process_document(path, payload["doc_id"])
                stats.processed += 1
                stats.changed = True
            except NeedsOcrSignal:
                stats.needs_ocr += 1
                stats.changed = True
            except Exception as exc:
                with session_scope() as session:
                    mark_document_status(
                        session,
                        payload["doc_id"],
                        status="failed",
                        error=str(exc)[:500],
                        metadata={"path": payload["path"], "filename": payload["filename"], "stage": "processing"},
                    )
                log_event(LOGGER, "ingest_failed", "Document processing failed", path=str(path), error=str(exc))
                stats.failed += 1

        if mark_missing:
            with session_scope() as session:
                deleted_ids = mark_missing_documents_deleted(session, source_type, seen_paths)
            stats.deleted += len(deleted_ids)
            stats.changed = stats.changed or bool(deleted_ids)

        if stats.changed:
            rebuild_vector_index()
            if rebuild_graph:
                GraphBuilder().rebuild()
            if recompute_pagerank:
                run_pagerank()

        duration = time.time() - started
        log_event(
            LOGGER,
            "ingest_complete",
            "Ingestion completed",
            source_dir=str(source_dir),
            processed=stats.processed,
            skipped=stats.skipped,
            failed=stats.failed,
            needs_ocr=stats.needs_ocr,
            deleted=stats.deleted,
            unsupported=stats.unsupported,
            duration_seconds=round(duration, 3),
        )
        return stats, duration

    def ingest_file(self, path: Path, *, source_type: str = "upload") -> tuple[IngestStats, float]:
        return self.ingest_directory(path.parent, source_type=source_type, rebuild_graph=True, recompute_pagerank=True, mark_missing=False)

    def _process_document(self, path: Path, doc_id: str) -> None:
        extraction = parse_file(path)
        cleaned_text = clean_text(extraction.text)
        metadata = dict(extraction.metadata)
        metadata["path"] = str(path.resolve())
        metadata["needs_ocr"] = extraction.needs_ocr
        if extraction.needs_ocr:
            with session_scope() as session:
                mark_document_status(session, doc_id, status="needs_ocr", metadata=metadata)
            raise NeedsOcrSignal()
        if not cleaned_text.strip():
            raise ValueError("no extractable text")
        language = detect_language(cleaned_text)
        title = infer_title(cleaned_text, path.name, metadata)
        author = str(metadata.get("author") or "").strip() or None
        chunks = self.chunker.chunk(doc_id, cleaned_text, extraction=extraction)
        if not chunks:
            raise ValueError("chunking produced no content")
        provider = get_embedding_provider()
        vectors = provider.embed([chunk.text for chunk in chunks])
        chunk_entities = {
            chunk.chunk_index: self.entity_extractor.extract(chunk.text, language)
            for chunk in chunks
        }
        with session_scope() as session:
            document = mark_document_status(
                session,
                doc_id,
                status="processing",
                title=title,
                author=author,
                language=language,
                metadata={**metadata, "chunk_count": len(chunks)},
            )
            persist_document_chunks(session, document, chunks, chunk_entities, vectors, provider.name, provider.model_name)
            mark_document_status(
                session,
                doc_id,
                status="processed",
                title=title,
                author=author,
                language=language,
                metadata={**metadata, "chunk_count": len(chunks)},
            )


class NeedsOcrSignal(Exception):
    pass


def run_ingest(source_dir: Path | None = None, rebuild_graph: bool = True, recompute_pagerank: bool = True) -> tuple[IngestStats, float]:
    settings = get_settings()
    service = IngestService()
    return service.ingest_directory(source_dir or settings.dataset_dir, rebuild_graph=rebuild_graph, recompute_pagerank=recompute_pagerank)
