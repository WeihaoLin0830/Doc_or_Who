"""
agent_tools.py — Herramientas que el agente puede invocar.

Cada tool es una función Python que se expone al LLM via function-calling.
TOOLS contiene las definiciones en formato OpenAI; execute_tool() las ejecuta.
"""

from __future__ import annotations

import json
from typing import Any


# ─── Definiciones de herramientas (OpenAI function-calling format) ─
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "Busca fragmentos relevantes en documentos de texto "
                "(actas, emails, memos, informes). Usa esta herramienta cuando "
                "la pregunta trata sobre políticas, comunicaciones, reuniones "
                "o cualquier información no numérica/tabular."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Búsqueda en lenguaje natural",
                    },
                    "doc_type": {
                        "type": "string",
                        "description": "Filtrar por tipo: email, memo, acta, informe, csv, otro (opcional)",
                    },
                    "date_filter": {
                        "type": "string",
                        "description": "Filtrar por fecha ISO: YYYY, YYYY-MM o YYYY-MM-DD (opcional)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_data",
            "description": (
                "Consulta datos numéricos y tabulares (ventas, inventarios, "
                "incidencias) ejecutando SQL sobre CSV/XLSX cargados en DuckDB. "
                "Usa esta herramienta para cifras, totales, comparativas, "
                "listados filtrados o estadísticas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Pregunta en lenguaje natural sobre datos tabulares",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_info",
            "description": (
                "Obtiene información sobre una persona u organización del grafo "
                "de conocimiento: documentos donde aparece, entidades relacionadas, "
                "comunidad y si es un broker de información."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {
                        "type": "string",
                        "description": "Nombre de la persona u organización",
                    },
                },
                "required": ["entity_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_connection",
            "description": (
                "Encuentra el camino de relaciones entre dos entidades "
                "(personas u organizaciones). Muestra qué las conecta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_a": {"type": "string", "description": "Entidad origen"},
                    "entity_b": {"type": "string", "description": "Entidad destino"},
                },
                "required": ["entity_a", "entity_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_available_tables",
            "description": (
                "Lista las tablas SQL disponibles con su esquema (columnas y tipos). "
                "Llama a esta herramienta ANTES de query_data si no conoces "
                "qué tablas o columnas existen."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ─── Ejecutor de herramientas ────────────────────────────────────
def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Ejecuta una tool por nombre y devuelve resultado como JSON string."""
    try:
        handler = _HANDLERS.get(name)
        if not handler:
            return json.dumps({"error": f"Tool desconocida: {name}"})
        return handler(**arguments)
    except Exception as e:
        return json.dumps({"error": f"Error en {name}: {e}"})


# ─── Implementación de cada tool ─────────────────────────────────

def _tool_search_documents(
    query: str,
    doc_type: str | None = None,
    date_filter: str | None = None,
) -> str:
    from backend.search.searcher import hybrid_search

    # Limpiar strings vacíos que el LLM a veces envía
    doc_type = doc_type or None
    date_filter = date_filter or None

    results = hybrid_search(
        query=query,
        doc_type=doc_type,
        date=date_filter,
        top_k=8,
    )
    if not results:
        return json.dumps({"found": 0, "chunks": []})

    chunks = []
    for r in results:
        chunks.append({
            "filename": r.filename,
            "title": r.title,
            "doc_type": r.doc_type,
            "dates": r.dates[:3],
            "persons": r.persons[:5],
            "organizations": r.organizations[:5],
            "text": r.text[:600],
            "score": round(r.score, 3),
        })

    return json.dumps(
        {"found": len(chunks), "chunks": chunks},
        ensure_ascii=False,
    )


def _tool_query_data(question: str) -> str:
    from backend.ai.sql_engine import natural_language_to_sql, execute_sql

    # Loop de auto-corrección: hasta 3 intentos
    error_feedback = ""
    sql = None
    result = None

    for _ in range(3):
        sql = natural_language_to_sql(question, error_feedback=error_feedback)
        if not sql:
            return json.dumps({"error": "No se pudo generar SQL"})

        result = execute_sql(sql)
        if not result.get("error"):
            break
        error_feedback = result["error"]
        sql = None

    if not sql or (result and result.get("error")):
        return json.dumps({"error": f"SQL inválido tras 3 intentos: {error_feedback}"})

    return json.dumps(
        {
            "sql": sql,
            "columns": result["columns"],
            "rows": result["rows"][:30],
            "total_rows": result["row_count"],
        },
        ensure_ascii=False,
        default=str,
    )


def _tool_get_entity_info(entity_name: str) -> str:
    from backend.graph import (
        get_entity, get_related_entities, get_related_docs, get_top_brokers,
        search_entities,
    )

    node = get_entity(entity_name)

    # Si no se encuentra exacto, buscar fuzzy
    if not node:
        candidates = search_entities(entity_name, top_k=3)
        if candidates:
            # Reintentar con el mejor match
            node = get_entity(candidates[0]["name"])
        if not node:
            return json.dumps({
                "error": f"Entidad '{entity_name}' no encontrada",
                "sugerencias": [c["name"] for c in candidates] if candidates else [],
            })

    brokers = get_top_brokers(top_k=20)
    is_broker = any(b["name"] == node.name for b in brokers)
    broker_rank = next(
        (i + 1 for i, b in enumerate(brokers) if b["name"] == node.name),
        None,
    )

    related = get_related_entities(node.name, top_k=8)
    docs = get_related_docs(node.name)

    return json.dumps({
        "name": node.name,
        "type": node.entity_type,
        "mentions": node.mentions,
        "community_id": node.community_id,
        "is_broker": is_broker,
        "broker_rank": broker_rank,
        "related_entities": [
            {"name": r["name"], "type": r["type"], "weight": r["weight"]}
            for r in related
        ],
        "documents": [
            {"doc_id": d.get("doc_id", ""), "title": d.get("title", ""), "filename": d.get("filename", "")}
            for d in docs[:8]
        ],
    }, ensure_ascii=False)


def _tool_find_connection(entity_a: str, entity_b: str) -> str:
    from backend.graph import find_connection_path
    result = find_connection_path(entity_a, entity_b)
    return json.dumps(result, ensure_ascii=False)


def _tool_list_tables() -> str:
    from backend.ai.sql_engine import get_table_list

    tables = get_table_list()
    if not tables:
        return json.dumps({"tables": [], "note": "No hay tablas disponibles"})

    summary = []
    for t in tables:
        cols_str = ", ".join(f"{c['name']} ({c['type']})" for c in t["columns"])
        summary.append({
            "name": t["name"],
            "row_count": t["row_count"],
            "columns": cols_str,
        })

    return json.dumps({"tables": summary}, ensure_ascii=False)


# Mapeo nombre → función
_HANDLERS = {
    "search_documents": _tool_search_documents,
    "query_data": _tool_query_data,
    "get_entity_info": _tool_get_entity_info,
    "find_connection": _tool_find_connection,
    "list_available_tables": _tool_list_tables,
}
