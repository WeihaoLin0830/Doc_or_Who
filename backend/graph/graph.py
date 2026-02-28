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
from difflib import SequenceMatcher
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

    # Deduplicar entidades similares (ej: "Pedro" merged en "Pedro Suárez")
    _deduplicate_entities()

    # Calcular métricas de análisis de grafo
    _compute_betweenness()
    _compute_communities()

    # Persistir en disco
    _save_graph()
    print(f"🕸️  Grafo construido: {len(_entity_nodes)} entidades, "
          f"{sum(sum(v.values()) for v in _edges.values()) // 2} aristas.")


def add_document_to_graph(doc: Document) -> None:
    """
    Añade un único documento al grafo existente de forma incremental.
    No reconstruye el grafo entero — solo agrega las entidades nuevas y aristas
    del documento. Persiste el resultado en disco.
    Usar tras subir un fichero vía /api/upload.
    """
    # Registrar el documento
    _documents[doc.doc_id] = {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "filename": doc.filename,
        "doc_type": doc.doc_type,
        "category": getattr(doc, "category", ""),
    }

    entities: list[tuple[str, str]] = []
    for person in (doc.persons or []):
        entities.append((person, "person"))
    for org in (doc.organizations or []):
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

    # Crear aristas por co-ocurrencia dentro del documento
    for i, (name_a, _) in enumerate(entities):
        for name_b, _ in entities[i + 1:]:
            key_a = _normalize_key(name_a)
            key_b = _normalize_key(name_b)
            if key_a != key_b:
                _edges[key_a][key_b] += 1
                _edges[key_b][key_a] += 1

    _save_graph()
    print(f"📄 Documento añadido al grafo: {doc.filename} "
          f"({len(entities)} entidades). Total nodos: {len(_entity_nodes)}.")


def get_entity(name: str) -> EntityNode | None:
    """Busca una entidad por nombre (case-insensitive)."""
    key = _normalize_key(name)
    return _entity_nodes.get(key)


