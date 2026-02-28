from __future__ import annotations

from backend.db import session_scope
from backend.repositories import iter_active_chunk_embeddings
from backend.types import ChunkEmbeddingRecord
from backend.vector import get_vector_index


def rebuild_vector_index():
    with session_scope() as session:
        rows = iter_active_chunk_embeddings(session)
    payloads = [ChunkEmbeddingRecord(chunk_id=chunk_id, vector=vector, provider="stored", model_name="stored") for chunk_id, _doc_id, vector in rows]
    return get_vector_index().rebuild(payloads)
