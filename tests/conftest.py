from __future__ import annotations

from pathlib import Path

import pytest


def reset_runtime() -> None:
    from backend.config import reset_settings_cache
    from backend.db import reset_db_cache
    from backend.embeddings import reset_embedding_provider_cache
    from backend.enrichment import reset_enrichment_cache
    from backend.ocr import reset_ocr_provider_cache
    from backend.vector import reset_vector_index_cache

    reset_settings_cache()
    reset_db_cache()
    reset_embedding_provider_cache()
    reset_enrichment_cache()
    reset_ocr_provider_cache()
    reset_vector_index_cache()


@pytest.fixture
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    dataset_dir = tmp_path / "dataset"
    data_dir = tmp_path / "data"
    upload_dir = tmp_path / "uploads"
    dataset_dir.mkdir()
    data_dir.mkdir()
    upload_dir.mkdir()

    monkeypatch.setenv("DOCUMENTWHO_DATASET_DIR", str(dataset_dir))
    monkeypatch.setenv("DOCUMENTWHO_DATA_DIR", str(data_dir))
    monkeypatch.setenv("DOCUMENTWHO_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("DOCUMENTWHO_DATABASE_URL", f"sqlite:///{(data_dir / 'documentwho.db').as_posix()}")
    monkeypatch.setenv("DOCUMENTWHO_EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setenv("DOCUMENTWHO_ENABLE_SPACY", "false")
    monkeypatch.setenv("DOCUMENTWHO_ENABLE_OCR", "false")
    monkeypatch.setenv("DOCUMENTWHO_HASHING_DIMENSION", "64")

    reset_runtime()

    from backend.db import bootstrap_database

    bootstrap_database(drop_existing=True)
    return {"dataset_dir": dataset_dir, "data_dir": data_dir, "upload_dir": upload_dir}
