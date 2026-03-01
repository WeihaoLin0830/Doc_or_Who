"""
graph/ — Grafo de conocimiento de entidades.

  graph.py → construcción del grafo, detección de comunidades,
             betweenness centrality, persistencia en JSON.

Este __init__.py re-exporta la API pública del módulo para que los imports
del tipo `from backend.graph import get_graph_data` sigan funcionando.
Los state internos (_documents, _entity_nodes) deben importarse directamente
desde backend.graph.graph para no perder la rebind que hace load_graph().
"""
from backend.graph.graph import (  # noqa: F401
    build_graph,
    get_graph_data,
    get_graph_data_filtered,
    get_all_entities,
    get_entity,
    get_related_entities,
    get_related_docs,
    find_connection_path,
    search_entities,
    get_stats,
    get_communities,
    get_top_brokers,
    load_graph,
    add_document_to_graph,
)
