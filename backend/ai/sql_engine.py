"""
sql_engine.py — Motor SQL sobre datos tabulares con DuckDB.

Carga automáticamente CSVs y XLSX del dataset como tablas DuckDB.
Permite ejecutar consultas SQL sobre datos numéricos/tabulares
sin necesidad de parsear el texto.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.config import DATASET_DIR, UPLOAD_DIR, DUCKDB_PATH

# ─── Lazy loading ────────────────────────────────────────────────
_con = None
_loaded_tables: set[str] = set()


def _get_connection():
    """Obtiene la conexión DuckDB (lazy, singleton)."""
    global _con
    if _con is None:
        try:
            import duckdb
            DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _con = duckdb.connect(str(DUCKDB_PATH))
        except ImportError:
            print("⚠️  duckdb no instalado. pip install duckdb")
            return None
    return _con


def _sanitize_table_name(name: str) -> str:
    """Convierte un nombre de fichero en un nombre de tabla SQL válido."""
    name = name.rsplit(".", 1)[0]  # Quitar extensión
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)  # Solo alfanuméricos
    name = re.sub(r"_+", "_", name).strip("_")   # Limpiar duplicados
    if name[0].isdigit():
        name = "t_" + name
    return name.lower()


def load_tables() -> list[str]:
    """
    Escanea DATASET_DIR y UPLOAD_DIR, carga todos los CSV/XLSX como tablas.
    Devuelve lista de nombres de tabla creados.
    """
    global _loaded_tables
    con = _get_connection()
    if con is None:
        return []

    tables_created: list[str] = []

    for directory in [DATASET_DIR, UPLOAD_DIR]:
        if not directory.exists():
            continue
        for filepath in sorted(directory.iterdir()):
            ext = filepath.suffix.lower()
            if ext not in (".csv", ".xlsx", ".xls"):
                continue

            table_name = _sanitize_table_name(filepath.name)
            if table_name in _loaded_tables:
                continue

            try:
                if ext == ".csv":
                    _load_csv(con, filepath, table_name)
                else:
                    _load_excel(con, filepath, table_name)

                _loaded_tables.add(table_name)
                tables_created.append(table_name)
            except Exception as e:
                print(f"⚠️  Error cargando {filepath.name}: {e}")

    return tables_created


def _load_csv(con, filepath: Path, table_name: str):
    """Carga un CSV en DuckDB con auto-detección de separador."""
    raw = filepath.read_bytes()[:2000]
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            sample = raw.decode(enc)
            break
        except UnicodeDecodeError:
            sample = raw.decode("latin-1")
            enc = "latin-1"

    sep = ";" if sample.count(";") > sample.count(",") else ","

    con.execute(f"""
        CREATE OR REPLACE TABLE "{table_name}" AS
        SELECT * FROM read_csv_auto('{filepath}',
            delim='{sep}', header=true, ignore_errors=true,
            encoding='{enc}')
    """)


def _load_excel(con, filepath: Path, table_name: str):
    """Carga un Excel en DuckDB via pandas intermedio."""
    import pandas as pd
    df = pd.read_excel(filepath, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    con.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM df')


def execute_sql(query: str) -> dict:
    """
    Ejecuta una consulta SQL y devuelve resultados.
    Returns:
        dict con 'columns', 'rows', 'row_count', 'error'.
    """
    con = _get_connection()
    if con is None:
        return {"error": "DuckDB no disponible", "columns": [], "rows": [], "row_count": 0}

    # Cargar tablas si no están cargadas
    if not _loaded_tables:
        load_tables()

    try:
        result = con.execute(query)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()

        # Limitar resultado a 200 filas
        truncated = len(rows) > 200
        rows = rows[:200]

        # Convertir a lista de dicts
        rows_dicts = [dict(zip(columns, row)) for row in rows]

        return {
            "columns": columns,
            "rows": rows_dicts,
            "row_count": len(rows_dicts),
            "truncated": truncated,
            "error": None,
        }
    except Exception as e:
        return {
            "error": str(e),
            "columns": [],
            "rows": [],
            "row_count": 0,
        }


def get_table_list() -> list[dict]:
    """Devuelve info de todas las tablas disponibles."""
    con = _get_connection()
    if con is None:
        return []

    if not _loaded_tables:
        load_tables()

    tables = []
    for name in sorted(_loaded_tables):
        try:
            count_result = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
            row_count = count_result[0] if count_result else 0

            cols_result = con.execute(f"""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = '{name}'
            """).fetchall()

            tables.append({
                "name": name,
                "row_count": row_count,
                "columns": [{"name": c[0], "type": c[1]} for c in cols_result],
            })
        except Exception:
            tables.append({"name": name, "row_count": 0, "columns": []})

    return tables


def natural_language_to_sql(question: str, error_feedback: str = "") -> str | None:
    """
    Usa Groq LLM para convertir una pregunta en lenguaje natural
    a una consulta SQL sobre las tablas disponibles.

    Args:
        question: Pregunta del usuario.
        error_feedback: Si un intento anterior falló, el mensaje de error
                        se pasa aquí para que el LLM se autocorrija.
    """
    from backend.config import GROQ_API_KEY, GROQ_MODEL

    if not GROQ_API_KEY:
        return None

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
    except ImportError:
        return None

    # Obtener esquema de tablas con muestra de valores para columnas de texto
    tables = get_table_list()
    schema_text = ""
    for t in tables:
        cols = ", ".join([f"{c['name']} ({c['type']})" for c in t["columns"]])
        schema_text += f"  Tabla '{t['name']}' ({t['row_count']} filas): {cols}\n"
        # Añadir muestra de valores para detectar formato de fechas/columnas clave
        try:
            con = _get_connection()
            sample_row = con.execute(f'SELECT * FROM "{t["name"]}" LIMIT 1').fetchone()
            if sample_row:
                schema_text += f"    Ejemplo de fila: {sample_row}\n"
        except Exception:
            pass

    if not schema_text:
        return None

    prompt = f"""Genera UNA consulta SQL (DuckDB) que responda la siguiente pregunta.
