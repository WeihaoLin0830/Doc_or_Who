from __future__ import annotations

from pathlib import Path

from backend.types import ExtractionResult

TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "latin-1", "cp1252")


def extract_text_file(path: Path) -> ExtractionResult:
    for encoding in TEXT_ENCODINGS:
        try:
            text = path.read_text(encoding=encoding)
            return ExtractionResult(path=path, text=text, metadata={"encoding": encoding})
        except (UnicodeDecodeError, ValueError):
            continue
    text = path.read_text(encoding="utf-8", errors="replace")
    return ExtractionResult(path=path, text=text, metadata={"encoding": "utf-8-replace"})
