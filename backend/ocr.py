from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

from backend.config import get_settings
from backend.logging import get_logger, log_event

LOGGER = get_logger(__name__)
_provider = None
_provider_loaded = False
_provider_error: str | None = None


@dataclass(slots=True)
class OcrResult:
    text: str
    metadata: dict[str, object]


class OcrProvider:
    name: str

    def extract_pdf(self, path: Path) -> OcrResult:
        raise NotImplementedError


class TesseractOcrProvider(OcrProvider):
    def __init__(self, *, languages: str, dpi: int, max_pages: int, tesseract_cmd: str | None = None) -> None:
        import pytesseract
        from PIL import Image
        from pytesseract import TesseractNotFoundError

        self.name = "tesseract"
        self._image_class = Image
        self._pytesseract = pytesseract
        self._not_found_error = TesseractNotFoundError
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self._language_spec = self._resolve_languages(languages)
        self._dpi = dpi
        self._max_pages = max_pages

    def _resolve_languages(self, languages: str) -> str:
        requested = [language.strip() for language in languages.split("+") if language.strip()]
        if not requested:
            requested = ["eng"]
        available = set(self._pytesseract.get_languages(config=""))
        if not available:
            raise RuntimeError("No Tesseract language data is available")
        selected = [language for language in requested if language in available]
        if selected:
            return "+".join(selected)
        if "eng" in available:
            return "eng"
        return sorted(available)[0]

    def _pixmap_to_image(self, pixmap: fitz.Pixmap):
        mode = "RGB" if pixmap.n < 4 else "RGBA"
        image = self._image_class.frombytes(mode, [pixmap.width, pixmap.height], pixmap.samples)
        if mode == "RGBA":
            image = image.convert("RGB")
        return image.convert("L")

    def extract_pdf(self, path: Path) -> OcrResult:
        pages: list[str] = []
        with fitz.open(str(path)) as document:
            page_count = document.page_count
            processed_pages = min(page_count, self._max_pages)
            matrix = fitz.Matrix(self._dpi / 72.0, self._dpi / 72.0)
            for page_index in range(processed_pages):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                image = self._pixmap_to_image(pixmap)
                text = self._pytesseract.image_to_string(image, lang=self._language_spec, config="--psm 6")
                if text.strip():
                    pages.append(text.strip())
        return OcrResult(
            text="\n\n".join(pages),
            metadata={
                "ocr_provider": self.name,
                "ocr_languages": self._language_spec,
                "ocr_dpi": self._dpi,
                "ocr_pages_processed": processed_pages,
                "ocr_page_count": page_count,
                "ocr_truncated": page_count > self._max_pages,
                "ocr_applied": True,
                "ocr_attempted": True,
                "ocr_available": True,
            },
        )


def get_ocr_provider() -> OcrProvider | None:
    global _provider, _provider_loaded, _provider_error
    if _provider_loaded:
        return _provider
    _provider_loaded = True
    settings = get_settings()
    if not settings.enable_ocr:
        _provider_error = "OCR disabled by configuration"
        return None
    if settings.ocr_provider != "tesseract":
        _provider_error = f"Unsupported OCR provider: {settings.ocr_provider}"
        return None
    try:
        _provider = TesseractOcrProvider(
            languages=settings.ocr_languages,
            dpi=settings.ocr_dpi,
            max_pages=settings.ocr_max_pages,
            tesseract_cmd=settings.tesseract_cmd,
        )
    except Exception as exc:
        _provider = None
        _provider_error = str(exc)
        log_event(LOGGER, "ocr_provider_unavailable", "OCR provider unavailable", provider=settings.ocr_provider, error=str(exc))
    return _provider


def get_ocr_provider_status() -> dict[str, object]:
    settings = get_settings()
    provider = get_ocr_provider()
    return {
        "ocr_enabled": settings.enable_ocr,
        "ocr_provider": provider.name if provider is not None else settings.ocr_provider,
        "ocr_available": provider is not None,
        "ocr_error": _provider_error,
    }


def reset_ocr_provider_cache() -> None:
    global _provider, _provider_loaded, _provider_error
    _provider = None
    _provider_loaded = False
    _provider_error = None
