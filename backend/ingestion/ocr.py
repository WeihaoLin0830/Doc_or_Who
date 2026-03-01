"""
ocr.py — OCR para documentos escaneados (PDFs con imágenes).

Usa EasyOCR como motor de reconocimiento óptico de caracteres.
Cuando PyMuPDF no extrae texto de un PDF, renderizamos cada
página a imagen y aplicamos EasyOCR para obtener el texto.
"""

from __future__ import annotations

from pathlib import Path

# ─── Lazy loading ────────────────────────────────────────────────
_reader = None


def _get_reader():
    """Carga EasyOCR reader solo cuando se necesita (lazy). Usa GPU si está disponible."""
    global _reader
    if _reader is None:
        try:
            import easyocr
            import torch
            use_gpu = torch.cuda.is_available()
            print(f"🔍 Cargando EasyOCR ({'GPU' if use_gpu else 'CPU'})...")
            _reader = easyocr.Reader(["es", "en"], gpu=use_gpu, verbose=False)
            print("✅ EasyOCR listo.")
        except ImportError:
            print("⚠️  EasyOCR no instalado. pip install easyocr")
            _reader = False
    return _reader if _reader is not False else None


def ocr_pdf(filepath: Path, dpi: int = 150) -> str:
    """
    Aplica OCR a un PDF escaneado.

    1. Renderiza cada página como imagen con PyMuPDF.
    2. Pasa cada imagen por EasyOCR.
    3. Devuelve el texto concatenado de todas las páginas.
    """
    reader = _get_reader()
    if reader is None:
        return ""

    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("⚠️  PyMuPDF no instalado.")
        return ""

    doc = fitz.open(str(filepath))
    pages_text: list[str] = []

    # Limitar a las primeras 10 páginas para rendimiento en CPU
    max_pages = min(len(doc), 10)

    for page_num in range(max_pages):
        page = doc[page_num]
        # Renderizar página a imagen (pixmap)
        zoom = dpi / 72
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)

        # Convertir pixmap a bytes PNG para EasyOCR
        img_bytes = pix.tobytes("png")

        try:
            results = reader.readtext(img_bytes, detail=0, paragraph=True)
            page_text = "\n".join(results)
            if page_text.strip():
                pages_text.append(f"--- Página {page_num + 1} ---\n{page_text}")
        except Exception as e:
            print(f"⚠️  OCR error página {page_num + 1}: {e}")
            continue

    doc.close()
    return "\n\n".join(pages_text)
