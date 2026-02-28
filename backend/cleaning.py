"""
cleaning.py — Limpieza de texto y detección de idioma.

Normaliza whitespace, arregla encoding roto, elimina ruido de PDF/OCR.
"""

import re

try:
    import ftfy
except ImportError:
    ftfy = None  # type: ignore


def clean_text(raw: str) -> str:
    """
    Pipeline de limpieza de texto extraído.
    1. Fix encoding con ftfy
    2. Normalizar whitespace
    3. Eliminar ruido de headers/footers de PDF
    4. Strip final
    """
    text = raw

    # 1. Reparar problemas de encoding (caracteres rotos del CSV/OCR)
    if ftfy is not None:
        text = ftfy.fix_text(text)

    # 2. Normalizar whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)        # Máximo 2 saltos de línea
    text = re.sub(r"[ \t]{2,}", " ", text)        # Múltiples espacios → 1
    text = re.sub(r"[ \t]+\n", "\n", text)        # Trailing spaces antes de newline

    # 3. Quitar ruido típico de PDFs: separadores de página, numeración suelta
    # Cubre: "--- Página 1 ---", "=== Page 2 ===", "Página 1 de 5", número sólo
    text = re.sub(r"[-=*_]{2,}\s*[Pp][aá]g(?:ina)?[s]?\s*\d+(?:\s*(?:de|of)\s*\d+)?\s*[-=*_]{0,10}", "", text)
    text = re.sub(r"[Pp]ágina\s+\d+(?:\s+de\s+\d+)?", "", text)
    text = re.sub(r"[Pp]age\s+\d+(?:\s+of\s+\d+)?", "", text)
    text = re.sub(r"^\s*\d{1,3}\s*$", "", text, flags=re.MULTILINE)
    # Quitar líneas que sólo tienen guiones, iguales o asteriscos (separadores visuales)
    text = re.sub(r"^\s*[-=*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    return text.strip()


def detect_language(text: str) -> str:
    """
    Detecta el idioma del texto usando langdetect.
    Solo analiza los primeros 500 caracteres (suficiente y rápido).
    Devuelve código ISO 639-1: 'es', 'ca', 'en', etc.
    """
    try:
        from langdetect import detect
        return detect(text[:500])
    except Exception:
        return "es"  # Fallback: español
