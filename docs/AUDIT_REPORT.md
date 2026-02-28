# Audit Report

## A. Existing Implementation That Was Correct

- The repo already had a working FastAPI entrypoint and a static frontend.
- PDF and DOCX extraction existed and proved the initial prototype concept.
- The prototype already understood chunk-level search as the right retrieval granularity.
- The prior implementation had the right high-level ambition around hybrid retrieval and entity graph exploration.
- The bundled dataset was useful and realistic enough to validate the rebuild against multiple document types and scanned-PDF edge cases.

## B. Missing Versus Requirements

- No relational persistence model for documents, chunks, entities, edges, or pagerank.
- No migrations, Makefile, README, architecture doc, or audit report.
- No incremental ingest based on `sha256 + mtime`.
- No `PPTX` support.
- No chunk offsets for highlighting.
- No PageRank job or pagerank-aware final ranking.
- No graph stored in queryable DB tables.
- No API routes for the required root-path contract with grouped search results and explanations.
- No tests or smoke verification path.
- No upload hardening and no Office zip safety checks.

## C. Incorrect or Fragile Behavior

- The previous smoke ingest failed hard on `.xlsx` because `openpyxl` was not declared.
- The old pipeline cleared search indexes and rebuilt from scratch every run.
- A single parse failure aborted the batch instead of recording document status and continuing.
- Two sample PDFs extracted zero text and were effectively dropped instead of being tracked as `needs_ocr`.
- The graph was stored separately from the search indexes, so stale graph state could outlive failed ingest runs.
- Search ranking used flat chunk-level RRF output and did not expose weighted lexical, semantic, and pagerank explanations.
- Status handling was not durable enough for operational debugging.

## D. What Changed and Why

- Replaced ad hoc dataclasses with a real SQLite + SQLAlchemy data model.
- Added Alembic migration `0001_initial` and FTS5 triggers.
- Replaced Whoosh and Chroma with SQLite FTS5 and FAISS so the MVP remains local-first while using one relational source of truth plus one vector index.
- Added safe extractors for `PDF`, `DOCX`, `PPTX`, `TXT`, `MD`, `CSV`, and `XLSX`.
- Added Office zip validation to reject macro-enabled formats and unsafe archive contents.
- Added deterministic chunking with overlap and stored offsets.
- Added baseline-always-on enrichment for entities and tags, plus optional spaCy augmentation.
- Added pluggable embeddings with `hashing`, `sentence_transformers`, and optional `openai`.
- Added a sparse graph build with `contains`, `mentions`, and `similar` edges.
- Added a NetworkX PageRank batch job and pagerank-aware ranking.
- Added grouped search results with snippets, highlights, retrieval-mode flags, and ranking explanations.
- Added upload handling that sanitizes filenames and preserves the user-facing original upload name.
- Added Tesseract-backed OCR for scanned PDFs, while keeping graceful fallback to `needs_ocr` when OCR is disabled or unavailable.
- Added unit and integration tests and isolated the test runner from unrelated system pytest plugins.

## E. End-to-End Runbook

### Setup

```bash
make setup
```

### Ingest

```bash
make ingest
```

### Run API

```bash
make run
```

### Smoke Requests

```bash
curl "http://127.0.0.1:8000/search?q=Aurora&top_k=5"
curl "http://127.0.0.1:8000/facets"
curl "http://127.0.0.1:8000/documents/<doc_id>"
curl "http://127.0.0.1:8000/graph/doc/<doc_id>"
```

### Observed Verification Notes

- The rebuilt ingest completed successfully against the bundled dataset when run with the local hashing provider for quick smoke verification.
- That run produced `23 processed` documents and `2 needs_ocr` documents from scanned PDFs, with no batch abort.
- The smoke `GET /search?q=Aurora&top_k=5` request returned 5 grouped results, with `email_seguimiento_aurora.txt` ranked first.
- `make lint`, `make test`, `make ingest`, and a timed `make run` startup check all completed successfully in the rebuilt repo.
- `make test` is backed by 11 unit/integration tests covering extraction, chunking, incremental skipping, search, facets, graph endpoints, upload indexing, and ranking math.
