from __future__ import annotations

from pathlib import Path

import fitz

from backend.ocr import get_ocr_provider, get_ocr_provider_status
from backend.types import ExtractionResult


def extract_pdf(path: Path) -> ExtractionResult:
    document = fitz.open(str(path))
    pages: list[str] = []
    metadata = {key: value for key, value in (document.metadata or {}).items() if value}
    metadata["page_count"] = document.page_count
    metadata["pages_with_text"] = 0
    for page_index, page in enumerate(document):
        text = page.get_text("text")
        if text.strip():
            pages.append(text)
            metadata["pages_with_text"] += 1
            metadata.setdefault("first_nonempty_page", page_index + 1)
    document.close()
    combined = "\n\n".join(pages)
    if combined.strip():
        metadata.update(
            {
                "ocr_applied": False,
                "ocr_attempted": False,
                "ocr_available": get_ocr_provider() is not None,
            }
        )
        return ExtractionResult(
            path=path,
            text=combined,
            metadata=metadata,
            needs_ocr=False,
        )

    metadata.update(get_ocr_provider_status())
    provider = get_ocr_provider()
    if provider is None:
        return ExtractionResult(
            path=path,
            text="",
            metadata=metadata,
            needs_ocr=True,
        )
    try:
        ocr_result = provider.extract_pdf(path)
    except Exception as exc:
        metadata.update(
            {
                "ocr_applied": False,
                "ocr_attempted": True,
                "ocr_error": str(exc),
            }
        )
        return ExtractionResult(
            path=path,
            text="",
            metadata=metadata,
            needs_ocr=True,
        )
    metadata.update(ocr_result.metadata)
    return ExtractionResult(
        path=path,
        text=ocr_result.text,
        metadata=metadata,
        needs_ocr=not bool(ocr_result.text.strip()),
    )
