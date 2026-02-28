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
import asyncio
import threading
import time as _time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import ROOT_DIR, UPLOAD_DIR, DATASET_DIR
from backend.graph import (
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
    add_document_to_graph,
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


@app.middleware("http")
async def no_cache_api(request, call_next):
    """Ensures API responses are never cached by the browser or any proxy."""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


# ─── Request models ──────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str
    doc_type: Optional[str] = None
    top_k: int = 8

class AgentRequest(BaseModel):
    question: str
    session_id: Optional[str] = None

class SqlQueryRequest(BaseModel):
    query: str

class SqlAskRequest(BaseModel):
    question: str


def _get_document_chunks_from_chroma(doc_id: str) -> tuple[list[dict], dict]:
    """Resuelve chunks y metadatos del documento desde ChromaDB."""
    from backend.search.indexer import _get_chroma_collection

    collection = _get_chroma_collection()
    results = collection.get(
        where={"doc_id": doc_id},
        include=["documents", "metadatas"],
    )

    if not results["ids"]:
        return [], {}

    chunks = []
    meta = results["metadatas"][0] if results["metadatas"] else {}
    for i, chunk_id in enumerate(results["ids"]):
        chunks.append({
            "chunk_id": chunk_id,
            "text": results["documents"][i],
            "metadata": results["metadatas"][i],
        })
    chunks.sort(key=lambda c: c["chunk_id"])
    return chunks, meta


def _get_document_chunks_from_whoosh(doc_id: str) -> tuple[list[dict], dict]:
    """Fallback robusto usando Whoosh, que almacena los chunks completos."""
    from whoosh import index as whoosh_index
    from backend.config import WHOOSH_DIR

    if not whoosh_index.exists_in(str(WHOOSH_DIR)):
        return [], {}

    ix = whoosh_index.open_dir(str(WHOOSH_DIR))
    with ix.searcher() as searcher:
        stored_docs = list(searcher.documents(doc_id=doc_id))

    if not stored_docs:
        return [], {}

    chunks = []
    for stored in stored_docs:
        metadata = {
            "doc_id": stored.get("doc_id", ""),
            "doc_type": stored.get("doc_type", ""),
            "title": stored.get("title", ""),
            "language": stored.get("language", ""),
            "filename": stored.get("filename", ""),
            "section": stored.get("section", ""),
            "level": stored.get("level", ""),
            "persons": stored.get("persons", ""),
            "organizations": stored.get("organizations", ""),
            "keywords": stored.get("keywords", ""),
            "dates": stored.get("dates", ""),
            "emails": stored.get("emails", ""),
        }
        chunks.append({
            "chunk_id": stored.get("chunk_id", ""),
            "text": stored.get("content", ""),
            "metadata": metadata,
        })

    chunks.sort(key=lambda c: c["chunk_id"])
    meta = chunks[0]["metadata"] if chunks else {}
    return chunks, meta


def _get_document_chunks(doc_id: str) -> tuple[list[dict], dict, str]:
    """Busca un documento por doc_id con fallback Chroma -> Whoosh."""
    try:
        chunks, meta = _get_document_chunks_from_chroma(doc_id)
        if chunks:
            return chunks, meta, "chroma"
    except Exception as exc:
        print(f"⚠️  Error resolving document {doc_id} from Chroma: {exc}")

    chunks, meta = _get_document_chunks_from_whoosh(doc_id)
    if chunks:
        return chunks, meta, "whoosh"
    return [], {}, "missing"


def _list_documents_from_whoosh() -> list[dict]:
    """Fallback para listar documentos únicos desde Whoosh si el grafo no está cargado."""
    from whoosh import index as whoosh_index
    from backend.config import WHOOSH_DIR

    if not whoosh_index.exists_in(str(WHOOSH_DIR)):
        return []

    ix = whoosh_index.open_dir(str(WHOOSH_DIR))
    documents: dict[str, dict] = {}
    with ix.searcher() as searcher:
        for stored in searcher.all_stored_fields():
            doc_id = stored.get("doc_id")
            if not doc_id or doc_id in documents:
                continue
            documents[doc_id] = {
                "doc_id": doc_id,
                "title": stored.get("title", ""),
                "filename": stored.get("filename", ""),
                "doc_type": stored.get("doc_type", ""),
                "category": "",
            }
    return list(documents.values())


# ─── Estado global de ingestión ─────────────────────────────────
_ingest_lock = threading.Lock()
_ingest_state: dict = {
    "running": False,
    "phase": None,        # "clearing" | "indexing" | "graph" | "done" | "error"
    "current": 0,
    "total": 0,
    "current_file": "",
    "docs_processed": 0,
    "elapsed": 0.0,
    "error": None,
}
_ingest_t0: float = 0.0


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

    # Inicializar expansor de sinónimos basado en corpus
    try:
        from backend.search.synonyms import initialize_synonyms
        initialize_synonyms()
    except Exception as e:
        print(f"⚠️  Error inicializando sinónimos: {e}")


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
    debug: bool = Query(False, description="Incluir explicación ampliada de ranking"),
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
        debug=debug,
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


@app.post("/api/agent/ask")
async def agent_ask(req: AgentRequest):
    """
    Agente orquestador: decide qué herramientas usar (búsqueda textual,
    SQL sobre datos tabulares, grafo de entidades) y combina los resultados
    para generar una respuesta completa.
    """
    import asyncio
    from functools import partial
    from backend.ai.agent import run_agent
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, partial(run_agent, question=req.question, session_id=req.session_id)
    )
    return result.to_dict()


