# DocumentWho

DocumentWho is a local-first document search platform built around chunk-level indexing, hybrid retrieval, metadata filtering, entity enrichment, a sparse knowledge graph, and PageRank-aware ranking. The default runtime stack is `FastAPI + SQLite FTS5 + FAISS`.

## Features

- Recursive ingest from `dataset_default/` or any configured directory.
- Incremental processing using `sha256 + mtime`.
- Safe extraction for `PDF`, `DOCX`, `PPTX`, `TXT`, `MD`, `CSV`, and `XLSX`.
- Chunk-level indexing with stored offsets for highlighting.
- Hybrid retrieval: `FTS5` keyword search + vector search + PageRank contribution.
- Metadata and entity facets.
- Knowledge graph endpoints for documents and entities.
- Per-document processing status with `processed`, `skipped`, `failed`, `needs_ocr`, `unsupported`, and `deleted`.
- Upload endpoint with filename sanitization and immediate indexing.
- OCR for scanned PDFs through Tesseract when available.

## Setup

```bash
make setup
```

This creates `venv`, installs runtime and dev dependencies, and applies the initial Alembic migration.

If you want OCR for scanned PDFs, install the system Tesseract binary as well. On Debian or Ubuntu:

```bash
sudo apt install tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng
```

## Run

Ingest the default corpus:

```bash
make ingest
```

Start the API and static UI:

```bash
make run
```

Or ingest and start everything in one command:

```bash
make start
```

Run tests:

```bash
make test
```

Run lint:

```bash
make lint
```

## Sample API Usage

Search:

```bash
curl "http://127.0.0.1:8000/search?q=Aurora&top_k=5"
```

Search with filters:

```bash
curl "http://127.0.0.1:8000/search?q=budget&ext=xlsx&date_from=2024-01-01"
```

Fetch facets:

```bash
curl "http://127.0.0.1:8000/facets"
```

Fetch one document:

```bash
curl "http://127.0.0.1:8000/documents/<doc_id>"
```

Fetch document graph:

```bash
curl "http://127.0.0.1:8000/graph/doc/<doc_id>"
```

Rebuild PageRank only:

```bash
make pagerank
```

Upload a document:

```bash
curl -F "file=@./some_note.txt" http://127.0.0.1:8000/upload
```

The web UI also exposes a file picker in the main search screen. Uploaded files are stored under `uploads/` and ingested immediately.

## Configuration

Copy `.env.example` values into your environment as needed.

Important variables:

- `DOCUMENTWHO_DATASET_DIR`
- `DOCUMENTWHO_DATA_DIR`
- `DOCUMENTWHO_UPLOAD_DIR`
- `DOCUMENTWHO_DATABASE_URL`
- `DOCUMENTWHO_EMBEDDING_PROVIDER`
- `DOCUMENTWHO_EMBEDDING_MODEL`
- `DOCUMENTWHO_SPACY_MODEL`
- `DOCUMENTWHO_ENABLE_OCR`
- `DOCUMENTWHO_OCR_LANGUAGES`
- `DOCUMENTWHO_TESSERACT_CMD`

## Embedding Providers

- `sentence_transformers`
  Default runtime provider.
- `hashing`
  Deterministic local fallback used in tests and low-friction smoke runs.
- `openai`
  Optional. Requires `OPENAI_API_KEY`.

## Troubleshooting

- If the spaCy model is not installed, ingestion still works. The system falls back to the rule-based entity extractor.
- If a PDF contains no native extractable text, the system attempts OCR with Tesseract when OCR is enabled and available.
- If OCR is disabled, Tesseract is missing, or OCR still yields no text, the document is marked `needs_ocr`.
- If `make ingest` reports many `skipped` files, that is expected when the files already exist in the index and their `sha256 + mtime` did not change.
- The search UI accepts empty text queries, so you can browse by facets or entity filters only.
- `make test` sets `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` so unrelated globally installed pytest plugins do not interfere with the repo test suite.

## Docs

- [Architecture](docs/ARCHITECTURE.md)
- [Audit Report](docs/AUDIT_REPORT.md)
