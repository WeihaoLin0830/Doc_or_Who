"""
parsers.py — Extracción de texto de cada formato de fichero.

Cada parser recibe un Path y devuelve texto plano.
El dispatcher `parse_file()` elige el parser correcto por extensión.
"""

from pathlib import Path

import pandas as pd


# ─── Parser TXT ──────────────────────────────────────────────────
def parse_txt(filepath: Path) -> str:
    """Lee un fichero de texto plano con fallback de encoding."""
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return filepath.read_text(encoding=enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return filepath.read_text(encoding="utf-8", errors="replace")


# ─── Parser CSV ──────────────────────────────────────────────────
def parse_csv(filepath: Path) -> tuple[pd.DataFrame, str]:
    """
    Lee un CSV detectando el separador automáticamente.
    Devuelve (DataFrame, texto_representación).
    El texto es para indexar: cada fila convertida a frase natural.
    """
    # Detectar separador leyendo la primera línea
    raw_bytes = filepath.read_bytes()
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            sample = raw_bytes[:2000].decode(enc)
            break
        except UnicodeDecodeError:
            sample = raw_bytes[:2000].decode("latin-1")
            enc = "latin-1"

    sep = ";" if sample.count(";") > sample.count(",") else ","

    df = pd.read_csv(filepath, sep=sep, encoding=enc, on_bad_lines="skip")

    # Limpiar nombres de columna (quitar espacios extra)
    df.columns = [c.strip() for c in df.columns]

    return df, _dataframe_to_text(df, filepath.stem)


def _dataframe_to_text(df: pd.DataFrame, name: str) -> str:
    """Convierte un DataFrame a texto legible para indexación."""
    lines = [f"Datos de '{name}' — {len(df)} filas, columnas: {', '.join(df.columns)}\n"]
    for _, row in df.iterrows():
        parts = [f"{col}: {val}" for col, val in row.items() if pd.notna(val)]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


# ─── Parser PDF (PyMuPDF) ───────────────────────────────────────
def parse_pdf(filepath: Path) -> str:
    """
    Extrae texto de un PDF digital con PyMuPDF.
    Si no hay texto (PDF escaneado), devuelve cadena vacía
    y el caller puede aplicar OCR.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("⚠️  PyMuPDF no instalado. Saltando PDF:", filepath.name)
        return ""

    doc = fitz.open(str(filepath))
    pages = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            pages.append(text)
    doc.close()
    return "\n\n".join(pages)


# ─── Parser DOCX ─────────────────────────────────────────────────
def parse_docx(filepath: Path) -> str:
    """Extrae texto de un fichero .docx con python-docx."""
    try:
        from docx import Document as DocxDocument
    except ImportError:
        print("⚠️  python-docx no instalado. Saltando DOCX:", filepath.name)
        return ""

    doc = DocxDocument(str(filepath))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


# ─── Parser XLSX ──────────────────────────────────────────────────
def parse_xlsx(filepath: Path) -> tuple[pd.DataFrame, str]:
    """Lee un fichero Excel (.xlsx) y devuelve (DataFrame, texto)."""
    try:
        import openpyxl  # noqa: F401 — needed by pandas
    except ImportError:
        pass

    df = pd.read_excel(filepath, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    return df, _dataframe_to_text(df, filepath.stem)


# ─── Dispatcher principal ────────────────────────────────────────
def parse_file(filepath: Path) -> tuple[str, pd.DataFrame | None]:
    """
    Dispatcher: elige el parser correcto según la extensión.
    Devuelve (texto, dataframe_o_None).
    El DataFrame solo se devuelve para ficheros CSV/XLSX.
    """
    ext = filepath.suffix.lower()

    if ext in (".txt", ".md"):
        return parse_txt(filepath), None

    if ext == ".csv":
        df, text = parse_csv(filepath)
        return text, df

    if ext in (".xlsx", ".xls"):
        df, text = parse_xlsx(filepath)
        return text, df

    if ext == ".pdf":
        return parse_pdf(filepath), None

    if ext in (".docx", ".doc"):
        return parse_docx(filepath), None

    # Fallback: intentar como texto plano
    return parse_txt(filepath), None
