from __future__ import annotations

import pytest

from tests.helpers import write_blank_pdf, write_csv, write_docx, write_pdf, write_pptx, write_text, write_xlsx


def test_parse_supported_files(isolated_environment):
    dataset_dir = isolated_environment["dataset_dir"]

    txt_path = write_text(dataset_dir / "note.txt", "Aurora kickoff with NovaTech Solutions.")
    md_path = write_text(dataset_dir / "readme.md", "# Budget\nBudget review for 2025.")
    pdf_path = write_pdf(dataset_dir / "offer.pdf", ["Offer for Aurora budget and supplier review."])
    docx_path = write_docx(dataset_dir / "minutes.docx", ["Meeting Minutes", "Pedro Suarez attended."])
    pptx_path = write_pptx(dataset_dir / "deck.pptx", [["Aurora Deck", "Supplier review", "Budget outlook"]])
    xlsx_path = write_xlsx(dataset_dir / "budget.xlsx", [{"Department": "Engineering", "Budget": 120000}])
    csv_path = write_csv(dataset_dir / "inventory.csv", [{"Asset": "RX400", "Owner": "Ana"}])

    from backend.parsers import parse_file

    assert "Aurora kickoff" in parse_file(txt_path).text
    assert "Budget review" in parse_file(md_path).text
    assert "supplier review" in parse_file(pdf_path).text.lower()
    assert "Meeting Minutes" in parse_file(docx_path).text
    assert "Aurora Deck" in parse_file(pptx_path).text
    assert "Engineering" in parse_file(xlsx_path).text
    assert "RX400" in parse_file(csv_path).text


def test_blank_pdf_marks_needs_ocr(isolated_environment):
    dataset_dir = isolated_environment["dataset_dir"]
    blank_pdf = write_blank_pdf(dataset_dir / "scan.pdf")

    from backend.parsers import parse_file

    result = parse_file(blank_pdf)
    assert result.needs_ocr is True
    assert result.text == ""


def test_blank_pdf_uses_ocr_when_provider_returns_text(isolated_environment, monkeypatch: pytest.MonkeyPatch):
    dataset_dir = isolated_environment["dataset_dir"]
    blank_pdf = write_blank_pdf(dataset_dir / "scan_ocr.pdf")

    from backend.ocr import OcrResult
    from backend.parsers import parse_file

    class FakeOcrProvider:
        name = "fake-ocr"

        def extract_pdf(self, _path):
            return OcrResult(
                text="Texto detectado por OCR para Aurora.",
                metadata={
                    "ocr_provider": self.name,
                    "ocr_attempted": True,
                    "ocr_applied": True,
                    "ocr_available": True,
                },
            )

    monkeypatch.setattr("backend.extractors.pdf.get_ocr_provider", lambda: FakeOcrProvider())
    monkeypatch.setattr(
        "backend.extractors.pdf.get_ocr_provider_status",
        lambda: {"ocr_enabled": True, "ocr_provider": "fake-ocr", "ocr_available": True, "ocr_error": None},
    )

    result = parse_file(blank_pdf)
    assert result.needs_ocr is False
    assert "OCR" in result.text
    assert result.metadata["ocr_provider"] == "fake-ocr"
    assert result.metadata["ocr_applied"] is True


def test_office_zip_validation_rejects_macro_file(isolated_environment):
    dataset_dir = isolated_environment["dataset_dir"]
    macro_file = dataset_dir / "unsafe.docm"
    macro_file.write_text("noop", encoding="utf-8")

    from backend.extractors.office import validate_office_zip

    with pytest.raises(ValueError):
        validate_office_zip(macro_file)
