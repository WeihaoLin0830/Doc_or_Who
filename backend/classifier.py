"""
classifier.py — Clasificar tipo de documento por reglas.

Sin LLM, sin modelo ML. Solo regex sobre el contenido + nombre de fichero.
Rápido, determinista, sin errores aleatorios.
"""

import re

import pandas as pd


# ─── Tipos de documento reconocidos ──────────────────────────────
DOC_TYPES = [
    "acta_reunion",
    "email",
    "memo",
    "contrato",
    "factura",
    "listado",
    "tickets",
    "inventario",
    "ventas",
    "tabla",
    "documento",  # fallback genérico
]


def classify_document(text: str, filename: str, df: pd.DataFrame | None = None) -> str:
    """
    Clasifica el tipo de documento por reglas.

    Primero intenta por estructura del CSV (si hay DataFrame).
    Luego por contenido del texto (regex).
    Devuelve uno de los DOC_TYPES.
    """

    # ── CSVs: clasificar por nombres de columna ──
    if df is not None:
        cols = [c.lower().strip() for c in df.columns]
        if "id_ticket" in cols:
            return "tickets"
        if "id_equipo" in cols:
            return "inventario"
        if "vendedor" in cols or "precio_unitario" in cols:
            return "ventas"
        return "tabla"

    # ── Texto: clasificar por contenido ──
    t = text.lower()

    if re.search(r"acta de reuni[oó]n|sprint review|asistentes:", t):
        return "acta_reunion"

    if re.search(r"^de:\s*.+\n.*para:", t, re.MULTILINE):
        return "email"

    if re.search(r"memorándum|memorando|circular interna", t):
        return "memo"

    if re.search(r"contrato|cláusula|firmado por|otorgante", t):
        return "contrato"

    if re.search(r"factura|base imponible|iva|importe total", t):
        return "factura"

    if re.search(r"proveedor|cif:|rating:", t):
        return "listado"

    return "documento"
