from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np


@dataclass(slots=True)
class ExtractionResult:
    path: Path
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    table_rows: list[dict[str, Any]] = field(default_factory=list)
    row_spans: list[tuple[int, int]] = field(default_factory=list)
    table_group_key: str | None = None
    needs_ocr: bool = False


@dataclass(slots=True)
class ChunkPayload:
    chunk_index: int
    text: str
    token_count: int
    char_start: int
    char_end: int
    section_title: str | None = None
    entity_texts: str = ""
    tag_texts: str = ""


@dataclass(slots=True)
class ExtractedEntity:
    canonical_text: str
    display_text: str
    type: str
    confidence: float
    importance_score: float = 0.0


@dataclass(slots=True)
class ChunkEmbeddingRecord:
    chunk_id: str
    vector: np.ndarray
    provider: str
    model_name: str


@dataclass(slots=True)
class VectorHit:
    chunk_id: str
    similarity: float


@dataclass(slots=True)
class VectorBuildStats:
    count: int
    dimension: int
    path: str


@dataclass(slots=True)
class GraphBuildStats:
    edge_count: int
    node_count: int
    similar_edge_count: int


@dataclass(slots=True)
class SearchParams:
    query: str
    ext: str | None = None
    language: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    entity: str | None = None
    tag: str | None = None
    top_k: int = 10
    debug: bool = False


@dataclass(slots=True)
class IngestStats:
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    needs_ocr: int = 0
    deleted: int = 0
    unsupported: int = 0
    total_seen: int = 0
    changed: bool = False


class Extractor(Protocol):
    def extract(self, path: Path) -> ExtractionResult:
        raise NotImplementedError


class EmbeddingProvider(Protocol):
    name: str
    model_name: str

    def embed(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError


class VectorIndex(Protocol):
    def rebuild(self, chunks: list[ChunkEmbeddingRecord]) -> VectorBuildStats:
        raise NotImplementedError

    def search(self, query_vector: np.ndarray, top_k: int, overfetch: int) -> list[VectorHit]:
        raise NotImplementedError

