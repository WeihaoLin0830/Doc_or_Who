"""
api.py — API REST con FastAPI.

Endpoints:
  GET  /api/search?q=...&type=...&top_k=10   → Búsqueda híbrida
  POST /api/ask                               → Pregunta al LLM (RAG)
  GET  /api/documents                         → Lista de documentos indexados
  GET  /api/documents/{doc_id}                → Detalle de un documento
  POST /api/documents/{doc_id}/summary        → Resumen LLM de documento
  GET  /api/graph                             → Grafo de entidades (vis-network)
  GET  /api/graph/entities                    → Lista de entidades
  GET  /api/graph/entity/{name}               → Detalle + relaciones de entidad
  GET  /api/stats                             → Estadísticas del dashboard
  GET  /api/sql/tables                        → Tablas SQL disponibles
  POST /api/sql/query                         → Ejecutar consulta SQL
  POST /api/sql/ask                           → Pregunta → SQL → resultado
  POST /api/ingest                            → Re-ejecutar pipeline de ingestión
  POST /api/upload                            → Subir y procesar un documento nuevo
  GET  /                                      → Servir frontend

Ejecutar:  uvicorn backend.api:app --reload --port 8000
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import ROOT_DIR, UPLOAD_DIR, DATASET_DIR, DATA_DIR
from backend.searcher import hybrid_search
from backend.graph import (
    get_graph_data,
    get_all_entities,
    get_entity,
    get_related_entities,
    get_related_docs,
    get_stats as graph_stats,
    load_graph,
)

# ─── Crear app ───────────────────────────────────────────────────
app = FastAPI(
    title="DocumentWho",
    description="Búsqueda inteligente de documentos corporativos",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request models ──────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str
    doc_type: Optional[str] = None
    top_k: int = 8

class SqlQueryRequest(BaseModel):
    query: str

class SqlAskRequest(BaseModel):
    question: str


# ─── Startup: cargar grafo + tablas SQL ──────────────────────────
@app.on_event("startup")
def startup():
    load_graph()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # Cargar tablas SQL en background
    try:
        from backend.sql_engine import load_tables
        tables = load_tables()
        if tables:
            print(f"📊 {len(tables)} tablas SQL cargadas: {', '.join(tables)}")
    except Exception as e:
        print(f"⚠️  Error cargando tablas SQL: {e}")


# ─── Búsqueda ────────────────────────────────────────────────────
@app.get("/api/search")
def search(
    q: str = Query(..., min_length=1, description="Consulta de búsqueda"),
    type: Optional[str] = Query(None, description="Filtrar por tipo de documento"),
    top_k: int = Query(10, ge=1, le=50),
):
    """Búsqueda híbrida BM25 + semántica con fusión RRF."""
    results = hybrid_search(query=q, doc_type=type, top_k=top_k)
    return {
        "query": q,
        "filter": type,
        "count": len(results),
        "results": [r.to_dict() for r in results],
    }


# ─── LLM RAG (Preguntas) ────────────────────────────────────────
@app.post("/api/ask")
def ask_question(req: AskRequest):
    """RAG: búsqueda + generación de respuesta con LLM."""
    from backend.llm import ask
    result = ask(question=req.question, doc_type=req.doc_type, top_k=req.top_k)
    return result


# ─── Documentos ──────────────────────────────────────────────────
@app.get("/api/documents")
def list_documents():
    """Lista todos los documentos indexados (metadatos del grafo)."""
    from backend.graph import _documents
    docs = list(_documents.values())
    return {"count": len(docs), "documents": docs}


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    """Detalle de un documento: busca sus chunks en ChromaDB."""
    from backend.indexer import _get_chroma_collection

    collection = _get_chroma_collection()

    # Buscar todos los chunks de este documento
    try:
        results = collection.get(
            where={"doc_id": doc_id},
            include=["documents", "metadatas"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not results["ids"]:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    chunks = []
    meta = results["metadatas"][0] if results["metadatas"] else {}
    for i, chunk_id in enumerate(results["ids"]):
        chunks.append({
            "chunk_id": chunk_id,
            "text": results["documents"][i],
            "metadata": results["metadatas"][i],
        })

    # Ordenar por chunk_id para mantener orden original
    chunks.sort(key=lambda c: c["chunk_id"])

    return {
        "doc_id": doc_id,
        "title": meta.get("title", ""),
        "filename": meta.get("filename", ""),
        "doc_type": meta.get("doc_type", ""),
        "num_chunks": len(chunks),
        "chunks": chunks,
    }


@app.post("/api/documents/{doc_id}/summary")
def document_summary(doc_id: str):
    """Genera un resumen del documento con LLM."""
    from backend.llm import summarize_document
    return summarize_document(doc_id)


# ─── Grafo de entidades ─────────────────────────────────────────
@app.get("/api/graph")
def graph():
    """Grafo completo en formato vis-network (nodos + aristas)."""
    return get_graph_data()


@app.get("/api/graph/entities")
def entities():
    """Lista de todas las entidades ordenadas por menciones."""
    return {"entities": get_all_entities()}


@app.get("/api/graph/entity/{name}")
def entity_detail(name: str):
    """Detalle de una entidad: info + relaciones + documentos."""
    node = get_entity(name)
    if not node:
        raise HTTPException(status_code=404, detail="Entidad no encontrada")
    return {
        "entity": node.to_dict(),
        "related": get_related_entities(name),
        "documents": get_related_docs(name),
    }


# ─── Dashboard stats ────────────────────────────────────────────
@app.get("/api/stats")
def stats():
    """Estadísticas globales para el dashboard."""
    gs = graph_stats()

    from backend.graph import _documents
    type_counts: dict[str, int] = {}
    for doc in _documents.values():
        t = doc.get("doc_type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "documents": gs["total_documents"],
        "entities": gs["total_entities"],
        "edges": gs["total_edges"],
        "entities_by_type": gs["entities_by_type"],
        "documents_by_type": type_counts,
    }


# ─── SQL Engine ──────────────────────────────────────────────────
@app.get("/api/sql/tables")
def sql_tables():
    """Lista las tablas SQL disponibles."""
    from backend.sql_engine import get_table_list
    tables = get_table_list()
    return {"tables": tables}


@app.post("/api/sql/query")
def sql_query(req: SqlQueryRequest):
    """Ejecuta una consulta SQL sobre los datos tabulares."""
    from backend.sql_engine import execute_sql
    result = execute_sql(req.query)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/sql/ask")
def sql_ask(req: SqlAskRequest):
    """Convierte pregunta a SQL con LLM, ejecuta y devuelve resultado."""
    from backend.sql_engine import natural_language_to_sql, execute_sql
    sql = natural_language_to_sql(req.question)
    if not sql:
        raise HTTPException(status_code=400, detail="No se pudo generar una consulta SQL")
    result = execute_sql(sql)
    result["sql"] = sql
    result["question"] = req.question
    return result


# ─── Ingestión ───────────────────────────────────────────────────
@app.post("/api/ingest")
def ingest():
    """Re-ejecuta el pipeline completo de ingestión."""
    from backend.ingest import run_full_pipeline
    docs = run_full_pipeline()
    return {"status": "ok", "documents_processed": len(docs)}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    """Sube un fichero nuevo y lo procesa."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    dest = UPLOAD_DIR / file.filename
    with open(dest, "wb") as f:
        content = await file.read()
        f.write(content)

    from backend.ingest import ingest_file
    doc = ingest_file(dest)
    if not doc:
        raise HTTPException(status_code=400, detail="Formato no soportado o sin contenido")

    # Actualizar grafo con el nuevo documento
    from backend.graph import build_graph, _documents
    from backend.graph import _entity_nodes
    # Reconstruir solo el documento nuevo es complejo, así que rehacemos el grafo
    # En producción optimizaríamos esto
    from backend.ingest import ingest_directory
    from backend.graph import build_graph as _bg
    # Simple approach: return success, graph updates on next full ingest
    load_graph()

    return {
        "status": "ok",
        "filename": file.filename,
        "doc_id": doc.doc_id,
        "doc_type": doc.doc_type,
        "title": doc.title,
    }


# ─── Servir frontend ────────────────────────────────────────────
FRONTEND_DIR = ROOT_DIR / "frontend"


@app.get("/")
def serve_frontend():
    """Sirve el fichero index.html del frontend."""
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "DocumentWho API — frontend no encontrado, usa /docs para la API"}


# Servir archivos estáticos del frontend (CSS, JS, etc.)
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
