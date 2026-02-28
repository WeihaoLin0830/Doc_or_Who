from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("doc_id", sa.Text(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False, unique=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("ext", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("mtime_epoch", sa.Float(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_deleted", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_table(
        "chunks",
        sa.Column("chunk_id", sa.Text(), primary_key=True),
        sa.Column("doc_id", sa.Text(), sa.ForeignKey("documents.doc_id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("section_title", sa.Text(), nullable=True),
        sa.Column("entity_texts", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("tag_texts", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("bm25_indexed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("doc_id", "chunk_index"),
    )
    op.create_table(
        "chunk_embeddings",
        sa.Column("chunk_id", sa.Text(), sa.ForeignKey("chunks.chunk_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vector_blob", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "entities",
        sa.Column("entity_id", sa.Text(), primary_key=True),
        sa.Column("canonical_text", sa.Text(), nullable=False),
        sa.Column("display_text", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("importance_score", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("canonical_text", "type"),
    )
    op.create_table(
        "chunk_entities",
        sa.Column("chunk_id", sa.Text(), sa.ForeignKey("chunks.chunk_id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.Text(), sa.ForeignKey("entities.entity_id", ondelete="CASCADE"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("chunk_id", "entity_id"),
    )
    op.create_table(
        "edges",
        sa.Column("edge_id", sa.Text(), primary_key=True),
        sa.Column("src_type", sa.Text(), nullable=False),
        sa.Column("src_id", sa.Text(), nullable=False),
        sa.Column("dst_type", sa.Text(), nullable=False),
        sa.Column("dst_id", sa.Text(), nullable=False),
        sa.Column("edge_type", sa.Text(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.UniqueConstraint("src_type", "src_id", "dst_type", "dst_id", "edge_type"),
    )
    op.create_table(
        "pagerank_scores",
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("pagerank", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("node_type", "node_id"),
    )
    op.execute(
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
    op.execute(
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
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            DELETE FROM chunks_fts WHERE rowid = old.rowid;
        END
        """
    )
    op.execute(
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
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_doc_id ON chunks (doc_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_status_deleted ON documents (status, is_deleted)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_edges_src ON edges (src_type, src_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_edges_dst ON edges (dst_type, dst_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunk_entities_entity ON chunk_entities (entity_id)")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS chunks_au")
    op.execute("DROP TRIGGER IF EXISTS chunks_ad")
    op.execute("DROP TRIGGER IF EXISTS chunks_ai")
    op.execute("DROP TABLE IF EXISTS chunks_fts")
    op.drop_table("pagerank_scores")
    op.drop_table("edges")
    op.drop_table("chunk_entities")
    op.drop_table("entities")
    op.drop_table("chunk_embeddings")
    op.drop_table("chunks")
    op.drop_table("documents")
