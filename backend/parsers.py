from __future__ import annotations

from pathlib import Path

from backend.extractors.office import extract_docx, extract_pptx
from backend.extractors.pdf import extract_pdf
from backend.extractors.tabular import extract_csv, extract_xlsx
from backend.extractors.text import extract_text_file
from backend.types import ExtractionResult

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md", ".csv", ".xlsx"}
UNSUPPORTED_BUT_KNOWN = {".doc", ".ppt", ".xls", ".docm", ".pptm", ".xlsm"}


def parse_file(path: Path) -> ExtractionResult:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return extract_pdf(path)
    if ext == ".docx":
        return extract_docx(path)
    if ext == ".pptx":
        return extract_pptx(path)
    if ext in {".txt", ".md"}:
        return extract_text_file(path)
    if ext == ".csv":
        return extract_csv(path)
    if ext == ".xlsx":
        return extract_xlsx(path)
    raise ValueError(f"Unsupported file type: {ext}")
