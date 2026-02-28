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
                "Busca fragmentos relevantes en los documentos corporativos "
                "usando búsqueda híbrida semántica + BM25. Usa esta herramienta "
                "para cualquier pregunta sobre contenido textual."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Búsqueda en lenguaje natural. Sé específico.",
                    },
                    "doc_type": {
                        "type": "string",
                        "description": (
                            "Filtro OPCIONAL por tipo de documento. "
                            "Valores EXACTOS válidos: acta_reunion, contrato, "
                            "documento, email, factura, informe, inventario, "
                            "listado, memo, tabla, tickets, ventas. "
                            "Déjalo vacío si no estás seguro del tipo."
                        ),
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
                "nóminas, incidencias, presupuestos) ejecutando SQL sobre "
                "CSV/XLSX cargados en DuckDB. Úsala SOLO para cifras, "
                "totales, conteos, comparativas o listados filtrados."
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
                "Obtiene información sobre una persona u organización del "
                "grafo de conocimiento: documentos donde aparece, entidades "
                "relacionadas, comunidad y si es broker de información. "
                "Usa esta herramienta SOLO cuando se pregunte específicamente "
                "sobre una persona u organización."
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
                "(personas u organizaciones). Usa SOLO cuando se pregunte "
                "explícitamente cómo se relacionan dos entidades."
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
                "Lista las tablas SQL disponibles con su esquema (columnas, "
                "tipos, filas). Llama ANTES de query_data si no conoces "
                "qué tablas o columnas existen."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "peek_table",
            "description": (
                "Muestra las primeras filas de una tabla SQL para entender "
                "qué datos contiene y cómo están formateados. Úsala cuando "
                "necesites ver datos de ejemplo antes de hacer una query."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Nombre exacto de la tabla",
                    },
                    "num_rows": {
                        "type": "integer",
                        "description": "Filas a mostrar (default 5, max 10)",
                    },
                },
                "required": ["table_name"],
            },
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

def _tool_search_documents(query: str, doc_type: str = "") -> str:
    """Búsqueda híbrida con filtro de tipo opcional."""
    from backend.search.searcher import hybrid_search

    # Normalizar doc_type vacío a None
    doc_type_filter = doc_type.strip() if doc_type else None
    if doc_type_filter == "":
        doc_type_filter = None

    results = hybrid_search(query=query, doc_type=doc_type_filter, top_k=8)
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
            "text": r.text[:800],
            "score": round(r.score, 3),
        })

    return json.dumps(
        {"found": len(chunks), "chunks": chunks},
        ensure_ascii=False,
    )


def _tool_query_data(question: str) -> str:
    """Text-to-SQL con loop de auto-corrección (hasta 3 intentos)."""
    from backend.ai.sql_engine import natural_language_to_sql, execute_sql, load_tables

    load_tables()
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
    """Busca una entidad en el grafo con fuzzy matching."""
    from backend.graph import (
        get_entity, get_related_entities, get_related_docs, get_top_brokers,
        search_entities,
    )

    node = get_entity(entity_name)

    # Si no se encuentra exacto, buscar fuzzy
    if not node:
        candidates = search_entities(entity_name, top_k=3)
        if candidates:
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
            {"doc_id": d.get("doc_id", ""), "title": d.get("title", ""),
             "filename": d.get("filename", "")}
            for d in docs[:8]
        ],
    }, ensure_ascii=False)


def _resolve_entity_name(name: str) -> str:
    """Intenta resolver un nombre parcial al nombre completo del grafo."""
    from backend.graph import get_entity, search_entities

    if get_entity(name):
        return name
    candidates = search_entities(name, top_k=1)
    if candidates:
        return candidates[0]["name"]
    return name


def _tool_find_connection(entity_a: str, entity_b: str) -> str:
    """Busca camino entre dos entidades, con fuzzy matching de nombres."""
    from backend.graph import find_connection_path

    resolved_a = _resolve_entity_name(entity_a)
    resolved_b = _resolve_entity_name(entity_b)

    result = find_connection_path(resolved_a, resolved_b)
    return json.dumps(result, ensure_ascii=False)


def _tool_list_tables() -> str:
    """Lista tablas SQL con esquema resumido."""
    from backend.ai.sql_engine import get_table_list, load_tables

    load_tables()
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


def _tool_peek_table(table_name: str, num_rows: int = 5) -> str:
    """Muestra las primeras filas de una tabla para inspección."""
    from backend.ai.sql_engine import execute_sql, load_tables

    # Asegurarse de que las tablas están cargadas
    load_tables()

    num_rows = min(max(1, num_rows), 10)
    result = execute_sql(f'SELECT * FROM "{table_name}" LIMIT {num_rows}')

    if result.get("error"):
        return json.dumps({"error": result["error"]})

    return json.dumps(
        {
            "table": table_name,
            "columns": result["columns"],
            "sample_rows": result["rows"],
            "showing": len(result["rows"]),
        },
        ensure_ascii=False,
        default=str,
    )


# Mapeo nombre → función
_HANDLERS = {
    "search_documents": _tool_search_documents,
    "query_data": _tool_query_data,
    "get_entity_info": _tool_get_entity_info,
    "find_connection": _tool_find_connection,
    "list_available_tables": _tool_list_tables,
    "peek_table": _tool_peek_table,
}
