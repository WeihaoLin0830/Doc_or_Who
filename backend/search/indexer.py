"""
indexer.py — Indexa chunks en ChromaDB (semántico) y Whoosh (BM25).

Dos índices separados, alimentados con los mismos chunks.
El searcher.py se encarga de fusionar resultados de ambos.
"""

from __future__ import annotations

import os
import shutil

from backend.config import (
    CHROMA_DIR,
    CHROMA_COLLECTION,
    CHROMA_TELEMETRY_ENABLED,
    EMBEDDING_MODEL,
    WHOOSH_DIR,
)
from backend.models import Chunk
from backend.search.text_normalize import char_ngrams, fold_text, normalize_numbers_in_text

# ─── Whoosh: analizador con eliminación de acentos ────────────────
# Permite buscar "reunion" y encontrar "reunión" y viceversa.
# Se aplica tanto al indexar como al parsear queries (MultifieldParser
# usa el analizador del campo para tokenizar los términos de búsqueda).
try:
    from whoosh.analysis import StandardAnalyzer, CharsetFilter
    from whoosh.support.charset import accent_map
    _ACCENT_ANALYZER = StandardAnalyzer() | CharsetFilter(accent_map)
except Exception:
    _ACCENT_ANALYZER = None  # fallback: Whoosh sin accent stripping

# ─── Lazy loading ────────────────────────────────────────────────
_embedding_model = None
_chroma_client = None       # kept globally so it isn't GC'd while collection is live
_chroma_collection = None
_whoosh_index = None


def _whoosh_has_folded_fields(ix) -> bool:
    schema_names = set(ix.schema.names())
    return {"content_folded", "title_folded"}.issubset(schema_names)


def _whoosh_has_char3_field(ix) -> bool:
    return "content_char3" in set(ix.schema.names())


def _whoosh_has_num_norm_field(ix) -> bool:
    return "content_num_norm" in set(ix.schema.names())


def _whoosh_missing_lexical_fields(ix) -> set[str]:
    required_fields = {"content_folded", "title_folded", "content_char3", "content_num_norm"}
    return required_fields.difference(ix.schema.names())


