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
    Agrupa documentos en una jerarquía de 2 niveles:
      - Nivel 1: clusters amplios por temática
      - Nivel 2: sub-clusters más específicos dentro de cada grupo

    Genera etiquetas inteligentes basadas en categorías, tipos, palabras clave
    y títulos de los documentos en lugar de usar simplemente el doc_type.
    """
    import re
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering
    from backend.search.indexer import _get_chroma_collection
    from backend.graph.graph import _documents

    collection = _get_chroma_collection()
    results = collection.get(include=["embeddings", "metadatas"])

    if not results["ids"]:
        return {"n_clusters": 0, "clusters": []}

    # ── Agrupar embeddings por doc_id → mean-pool ─────────────────
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

    def _build_doc_info(doc_id: str) -> dict:
        meta = doc_meta.get(doc_id, {})
        graph_info = _documents.get(doc_id, {})
        return {
            "doc_id": doc_id,
            "title": meta.get("title", ""),
            "filename": meta.get("filename", ""),
            "doc_type": meta.get("doc_type", ""),
            "category": graph_info.get("category", meta.get("category", "")),
            "keywords": graph_info.get("keywords", []),
        }

    if n_docs < 2:
        info = _build_doc_info(doc_ids[0])
        return {
            "n_clusters": 1,
            "clusters": [{
                "cluster_id": 0,
                "label": info["category"] or info["doc_type"] or "Documentos",
                "keywords": info["keywords"][:5],
                "categories": [info["category"]] if info["category"] else [],
                "children": [],
                "documents": [{k: v for k, v in info.items() if k != "keywords"}],
            }],
        }

    # ── Vectores normalizados ─────────────────────────────────────
    vectors = np.array([np.mean(np.array(doc_embs[did]), axis=0) for did in doc_ids])
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1e-9
    vectors = vectors / norms

    # ── Helper: generar etiqueta inteligente para un grupo ────────
    _STOP_WORDS = {
        "de", "del", "la", "las", "los", "el", "en", "y", "a", "para",
        "por", "con", "un", "una", "s.l", "s.l.", "s.a", "s.a.", "—",
        "es", "su", "se", "al", "lo", "no", "más", "como", "o", "e",
        "que", "datos", "número", "dear", "from", "the", "and", "of",
    }

    def _smart_label(docs_info: list[dict]) -> str:
        """Determina un nombre descriptivo para un grupo de docs."""
        # 1. Si todos comparten la misma categoría y no es "General", usarla
        cats = set(d.get("category", "") for d in docs_info)
        cats.discard("")
        cats.discard("General")
        if len(cats) == 1:
            cat = cats.pop()
            # Enriquecer con tipo si es distinguible
            types = set(d.get("doc_type", "") for d in docs_info)
            types.discard("documento")
            if len(types) == 1:
                t = types.pop().replace("_", " ").title()
                return f"{cat} — {t}"
            return cat

        # 2. Si hay tipos específicos (no genérico "documento"), usar esos
        type_counts: dict[str, int] = {}
        for d in docs_info:
            t = d.get("doc_type", "documento")
            type_counts[t] = type_counts.get(t, 0) + 1
        specific_types = {t: c for t, c in type_counts.items() if t != "documento"}
        if specific_types:
            top = max(specific_types, key=specific_types.get)
            label = top.replace("_", " ").title()
            if len(specific_types) > 1:
                second = sorted(specific_types, key=specific_types.get, reverse=True)[1]
                label += f" y {second.replace('_', ' ').title()}"
            # Añadir categoría si hay una predominante
            if cats:
                top_cat = max(cats, key=lambda c: sum(1 for d in docs_info if d.get("category") == c))
                label = f"{top_cat} — {label}"
            return label

        # 3. Extraer palabras significativas de los títulos
        word_freq: dict[str, int] = {}
        for d in docs_info:
            title = d.get("title", "")
            words = re.findall(r"[A-Za-zÀ-ÿ]{3,}", title)
            seen = set()
            for w in words:
                wl = w.lower()
                if wl not in _STOP_WORDS and wl not in seen:
                    word_freq[wl] = word_freq.get(wl, 0) + 1
                    seen.add(wl)

        # Palabras que aparecen en >50% de los docs del grupo → tema
        threshold = max(2, len(docs_info) * 0.4)
        common = [w for w, c in sorted(word_freq.items(), key=lambda x: -x[1]) if c >= threshold]
        if common:
            label_words = [w.title() for w in common[:3]]
            return " · ".join(label_words)

        # 4. Categorías predominantes
        if cats:
            return " / ".join(sorted(cats)[:2])

        # 5. Fallback: usar las keywords del grafo
        kw_freq: dict[str, int] = {}
        for d in docs_info:
            for kw in d.get("keywords", []):
                kl = kw.lower().strip()
                if kl:
                    kw_freq[kl] = kw_freq.get(kl, 0) + 1
        if kw_freq:
            top_kw = sorted(kw_freq, key=kw_freq.get, reverse=True)[:2]
            return " · ".join(w.title() for w in top_kw)

        return "Documentos varios"

    def _extract_keywords(docs_info: list[dict]) -> list[str]:
        """Extrae keywords representativas de un grupo."""
        kw_freq: dict[str, int] = {}
        for d in docs_info:
            for kw in d.get("keywords", []):
                kl = kw.lower().strip()
                if kl:
                    kw_freq[kl] = kw_freq.get(kl, 0) + 1
        # También extraer de títulos
        word_freq: dict[str, int] = {}
        for d in docs_info:
            words = re.findall(r"[A-Za-zÀ-ÿ]{4,}", d.get("title", ""))
            for w in words:
                wl = w.lower()
                if wl not in _STOP_WORDS:
                    word_freq[wl] = word_freq.get(wl, 0) + 1
        # Combinar ambas fuentes
        combined = {**word_freq}
        for k, v in kw_freq.items():
            combined[k] = combined.get(k, 0) + v * 2  # Pesar más las keywords
        return sorted(combined, key=combined.get, reverse=True)[:8]

    # ── Nivel 1: clusters amplios ─────────────────────────────────
    k1 = n_clusters
    if k1 is None:
        k1 = max(2, min(6, int(np.sqrt(n_docs / 2) + 0.5)))
    k1 = min(k1, n_docs)

    model1 = AgglomerativeClustering(n_clusters=k1, metric="cosine", linkage="average")
    labels1 = model1.fit_predict(vectors)

    # ── Construir clusters jerárquicos ────────────────────────────
    cluster_list = []
    for cid in range(k1):
        member_indices = [i for i, l in enumerate(labels1) if l == cid]
        if not member_indices:
            continue

        member_ids = [doc_ids[i] for i in member_indices]
        member_info = [_build_doc_info(did) for did in member_ids]
        member_vecs = vectors[member_indices]

        parent_label = _smart_label(member_info)
        parent_keywords = _extract_keywords(member_info)
        parent_cats = sorted(set(d.get("category", "") for d in member_info) - {""})

        # ── Nivel 2: sub-clusters si hay suficientes docs ─────────
        children = []
        if len(member_ids) >= 4:
            k2 = max(2, min(4, len(member_ids) // 2))
            model2 = AgglomerativeClustering(n_clusters=k2, metric="cosine", linkage="average")
            labels2 = model2.fit_predict(member_vecs)

            for scid in range(k2):
                sub_indices = [j for j, l in enumerate(labels2) if l == scid]
                if not sub_indices:
                    continue
                sub_info = [member_info[j] for j in sub_indices]
                sub_label = _smart_label(sub_info)
                # Evitar que sub-label sea igual al padre
                if sub_label == parent_label:
                    types_here = set(d.get("doc_type", "") for d in sub_info) - {"documento"}
                    if types_here:
                        sub_label = " · ".join(t.replace("_", " ").title() for t in sorted(types_here)[:2])
                    else:
                        sub_label = f"Grupo {scid + 1}"

                sub_keywords = _extract_keywords(sub_info)
                sub_cats = sorted(set(d.get("category", "") for d in sub_info) - {""})
                children.append({
                    "cluster_id": scid,
                    "label": sub_label,
                    "keywords": sub_keywords,
                    "categories": sub_cats,
                    "documents": [{k: v for k, v in d.items() if k != "keywords"} for d in sub_info],
                })
        else:
            # Pocos docs → un solo sub-cluster con todos
            children.append({
                "cluster_id": 0,
                "label": parent_label,
                "keywords": parent_keywords,
                "categories": parent_cats,
                "documents": [{k: v for k, v in d.items() if k != "keywords"} for d in member_info],
            })

        cluster_list.append({
            "cluster_id": cid,
            "label": parent_label,
            "keywords": parent_keywords,
            "categories": parent_cats,
            "children": children,
            "documents": [{k: v for k, v in d.items() if k != "keywords"} for d in member_info],
        })

    return {"n_clusters": len(cluster_list), "clusters": cluster_list}


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