def search_entities(query: str, top_k: int = 10) -> list[dict]:
    """Búsqueda parcial/fuzzy de entidades por nombre."""
    q = query.strip().lower()
    scored: list[tuple[float, EntityNode]] = []
    for key, node in _entity_nodes.items():
        if q in key:
            scored.append((1.0 + node.mentions * 0.01, node))
        else:
            ratio = SequenceMatcher(None, q, key).ratio()
            if ratio > 0.6:
                scored.append((ratio, node))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"name": n.name, "type": n.entity_type, "mentions": n.mentions, "num_docs": len(n.doc_ids)}
        for _, n in scored[:top_k]
    ]


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
    # Calcular grado de cada nodo (centralidad de grado)
    degree: dict[str, int] = {key: len(targets) for key, targets in _edges.items()}

    nodes = []
    for key, node in _entity_nodes.items():
        # Colores por comunidad (7 paleta) con distinción person/org por borde
        color = _community_color(node.community_id, node.entity_type)
        degree_val = degree.get(key, 0)
        nodes.append({
            "id": key,
            "label": node.name,
            "group": node.entity_type,
            "value": max(node.mentions, 1) + node.betweenness * 20,  # size = mentions + betweenness
            "degree": degree_val,
            "community": node.community_id,
            "betweenness": round(node.betweenness, 4),
            "color": color,
            "title": (
                f"<b>{node.name}</b> ({node.entity_type})<br>"
                f"📄 {len(node.doc_ids)} docs · 🗣 {node.mentions} menciones<br>"
                f"🔗 {degree_val} conexiones · 🌉 betweenness {node.betweenness:.3f}<br>"
                f"🏘 comunidad #{node.community_id}"
            ),
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


def get_graph_data_filtered(
    doc_id: str | None = None,
    entity_type: str | None = None,
) -> dict:
    """
    Devuelve el grafo filtrado por documento y/o tipo de entidad.
    Si no se especifican filtros, devuelve el grafo completo.
    """
    if not doc_id and not entity_type:
        return get_graph_data()

    # Filtrar nodos
    filtered_keys: set[str] = set()
    for key, node in _entity_nodes.items():
        if entity_type and node.entity_type != entity_type:
            continue
        if doc_id and doc_id not in node.doc_ids:
            continue
        filtered_keys.add(key)

    nodes = []
    for key in filtered_keys:
        node = _entity_nodes[key]
        color = "#4CAF50" if node.entity_type == "person" else "#2196F3"
        nodes.append({
            "id": key,
            "label": node.name,
            "group": node.entity_type,
            "value": node.mentions,
            "color": color,
            "title": f"{node.name} ({node.entity_type}) — {node.mentions} menciones en {len(node.doc_ids)} docs",
        })

    # Filtrar aristas: solo entre nodos filtrados
    edges = []
    seen = set()
    for source in filtered_keys:
        if source not in _edges:
            continue
        for target, weight in _edges[source].items():
            if target not in filtered_keys:
                continue
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


def find_connection_path(name_a: str, name_b: str) -> dict:
    """
    Encuentra el camino más corto entre dos entidades en el grafo (BFS).
    Responde: "¿Qué conecta a A con B?" mostrando la cadena y los docs en común.
    """
    key_a = _normalize_key(name_a)
    key_b = _normalize_key(name_b)

    if key_a not in _entity_nodes:
        return {"found": False, "error": f"Entidad '{name_a}' no encontrada"}
    if key_b not in _entity_nodes:
        return {"found": False, "error": f"Entidad '{name_b}' no encontrada"}
    if key_a == key_b:
        return {"found": True, "path": [_entity_nodes[key_a].to_dict()], "hops": 0}

    # BFS
    from collections import deque
    queue: deque[list[str]] = deque([[key_a]])
    visited: set[str] = {key_a}

    while queue:
        path = queue.popleft()
        current = path[-1]

        for neighbor in _edges.get(current, {}):
            if neighbor == key_b:
                full_path = path + [neighbor]
                # Construir respuesta con nodos e información de conexión
                path_nodes = []
                for key in full_path:
                    node = _entity_nodes[key]
                    path_nodes.append({
                        "name": node.name,
                        "type": node.entity_type,
                        "mentions": node.mentions,
                        "doc_ids": node.doc_ids,
                    })
                # Documentos que conectan cada par consecutivo
                connections = []
                for i in range(len(full_path) - 1):
                    k1, k2 = full_path[i], full_path[i + 1]
                    shared_docs = [
                        _documents[did]
                        for did in set(_entity_nodes[k1].doc_ids) & set(_entity_nodes[k2].doc_ids)
                        if did in _documents
                    ]
                    connections.append({
                        "from": _entity_nodes[k1].name,
                        "to": _entity_nodes[k2].name,
                        "weight": _edges[k1].get(k2, 0),
                        "shared_documents": shared_docs,
                    })
                return {
                    "found": True,
                    "hops": len(full_path) - 1,
                    "path": path_nodes,
                    "connections": connections,
                }
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(path + [neighbor])

    return {"found": False, "error": f"No existe conexión entre '{name_a}' y '{name_b}'"}


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


def get_communities() -> list[dict]:
    """Devuelve las comunidades detectadas con sus miembros."""
    groups: dict[int, list[dict]] = defaultdict(list)
    for key, node in _entity_nodes.items():
        groups[node.community_id].append({
            "name": node.name,
            "type": node.entity_type,
            "mentions": node.mentions,
            "betweenness": round(node.betweenness, 4),
        })
    result = []
    for comm_id, members in sorted(groups.items()):
        # Label the community by the most-mentioned member
        anchor = max(members, key=lambda m: m["mentions"])
        result.append({
            "community_id": comm_id,
            "label": anchor["name"],
            "size": len(members),
            "color": _community_color(comm_id, ""),
            "members": sorted(members, key=lambda m: m["mentions"], reverse=True),
        })
    return sorted(result, key=lambda c: c["size"], reverse=True)


def get_top_brokers(top_k: int = 5) -> list[dict]:
    """Devuelve las entidades con mayor betweenness (conectores clave del grafo)."""
    nodes = sorted(_entity_nodes.values(), key=lambda n: n.betweenness, reverse=True)
    return [
        {
            "name": n.name,
            "type": n.entity_type,
            "betweenness": round(n.betweenness, 4),
            "mentions": n.mentions,
            "num_docs": len(n.doc_ids),
        }
        for n in nodes[:top_k]
        if n.betweenness > 0
    ]


# ─── Utilidades internas ─────────────────────────────────────────
def _normalize_key(name: str) -> str:
    """Normaliza el nombre para usar como clave del grafo.

    Aplica: strip + lowercase + eliminación de acentos/diacríticos.
    Así 'Ana Belén' y 'ana belen' mapean a la misma clave y se deduplicarán.
    """
    import unicodedata
    nfd = unicodedata.normalize("NFKD", name.strip().lower())
    return "".join(c for c in nfd if not unicodedata.combining(c))


# Paleta de 8 colores por comunidad (pares claro/oscuro para person/org)
_COMMUNITY_PALETTE = [
    "#6366f1",  # indigo
    "#f59e0b",  # amber
    "#10b981",  # emerald
    "#ef4444",  # red
    "#8b5cf6",  # violet
    "#06b6d4",  # cyan
    "#f97316",  # orange
    "#ec4899",  # pink
]

def _community_color(community_id: int, entity_type: str) -> str:
    """Devuelve el color de un nodo según su comunidad."""
    if community_id < 0:
        return "#4CAF50" if entity_type == "person" else "#2196F3"
    base = _COMMUNITY_PALETTE[community_id % len(_COMMUNITY_PALETTE)]
    return base


def _compute_betweenness() -> None:
    """
    Calcula betweenness centrality para todos los nodos (Brandes algorithm).
    Actualiza _entity_nodes[key].betweenness in-place.
    Normalizado: divide por (n-1)(n-2) para grafos no dirigidos.
    """
    from collections import deque

    keys = list(_entity_nodes.keys())
    n = len(keys)
    if n < 3:
        return

    betweenness: dict[str, float] = {k: 0.0 for k in keys}

    for s in keys:
        # Brandes BFS
        stack: list[str] = []
        predecessors: dict[str, list[str]] = {k: [] for k in keys}
        num_paths: dict[str, float] = {k: 0.0 for k in keys}
        num_paths[s] = 1.0
        dist: dict[str, int] = {k: -1 for k in keys}
        dist[s] = 0
        queue: deque[str] = deque([s])

        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in _edges.get(v, {}):
                if w not in _entity_nodes:
                    continue
                if dist[w] < 0:
                    queue.append(w)
                    dist[w] = dist[v] + 1
                if dist[w] == dist[v] + 1:
                    num_paths[w] += num_paths[v]
                    predecessors[w].append(v)

        # Back-propagation of dependencies
        delta: dict[str, float] = {k: 0.0 for k in keys}
        while stack:
            w = stack.pop()
            for v in predecessors[w]:
                if num_paths[w] > 0:
                    delta[v] += (num_paths[v] / num_paths[w]) * (1.0 + delta[w])
            if w != s:
                betweenness[w] += delta[w]

    # Normalize for undirected graph: divide by (n-1)(n-2)
    norm = float((n - 1) * (n - 2))
    for key in keys:
        _entity_nodes[key].betweenness = betweenness[key] / norm if norm > 0 else 0.0

    top = sorted(keys, key=lambda k: _entity_nodes[k].betweenness, reverse=True)[:3]
    if top:
        print(f"🌉 Top brokers: {', '.join(_entity_nodes[k].name for k in top)}")


def _compute_communities() -> None:
    """
    Simplified Louvain community detection via greedy modularity maximization.
    Stores community_id on each EntityNode.
    """
    keys = list(_entity_nodes.keys())
    n = len(keys)
    if n == 0:
        return

    # Total edge weight
    m = sum(sum(v.values()) for v in _edges.values()) / 2.0
    if m == 0:
        for i, k in enumerate(keys):
            _entity_nodes[k].community_id = i
        return

    # community[node_key] = community_label (initially = node_key itself)
    community: dict[str, str] = {k: k for k in keys}
    # sigma[comm_label] = sum of degrees of all nodes in that community
    degree: dict[str, float] = {k: float(sum(_edges.get(k, {}).values())) for k in keys}
    sigma: dict[str, float] = {k: degree[k] for k in keys}

    improved = True
    max_iter = 30
    iteration = 0

    while improved and iteration < max_iter:
        improved = False
        iteration += 1

        for v in keys:
            c_v = community[v]
            k_v = degree[v]

            # Compute edges from v to each neighboring community
            k_in: dict[str, float] = {}
            for neighbor, weight in _edges.get(v, {}).items():
                if neighbor not in _entity_nodes:
                    continue
                nc = community[neighbor]
                k_in[nc] = k_in.get(nc, 0.0) + weight

            # Temporarily remove v from its community
            sigma[c_v] -= k_v
            k_in_current = k_in.get(c_v, 0.0)

            best_comm = c_v
            best_gain = 0.0

            for d, ki_in_d in k_in.items():
                if d == c_v:
                    continue
                # ΔQ = (ki_in_d - ki_in_current) / m + k_v * (sigma[c_v] - sigma[d]) / (2m²)
                gain = (ki_in_d - k_in_current) / m + k_v * (sigma[c_v] - sigma.get(d, 0.0)) / (2 * m * m)
                if gain > best_gain:
                    best_gain = gain
                    best_comm = d

            if best_comm != c_v:
                community[v] = best_comm
                sigma[best_comm] = sigma.get(best_comm, 0.0) + k_v
                improved = True
            else:
                sigma[c_v] += k_v  # restore

    # Remap to sequential integers
    unique_comms = sorted(set(community.values()))
    remap = {old: new for new, old in enumerate(unique_comms)}
    for k in keys:
        _entity_nodes[k].community_id = remap[community[k]]

    num_communities = len(unique_comms)
    print(f"🏘  Comunidades detectadas: {num_communities}")


def _deduplicate_entities() -> None:
    """
    Fusiona entidades casi duplicadas (ej: 'Pedro' ⊂ 'Pedro Suárez').
    Estrategia: si el nombre de un nodo es substring del nombre de otro
    nodo del mismo tipo y el ratio de similitud es alto, se fusionan
    en el nodo más específico (el más largo).
    """
    global _entity_nodes, _edges

    keys = list(_entity_nodes.keys())
    # Mapa: clave_a_eliminar → clave_a_conservar
    merge_map: dict[str, str] = {}

    for i, key_a in enumerate(keys):
        if key_a in merge_map:
            continue
        node_a = _entity_nodes[key_a]
        for key_b in keys[i + 1:]:
            if key_b in merge_map:
                continue
            node_b = _entity_nodes[key_b]
            # Sólo fusionar mismo tipo de entidad
            if node_a.entity_type != node_b.entity_type:
                continue
            # Substring: el más corto es parte del más largo
            if key_a in key_b or key_b in key_a:
                # Conservar el nombre más largo (más específico)
                keep, drop = (key_b, key_a) if len(key_b) > len(key_a) else (key_a, key_b)
                merge_map[drop] = keep

    if not merge_map:
        return

    # Aplicar fusiones
    for drop_key, keep_key in merge_map.items():
        if drop_key not in _entity_nodes or keep_key not in _entity_nodes:
            continue
        drop_node = _entity_nodes.pop(drop_key)
        keep_node = _entity_nodes[keep_key]
        # Fusionar doc_ids y menciones
        for did in drop_node.doc_ids:
            if did not in keep_node.doc_ids:
                keep_node.doc_ids.append(did)
        keep_node.mentions += drop_node.mentions
        # Redirigir aristas del nodo eliminado al nodo conservado
        for neighbor, weight in list(_edges.get(drop_key, {}).items()):
            real_neighbor = merge_map.get(neighbor, neighbor)
            if real_neighbor == keep_key:
                continue  # No auto-aristas
            _edges[keep_key][real_neighbor] += weight
            _edges[real_neighbor][keep_key] += weight
            # Limpiar referencia antigua
            _edges[real_neighbor].pop(drop_key, None)
        _edges.pop(drop_key, None)

    print(f"🔀 Entidades fusionadas: {len(merge_map)} duplicados eliminados.")


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
