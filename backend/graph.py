from __future__ import annotations

import numpy as np
from sqlalchemy import func, or_, select

from backend.config import get_settings
from backend.db import session_scope
from backend.models import ChunkEntityRecord, ChunkRecord, DocumentRecord, EdgeRecord, EntityRecord, PageRankScoreRecord
from backend.repositories import edge_id_for, iter_active_chunk_embeddings, persist_edges
from backend.schemas import GraphEdge, GraphNode, GraphResponse
from backend.types import GraphBuildStats
from backend.vector import faiss


def _node_key(node_type: str, node_id: str) -> str:
    return f"{node_type}:{node_id}"


class GraphBuilder:
    def rebuild(self) -> GraphBuildStats:
        settings = get_settings()
        with session_scope() as session:
            chunk_rows = session.execute(
                select(ChunkRecord.chunk_id, ChunkRecord.doc_id)
                .join(DocumentRecord, DocumentRecord.doc_id == ChunkRecord.doc_id)
                .where(DocumentRecord.is_deleted == 0, DocumentRecord.status.in_(("processed", "skipped")))
                .order_by(ChunkRecord.doc_id, ChunkRecord.chunk_index)
            ).all()
            mention_rows = session.execute(
                select(ChunkEntityRecord.chunk_id, ChunkEntityRecord.entity_id, ChunkEntityRecord.confidence)
                .join(ChunkRecord, ChunkRecord.chunk_id == ChunkEntityRecord.chunk_id)
                .join(DocumentRecord, DocumentRecord.doc_id == ChunkRecord.doc_id)
                .where(DocumentRecord.is_deleted == 0, DocumentRecord.status.in_(("processed", "skipped")))
            ).all()
            edges: list[dict[str, object]] = []
            nodes: set[tuple[str, str]] = set()
            for chunk_id, doc_id in chunk_rows:
                edges.append(
                    {
                        "edge_id": edge_id_for("doc", doc_id, "chunk", chunk_id, "contains"),
                        "src_type": "doc",
                        "src_id": doc_id,
                        "dst_type": "chunk",
                        "dst_id": chunk_id,
                        "edge_type": "contains",
                        "weight": 1.0,
                    }
                )
                nodes.add(("doc", doc_id))
                nodes.add(("chunk", chunk_id))
            for chunk_id, entity_id, confidence in mention_rows:
                edges.append(
                    {
                        "edge_id": edge_id_for("chunk", chunk_id, "entity", entity_id, "mentions"),
                        "src_type": "chunk",
                        "src_id": chunk_id,
                        "dst_type": "entity",
                        "dst_id": entity_id,
                        "edge_type": "mentions",
                        "weight": float(confidence),
                    }
                )
                nodes.add(("chunk", chunk_id))
                nodes.add(("entity", entity_id))

            similar_edges = self._build_similarity_edges(settings.graph_similarity_top_k, settings.graph_similarity_threshold)
            for edge in similar_edges:
                edges.append(edge)
                nodes.add(("chunk", edge["src_id"]))
                nodes.add(("chunk", edge["dst_id"]))

            persist_edges(session, edges)
            return GraphBuildStats(edge_count=len(edges), node_count=len(nodes), similar_edge_count=len(similar_edges))

    def _build_similarity_edges(self, top_k: int, threshold: float) -> list[dict[str, object]]:
        with session_scope() as session:
            rows = iter_active_chunk_embeddings(session)
        if len(rows) < 2:
            return []
        chunk_ids = [chunk_id for chunk_id, _doc_id, _vector in rows]
        doc_ids = [doc_id for _chunk_id, doc_id, _vector in rows]
        matrix = np.asarray([vector for _chunk_id, _doc_id, vector in rows], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix = matrix / norms
        if faiss is not None:
            index = faiss.IndexFlatIP(matrix.shape[1])
            index.add(matrix)
            scores, indices = index.search(matrix, min(top_k + 1, len(chunk_ids)))
        else:
            scores = matrix @ matrix.T
            order = np.argsort(scores, axis=1)[:, ::-1][:, : min(top_k + 1, len(chunk_ids))]
            indices = order

        seen_pairs: set[tuple[str, str]] = set()
        edges: list[dict[str, object]] = []
        for source_index, source_chunk_id in enumerate(chunk_ids):
            for neighbor_rank, target_index in enumerate(indices[source_index]):
                if target_index < 0 or target_index == source_index:
                    continue
                similarity = float(scores[source_index][neighbor_rank] if faiss is not None else scores[source_index][target_index])
                if similarity < threshold:
                    continue
                if doc_ids[source_index] == doc_ids[target_index]:
                    continue
                src_id, dst_id = sorted((source_chunk_id, chunk_ids[target_index]))
                pair = (src_id, dst_id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                edges.append(
                    {
                        "edge_id": edge_id_for("chunk", src_id, "chunk", dst_id, "similar"),
                        "src_type": "chunk",
                        "src_id": src_id,
                        "dst_type": "chunk",
                        "dst_id": dst_id,
                        "edge_type": "similar",
                        "weight": similarity,
                    }
                )
        return edges


def _pagerank_map(session, node_ids: set[tuple[str, str]]) -> dict[tuple[str, str], float]:
    if not node_ids:
        return {}
    rows = session.execute(
        select(PageRankScoreRecord.node_type, PageRankScoreRecord.node_id, PageRankScoreRecord.pagerank).where(
            or_(
                *[
                    (PageRankScoreRecord.node_type == node_type) & (PageRankScoreRecord.node_id == node_id)
                    for node_type, node_id in node_ids
                ]
            )
        )
    ).all()
    return {(node_type, node_id): pagerank for node_type, node_id, pagerank in rows}


def get_doc_graph(doc_id: str) -> GraphResponse | None:
    with session_scope() as session:
        document = session.get(DocumentRecord, doc_id)
        if document is None or document.is_deleted:
            return None
        chunks = session.scalars(select(ChunkRecord).where(ChunkRecord.doc_id == doc_id).order_by(ChunkRecord.chunk_index)).all()
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        entity_rows = session.execute(
            select(EntityRecord, ChunkEntityRecord.chunk_id)
            .join(ChunkEntityRecord, ChunkEntityRecord.entity_id == EntityRecord.entity_id)
            .where(ChunkEntityRecord.chunk_id.in_(chunk_ids))
        ).all() if chunk_ids else []
        similar_rows = session.execute(
            select(EdgeRecord).where(
                EdgeRecord.edge_type == "similar",
                or_(EdgeRecord.src_id.in_(chunk_ids), EdgeRecord.dst_id.in_(chunk_ids)),
            )
        ).scalars().all() if chunk_ids else []
        external_chunk_ids = {
            edge.dst_id if edge.src_id in chunk_ids else edge.src_id
            for edge in similar_rows
            if (edge.dst_id if edge.src_id in chunk_ids else edge.src_id) not in chunk_ids
        }
        external_chunks = session.scalars(select(ChunkRecord).where(ChunkRecord.chunk_id.in_(external_chunk_ids))).all() if external_chunk_ids else []
        external_docs = {
            chunk.doc_id: session.get(DocumentRecord, chunk.doc_id)
            for chunk in external_chunks
        }
        node_ids = {("doc", doc_id)} | {("chunk", chunk.chunk_id) for chunk in chunks}
        node_ids |= {("entity", entity.entity_id) for entity, _chunk_id in entity_rows}
        node_ids |= {("chunk", chunk.chunk_id) for chunk in external_chunks}
        node_ids |= {("doc", chunk.doc_id) for chunk in external_chunks}
        pageranks = _pagerank_map(session, node_ids)

        nodes = [
            GraphNode(
                id=_node_key("doc", document.doc_id),
                label=document.title or document.filename,
                node_type="doc",
                pagerank=pageranks.get(("doc", document.doc_id), 0.0),
                metadata={"filename": document.filename, "status": document.status, "ext": document.ext},
            )
        ]
        edges: list[GraphEdge] = []
        for chunk in chunks:
            nodes.append(
                GraphNode(
                    id=_node_key("chunk", chunk.chunk_id),
                    label=chunk.section_title or f"Chunk {chunk.chunk_index}",
                    node_type="chunk",
                    pagerank=pageranks.get(("chunk", chunk.chunk_id), 0.0),
                    metadata={"chunk_index": chunk.chunk_index},
                )
            )
            edges.append(
                GraphEdge(
                    id=edge_id_for("doc", document.doc_id, "chunk", chunk.chunk_id, "contains"),
                    source=_node_key("doc", document.doc_id),
                    target=_node_key("chunk", chunk.chunk_id),
                    edge_type="contains",
                    weight=1.0,
                )
            )

        seen_entities: set[str] = set()
        for entity, chunk_id in entity_rows:
            if entity.entity_id not in seen_entities:
                nodes.append(
                    GraphNode(
                        id=_node_key("entity", entity.entity_id),
                        label=entity.display_text,
                        node_type="entity",
                        pagerank=pageranks.get(("entity", entity.entity_id), 0.0),
                        metadata={"entity_type": entity.type},
                    )
                )
                seen_entities.add(entity.entity_id)
            edges.append(
                GraphEdge(
                    id=edge_id_for("chunk", chunk_id, "entity", entity.entity_id, "mentions"),
                    source=_node_key("chunk", chunk_id),
                    target=_node_key("entity", entity.entity_id),
                    edge_type="mentions",
                    weight=1.0,
                )
            )

        for external_chunk in external_chunks:
            external_doc = external_docs.get(external_chunk.doc_id)
            if external_doc is None:
                continue
            nodes.append(
                GraphNode(
                    id=_node_key("doc", external_doc.doc_id),
                    label=external_doc.title or external_doc.filename,
                    node_type="doc",
                    pagerank=pageranks.get(("doc", external_doc.doc_id), 0.0),
                    metadata={"filename": external_doc.filename, "ext": external_doc.ext},
                )
            )
            nodes.append(
                GraphNode(
                    id=_node_key("chunk", external_chunk.chunk_id),
                    label=external_chunk.section_title or f"Chunk {external_chunk.chunk_index}",
                    node_type="chunk",
                    pagerank=pageranks.get(("chunk", external_chunk.chunk_id), 0.0),
                    metadata={"chunk_index": external_chunk.chunk_index},
                )
            )
            edges.append(
                GraphEdge(
                    id=edge_id_for("doc", external_doc.doc_id, "chunk", external_chunk.chunk_id, "contains"),
                    source=_node_key("doc", external_doc.doc_id),
                    target=_node_key("chunk", external_chunk.chunk_id),
                    edge_type="contains",
                    weight=1.0,
                )
            )

        for edge in similar_rows:
            edges.append(
                GraphEdge(
                    id=edge.edge_id,
                    source=_node_key("chunk", edge.src_id),
                    target=_node_key("chunk", edge.dst_id),
                    edge_type=edge.edge_type,
                    weight=edge.weight,
                )
            )
        return GraphResponse(root_id=_node_key("doc", doc_id), nodes=_unique_nodes(nodes), edges=_unique_edges(edges))


def get_entity_graph(entity_id: str) -> GraphResponse | None:
    with session_scope() as session:
        entity = session.get(EntityRecord, entity_id)
        if entity is None:
            entity = session.scalar(
                select(EntityRecord).where(
                    or_(EntityRecord.canonical_text == entity_id, EntityRecord.display_text == entity_id)
                )
            )
        if entity is None:
            return None
        chunk_rows = session.execute(
            select(ChunkRecord, DocumentRecord, ChunkEntityRecord.confidence)
            .join(DocumentRecord, DocumentRecord.doc_id == ChunkRecord.doc_id)
            .join(ChunkEntityRecord, ChunkEntityRecord.chunk_id == ChunkRecord.chunk_id)
            .where(ChunkEntityRecord.entity_id == entity.entity_id)
        ).all()
        chunk_ids = [chunk.chunk_id for chunk, _doc, _confidence in chunk_rows]
        neighbor_rows = session.execute(
            select(EntityRecord, func.count(func.distinct(ChunkEntityRecord.chunk_id)))
            .join(ChunkEntityRecord, ChunkEntityRecord.entity_id == EntityRecord.entity_id)
            .where(ChunkEntityRecord.chunk_id.in_(chunk_ids), EntityRecord.entity_id != entity.entity_id)
            .group_by(EntityRecord.entity_id)
            .order_by(func.count(func.distinct(ChunkEntityRecord.chunk_id)).desc())
            .limit(15)
        ).all() if chunk_ids else []

        node_ids = {("entity", entity.entity_id)}
        node_ids |= {("chunk", chunk.chunk_id) for chunk, _doc, _confidence in chunk_rows}
        node_ids |= {("doc", doc.doc_id) for _chunk, doc, _confidence in chunk_rows}
        node_ids |= {("entity", neighbor.entity_id) for neighbor, _count in neighbor_rows}
        pageranks = _pagerank_map(session, node_ids)

        nodes = [
            GraphNode(
                id=_node_key("entity", entity.entity_id),
                label=entity.display_text,
                node_type="entity",
                pagerank=pageranks.get(("entity", entity.entity_id), 0.0),
                metadata={"entity_type": entity.type},
            )
        ]
        edges: list[GraphEdge] = []
        for chunk, document, confidence in chunk_rows:
            nodes.append(
                GraphNode(
                    id=_node_key("doc", document.doc_id),
                    label=document.title or document.filename,
                    node_type="doc",
                    pagerank=pageranks.get(("doc", document.doc_id), 0.0),
                    metadata={"filename": document.filename, "ext": document.ext},
                )
            )
            nodes.append(
                GraphNode(
                    id=_node_key("chunk", chunk.chunk_id),
                    label=chunk.section_title or f"Chunk {chunk.chunk_index}",
                    node_type="chunk",
                    pagerank=pageranks.get(("chunk", chunk.chunk_id), 0.0),
                    metadata={"chunk_index": chunk.chunk_index},
                )
            )
            edges.append(
                GraphEdge(
                    id=edge_id_for("doc", document.doc_id, "chunk", chunk.chunk_id, "contains"),
                    source=_node_key("doc", document.doc_id),
                    target=_node_key("chunk", chunk.chunk_id),
                    edge_type="contains",
                    weight=1.0,
                )
            )
            edges.append(
                GraphEdge(
                    id=edge_id_for("chunk", chunk.chunk_id, "entity", entity.entity_id, "mentions"),
                    source=_node_key("chunk", chunk.chunk_id),
                    target=_node_key("entity", entity.entity_id),
                    edge_type="mentions",
                    weight=confidence,
                )
            )
        for neighbor, count in neighbor_rows:
            nodes.append(
                GraphNode(
                    id=_node_key("entity", neighbor.entity_id),
                    label=neighbor.display_text,
                    node_type="entity",
                    pagerank=pageranks.get(("entity", neighbor.entity_id), 0.0),
                    metadata={"entity_type": neighbor.type},
                )
            )
            edges.append(
                GraphEdge(
                    id=edge_id_for("entity", entity.entity_id, "entity", neighbor.entity_id, "co_mention"),
                    source=_node_key("entity", entity.entity_id),
                    target=_node_key("entity", neighbor.entity_id),
                    edge_type="co_mention",
                    weight=float(count),
                )
            )
        return GraphResponse(root_id=_node_key("entity", entity.entity_id), nodes=_unique_nodes(nodes), edges=_unique_edges(edges))


def get_overview_graph(limit: int = 30) -> GraphResponse:
    with session_scope() as session:
        top_entities = session.execute(
            select(EntityRecord, func.count(ChunkEntityRecord.chunk_id).label("mentions"))
            .join(ChunkEntityRecord, ChunkEntityRecord.entity_id == EntityRecord.entity_id)
            .group_by(EntityRecord.entity_id)
            .order_by(func.count(ChunkEntityRecord.chunk_id).desc())
            .limit(limit)
        ).all()
        nodes = [
            GraphNode(
                id=_node_key("entity", entity.entity_id),
                label=entity.display_text,
                node_type="entity",
                pagerank=0.0,
                metadata={"entity_type": entity.type, "mentions": mentions},
            )
            for entity, mentions in top_entities
        ]
        return GraphResponse(root_id="overview", nodes=_unique_nodes(nodes), edges=[])


def _unique_nodes(nodes: list[GraphNode]) -> list[GraphNode]:
    deduped: dict[str, GraphNode] = {}
    for node in nodes:
        deduped[node.id] = node
    return list(deduped.values())


def _unique_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    deduped: dict[str, GraphEdge] = {}
    for edge in edges:
        deduped[edge.id] = edge
    return list(deduped.values())