def _get_embedding_model():
    """Carga el modelo de embeddings solo cuando se necesita."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        print(f"📦 Cargando modelo de embeddings: {EMBEDDING_MODEL}...")
        # device="cpu" evita el error de meta tensors con torch >= 2.6 +
        # sentence-transformers >= 5.x (que usa accelerate device_map por defecto)
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
        print("✅ Modelo cargado.")
    return _embedding_model


def _get_chroma_collection():
    """Obtiene (o crea) la colección de ChromaDB."""
    global _chroma_client, _chroma_collection
    if _chroma_collection is None:
        import chromadb
        from chromadb.config import Settings

        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault(
            "ANONYMIZED_TELEMETRY",
            "TRUE" if CHROMA_TELEMETRY_ENABLED else "FALSE",
        )
        print(
            "🛰️ Chroma telemetry "
            f"{'enabled' if CHROMA_TELEMETRY_ENABLED else 'disabled'}."
        )
        chroma_settings = {
            "anonymized_telemetry": CHROMA_TELEMETRY_ENABLED,
            "is_persistent": True,
            "persist_directory": str(CHROMA_DIR),
        }
        if not CHROMA_TELEMETRY_ENABLED:
            chroma_settings["chroma_product_telemetry_impl"] = (
                "backend.search.chroma_telemetry.NoOpTelemetry"
            )
            chroma_settings["chroma_telemetry_impl"] = (
                "backend.search.chroma_telemetry.NoOpTelemetry"
            )
        _chroma_client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(**chroma_settings),
        )
        _chroma_collection = _chroma_client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
    return _chroma_collection


def _get_whoosh_index(create: bool = False):
    """
    Obtiene (o crea) el índice Whoosh.

    Note: changing the schema does not migrate an existing Whoosh index.
    Rebuild from scratch with clear_indices()/full re-ingest after schema updates.
    """
    global _whoosh_index
    from whoosh import index as whoosh_index
    from whoosh.fields import Schema, TEXT, ID, KEYWORD

    # Usar el analizador con accent stripping si está disponible
    _ta = {"analyzer": _ACCENT_ANALYZER} if _ACCENT_ANALYZER is not None else {}

    schema = Schema(
        chunk_id=ID(stored=True, unique=True),
        doc_id=ID(stored=True),
        title=TEXT(stored=True, **_ta),
        title_folded=TEXT(**_ta),
        content=TEXT(stored=True, **_ta),
        content_folded=TEXT(**_ta),
        content_char3=TEXT(**_ta),
        content_num_norm=TEXT(**_ta),
        doc_type=TEXT(stored=True),
        language=TEXT(stored=True),
        filename=TEXT(stored=True),
        section=TEXT(stored=True, **_ta),
        level=TEXT(stored=True),
        persons=TEXT(stored=True, **_ta),
        organizations=TEXT(stored=True, **_ta),
        keywords=KEYWORD(stored=True, commas=True),
        dates=TEXT(stored=True),
        emails=TEXT(stored=True),
    )

    WHOOSH_DIR.mkdir(parents=True, exist_ok=True)

    if whoosh_index.exists_in(str(WHOOSH_DIR)):
        print(f"📖 Opening existing Whoosh index at {WHOOSH_DIR}")
        _whoosh_index = whoosh_index.open_dir(str(WHOOSH_DIR))
        missing_fields = sorted(_whoosh_missing_lexical_fields(_whoosh_index))
        if missing_fields:
            print(
                "⚠️  Existing Whoosh index uses an old schema missing fields "
                f"{', '.join(missing_fields)}. "
                "Run clear_indices() or a full re-ingest to rebuild lexical search."
            )
    else:
        print(f"🆕 Creating Whoosh index at {WHOOSH_DIR}")
        _whoosh_index = whoosh_index.create_in(str(WHOOSH_DIR), schema)

    return _whoosh_index


# ─── Indexación ──────────────────────────────────────────────────
def index_chunks(chunks: list[Chunk], clear_existing: bool = False) -> int:
    """
    Indexa una lista de chunks en ambos índices (ChromaDB + Whoosh).
    Devuelve el número de chunks indexados.
    """
    if not chunks:
        return 0

    if clear_existing:
        clear_indices()

    n_chroma = _index_chroma(chunks)
    n_whoosh = _index_whoosh(chunks)

    print(f"📇 Indexados: {n_chroma} chunks en ChromaDB, {n_whoosh} en Whoosh.")
    return n_chroma


def _index_chroma(chunks: list[Chunk]) -> int:
    """Indexa chunks en ChromaDB con embeddings."""
    model = _get_embedding_model()
    collection = _get_chroma_collection()

    # Preparar datos en batch
    ids = []
    documents = []
    metadatas = []
    embeddings_list = []

    for chunk in chunks:
        ids.append(chunk.chunk_id)
        documents.append(chunk.text)
        metadatas.append(chunk.metadata)

    # Generar embeddings en batch (mucho más rápido que uno a uno)
    print(f"🧮 Generando embeddings para {len(chunks)} chunks...")
    texts = [c.text for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=32)
    embeddings_list = [emb.tolist() for emb in embeddings]

    # Insertar en ChromaDB (en batches de 100 para evitar límites)
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        end = min(i + batch_size, len(ids))
        collection.upsert(
            ids=ids[i:end],
            documents=documents[i:end],
            metadatas=metadatas[i:end],
            embeddings=embeddings_list[i:end],
        )

    return len(ids)


def _index_whoosh(chunks: list[Chunk]) -> int:
    """Indexa chunks en Whoosh (BM25 full-text search)."""
    ix = _get_whoosh_index()
    has_folded_fields = _whoosh_has_folded_fields(ix)
    has_char3_field = _whoosh_has_char3_field(ix)
    has_num_norm_field = _whoosh_has_num_norm_field(ix)
    writer = ix.writer()
    committed = False

    try:
        # Replace all chunks for each incoming document so stale chunk rows do not
        # remain when a document is re-chunked with fewer fragments.
        for doc_id in sorted({chunk.doc_id or chunk.metadata["doc_id"] for chunk in chunks}):
            writer.delete_by_term("doc_id", doc_id)

        for chunk in chunks:
            meta = chunk.metadata
            payload = dict(
                chunk_id=chunk.chunk_id,
                doc_id=meta["doc_id"],
                title=meta["title"],
                content=chunk.text,
                doc_type=meta["doc_type"],
                language=meta["language"],
                filename=meta["filename"],
                section=meta["section"],
                level=meta["level"],
                persons=meta["persons"],
                organizations=meta["organizations"],
                keywords=meta["keywords"],
                dates=meta["dates"],
                emails=meta.get("emails", ""),
            )
            if has_folded_fields:
                payload["title_folded"] = fold_text(meta["title"])
                payload["content_folded"] = fold_text(chunk.text)
            if has_char3_field:
                payload["content_char3"] = " ".join(char_ngrams(fold_text(chunk.text), 3))
            if has_num_norm_field:
                payload["content_num_norm"] = normalize_numbers_in_text(
                    chunk.text,
                    language=chunk.language or meta.get("language"),
                )
            writer.update_document(**payload)

        writer.commit()
        committed = True
    finally:
        if not committed:
            writer.cancel()

    with ix.searcher() as searcher:
        print(f"📚 Whoosh doc_count after batch: {searcher.doc_count()}")
    return len(chunks)


def clear_indices():
    """
    Borra ambos índices para reindexar desde cero.

    ChromaDB: usa la API (delete_collection) en lugar de eliminar el directorio.
    Esto evita la carrera entre el hilo WAL de SQLite y el nuevo PersistentClient
    que causaba el error 'attempt to write a readonly database'.
    Si no hay cliente activo, el directorio se elimina como fallback.
    """
    global _chroma_client, _chroma_collection, _whoosh_index

    # ── ChromaDB: limpiar via API para mantener la conexión SQLite activa ──
    if _chroma_client is not None:
        try:
            _chroma_client.delete_collection(CHROMA_COLLECTION)
            # Dejar el cliente vivo: el próximo _get_chroma_collection()
            # llamará get_or_create sobre la misma conexión SQLite válida.
        except Exception as exc:
            print(f"  ⚠️  ChromaDB delete_collection fallido ({exc}). Borrando directorio.")
            _chroma_client = None
            import gc; gc.collect()
            if CHROMA_DIR.exists():
                shutil.rmtree(CHROMA_DIR)
        _chroma_collection = None  # forzar re-create en el siguiente acceso
    else:
        # Sin cliente activo → borrado seguro de directorio
        _chroma_collection = None
        import gc; gc.collect()
        if CHROMA_DIR.exists():
            shutil.rmtree(CHROMA_DIR)

    # ── Whoosh: siempre borrar directorio (safe, no background threads) ──
    if WHOOSH_DIR.exists():
        shutil.rmtree(WHOOSH_DIR)
    _whoosh_index = None
    print("🗑️  Índices borrados.")


def find_duplicates(threshold: float = 0.85) -> list[dict]:
    """
    Detecta documentos near-duplicados usando embeddings mean-pooled por documento.

    Estrategia:
    1. Obtener todos los chunks de ChromaDB con sus embeddings.
    2. Agrupar chunks por doc_id y calcular el embedding medio (mean-pool).
    3. Calcular similitud coseno entre todos los pares de documentos.
    4. Retornar pares con similitud >= threshold, ordenados de mayor a menor.

    Args:
        threshold: Umbral de similitud coseno (0–1). Por defecto 0.85.

    Returns:
        Lista de dicts con doc_a, doc_b, similarity.
    """
    import numpy as np

    collection = _get_chroma_collection()
    results = collection.get(include=["embeddings", "metadatas"])

    if not results["ids"]:
        return []

    # Agrupar embeddings por doc_id
    doc_embs: dict[str, list[list[float]]] = {}
    doc_meta: dict[str, dict] = {}

    for chunk_id, meta, emb in zip(
        results["ids"], results["metadatas"], results["embeddings"]
    ):
        doc_id = meta.get("doc_id", chunk_id)
        if doc_id not in doc_embs:
            doc_embs[doc_id] = []
            doc_meta[doc_id] = meta
        doc_embs[doc_id].append(emb)

    if len(doc_embs) < 2:
        return []

    # Mean-pool: un vector por documento
    doc_ids = list(doc_embs.keys())
    doc_vectors = {
        did: np.mean(np.array(embs), axis=0)
        for did, embs in doc_embs.items()
    }

    duplicates: list[dict] = []

    for i in range(len(doc_ids)):
        for j in range(i + 1, len(doc_ids)):
            a, b = doc_ids[i], doc_ids[j]
            va, vb = doc_vectors[a], doc_vectors[b]
            norm = np.linalg.norm(va) * np.linalg.norm(vb)
            sim = float(np.dot(va, vb) / (norm + 1e-9))
            if sim >= threshold:
                duplicates.append({
                    "doc_a": {
                        "doc_id": a,
                        "filename": doc_meta[a].get("filename", ""),
                        "title": doc_meta[a].get("title", ""),
                    },
                    "doc_b": {
                        "doc_id": b,
                        "filename": doc_meta[b].get("filename", ""),
                        "title": doc_meta[b].get("title", ""),
                    },
                    "similarity": round(sim, 4),
                })

    return sorted(duplicates, key=lambda x: x["similarity"], reverse=True)
