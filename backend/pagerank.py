from __future__ import annotations

import math

import networkx as nx
from sqlalchemy import select

from backend.db import session_scope
from backend.models import EdgeRecord
from backend.repositories import persist_pagerank


def run_pagerank() -> dict[str, float]:
    with session_scope() as session:
        edge_rows = session.scalars(select(EdgeRecord)).all()
        if not edge_rows:
            persist_pagerank(session, [])
            return {}
        graph = nx.DiGraph()
        for edge in edge_rows:
            src = f"{edge.src_type}:{edge.src_id}"
            dst = f"{edge.dst_type}:{edge.dst_id}"
            graph.add_edge(src, dst, weight=edge.weight)
            graph.add_edge(dst, src, weight=edge.weight)
        scores = nx.pagerank(graph, weight="weight")
        rows = []
        for node_key, pagerank in scores.items():
            node_type, node_id = node_key.split(":", 1)
            rows.append({"node_type": node_type, "node_id": node_id, "pagerank": pagerank})
        persist_pagerank(session, rows)
        return scores


def normalize_pagerank(score: float, max_score: float) -> float:
    if max_score <= 0 or score <= 0:
        return 0.0
    return math.log1p(score) / math.log1p(max_score)
