"""
graph.py — Grafo de entidades extraídas de los documentos.

Construye un grafo con NetworkX donde:
- Nodos = entidades (personas, organizaciones, productos, proyectos)
- Aristas = co-ocurrencia dentro del mismo documento/chunk

Permite: "¿Qué documentos conectan a Pedro Suárez con ShenTech?"
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from backend.config import GRAPH_PATH
from backend.models import Document, EntityNode

# ─── Grafo en memoria ────────────────────────────────────────────
_entity_nodes: dict[str, EntityNode] = {}
_edges: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_documents: dict[str, dict] = {}


def build_graph(documents: list[Document]) -> None:
    """
    Construye el grafo de entidades a partir de documentos enriquecidos.
    Cada persona/org del mismo documento genera aristas entre sí.
    """
    global _entity_nodes, _edges, _documents
    _entity_nodes.clear()
    _edges.clear()
    _documents.clear()

    for doc in documents:
        # Guardar info del documento
        _documents[doc.doc_id] = {
            "doc_id": doc.doc_id,
            "title": doc.title,
            "filename": doc.filename,
            "doc_type": doc.doc_type,
            "category": doc.category,
        }

        # Recoger todas las entidades del documento
        entities: list[tuple[str, str]] = []  # (nombre, tipo)
        for person in doc.persons:
            entities.append((person, "person"))
        for org in doc.organizations:
            entities.append((org, "organization"))

        # Crear/actualizar nodos
        for name, etype in entities:
            key = _normalize_key(name)
            if key not in _entity_nodes:
                _entity_nodes[key] = EntityNode(name=name, entity_type=etype)
            node = _entity_nodes[key]
            if doc.doc_id not in node.doc_ids:
                node.doc_ids.append(doc.doc_id)
            node.mentions += 1

        # Crear aristas por co-ocurrencia
        for i, (name_a, _) in enumerate(entities):
            for name_b, _ in entities[i + 1:]:
                key_a = _normalize_key(name_a)
                key_b = _normalize_key(name_b)
                if key_a != key_b:
                    _edges[key_a][key_b] += 1
                    _edges[key_b][key_a] += 1

    # Persistir en disco
    _save_graph()
    print(f"🕸️  Grafo construido: {len(_entity_nodes)} entidades, "
          f"{sum(sum(v.values()) for v in _edges.values()) // 2} aristas.")


def get_entity(name: str) -> EntityNode | None:
    """Busca una entidad por nombre (case-insensitive)."""
    key = _normalize_key(name)
    return _entity_nodes.get(key)


def get_related_entities(name: str, top_k: int = 10) -> list[dict]:
    """
    Devuelve las entidades más relacionadas con una entidad dada.
    Ordenadas por peso de la arista (co-ocurrencias).
    """
    key = _normalize_key(name)
    if key not in _edges:
        return []

    neighbors = _edges[key]
    sorted_neighbors = sorted(neighbors.items(), key=lambda x: x[1], reverse=True)

    results = []
    for neighbor_key, weight in sorted_neighbors[:top_k]:
        node = _entity_nodes.get(neighbor_key)
        if node:
            results.append({
                "name": node.name,
                "type": node.entity_type,
                "weight": weight,
                "mentions": node.mentions,
                "doc_ids": node.doc_ids,
            })
    return results


def get_related_docs(name: str) -> list[dict]:
    """Devuelve los documentos donde aparece una entidad."""
    key = _normalize_key(name)
    node = _entity_nodes.get(key)
    if not node:
        return []
    return [_documents[did] for did in node.doc_ids if did in _documents]


def get_graph_data() -> dict:
    """
    Devuelve el grafo completo en formato vis-network compatible.
    Para visualización en el frontend.
    """
    nodes = []
    for key, node in _entity_nodes.items():
        color = "#4CAF50" if node.entity_type == "person" else "#2196F3"
        nodes.append({
            "id": key,
            "label": node.name,
            "group": node.entity_type,
            "value": node.mentions,
            "color": color,
            "title": f"{node.name} ({node.entity_type}) — {node.mentions} menciones en {len(node.doc_ids)} docs",
        })

    edges = []
    seen = set()
    for source, targets in _edges.items():
        for target, weight in targets.items():
            edge_key = tuple(sorted([source, target]))
            if edge_key not in seen:
                seen.add(edge_key)
                edges.append({
                    "from": source,
                    "to": target,
                    "value": weight,
                    "title": f"{weight} co-ocurrencias",
                })

    return {"nodes": nodes, "edges": edges}


def get_all_entities() -> list[dict]:
    """Devuelve todas las entidades del grafo."""
    return [
        {
            "name": node.name,
            "type": node.entity_type,
            "mentions": node.mentions,
            "num_docs": len(node.doc_ids),
        }
        for node in sorted(_entity_nodes.values(), key=lambda n: n.mentions, reverse=True)
    ]


def get_stats() -> dict:
    """Estadísticas del grafo."""
    type_counts = defaultdict(int)
    for node in _entity_nodes.values():
        type_counts[node.entity_type] += 1
    return {
        "total_entities": len(_entity_nodes),
        "total_edges": sum(sum(v.values()) for v in _edges.values()) // 2,
        "total_documents": len(_documents),
        "entities_by_type": dict(type_counts),
    }


# ─── Utilidades internas ─────────────────────────────────────────
def _normalize_key(name: str) -> str:
    """Normaliza el nombre para usar como clave del grafo."""
    return name.strip().lower()


def _save_graph():
    """Persiste el grafo a disco en JSON."""
    GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "nodes": {k: v.to_dict() for k, v in _entity_nodes.items()},
        "edges": {k: dict(v) for k, v in _edges.items()},
        "documents": _documents,
    }
    GRAPH_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def load_graph():
    """Carga el grafo desde disco si existe."""
    global _entity_nodes, _edges, _documents
    if not GRAPH_PATH.exists():
        return

    data = json.loads(GRAPH_PATH.read_text())

    _entity_nodes = {
        k: EntityNode(**v) for k, v in data.get("nodes", {}).items()
    }
    _edges = defaultdict(lambda: defaultdict(int))
    for k, v in data.get("edges", {}).items():
        for k2, w in v.items():
            _edges[k][k2] = w
    _documents = data.get("documents", {})