SOLO devuelve la consulta SQL, sin explicaciones ni markdown.

Esquema de tablas disponibles:
{schema_text}

Pregunta: {question}"""

    if error_feedback:
        prompt += f"\n\nINTENTO ANTERIOR FALLÓ con error: {error_feedback}\nCorrige la consulta."

    prompt += "\n\nSQL:"

    try:
        for _attempt in range(2):
            try:
                response = client.chat.completions.create(
                    model=GROQ_MODEL,  # 8b rápido para SQL (el agente 70b orquesta)
                    messages=[
                        {"role": "system", "content": (
                            "Eres un experto en SQL y DuckDB. "
                            "Genera consultas DuckDB correctas y concisas. "
                            "Devuelve SOLO la consulta SQL, sin explicaciones, sin markdown, sin ```sql. "
                            "Usa los nombres exactos de tabla y columna del esquema. "
                            "REGLAS DuckDB importantes: "
                            "- Para diferencia de fechas usa date_diff('day', fecha_inicio, fecha_fin) con 3 args. "
                            "  NUNCA uses datediff(f1, f2) con 2 argumentos, eso NO existe en DuckDB. "
                            "- Si la pregunta pide CONTAR (cuántas, número de, total de registros), "
                            "  incluye COUNT(*) AS total junto con las demás métricas. "
                            "- Para decimales con coma (ej '895,00') usa REPLACE(col, ',', '.') y CAST a DOUBLE. "
                            "- Para filtrar fechas VARCHAR usa LIKE o CAST; para DATE usa comparaciones directas. "
                            "- Si calculas diferencia de fechas y puede haber NULLs, filtra con WHERE fecha IS NOT NULL."
                        )},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                    max_tokens=400,
                )
                break
            except Exception as retry_err:
                if "429" in str(retry_err) or "rate_limit" in str(retry_err):
                    import time; time.sleep(3 * (_attempt + 1))
                    continue
                raise
        sql = response.choices[0].message.content.strip()
        # Limpiar posible markdown
        sql = sql.replace("```sql", "").replace("```", "").strip()
        # Post-proceso: si la pregunta pide conteo y el SQL tiene GROUP BY pero
        # no COUNT, inyectar COUNT(*) AS total automáticamente.
        sql = _inject_count_if_needed(sql, question)
        return sql
    except Exception:
        return None


def _inject_count_if_needed(sql: str, question: str) -> str:
    """Inyecta COUNT(*) AS total si la pregunta pide contar y el SQL no lo tiene."""
    import unicodedata

    def _strip_accents(s: str) -> str:
        return "".join(
            c for c in unicodedata.normalize("NFD", s)
            if unicodedata.category(c) != "Mn"
        )

    # Normalizar pregunta (minúsculas, sin tildes) para detección robusta
    q_norm = _strip_accents(question.lower())
    count_words = (
        "cuantas", "cuantos", "numero de", "total de",
        "conteo", "count", "cuanto hay", "cuantos hay",
    )
    has_count_intent = any(w in q_norm for w in count_words)
    sql_upper = sql.upper()
    has_group_by = "GROUP BY" in sql_upper
    has_count = "COUNT(" in sql_upper

    if has_count_intent and has_group_by and not has_count:
        # Insertar COUNT(*) AS total justo después del SELECT
        sql = re.sub(
            r'(?i)^(SELECT\s+)',
            r'\1COUNT(*) AS total, ',
            sql,
            count=1,
        )
    return sql
