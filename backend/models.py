from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, LargeBinary, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from backend.utils import utcnow_text


class Base(DeclarativeBase):
    pass


class DocumentRecord(Base):
    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    ext: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mtime_epoch: Mapped[float] = mapped_column(Float, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=utcnow_text)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=utcnow_text)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    chunks: Mapped[list["ChunkRecord"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class ChunkRecord(Base):
    __tablename__ = "chunks"

    chunk_id: Mapped[str] = mapped_column(Text, primary_key=True)
    doc_id: Mapped[str] = mapped_column(Text, ForeignKey("documents.doc_id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    section_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_texts: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tag_texts: Mapped[str] = mapped_column(Text, nullable=False, default="")
    bm25_indexed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=utcnow_text)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=utcnow_text)

    document: Mapped[DocumentRecord] = relationship(back_populates="chunks")
    embedding: Mapped["ChunkEmbeddingRecord | None"] = relationship(back_populates="chunk", cascade="all, delete-orphan")
    entity_links: Mapped[list["ChunkEntityRecord"]] = relationship(back_populates="chunk", cascade="all, delete-orphan")


class ChunkEmbeddingRecord(Base):
    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[str] = mapped_column(Text, ForeignKey("chunks.chunk_id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=utcnow_text)

    chunk: Mapped[ChunkRecord] = relationship(back_populates="embedding")


class EntityRecord(Base):
    __tablename__ = "entities"

    entity_id: Mapped[str] = mapped_column(Text, primary_key=True)
    canonical_text: Mapped[str] = mapped_column(Text, nullable=False)
    display_text: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    importance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    chunk_links: Mapped[list["ChunkEntityRecord"]] = relationship(back_populates="entity", cascade="all, delete-orphan")


class ChunkEntityRecord(Base):
    __tablename__ = "chunk_entities"

    chunk_id: Mapped[str] = mapped_column(Text, ForeignKey("chunks.chunk_id", ondelete="CASCADE"), primary_key=True)
    entity_id: Mapped[str] = mapped_column(Text, ForeignKey("entities.entity_id", ondelete="CASCADE"), primary_key=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    chunk: Mapped[ChunkRecord] = relationship(back_populates="entity_links")
    entity: Mapped[EntityRecord] = relationship(back_populates="chunk_links")


class EdgeRecord(Base):
    __tablename__ = "edges"

    edge_id: Mapped[str] = mapped_column(Text, primary_key=True)
    src_type: Mapped[str] = mapped_column(Text, nullable=False)
    src_id: Mapped[str] = mapped_column(Text, nullable=False)
    dst_type: Mapped[str] = mapped_column(Text, nullable=False)
    dst_id: Mapped[str] = mapped_column(Text, nullable=False)
    edge_type: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)


class PageRankScoreRecord(Base):
    __tablename__ = "pagerank_scores"

    node_type: Mapped[str] = mapped_column(Text, primary_key=True)
    node_id: Mapped[str] = mapped_column(Text, primary_key=True)
    pagerank: Mapped[float] = mapped_column(Float, nullable=False)
