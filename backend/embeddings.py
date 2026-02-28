from __future__ import annotations

import hashlib

import numpy as np

from backend.config import get_settings
from backend.logging import get_logger, log_event

LOGGER = get_logger(__name__)
_provider = None


class HashingEmbeddingProvider:
    def __init__(self, dimension: int) -> None:
        self.name = "hashing"
        self.model_name = f"hashing-{dimension}"
        self.dimension = dimension

    def embed(self, texts: list[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row_index, text in enumerate(texts):
            tokens = text.lower().split()
            if not tokens:
                continue
            for token in tokens:
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "little") % self.dimension
                sign = -1.0 if digest[4] % 2 else 1.0
                matrix[row_index, index] += sign
            norm = np.linalg.norm(matrix[row_index])
            if norm:
                matrix[row_index] /= norm
        return matrix


class SentenceTransformerEmbeddingProvider:
    def __init__(self, model_name: str) -> None:
        self.name = "sentence_transformers"
        self.model_name = model_name
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self._model.encode(texts, show_progress_bar=False), dtype=np.float32)


class OpenAIEmbeddingProvider:
    def __init__(self, api_key: str, model_name: str) -> None:
        self.name = "openai"
        self.model_name = model_name
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)

    def embed(self, texts: list[str]) -> np.ndarray:
        response = self._client.embeddings.create(model=self.model_name, input=texts)
        return np.asarray([row.embedding for row in response.data], dtype=np.float32)


def get_embedding_provider():
    global _provider
    if _provider is not None:
        return _provider
    settings = get_settings()
    if settings.embedding_provider == "hashing":
        _provider = HashingEmbeddingProvider(settings.hashing_dimension)
        return _provider
    if settings.embedding_provider == "openai" and settings.openai_api_key:
        _provider = OpenAIEmbeddingProvider(settings.openai_api_key, settings.openai_embedding_model)
        return _provider
    try:
        _provider = SentenceTransformerEmbeddingProvider(settings.embedding_model)
    except Exception as exc:
        log_event(LOGGER, "embedding_provider_fallback", "Falling back to hashing embeddings", error=str(exc))
        _provider = HashingEmbeddingProvider(settings.hashing_dimension)
    return _provider


def reset_embedding_provider_cache() -> None:
    global _provider
    _provider = None
