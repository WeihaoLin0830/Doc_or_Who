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
from backend.graph import (
    get_graph_data,
    get_graph_data_filtered,
    get_all_entities,
    get_entity,
    get_related_entities,
    get_related_docs,
    find_connection_path,
    search_entities,
    get_stats as graph_stats,
    get_communities,
    get_top_brokers,
    load_graph,
)
from backend.search.indexer import find_duplicates

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

    # Precargar modelo de embeddings y ChromaDB para que la primera búsqueda
    # no sufra el coste de carga del modelo (~5-15 s).
    try:
        from backend.search.indexer import _get_embedding_model, _get_chroma_collection
        _get_embedding_model()
        _get_chroma_collection()
        print("✅ Modelo de embeddings y ChromaDB precargados.")
    except Exception as e:
        print(f"⚠️  Error precargando embeddings: {e}")

    # Cargar tablas SQL
    try:
        from backend.ai.sql_engine import load_tables
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
    language: Optional[str] = Query(None, description="Filtrar por idioma"),
    person: Optional[str] = Query(None, description="Filtrar por persona"),
    organization: Optional[str] = Query(None, description="Filtrar por organización"),
    date: Optional[str] = Query(None, description="Filtrar por fecha (ej: 2025, 2025-01, enero)"),
    top_k: int = Query(10, ge=1, le=50),
):
    """Búsqueda híbrida BM25 + semántica con fusión RRF + facets dinámicos."""
    from backend.search.searcher import hybrid_search_with_facets
    data = hybrid_search_with_facets(
        query=q,
        doc_type=type,
        language=language,
        person=person,
        organization=organization,
        date=date,
        top_k=top_k,
    )
    return {
        "query": q,
        "filters": {"type": type, "language": language, "person": person, "organization": organization, "date": date},
        "count": len(data["results"]),
        "results": [r.to_dict() for r in data["results"]],
        "facets": data["facets"],
    }


# ─── LLM RAG (Preguntas) ────────────────────────────────────────
@app.post("/api/ask")
def ask_question(req: AskRequest):
    """RAG: búsqueda + generación de respuesta con LLM."""
    from backend.ai.llm import ask
    result = ask(question=req.question, doc_type=req.doc_type, top_k=req.top_k)
    return result


# ─── Documentos ──────────────────────────────────────────────────
@app.get("/api/documents")
def list_documents():
    """Lista todos los documentos indexados (metadatos del grafo)."""
    from backend.graph.graph import _documents
    docs = list(_documents.values())
    return {"count": len(docs), "documents": docs}


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    """Detalle de un documento: busca sus chunks en ChromaDB."""
    from backend.search.indexer import _get_chroma_collection

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
        "language": meta.get("language", ""),
        "num_chunks": len(chunks),
        "chunks": chunks,
        "has_file": _find_original_file(meta.get("filename", "")) is not None,
    }


def _find_original_file(filename: str) -> Path | None:
    """Busca el fichero original en dataset_default o uploads."""
    if not filename:
        return None
    for directory in [DATASET_DIR, UPLOAD_DIR]:
        candidate = directory / filename
        if candidate.exists():
            return candidate
    return None


