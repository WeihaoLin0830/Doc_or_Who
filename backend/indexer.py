"""
indexer.py — Indexa chunks en ChromaDB (semántico) y Whoosh (BM25).

Dos índices separados, alimentados con los mismos chunks.
El searcher.py se encarga de fusionar resultados de ambos.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from backend.config import (
    CHROMA_DIR,
    CHROMA_COLLECTION,
    EMBEDDING_MODEL,
    WHOOSH_DIR,
)
from backend.models import Chunk

# ─── Lazy loading ────────────────────────────────────────────────
_embedding_model = None
_chroma_collection = None
_whoosh_index = None


def _get_embedding_model():
    """Carga el modelo de embeddings solo cuando se necesita."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        print(f"📦 Cargando modelo de embeddings: {EMBEDDING_MODEL}...")
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL)
        print("✅ Modelo cargado.")
    return _embedding_model


def _get_chroma_collection():
    """Obtiene (o crea) la colección de ChromaDB."""
    global _chroma_collection
    if _chroma_collection is None:
        import chromadb
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _chroma_collection = client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
    return _chroma_collection


def _get_whoosh_index(create: bool = False):
    """Obtiene (o crea) el índice Whoosh."""
    global _whoosh_index
    from whoosh import index as whoosh_index
    from whoosh.fields import Schema, TEXT, ID, KEYWORD

    schema = Schema(
        chunk_id=ID(stored=True, unique=True),
        doc_id=ID(stored=True),
        title=TEXT(stored=True),
        content=TEXT(stored=True),
        doc_type=TEXT(stored=True),
        filename=TEXT(stored=True),
        section=TEXT(stored=True),
        level=TEXT(stored=True),
        persons=TEXT(stored=True),
        organizations=TEXT(stored=True),
        keywords=KEYWORD(stored=True, commas=True),
        dates=TEXT(stored=True),
    )

    WHOOSH_DIR.mkdir(parents=True, exist_ok=True)

    if create or not whoosh_index.exists_in(str(WHOOSH_DIR)):
        _whoosh_index = whoosh_index.create_in(str(WHOOSH_DIR), schema)
    else:
        _whoosh_index = whoosh_index.open_dir(str(WHOOSH_DIR))

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
    ix = _get_whoosh_index(create=True)
    writer = ix.writer()

    for chunk in chunks:
        meta = chunk.metadata
        writer.update_document(
            chunk_id=chunk.chunk_id,
            doc_id=meta["doc_id"],
            title=meta["title"],
            content=chunk.text,
            doc_type=meta["doc_type"],
            filename=meta["filename"],
            section=meta["section"],
            level=meta["level"],
            persons=meta["persons"],
            organizations=meta["organizations"],
            keywords=meta["keywords"],
            dates=meta["dates"],
        )

    writer.commit()
    return len(chunks)


def clear_indices():
    """Borra ambos índices para reindexar desde cero."""
    global _chroma_collection, _whoosh_index

    if CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)
    if WHOOSH_DIR.exists():
        shutil.rmtree(WHOOSH_DIR)

    _chroma_collection = None
    _whoosh_index = None
    print("🗑️  Índices borrados.")
