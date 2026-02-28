"""
config.py — Rutas, constantes y configuración central.

Todas las rutas y parámetros del proyecto están aquí.
Si cambias la ubicación de datos o el modelo de embeddings, solo tocas este fichero.
"""

from pathlib import Path

# ─── Rutas del proyecto ───────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent          # DocumentWho/
DATASET_DIR = ROOT_DIR / "dataset_default"                 # Datos originales
DATA_DIR = ROOT_DIR / "data"                               # Datos procesados
WHOOSH_DIR = DATA_DIR / "whoosh_index"                     # Índice BM25
CHROMA_DIR = DATA_DIR / "chroma_db"                        # Índice vectorial
GRAPH_PATH = DATA_DIR / "entity_graph.json"                # Grafo de entidades
UPLOAD_DIR = ROOT_DIR / "uploads"                          # Documentos subidos

# ─── Modelo de embeddings ────────────────────────────────────────
# Multilingual, rápido en CPU, 384 dimensiones, soporta español nativo.
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# ─── ChromaDB ─────────────────────────────────────────────────────
CHROMA_COLLECTION = "documentwho"

# ─── Chunking ─────────────────────────────────────────────────────
MAX_CHUNK_TOKENS = 512        # Tamaño máximo de un chunk (en tokens aprox)
CHUNK_OVERLAP_TOKENS = 50     # Solapamiento entre chunks contiguos

# ─── Búsqueda ─────────────────────────────────────────────────────
SEARCH_TOP_K = 20             # Resultados por índice antes de fusionar
FINAL_TOP_K = 10              # Resultados finales después de RRF
RRF_K = 60                    # Constante para Reciprocal Rank Fusion
SEMANTIC_MIN_SCORE = 0.30     # Umbral mínimo de similitud coseno (0=nada, 1=exacto)
MAX_CHUNKS_PER_DOC = 3        # Máximo de chunks del mismo documento en resultados

# ─── NER / spaCy ──────────────────────────────────────────────────
SPACY_MODEL = "es_core_news_md"

# ─── Keywords ─────────────────────────────────────────────────────
YAKE_MAX_KEYWORDS = 8
YAKE_LANGUAGE = "es"

# ─── LLM (Groq) ───────────────────────────────────────────────────
import os
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.1-8b-instant"

# ─── DuckDB ───────────────────────────────────────────────────────
DUCKDB_PATH = DATA_DIR / "tables.duckdb"