@app.get("/api/documents/{doc_id}/file")
def get_document_file(doc_id: str):
    """Sirve el fichero original para previsualización."""
    from backend.search.indexer import _get_chroma_collection

    collection = _get_chroma_collection()
    try:
        results = collection.get(
            where={"doc_id": doc_id},
            include=["metadatas"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not results["ids"]:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    filename = results["metadatas"][0].get("filename", "") if results["metadatas"] else ""
    filepath = _find_original_file(filename)

    if not filepath:
        raise HTTPException(status_code=404, detail=f"Fichero original no encontrado: {filename}")

    # Determinar media type
    ext = filepath.suffix.lower()
    media_types = {
        ".pdf": "application/pdf",
        ".txt": "text/plain; charset=utf-8",
        ".csv": "text/csv; charset=utf-8",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    # PDFs y texto: forzar vista inline (no descargar)
    if ext in (".pdf", ".txt", ".csv"):
        return FileResponse(
            path=str(filepath),
            media_type=media_type,
            headers={"Content-Disposition": f"inline; filename=\"{filename}\""},
        )

    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type=media_type,
    )


@app.get("/api/documents/{doc_id}/table")
def get_document_table(doc_id: str, max_rows: int = Query(500, le=2000)):
    """
    Parsea el fichero original (CSV/XLSX/XLS) como tabla estructurada.
    Devuelve {columns: [...], rows: [[...], ...]} listo para renderizar en HTML.
    """
    import pandas as pd
    from backend.search.indexer import _get_chroma_collection

    collection = _get_chroma_collection()
    try:
        results = collection.get(where={"doc_id": doc_id}, include=["metadatas"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not results["ids"]:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    filename = results["metadatas"][0].get("filename", "") if results["metadatas"] else ""
    filepath = _find_original_file(filename)
    if not filepath:
        raise HTTPException(status_code=404, detail=f"Fichero no encontrado: {filename}")

    ext = filepath.suffix.lower()
    try:
        if ext == ".csv":
            # Intentar detectar separador automáticamente
            df = pd.read_csv(filepath, sep=None, engine="python", dtype=str, nrows=max_rows)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(filepath, dtype=str, nrows=max_rows)
        else:
            raise HTTPException(status_code=400, detail=f"Formato no tabular: {ext}")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Error al parsear tabla: {e}")

    df = df.fillna("")
    return {
        "filename": filename,
        "columns": df.columns.tolist(),
        "rows": df.values.tolist(),
        "total_rows": len(df),
    }


@app.get("/api/documents/{doc_id}/raw")
def get_document_raw_text(doc_id: str):
    """Devuelve el texto completo reconstruido del documento."""
    from backend.search.indexer import _get_chroma_collection

    collection = _get_chroma_collection()
    try:
        results = collection.get(
            where={"doc_id": doc_id},
            include=["documents", "metadatas"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not results["ids"]:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    # Reconstruir texto completo ordenando chunks
    chunk_data = []
    for i, chunk_id in enumerate(results["ids"]):
        chunk_data.append({
            "chunk_id": chunk_id,
            "text": results["documents"][i],
        })
    chunk_data.sort(key=lambda c: c["chunk_id"])
    full_text = "\n\n".join(c["text"] for c in chunk_data)

    meta = results["metadatas"][0] if results["metadatas"] else {}
    return {
        "doc_id": doc_id,
        "filename": meta.get("filename", ""),
        "text": full_text,
    }


@app.post("/api/documents/{doc_id}/summary")
def document_summary(doc_id: str):
    """Genera un resumen del documento con LLM."""
    from backend.ai.llm import summarize_document
    return summarize_document(doc_id)


# ─── Grafo de entidades ─────────────────────────────────────────
@app.get("/api/graph")
def graph(
    doc_id: Optional[str] = Query(None, description="Filtrar por documento"),
    entity_type: Optional[str] = Query(None, description="Filtrar por tipo de entidad (person/organization)"),
):
    """Grafo en formato vis-network, opcionalmente filtrado por documento o tipo de entidad."""
    from backend.graph import get_graph_data_filtered
    return get_graph_data_filtered(doc_id=doc_id, entity_type=entity_type)


@app.get("/api/graph/entities")
def entities():
    """Lista de todas las entidades ordenadas por menciones."""
    return {"entities": get_all_entities()}


@app.get("/api/graph/search")
def entity_search(q: str = Query("", description="Texto de búsqueda de entidades")):
    """Búsqueda parcial de entidades (para autocompletado)."""
    if not q.strip():
        return {"entities": []}
    return {"entities": search_entities(q, top_k=10)}


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


@app.get("/api/graph/path")
def graph_path(
    from_entity: str = Query(..., alias="from", description="Nombre de la entidad origen"),
    to_entity: str = Query(..., alias="to", description="Nombre de la entidad destino"),
):
    """Camino más corto entre dos entidades (BFS). ¿Qué conecta A con B?"""
    return find_connection_path(from_entity, to_entity)


# ─── Dashboard stats ────────────────────────────────────────────
@app.get("/api/graph/communities")
def graph_communities():
    """Retorna las comunidades Louvain del grafo de entidades."""
    return {"communities": get_communities()}


@app.get("/api/graph/brokers")
def graph_brokers(top_k: int = 10):
    """Retorna las entidades con mayor betweenness centrality (brokers de información)."""
    return {"brokers": get_top_brokers(top_k=top_k)}


@app.get("/api/duplicates")
def duplicates(threshold: float = 0.85):
    """
    Detecta documentos near-duplicados usando mean-pooled embeddings.
    threshold: umbral de similitud coseno (0-1), por defecto 0.85.
    """
    dupes = find_duplicates(threshold=threshold)
    return {"duplicates": dupes, "count": len(dupes)}


@app.get("/api/stats")
def stats():
    """Estadísticas globales para el dashboard."""
    gs = graph_stats()

    from backend.graph.graph import _documents
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
    from backend.ai.sql_engine import get_table_list
    tables = get_table_list()
    return {"tables": tables}


@app.post("/api/sql/query")
def sql_query(req: SqlQueryRequest):
    """Ejecuta una consulta SQL sobre los datos tabulares."""
    from backend.ai.sql_engine import execute_sql
    result = execute_sql(req.query)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/sql/ask")
def sql_ask(req: SqlAskRequest):
    """Convierte pregunta a SQL con LLM, ejecuta y devuelve resultado."""
    from backend.ai.sql_engine import natural_language_to_sql, execute_sql
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
    from backend.ingestion.ingest import run_full_pipeline
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

    from backend.ingestion.ingest import ingest_file
    doc = ingest_file(dest)
    if not doc:
        raise HTTPException(status_code=400, detail="Formato no soportado o sin contenido")

    # Actualizar grafo con el nuevo documento
    from backend.graph import build_graph
    from backend.graph.graph import _documents, _entity_nodes
    # Reconstruir solo el documento nuevo es complejo, así que rehacemos el grafo
    # En producción optimizaríamos esto
    from backend.ingestion.ingest import ingest_directory
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
