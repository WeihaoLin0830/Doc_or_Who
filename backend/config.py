from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    dataset_dir: Path
    data_dir: Path
    upload_dir: Path
    vector_dir: Path
    vector_index_path: Path
    vector_mapping_path: Path
    database_url: str
    embedding_provider: str
    embedding_model: str
    openai_embedding_model: str
    openai_api_key: str | None
    hashing_dimension: int
    spacy_model: str
    file_size_limit_bytes: int
    chunk_target_tokens: int
    chunk_min_tokens: int
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    search_top_k: int
    final_top_k: int
    semantic_overfetch_multiplier: int
    keyword_weight: float
    semantic_weight: float
    pagerank_weight: float
    graph_similarity_top_k: int
    graph_similarity_threshold: float
    default_language: str
    enable_spacy: bool
    enable_ocr: bool
    ocr_provider: str
    ocr_languages: str
    ocr_dpi: int
    ocr_max_pages: int
    tesseract_cmd: str | None
    api_host: str
    api_port: int
    log_level: str

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.vector_dir.mkdir(parents=True, exist_ok=True)


def _resolve_path(raw: str | None, base: Path, default_name: str) -> Path:
    path = Path(raw) if raw else base / default_name
    return path if path.is_absolute() else (base / path).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    root_dir = Path(__file__).resolve().parent.parent
    data_dir = _resolve_path(os.getenv("DOCUMENTWHO_DATA_DIR"), root_dir, "data")
    dataset_dir = _resolve_path(os.getenv("DOCUMENTWHO_DATASET_DIR"), root_dir, "dataset_default")
    upload_dir = _resolve_path(os.getenv("DOCUMENTWHO_UPLOAD_DIR"), root_dir, "uploads")
    vector_dir = data_dir / "vector"
    default_db = f"sqlite:///{(data_dir / 'documentwho.db').as_posix()}"
    settings = Settings(
        root_dir=root_dir,
        dataset_dir=dataset_dir,
        data_dir=data_dir,
        upload_dir=upload_dir,
        vector_dir=vector_dir,
        vector_index_path=vector_dir / "chunks.faiss",
        vector_mapping_path=vector_dir / "mapping.json",
        database_url=os.getenv("DOCUMENTWHO_DATABASE_URL", default_db),
        embedding_provider=os.getenv("DOCUMENTWHO_EMBEDDING_PROVIDER", "sentence_transformers"),
        embedding_model=os.getenv("DOCUMENTWHO_EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"),
        openai_embedding_model=os.getenv("DOCUMENTWHO_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        hashing_dimension=int(os.getenv("DOCUMENTWHO_HASHING_DIMENSION", "256")),
        spacy_model=os.getenv("DOCUMENTWHO_SPACY_MODEL", "es_core_news_md"),
        file_size_limit_bytes=int(float(os.getenv("DOCUMENTWHO_FILE_SIZE_LIMIT_MB", "50")) * 1024 * 1024),
        chunk_target_tokens=int(os.getenv("DOCUMENTWHO_CHUNK_TARGET_TOKENS", "650")),
        chunk_min_tokens=int(os.getenv("DOCUMENTWHO_CHUNK_MIN_TOKENS", "500")),
        chunk_max_tokens=int(os.getenv("DOCUMENTWHO_CHUNK_MAX_TOKENS", "800")),
        chunk_overlap_tokens=int(os.getenv("DOCUMENTWHO_CHUNK_OVERLAP_TOKENS", "80")),
        search_top_k=int(os.getenv("DOCUMENTWHO_SEARCH_TOP_K", "50")),
        final_top_k=int(os.getenv("DOCUMENTWHO_FINAL_TOP_K", "10")),
        semantic_overfetch_multiplier=int(os.getenv("DOCUMENTWHO_SEMANTIC_OVERFETCH_MULTIPLIER", "5")),
        keyword_weight=float(os.getenv("DOCUMENTWHO_KEYWORD_WEIGHT", "0.55")),
        semantic_weight=float(os.getenv("DOCUMENTWHO_SEMANTIC_WEIGHT", "0.35")),
        pagerank_weight=float(os.getenv("DOCUMENTWHO_PAGERANK_WEIGHT", "0.10")),
        graph_similarity_top_k=int(os.getenv("DOCUMENTWHO_GRAPH_SIMILARITY_TOP_K", "15")),
        graph_similarity_threshold=float(os.getenv("DOCUMENTWHO_GRAPH_SIMILARITY_THRESHOLD", "0.78")),
        default_language=os.getenv("DOCUMENTWHO_DEFAULT_LANGUAGE", "unknown"),
        enable_spacy=_env_bool("DOCUMENTWHO_ENABLE_SPACY", True),
        enable_ocr=_env_bool("DOCUMENTWHO_ENABLE_OCR", True),
        ocr_provider=os.getenv("DOCUMENTWHO_OCR_PROVIDER", "tesseract"),
        ocr_languages=os.getenv("DOCUMENTWHO_OCR_LANGUAGES", "spa+eng"),
        ocr_dpi=int(os.getenv("DOCUMENTWHO_OCR_DPI", "200")),
        ocr_max_pages=int(os.getenv("DOCUMENTWHO_OCR_MAX_PAGES", "20")),
        tesseract_cmd=os.getenv("DOCUMENTWHO_TESSERACT_CMD"),
        api_host=os.getenv("DOCUMENTWHO_API_HOST", "127.0.0.1"),
        api_port=int(os.getenv("DOCUMENTWHO_API_PORT", "8000")),
        log_level=os.getenv("DOCUMENTWHO_LOG_LEVEL", "INFO"),
    )
    settings.ensure_directories()
    return settings


def reset_settings_cache() -> None:
    get_settings.cache_clear()