# ─── Documentos ──────────────────────────────────────────────────
@app.get("/api/documents")
def list_documents():
    """Lista todos los documentos indexados (metadatos del grafo)."""
    from backend.graph.graph import _documents
    docs = list(_documents.values())
    if not docs:
        docs = _list_documents_from_whoosh()
    return {"count": len(docs), "documents": docs}


@app.get("/api/documents/clusters")
def cluster_documents(n_clusters: Optional[int] = None):
    """
    Agrupa documentos por similitud semántica usando Agglomerative Clustering
    sobre los embeddings mean-pooled de ChromaDB.

    n_clusters: número deseado de clusters. Si es None, se elige
    automáticamente con un heurístico (sqrt(n_docs/2), min 2, max 8).
    """
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering
    from backend.search.indexer import _get_chroma_collection
    from backend.graph.graph import _documents

    collection = _get_chroma_collection()
    results = collection.get(include=["embeddings", "metadatas"])

    if not results["ids"]:
        return {"n_clusters": 0, "clusters": []}

    # Agrupar embeddings por doc_id → mean-pool
    doc_embs: dict[str, list[list[float]]] = {}
    doc_meta: dict[str, dict] = {}
    for chunk_id, meta, emb in zip(results["ids"], results["metadatas"], results["embeddings"]):
        doc_id = meta.get("doc_id", chunk_id)
        if doc_id not in doc_embs:
            doc_embs[doc_id] = []
            doc_meta[doc_id] = meta
        doc_embs[doc_id].append(emb)

    doc_ids = list(doc_embs.keys())
    n_docs = len(doc_ids)

    if n_docs < 2:
        single_meta = doc_meta[doc_ids[0]]
        return {
            "n_clusters": 1,
            "clusters": [{
                "cluster_id": 0,
                "label": single_meta.get("doc_type", "Documentos"),
                "documents": [{
                    "doc_id": doc_ids[0],
                    "title": single_meta.get("title", ""),
                    "filename": single_meta.get("filename", ""),
                    "doc_type": single_meta.get("doc_type", ""),
                    "category": _documents.get(doc_ids[0], {}).get("category", ""),
                }],
            }],
        }

    vectors = np.array([np.mean(np.array(doc_embs[did]), axis=0) for did in doc_ids])
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1e-9
    vectors = vectors / norms

    k = n_clusters
    if k is None:
        k = max(2, min(8, int(np.sqrt(n_docs / 2) + 0.5)))
    k = min(k, n_docs)

    model = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average")
    labels = model.fit_predict(vectors)

    cluster_docs: dict[int, list[dict]] = {}
    for idx, doc_id in enumerate(doc_ids):
        c = int(labels[idx])
        if c not in cluster_docs:
            cluster_docs[c] = []
        meta = doc_meta[doc_id]
        doc_info = _documents.get(doc_id, {})
        cluster_docs[c].append({
            "doc_id": doc_id,
            "title": meta.get("title", ""),
            "filename": meta.get("filename", ""),
            "doc_type": meta.get("doc_type", ""),
            "category": doc_info.get("category", ""),
        })

    cluster_list = []
    for cid in sorted(cluster_docs.keys()):
        docs = cluster_docs[cid]
        type_counts: dict[str, int] = {}
        for d in docs:
            t = d.get("doc_type", "documento")
            type_counts[t] = type_counts.get(t, 0) + 1
        top_type = max(type_counts, key=type_counts.get) if type_counts else "documentos"
        label = f"{top_type.replace('_', ' ').title()}" if len(type_counts) == 1 else \
                f"{top_type.replace('_', ' ').title()} y otros"

        kw_freq: dict[str, int] = {}
        categories_set: set[str] = set()
        for d in docs:
            doc_id = d["doc_id"]
            doc_info = _documents.get(doc_id, {})
            for kw in doc_info.get("keywords", []):
                kw_lower = kw.lower().strip()
                if kw_lower:
                    kw_freq[kw_lower] = kw_freq.get(kw_lower, 0) + 1
            cat = d.get("category") or doc_info.get("category", "")
            if cat:
                categories_set.add(cat)
        top_keywords = sorted(kw_freq, key=kw_freq.get, reverse=True)[:8]

        cluster_list.append({
            "cluster_id": cid,
            "label": label,
            "keywords": top_keywords,
            "categories": sorted(categories_set),
            "documents": docs,
        })

    return {"n_clusters": k, "clusters": cluster_list}


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    """Detalle de un documento: resuelve sus chunks desde Chroma y cae a Whoosh si hace falta."""
    chunks, meta, backend_used = _get_document_chunks(doc_id)

    if not chunks:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    return {
        "doc_id": doc_id,
        "title": meta.get("title", ""),
        "filename": meta.get("filename", ""),
        "doc_type": meta.get("doc_type", ""),
        "language": meta.get("language", ""),
        "num_chunks": len(chunks),
        "chunks": chunks,
        "has_file": _find_original_file(meta.get("filename", "")) is not None,
        "backend": backend_used,
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
    _, meta, _ = _get_document_chunks(doc_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    filename = meta.get("filename", "")
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
@app.get("/api/ingest/status")
def ingest_status():
    """Estado en tiempo real del pipeline de ingestión."""
    state = dict(_ingest_state)
    if state["running"]:
        state["elapsed"] = round(_time.time() - _ingest_t0, 1)
    return state


@app.post("/api/ingest")
def ingest():
    """
    Lanza el pipeline de ingestión completo en background.
    Retorna inmediatamente — sondea /api/ingest/status para seguir el progreso.
    Devuelve 409 si ya hay una ingestión en curso.
    """
    global _ingest_t0

    if not _ingest_lock.acquire(blocking=False):
        return {"status": "already_running", "running": True, **_ingest_state}

    _ingest_state.update({
        "running": True,
        "phase": "starting",
        "current": 0,
        "total": 0,
        "current_file": "",
        "docs_processed": 0,
        "elapsed": 0.0,
        "error": None,
    })
    _ingest_t0 = _time.time()

    def _run_pipeline():
        try:
            from backend.ingestion.ingest import run_full_pipeline
            docs = run_full_pipeline(_status=_ingest_state)
            _ingest_state.update({
                "running": False,
                "phase": "done",
                "docs_processed": len(docs),
                "elapsed": round(_time.time() - _ingest_t0, 1),
                "current_file": "",
                "error": None,
            })
            try:
                import backend.ai.agent as _ag; _ag._schema_cache_time = 0
            except Exception:
                pass
            load_graph()
        except Exception as exc:
            _ingest_state.update({
                "running": False,
                "phase": "error",
                "error": str(exc),
                "elapsed": round(_time.time() - _ingest_t0, 1),
                "current_file": "",
            })
        finally:
            _ingest_lock.release()

    threading.Thread(target=_run_pipeline, daemon=True, name="ingest-pipeline").start()
    return {"status": "started", "running": True}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    """Sube un fichero nuevo, lo valida y lo procesa sin bloquear el event loop."""
    from backend.ingestion.ingest import ingest_file, SUPPORTED_EXTENSIONS, _file_id
    from backend.graph.graph import _documents

    # No permitir uploads mientras hay una re-ingestión en curso (evita carreras)
    if _ingest_state.get("running"):
        raise HTTPException(
            status_code=409,
            detail="Re-ingestión en curso. Espera a que termine antes de subir documentos."
        )

    # Detectar duplicados: si el archivo ya existe en el sistema, rechazar
    doc_id = _file_id(Path(file.filename))
    if doc_id in _documents:
        raise HTTPException(
            status_code=409,
            detail=f"Documento '{file.filename}' ya está indexado. Si deseas reemplazarlo, usa 'Re-indexar todo'."
        )

    # Validar extensión antes de leer
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Formato '{ext}' no soportado. Usa: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    # Leer contenido y validar tamaño (máx 50 MB)
    content = await file.read()
    MAX_BYTES = 50 * 1024 * 1024
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo demasiado grande ({len(content) // (1024*1024)} MB). Máximo 50 MB."
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / file.filename
    dest.write_bytes(content)

    # Ejecutar ingest en thread pool para no bloquear el event loop (Python 3.9+)
    import traceback as _tb
    try:
        doc = await asyncio.to_thread(ingest_file, dest)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error al procesar el documento: {type(exc).__name__}: {exc}\n{_tb.format_exc()}"
        )

    if not doc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Sin contenido útil o formato no procesable")

    # Añadir el documento al grafo de forma incremental (sin reconstruir todo)
    add_document_to_graph(doc)
    try:
        import backend.ai.agent as _ag; _ag._schema_cache_time = 0
    except Exception:
        pass

    # Contar chunks indexados para el response
    try:
        from backend.search.indexer import _get_chroma_collection
        col = _get_chroma_collection()
        doc_chunks = col.get(where={"doc_id": doc.doc_id}, include=[])
        chunks_indexed = len(doc_chunks.get("ids", []))
    except Exception:
        chunks_indexed = 0

    return {
        "status": "ok",
        "filename": file.filename,
        "doc_id": doc.doc_id,
        "doc_type": doc.doc_type,
        "title": doc.title,
        "language": doc.language,
        "chunks_indexed": chunks_indexed,
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
