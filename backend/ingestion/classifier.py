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
    "informe",
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
    # ORDEN IMPORTA: reglas más específicas primero
    t = text.lower()
    fname = filename.lower()

    # 1. Por nombre de fichero (alta confianza)
    if "acta" in fname and "reunion" in fname:
        return "acta_reunion"
    if "memo" in fname:
        return "memo"
    if "factura" in fname or "invoice" in fname:
        return "factura"
    if "contrato" in fname or "nda" in fname:
        return "contrato"
    if "proveedores" in fname:
        return "listado"
    if "ficha" in fname or "manual" in fname or "catalogo" in fname:
        return "documento"
    if "presupuesto" in fname or "nomina" in fname:
        return "tabla"
    if "informe" in fname or "auditoria" in fname:
        return "informe"
    if "certificado" in fname or "pliego" in fname or "licitacion" in fname:
        return "documento"
    if "pedido" in fname or "order" in fname:
        return "factura"
    if "offer" in fname or "propuesta" in fname:
        return "contrato"

    # 2. Por contenido (menor confianza, reglas estrechas)
    if re.search(r"acta de reuni[oó]n|sprint review|sprint #\d+", t):
        return "acta_reunion"

    if re.search(r"memorándum|memorando|circular interna", t):
        return "memo"

    if re.search(r"^de:\s*.+\n.*para:", t, re.MULTILINE):
        return "email"

    if re.search(r"base imponible|n\.?º\s*factura|importe total", t):
        return "factura"

    if re.search(r"cláusula\s+\d|firmado por ambas|las partes acuerdan", t):
        return "contrato"

    if re.search(r"listado de proveedores|rating:|cif:", t):
        return "listado"

    return "documento"
