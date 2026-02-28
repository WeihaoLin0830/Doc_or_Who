from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
import hashlib
from pathlib import Path

from fastapi import APIRouter, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings
from backend.db import bootstrap_database, session_scope
from backend.fts import fetch_facets
from backend.graph import get_doc_graph, get_entity_graph, get_overview_graph
from backend.ingest import IngestService, run_ingest
from backend.repositories import get_document_detail, list_documents, metadata_for_document
from backend.schemas import (
    DocumentDetailResponse,
    DocumentsListResponse,
    DocumentSummary,
    HealthResponse,
    IngestRequest,
    IngestResponse,
)
from backend.searcher import SearchService
from backend.types import SearchParams
from backend.utils import safe_filename
from backend.vector import get_vector_index

service = IngestService()
search_service = SearchService()

@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap_database()
    get_settings().ensure_directories()
    yield


app = FastAPI(title="DocumentWho", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/ingest", response_model=IngestResponse)
    def ingest(request: IngestRequest | None = None) -> IngestResponse:
        request = request or IngestRequest()
        settings = get_settings()
        source_dir = Path(request.source_dir).resolve() if request.source_dir else settings.dataset_dir
        stats, duration = run_ingest(source_dir, rebuild_graph=request.rebuild_graph, recompute_pagerank=request.recompute_pagerank)
        payload = asdict(stats)
        payload.pop("changed", None)
        return IngestResponse(source_dir=str(source_dir), duration_seconds=duration, **payload)

    @router.post("/upload")
    async def upload(file: UploadFile = File(...)) -> dict[str, object]:
        settings = get_settings()
        content = await file.read()
        if len(content) > settings.file_size_limit_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file exceeds size limit")
        digest = hashlib.sha256(content).hexdigest()[:12]
        safe_name = safe_filename(file.filename or "upload")
        destination = settings.upload_dir / f"{digest}_{safe_name}"
        destination.write_bytes(content)
        stats, duration = service.ingest_directory(
            settings.upload_dir,
            source_type="upload",
            rebuild_graph=True,
            recompute_pagerank=True,
            mark_missing=False,
            filename_overrides={str(destination.resolve()): safe_name},
        )
        return {
            "filename": safe_name,
            "stored_path": str(destination),
            "processed": stats.processed,
            "failed": stats.failed,
            "needs_ocr": stats.needs_ocr,
            "duration_seconds": duration,
        }

    @router.get("/search")
    def search(
        q: str = Query(""),
        ext: str | None = None,
        language: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        entity: str | None = None,
        tag: str | None = None,
        top_k: int = Query(10, ge=1, le=50),
        debug: bool = False,
    ):
        params = SearchParams(
            query=q,
            ext=ext,
            language=language,
            date_from=date_from,
            date_to=date_to,
            entity=entity,
            tag=tag,
            top_k=top_k,
            debug=debug,
        )
        return search_service.search(params)

    @router.get("/facets")
    def facets(
        q: str = Query(""),
        ext: str | None = None,
        language: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        entity: str | None = None,
        tag: str | None = None,
    ):
        if q.strip():
            params = SearchParams(
                query=q,
                ext=ext,
                language=language,
                date_from=date_from,
                date_to=date_to,
                entity=entity,
                tag=tag,
                top_k=50,
                debug=False,
            )
            return search_service.search(params).facets
        with session_scope() as session:
            return fetch_facets(
                session,
                {
                    "ext": ext,
                    "language": language,
                    "date_from": date_from,
                    "date_to": date_to,
                    "entity": entity,
                    "tag": tag,
                },
            )

    @router.get("/documents", response_model=DocumentsListResponse)
    def documents() -> DocumentsListResponse:
        with session_scope() as session:
            docs = list_documents(session)
            return DocumentsListResponse(
                count=len(docs),
                documents=[
                    DocumentSummary(
                        doc_id=document.doc_id,
                        filename=document.filename,
                        title=document.title,
                        ext=document.ext,
                        status=document.status,
                        updated_at=document.updated_at,
                    )
                    for document in docs
                ],
            )

    @router.get("/documents/{doc_id}", response_model=DocumentDetailResponse)
    def document_detail(doc_id: str) -> DocumentDetailResponse:
        with session_scope() as session:
            payload = get_document_detail(session, doc_id)
            if payload is None:
                raise HTTPException(status_code=404, detail="Document not found")
            document = payload["document"]
            return DocumentDetailResponse(
                doc_id=document.doc_id,
                filename=document.filename,
                title=document.title,
                ext=document.ext,
                mime=document.mime,
                language=document.language,
                status=document.status,
                error=document.error,
                author=document.author,
                metadata=metadata_for_document(document),
                chunks=[
                    {
                        "chunk_id": chunk.chunk_id,
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                        "token_count": chunk.token_count,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "section_title": chunk.section_title,
                        "entity_texts": chunk.entity_texts,
                        "tag_texts": chunk.tag_texts,
                    }
                    for chunk in payload["chunks"]
                ],
            )

    @router.get("/graph")
    def overview_graph():
        return get_overview_graph()

    @router.get("/graph/doc/{doc_id}")
    def graph_doc(doc_id: str):
        graph = get_doc_graph(doc_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="Document graph not found")
        return graph

    @router.get("/graph/entity/{entity_id}")
    def graph_entity(entity_id: str):
        graph = get_entity_graph(entity_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="Entity graph not found")
        return graph

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", database_ready=True, vector_ready=get_vector_index().is_ready())

    return router


api_router = build_router()
app.include_router(api_router)
app.include_router(api_router, prefix="/api")

frontend_dir = get_settings().root_dir / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/")
def root() -> FileResponse:
    index_path = frontend_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)
