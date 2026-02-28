"""
ingest.py — Orquestador del pipeline de ingestión.

Flujo por cada fichero:
  1. parse  → extraer texto crudo
  2. clean  → normalizar texto
  3. detect_language → idioma
  4. classify → tipo de documento
  5. enrich  → NER, keywords, resumen, título
  6. chunk   → fragmentar adaptativamente
  7. index   → insertar en ChromaDB + Whoosh
  8. graph   → actualizar grafo de entidades

Ejecutar:  python -m backend.ingestion.ingest
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from backend.config import DATASET_DIR, UPLOAD_DIR
from backend.models import Document
from backend.ingestion.parsers import parse_file
from backend.ingestion.cleaning import clean_text, detect_language
from backend.ingestion.classifier import classify_document
from backend.ingestion.enrichment import enrich_document
from backend.ingestion.chunker import chunk_document
from backend.search.indexer import index_chunks, clear_indices
from backend.graph import build_graph


# ─── Extensiones soportadas ──────────────────────────────────────
SUPPORTED_EXTENSIONS = {".txt", ".csv", ".pdf", ".docx", ".xlsx", ".xls"}


def _file_id(filepath: Path) -> str:
    """Genera un ID determinista a partir de la ruta relativa del fichero."""
    return hashlib.md5(filepath.name.encode()).hexdigest()[:12]


def ingest_file(filepath: Path) -> Document | None:
    """
    Procesa un solo fichero y devuelve el Document enriquecido.
    Los chunks se indexan como efecto secundario.
    Retorna None si el fichero no es soportable.
    """
    ext = filepath.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        print(f"⏭️  Ignorando {filepath.name} (extensión {ext})")
        return None

    print(f"📄 Procesando: {filepath.name}")

    # 1. Parsear
    text, dataframe = parse_file(filepath)
    if not text.strip():
        print(f"⚠️  Sin contenido útil: {filepath.name}")
        return None

    # 2. Limpiar
    text = clean_text(text)

    # 3. Detectar idioma
    lang = detect_language(text)

    # 4. Clasificar
    doc_type = classify_document(text, filepath.name, dataframe)

    # 5. Crear documento base
    doc = Document(
        doc_id=_file_id(filepath),
        filename=filepath.name,
        filepath=str(filepath),
        raw_text=text,
        doc_type=doc_type,
        language=lang,
    )

    # 6. Enriquecer (NER, keywords, resumen, título)
    doc = enrich_document(doc)
    print(f"   Tipo: {doc.doc_type} | Idioma: {doc.language} | "
          f"Título: {doc.title[:50]}...")

    # 7. Fragmentar
    chunks = chunk_document(doc, df=dataframe)
    print(f"   {len(chunks)} chunks generados")

    # 8. Indexar chunks
    index_chunks(chunks)

    return doc


def ingest_directory(directory: Path) -> list[Document]:
    """Procesa todos los ficheros de un directorio."""
    files = sorted(
        f for f in directory.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    print(f"\n{'='*60}")
    print(f"🚀 Ingestando {len(files)} ficheros de {directory.name}/")
    print(f"{'='*60}\n")

    documents = []
    for filepath in files:
        doc = ingest_file(filepath)
        if doc:
            documents.append(doc)
        print()

    return documents


def run_full_pipeline():
    """
    Pipeline completo:
    1. Limpia índices previos
    2. Ingesta todos los ficheros del dataset
    3. Construye el grafo de entidades
    """
    t0 = time.time()

    # Limpiar índices previos
    print("🧹 Limpiando índices previos...")
    clear_indices()

    # Ingestar dataset principal
    documents = ingest_directory(DATASET_DIR)

    # Ingestar uploads si existen
    if UPLOAD_DIR.exists() and any(UPLOAD_DIR.iterdir()):
        uploads = ingest_directory(UPLOAD_DIR)
        documents.extend(uploads)

    # Construir grafo de entidades
    print(f"\n{'='*60}")
    print("🕸️  Construyendo grafo de entidades...")
    build_graph(documents)

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"✅ Pipeline completado en {elapsed:.1f}s")
    print(f"   {len(documents)} documentos procesados")
    print(f"{'='*60}")

    return documents


# ─── Ejecución directa ───────────────────────────────────────────
if __name__ == "__main__":
    run_full_pipeline()
