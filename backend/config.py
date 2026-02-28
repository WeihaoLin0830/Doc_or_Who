"""
config.py — Rutas, constantes y configuración central.

Todas las rutas y parámetros del proyecto están aquí.
Si cambias la ubicación de datos o el modelo de embeddings, solo tocas este fichero.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ─── Rutas del proyecto ───────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent          # DocumentWho/
load_dotenv(ROOT_DIR / ".env")
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
CHROMA_TELEMETRY_ENABLED = os.getenv("CHROMA_TELEMETRY_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
os.environ.setdefault(
    "ANONYMIZED_TELEMETRY",
    "TRUE" if CHROMA_TELEMETRY_ENABLED else "FALSE",
)

# ─── Chunking ─────────────────────────────────────────────────────
MAX_CHUNK_TOKENS = 512        # Tamaño máximo de un chunk (en tokens aprox)
CHUNK_OVERLAP_TOKENS = 50     # Solapamiento entre chunks contiguos

# ─── Búsqueda ─────────────────────────────────────────────────────
SEARCH_TOP_K = 20             # Resultados por índice antes de fusionar
FINAL_TOP_K = 10              # Resultados finales después de RRF
RRF_K = 60                    # Constante para Reciprocal Rank Fusion
SEMANTIC_MIN_SCORE = float(os.getenv("SEMANTIC_MIN_SCORE", "0.36"))
                              # MiniLM-L12-v2 sobre corpus corporativo español:
                              # Calibrado: palabras ajenas al corpus puntúan ≤0.355 (p.ej. "espagueti"→0.354)
                              # Queries semánticas reales puntúan ≥0.41 (p.ej. "trabajo remoto"→0.461)
                              # Umbral 0.36 separa ruido semántico de coincidencias reales
MAX_CHUNKS_PER_DOC = 3        # Máximo de chunks del mismo documento en resultados
CHAR3_MIN_COVERAGE = float(os.getenv("CHAR3_MIN_COVERAGE", "0.40"))
                              # Fracción mínima de trigramas del query que deben aparecer en resultado char3
                              # 0.40 filtra falsos positivos (p.ej. "espagueti"→"ESP32": 1/7=14%)
                              # y mantiene typos reales (p.ej. "teletrabaj0"→"teletrabajo": 8/9=89%)
GRAPH_BOOST = float(os.getenv("GRAPH_BOOST", "0.15"))  # Multiplicador extra si el doc contiene entidades de la query

# ─── NER / spaCy ──────────────────────────────────────────────────
SPACY_MODEL = "es_core_news_md"

# ─── Keywords ─────────────────────────────────────────────────────
YAKE_MAX_KEYWORDS = 8
YAKE_LANGUAGE = "es"

# ─── LLM (Groq) ───────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.1-8b-instant"            # Modelo rápido (subtareas)
AGENT_MODEL = "llama-3.3-70b-versatile"         # Modelo orquestador (tool-calling)

LEXICAL_STRICT = os.getenv("LEXICAL_STRICT", "false").strip().lower() in {"1", "true", "yes", "on"}
FUZZY = os.getenv("FUZZY", "false").strip().lower() in {"1", "true", "yes", "on"}
FUSION_MODE = os.getenv("FUSION_MODE", "weighted").strip().lower()
if FUSION_MODE not in {"rrf", "weighted"}:
    FUSION_MODE = "rrf"
WEIGHT_LEXICAL = float(os.getenv("WEIGHT_LEXICAL", "0.55"))
WEIGHT_SEMANTIC = float(os.getenv("WEIGHT_SEMANTIC", "0.45"))

# ─── DuckDB ───────────────────────────────────────────────────────
DUCKDB_PATH = DATA_DIR / "tables.duckdb"
