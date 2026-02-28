# Architecture

## Module Boundaries

- `backend/api.py`
  FastAPI entrypoint, route registration, upload handling, and compatibility aliases under `/api/*`.
- `backend/config.py`
  Environment-driven settings with cache reset support for tests.
- `backend/db.py`
  SQLite engine/session bootstrap and FTS trigger setup.
- `backend/models.py`
  SQLAlchemy models for documents, chunks, embeddings, entities, edges, and pagerank scores.
- `backend/repositories.py`
  Stable DB operations: scan/upsert metadata, replace document artifacts, filter chunks, and persist graph outputs.
- `backend/parsers.py` and `backend/extractors/*`
  Format-specific extraction with safe Office zip validation.
- `backend/cleaning.py`
  Text cleanup and language detection.
- `backend/chunker.py`
  Heading-aware chunking for narrative text and row/group/document chunking for tabular data.
- `backend/enrichment.py`
  Rule-based entity extraction, YAKE-style tags, optional spaCy augmentation.
- `backend/embeddings.py`
  `hashing`, `sentence_transformers`, and optional `openai` embedding providers.
- `backend/vector.py`
  FAISS-backed vector rebuild and query path.
- `backend/fts.py`
  FTS5 query construction and facet queries.
- `backend/graph.py`
  Sparse graph rebuild and graph exploration responses.
- `backend/pagerank.py`
  Batch PageRank over persisted edges.
- `backend/ingest.py`
  Incremental orchestration, per-document error isolation, and batch rebuild coordination.
- `backend/searcher.py`
  Hybrid retrieval, score normalization, document grouping, and explanations.
- `backend/cli.py`
  Operational entrypoints for ingest, pagerank, search, and index rebuilds.

## Ingest Flow

1. Scan a configured directory recursively.
2. Skip hidden files and symlinks.
3. Compute `sha256`, `mtime`, size, MIME, and deterministic `doc_id`.
4. Upsert document metadata.
5. If unchanged and already searchable, mark `skipped`.
6. Extract text and metadata with safe format-specific handlers.
7. If a PDF has no native text, attempt OCR through the configured OCR provider.
8. If OCR is unavailable or still yields no text, mark `needs_ocr`.
9. Clean text and detect language.
10. Chunk the cleaned text at chunk level with offsets.
11. Extract entities and tags per chunk.
12. Generate embeddings for all chunks in batch.
13. Replace chunks, chunk embeddings, and chunk entities inside one per-document transaction.
14. Continue even if one file fails.
15. After the batch, rebuild the vector index, graph edges, and pagerank scores if the active corpus changed.

## Query Flow

1. `GET /search` receives a free-text query and optional metadata/entity filters.
2. FTS5 returns lexical candidates with snippets and BM25 scores.
3. FAISS returns semantic candidates by cosine similarity.
4. Candidate sets are merged on `chunk_id`.
5. The service loads chunk/document/entity metadata for the merged set.
6. Keyword, semantic, and pagerank scores are normalized.
7. Final chunk score uses weighted combination:
   `0.55 * keyword + 0.35 * semantic + 0.10 * pagerank`
8. Chunks are grouped by document.
9. Each document result returns up to 3 snippets and a short explanation.
10. Facets are calculated from the filtered active corpus.

## Storage Design

Primary data:

- SQLite database at `data/documentwho.db`
- FAISS index at `data/vector/chunks.faiss`
- FAISS row mapping at `data/vector/mapping.json`

Relational entities:

- `documents`
- `chunks`
- `chunk_embeddings`
- `entities`
- `chunk_entities`
- `edges`
- `pagerank_scores`

FTS:

- SQLite `chunks_fts` virtual table
- insert/update/delete triggers on `chunks`

Why this split:

- SQLite keeps local setup simple and provides transactional document metadata plus FTS5.
- FAISS gives fast dense retrieval without needing a server process.
- Raw vectors remain stored in SQLite so the FAISS index can be rebuilt deterministically.

## Graph and PageRank Pipeline

Graph edges:

- `doc -> chunk` via `contains`
- `chunk -> entity` via `mentions`
- `chunk <-> chunk` via `similar`

Similarity policy:

- top `K=15`
- cosine threshold `>= 0.78`
- cross-document only
- undirected similarity stored once per pair

PageRank:

- Convert every stored edge to two directed weighted edges in NetworkX.
- Run batch pagerank.
- Persist scores by node type and node id.
- Normalize chunk scores at query time with `log1p`.

## Scaling Path

Current MVP:

- SQLite
- FTS5
- FAISS
- synchronous batch rebuilds

Scaling without redesign:

1. Replace SQLite with Postgres while keeping the repository interfaces.
2. Swap FAISS for `pgvector`, `Qdrant`, or another dedicated vector service behind `backend/vector.py`.
3. Move keyword search to Postgres `tsvector` or OpenSearch behind `backend/fts.py`.
4. Move ingest orchestration to a background worker queue while preserving `IngestService`.
5. Replace batch NetworkX pagerank with a scheduled graph job over a graph database or analytics engine if corpus size requires it.
