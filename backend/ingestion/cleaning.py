"""
cleaning.py — Limpieza de texto y detección de idioma.

Normaliza whitespace, arregla encoding roto, elimina ruido de PDF/OCR.
"""

import re
import unicodedata

try:
    import ftfy
except ImportError:
    ftfy = None  # type: ignore

# Guiones Unicode que deben normalizarse a espacio simple
# (em-dash, en-dash, horizontal bar, figure dash, swung dash…)
_UNICODE_DASHES_RE = re.compile(
    r"[\u2012\u2013\u2014\u2015\u2016\u2017\u2E3A\u2E3B\uFE58\uFE63\uFF0D]"
)

# URLs y emails que polucionan el índice con tokens sin valor semántico
_URL_RE = re.compile(
    r"https?://[^\s]+|www\.[^\s]+", re.IGNORECASE
)
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)


def clean_text(raw: str) -> str:
    """
    Pipeline de limpieza de texto extraído.
    1. Fix encoding con ftfy
    2. Eliminar caracteres de control (excepto whitespace estándar)
    3. Normalizar guiones Unicode a espacio
    4. Eliminar URLs y emails (polutan el índice con tokens sin valor)
    5. Normalizar whitespace
    6. Eliminar ruido de headers/footers de PDF
    7. Strip final
    """
    text = raw

    # 1. Reparar problemas de encoding (caracteres rotos del CSV/OCR)
    if ftfy is not None:
        text = ftfy.fix_text(text)

    # 2. Eliminar caracteres de control que no sean \n \r \t espacio
    text = "".join(
        ch for ch in text
        if ch in ("\n", "\r", "\t", " ") or not unicodedata.category(ch).startswith("C")
    )

    # 3. Normalizar guiones Unicode largos → espacio (em-dash, en-dash, etc.)
    #    — y – en documentos corporativos suelen actuar como separadores de frase
    text = _UNICODE_DASHES_RE.sub(" ", text)

    # 4. Eliminar URLs y correos electrónicos del texto indexado
    #    Generan tokens inútiles como "https", "mailto", "www", "com"…
    text = _URL_RE.sub(" ", text)
    text = _EMAIL_RE.sub(" ", text)

    # 5. Normalizar whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)        # Máximo 2 saltos de línea
    text = re.sub(r"[ \t]{2,}", " ", text)        # Múltiples espacios → 1
    text = re.sub(r"[ \t]+\n", "\n", text)        # Trailing spaces antes de newline

    # 6. Quitar ruido típico de PDFs: separadores de página, numeración suelta
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
