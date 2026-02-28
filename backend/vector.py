from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from backend.config import get_settings
from backend.logging import get_logger, log_event
from backend.types import ChunkEmbeddingRecord, VectorBuildStats, VectorHit

LOGGER = get_logger(__name__)

try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover - fallback is tested instead
    faiss = None


class FaissVectorIndex:
    def __init__(self) -> None:
        self._index = None
        self._mapping: list[str] = []

    def _mapping_path(self) -> Path:
        return get_settings().vector_mapping_path

    def _index_path(self) -> Path:
        return get_settings().vector_index_path

    def _load(self) -> None:
        if self._index is not None:
            return
        mapping_path = self._mapping_path()
        index_path = self._index_path()
        if not mapping_path.exists() or not index_path.exists():
            self._index = None
            self._mapping = []
            return
        self._mapping = json.loads(mapping_path.read_text())
        if faiss is not None:
            self._index = faiss.read_index(str(index_path))
        else:
            self._index = np.load(index_path, allow_pickle=False)

    def rebuild(self, chunks: list[ChunkEmbeddingRecord]) -> VectorBuildStats:
        settings = get_settings()
        settings.ensure_directories()
        if not chunks:
            if self._index_path().exists():
                self._index_path().unlink()
            self._mapping_path().write_text("[]")
            self._index = None
            self._mapping = []
            return VectorBuildStats(count=0, dimension=0, path=str(self._index_path()))

        matrix = np.asarray([chunk.vector for chunk in chunks], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix = matrix / norms
        self._mapping = [chunk.chunk_id for chunk in chunks]
        if faiss is not None:
            index = faiss.IndexFlatIP(matrix.shape[1])
            index.add(matrix)
            faiss.write_index(index, str(self._index_path()))
            self._index = index
        else:
            np.save(self._index_path(), matrix, allow_pickle=False)
            self._index = matrix
        self._mapping_path().write_text(json.dumps(self._mapping))
        log_event(LOGGER, "vector_rebuild", "Vector index rebuilt", count=len(chunks), dimension=matrix.shape[1])
        return VectorBuildStats(count=len(chunks), dimension=matrix.shape[1], path=str(self._index_path()))

    def search(self, query_vector: np.ndarray, top_k: int, overfetch: int) -> list[VectorHit]:
        self._load()
        if self._index is None or not self._mapping:
            return []
        query = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)
        norm = np.linalg.norm(query, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        query = query / norm
        limit = min(max(top_k, overfetch), len(self._mapping))
        if faiss is not None:
            if query.shape[1] != self._index.d:
                log_event(
                    LOGGER,
                    "vector_dimension_mismatch",
                    "Skipping semantic search because query and index dimensions do not match",
                    query_dim=int(query.shape[1]),
                    index_dim=int(self._index.d),
                )
                return []
            scores, indices = self._index.search(query, limit)
            pairs = zip(indices[0], scores[0], strict=True)
        else:
            if query.shape[1] != self._index.shape[1]:
                log_event(
                    LOGGER,
                    "vector_dimension_mismatch",
                    "Skipping semantic search because query and index dimensions do not match",
                    query_dim=int(query.shape[1]),
                    index_dim=int(self._index.shape[1]),
                )
                return []
            scores = (self._index @ query.T).reshape(-1)
            sorted_indices = np.argsort(scores)[::-1][:limit]
            pairs = [(int(index), float(scores[index])) for index in sorted_indices]
        results: list[VectorHit] = []
        for index, score in pairs:
            if index < 0:
                continue
            results.append(VectorHit(chunk_id=self._mapping[index], similarity=float(score)))
        return results

    def is_ready(self) -> bool:
        self._load()
        return bool(self._mapping)


_vector_index = FaissVectorIndex()


def get_vector_index() -> FaissVectorIndex:
    return _vector_index


def reset_vector_index_cache() -> None:
    global _vector_index
    _vector_index = FaissVectorIndex()
