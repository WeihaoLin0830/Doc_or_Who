from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
        _engine = create_engine(settings.database_url, future=True, connect_args=connect_args)

        if settings.database_url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _sqlite_on_connect(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def bootstrap_database(drop_existing: bool = False) -> None:
    from backend.models import Base

    engine = get_engine()
    if drop_existing:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    ensure_fts()


def ensure_fts() -> None:
    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    doc_id UNINDEXED,
                    title,
                    text,
                    section_title,
                    filename,
                    ext,
                    entity_texts,
                    tag_texts,
                    tokenize = 'unicode61'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunks_fts (
                        rowid, chunk_id, doc_id, title, text, section_title, filename, ext, entity_texts, tag_texts
                    )
                    VALUES (
                        new.rowid,
                        new.chunk_id,
                        new.doc_id,
                        COALESCE((SELECT title FROM documents WHERE doc_id = new.doc_id), ''),
                        new.text,
                        COALESCE(new.section_title, ''),
                        COALESCE((SELECT filename FROM documents WHERE doc_id = new.doc_id), ''),
                        COALESCE((SELECT ext FROM documents WHERE doc_id = new.doc_id), ''),
                        COALESCE(new.entity_texts, ''),
                        COALESCE(new.tag_texts, '')
                    );
                END
                """
            )
        )
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN DELETE FROM chunks_fts WHERE rowid = old.rowid; END"))
        connection.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                    DELETE FROM chunks_fts WHERE rowid = old.rowid;
                    INSERT INTO chunks_fts (
                        rowid, chunk_id, doc_id, title, text, section_title, filename, ext, entity_texts, tag_texts
                    )
                    VALUES (
                        new.rowid,
                        new.chunk_id,
                        new.doc_id,
                        COALESCE((SELECT title FROM documents WHERE doc_id = new.doc_id), ''),
                        new.text,
                        COALESCE(new.section_title, ''),
                        COALESCE((SELECT filename FROM documents WHERE doc_id = new.doc_id), ''),
                        COALESCE((SELECT ext FROM documents WHERE doc_id = new.doc_id), ''),
                        COALESCE(new.entity_texts, ''),
                        COALESCE(new.tag_texts, '')
                    );
                END
                """
            )
        )


def reset_db_cache() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None

