from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FacetBucket(BaseModel):
    value: str
    count: int


class SearchFacets(BaseModel):
    ext: list[FacetBucket] = Field(default_factory=list)
    language: list[FacetBucket] = Field(default_factory=list)
    status: list[FacetBucket] = Field(default_factory=list)
    tags: list[FacetBucket] = Field(default_factory=list)
    entities_by_type: dict[str, list[FacetBucket]] = Field(default_factory=dict)


class ChunkSnippet(BaseModel):
    chunk_id: str
    section_title: str | None = None
    text: str
    highlight: str
    keyword_score: float
    semantic_score: float
    pagerank_score: float
    score: float
    char_start: int
    char_end: int


class DocumentSearchResult(BaseModel):
    doc_id: str
    filename: str
    title: str | None = None
    ext: str
    language: str | None = None
    status: str
    score: float
    best_chunk_id: str
    matched_terms: list[str] = Field(default_factory=list)
    matched_entities: list[str] = Field(default_factory=list)
    keyword_score: float
    semantic_score: float
    pagerank_score: float
    ranking_breakdown: dict[str, float] = Field(default_factory=dict)
    retrieval_modes: list[str] = Field(default_factory=list)
    why_this_result: str
    snippets: list[ChunkSnippet] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    filters: dict[str, Any]
    results: list[DocumentSearchResult]
    facets: SearchFacets
    debug: dict[str, Any] | None = None


class IngestResponse(BaseModel):
    source_dir: str
    processed: int
    skipped: int
    failed: int
    needs_ocr: int
    deleted: int
    unsupported: int
    total_seen: int
    duration_seconds: float


class ChunkDetail(BaseModel):
    chunk_id: str
    chunk_index: int
    text: str
    token_count: int
    char_start: int
    char_end: int
    section_title: str | None = None
    entity_texts: str = ""
    tag_texts: str = ""


class DocumentDetailResponse(BaseModel):
    doc_id: str
    filename: str
    title: str | None = None
    ext: str
    mime: str
    language: str | None = None
    status: str
    error: str | None = None
    author: str | None = None
    metadata: dict[str, Any]
    chunks: list[ChunkDetail] = Field(default_factory=list)


class DocumentSummary(BaseModel):
    doc_id: str
    filename: str
    title: str | None = None
    ext: str
    status: str
    updated_at: str


class DocumentsListResponse(BaseModel):
    count: int
    documents: list[DocumentSummary]


class GraphNode(BaseModel):
    id: str
    label: str
    node_type: str
    pagerank: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    edge_type: str
    weight: float


class GraphResponse(BaseModel):
    root_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class HealthResponse(BaseModel):
    status: str
    database_ready: bool
    vector_ready: bool


class IngestRequest(BaseModel):
    source_dir: str | None = None
    rebuild_graph: bool = True
    recompute_pagerank: bool = True
