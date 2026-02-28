"""
chunker.py — Fragmentación adaptativa de documentos.

Cada tipo de documento tiene su propia estrategia de chunking.
Los chunks se crean con metadatos heredados del documento padre.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pandas as pd

from backend.config import MAX_CHUNK_TOKENS
from backend.models import Chunk, Document

if TYPE_CHECKING:
    pass


def chunk_document(doc: Document, df: pd.DataFrame | None = None) -> list[Chunk]:
    """
    Dispatcher: elige la estrategia de chunking según doc.doc_type.
    Devuelve una lista de Chunks listos para indexar.
    """
    strategy = {
        "acta_reunion": _chunk_acta,
        "email": _chunk_email,
        "memo": _chunk_memo,
        "listado": _chunk_listado,
        "tickets": lambda d, **kw: _chunk_csv(d, df, "tickets"),
        "inventario": lambda d, **kw: _chunk_csv(d, df, "inventario"),
        "ventas": lambda d, **kw: _chunk_csv(d, df, "ventas"),
        "tabla": lambda d, **kw: _chunk_csv(d, df, "tabla"),
    }

    func = strategy.get(doc.doc_type, _chunk_generic)
    chunks = func(doc)

    # Inyectar metadatos del padre en cada chunk
    for chunk in chunks:
        chunk.doc_id = doc.doc_id
        chunk.doc_type = doc.doc_type
        chunk.title = doc.title
        chunk.language = doc.language
        chunk.filename = doc.filename
        chunk.persons = doc.persons
        chunk.organizations = doc.organizations
        chunk.keywords = doc.keywords
        chunk.dates = doc.dates

    return chunks


# ─── ACTAS DE REUNIÓN ────────────────────────────────────────────
def _chunk_acta(doc: Document) -> list[Chunk]:
    """
    Divide un acta por secciones numeradas (1. TITULO, 2. TITULO...).
    Incluye el header del acta como prefijo de contexto en cada chunk.
    """
    text = doc.raw_text
    chunks: list[Chunk] = []

    # Extraer header (todo antes de la primera sección numerada)
    header_match = re.search(r"^(.*?)(?=\n\d+\.\s)", text, re.DOTALL)
    header = header_match.group(1).strip() if header_match else ""

    # Dividir por secciones numeradas
    sections = re.split(r"\n(?=\d+\.\s)", text)

    for i, section in enumerate(sections):
        section = section.strip()
        if not section:
            continue

        # Extraer nombre de sección
        sec_match = re.match(r"\d+\.\s*(.+?)(?:\n|$)", section)
        sec_name = sec_match.group(1).strip() if sec_match else f"Sección {i}"

        # Prefijo de contexto: header + nombre sección
        chunk_text = f"[Contexto: {header[:200]}]\n\n{section}" if header else section

        chunks.append(Chunk(
            chunk_id=f"{doc.doc_id}_sec{i}",
            text=chunk_text,
            chunk_index=i,
            section=sec_name,
        ))

    # Si no se encontraron secciones, chunk genérico
    if not chunks:
        return _chunk_generic(doc)

    return chunks


# ─── EMAILS ──────────────────────────────────────────────────────
def _chunk_email(doc: Document) -> list[Chunk]:
    """
    Divide un hilo de emails por mensaje individual.
    Cada mensaje conserva sus headers (De, Para, Fecha, Asunto).
    """
    text = doc.raw_text
    chunks: list[Chunk] = []

    # Separar mensajes por línea "---" o "De:" al inicio de línea
    messages = re.split(r"\n---\n", text)

    for i, msg in enumerate(messages):
        msg = msg.strip()
        if not msg:
            continue

        chunks.append(Chunk(
            chunk_id=f"{doc.doc_id}_msg{i}",
            text=msg,
            chunk_index=i,
            section=f"Mensaje {i + 1}",
            level="micro",
        ))

    # Chunk extra: resumen del hilo completo
    if len(messages) > 1:
        chunks.append(Chunk(
            chunk_id=f"{doc.doc_id}_thread",
            text=f"[Hilo completo de email — {len(messages)} mensajes]\n\n{text}",
            chunk_index=len(messages),
            section="Hilo completo",
            level="macro",
        ))

    return chunks if chunks else _chunk_generic(doc)


# ─── MEMOS / COMUNICADOS ────────────────────────────────────────
def _chunk_memo(doc: Document) -> list[Chunk]:
    """
    Si el memo es corto (< MAX_CHUNK_TOKENS), un solo chunk.
    Si es largo, dividir por secciones numeradas o por párrafos.
    """
    text = doc.raw_text
    word_count = len(text.split())

    # Memo corto: indexar el documento completo como un solo chunk
    if word_count < MAX_CHUNK_TOKENS:
        return [Chunk(
            chunk_id=f"{doc.doc_id}_full",
            text=text,
            chunk_index=0,
            section="Documento completo",
        )]

    # Memo largo: intentar dividir por secciones
    sections = re.split(r"\n(?=[A-ZÁÉÍÓÚÑ]{3,})", text)
    if len(sections) < 2:
        sections = re.split(r"\n\s*\d+\.\s", text)

    chunks: list[Chunk] = []
    for i, sec in enumerate(sections):
        sec = sec.strip()
        if len(sec) < 20:
            continue
        chunks.append(Chunk(
            chunk_id=f"{doc.doc_id}_sec{i}",
            text=sec,
            chunk_index=i,
            section=f"Sección {i}",
        ))

    return chunks if chunks else _chunk_generic(doc)


# ─── LISTADOS (Proveedores, etc.) ───────────────────────────────
def _chunk_listado(doc: Document) -> list[Chunk]:
    """
    Un chunk por bloque de entidad (cada proveedor = 1 chunk).
    Detecta bloques por numeración (1. Nombre, 2. Nombre...).
    """
    text = doc.raw_text
    chunks: list[Chunk] = []

    # Separar por entradas numeradas
    entries = re.split(r"\n(?=\d{1,2}\.\s)", text)

    # El primer bloque es normalmente el header
    header = entries[0].strip() if entries else ""

    for i, entry in enumerate(entries[1:], start=1):
        entry = entry.strip()
        if not entry:
            continue

        # Extraer nombre de la entidad (primera línea del bloque)
        first_line = entry.split("\n")[0]
        name = re.sub(r"^\d+\.\s*", "", first_line).strip()

        chunks.append(Chunk(
            chunk_id=f"{doc.doc_id}_ent{i}",
            text=f"[{header[:150]}]\n\n{entry}",
            chunk_index=i,
            section=name,
            level="micro",
        ))

    # Chunk de resumen con el header completo
    if header:
        chunks.insert(0, Chunk(
            chunk_id=f"{doc.doc_id}_header",
            text=header,
            chunk_index=0,
            section="Resumen listado",
            level="macro",
        ))

    return chunks if chunks else _chunk_generic(doc)


# ─── CSV / DATOS TABULARES ───────────────────────────────────────
def _chunk_csv(doc: Document, df: pd.DataFrame | None, subtype: str) -> list[Chunk]:
    """
    Triple nivel de chunking para datos tabulares:
    - Nivel 1 (micro): cada fila como texto natural
    - Nivel 2 (meso): agrupación por entidad clave
    - Nivel 3 (macro): resumen estadístico del fichero
    """
    if df is None or df.empty:
        return _chunk_generic(doc)

    chunks: list[Chunk] = []

    # ── Nivel 1: fila a texto natural ──
    for idx, row in df.iterrows():
        parts = [f"{col}: {val}" for col, val in row.items() if pd.notna(val)]
        row_text = " | ".join(parts)
        chunks.append(Chunk(
            chunk_id=f"{doc.doc_id}_row{idx}",
            text=row_text,
            chunk_index=int(idx) if isinstance(idx, (int, float)) else 0,
            section=f"Fila {idx}",
            level="micro",
        ))

    # ── Nivel 2: agrupación por entidad clave ──
    group_col = _find_group_column(df, subtype)
    if group_col and group_col in df.columns:
        for name, group in df.groupby(group_col):
            summary_lines = []
            for _, row in group.iterrows():
                parts = [f"{c}: {v}" for c, v in row.items() if pd.notna(v) and c != group_col]
                summary_lines.append(" | ".join(parts))
            group_text = f"{group_col}: {name} ({len(group)} registros)\n" + "\n".join(summary_lines[:20])
            chunks.append(Chunk(
                chunk_id=f"{doc.doc_id}_grp_{str(name)[:30]}",
                text=group_text,
                chunk_index=0,
                section=f"{group_col}: {name}",
                level="meso",
            ))

    # ── Nivel 3: resumen global ──
    stats_text = _generate_csv_summary(df, subtype, doc.filename)
    chunks.append(Chunk(
        chunk_id=f"{doc.doc_id}_summary",
        text=stats_text,
        chunk_index=0,
        section="Resumen estadístico",
        level="macro",
    ))

    return chunks


def _find_group_column(df: pd.DataFrame, subtype: str) -> str | None:
    """Elige la columna de agrupación según el tipo de CSV."""
    col_map = {
        "tickets": "cliente",
        "inventario": "departamento",
        "ventas": "cliente",
    }
    preferred = col_map.get(subtype)
    if preferred and preferred in df.columns:
        return preferred
    return None


def _generate_csv_summary(df: pd.DataFrame, subtype: str, filename: str) -> str:
    """Genera un resumen estadístico en texto natural del DataFrame."""
    lines = [f"Resumen de '{filename}': {len(df)} filas, {len(df.columns)} columnas."]

    # Contar valores únicos de columnas categóricas
    for col in df.columns:
        if df[col].dtype == "object" and df[col].nunique() < 30:
            top = df[col].value_counts().head(5)
            top_str = ", ".join(f"{k} ({v})" for k, v in top.items())
            lines.append(f"  {col}: {df[col].nunique()} valores únicos. Top: {top_str}")

    # Columnas numéricas
    numeric = df.select_dtypes(include="number")
    for col in numeric.columns:
        lines.append(f"  {col}: min={numeric[col].min()}, max={numeric[col].max()}, "
                     f"media={numeric[col].mean():.1f}")

    return "\n".join(lines)


# ─── GENÉRICO (fallback) ─────────────────────────────────────────
def _chunk_generic(doc: Document) -> list[Chunk]:
    """
    Chunking genérico por ventana de palabras con solapamiento.
    Usado como fallback si no hay estrategia específica.
    """
    text = doc.raw_text
    words = text.split()
    chunks: list[Chunk] = []

    step = MAX_CHUNK_TOKENS
    overlap = 50
    i = 0
    idx = 0

    while i < len(words):
        chunk_words = words[i: i + step]
        chunk_text = " ".join(chunk_words)
        chunks.append(Chunk(
            chunk_id=f"{doc.doc_id}_chunk{idx}",
            text=chunk_text,
            chunk_index=idx,
        ))
        i += step - overlap
        idx += 1

    return chunks
