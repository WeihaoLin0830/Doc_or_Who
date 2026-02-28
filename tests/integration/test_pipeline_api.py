from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.helpers import write_blank_pdf, write_csv, write_docx, write_pdf, write_pptx, write_text, write_xlsx


def build_sample_corpus(dataset_dir: Path) -> None:
    write_text(
        dataset_dir / "aurora_notes.txt",
        "\n".join(
            [
                "ACTA DE REUNION - PROYECTO AURORA",
                "Pedro Suarez reviewed the supplier delay with NovaTech Solutions S.L.",
                "Budget pressure remains high and the Aurora demo depends on the supplier shipment.",
            ]
        ),
    )
    write_text(dataset_dir / "memo.md", "# Supplier Memo\nBudget and supplier controls for February.")
    write_docx(dataset_dir / "minutes.docx", ["Project Minutes", "Ana Belen Rivas approved the budget increase."])
    write_pptx(dataset_dir / "roadmap.pptx", [["Aurora Roadmap", "Supplier risk", "Budget checkpoints"]])
    write_xlsx(
        dataset_dir / "budget.xlsx",
        [
            {"Department": "Engineering", "Budget": 120000, "Month": "January"},
            {"Department": "Engineering", "Budget": 140000, "Month": "February"},
        ],
    )
    write_csv(
        dataset_dir / "tickets.csv",
        [
            {"client": "Aurora", "priority": "high", "summary": "Supplier shipment blocked"},
            {"client": "Mares", "priority": "low", "summary": "Printer issue"},
        ],
    )
    write_pdf(dataset_dir / "proposal.pdf", ["Aurora proposal with budget 50000 EUR and supplier timeline."])
    write_blank_pdf(dataset_dir / "scan.pdf")
    (dataset_dir / "broken.docx").write_text("not-a-zip", encoding="utf-8")
    (dataset_dir / "ignore.bin").write_bytes(b"\x00\x01\x02")


def test_ingest_search_and_api_end_to_end(isolated_environment):
    dataset_dir = isolated_environment["dataset_dir"]
    build_sample_corpus(dataset_dir)

    from backend.api import app
    from backend.db import session_scope
    from backend.ingest import run_ingest
    from backend.models import ChunkRecord, DocumentRecord, EdgeRecord, EntityRecord, PageRankScoreRecord

    stats, _duration = run_ingest(dataset_dir)
    assert stats.processed >= 7
    assert stats.needs_ocr == 1
    assert stats.failed >= 1
    assert stats.unsupported == 1

    with session_scope() as session:
        assert session.scalar(select(func.count(DocumentRecord.doc_id))) >= 9
        assert session.scalar(select(func.count(ChunkRecord.chunk_id))) > 0
        assert session.scalar(select(func.count(EntityRecord.entity_id))) > 0
        assert session.scalar(select(func.count(EdgeRecord.edge_id))) > 0
        assert session.scalar(select(func.count(PageRankScoreRecord.node_id))) > 0
        doc_id = session.scalar(
            select(DocumentRecord.doc_id).where(DocumentRecord.status.in_(["processed", "skipped"])).limit(1)
        )
        entity_id = session.scalar(select(EntityRecord.entity_id).limit(1))
        entity_text = session.scalar(select(EntityRecord.display_text).limit(1))

    client = TestClient(app)

    search_response = client.get("/search", params={"q": "Aurora supplier budget", "top_k": 5})
    assert search_response.status_code == 200
    search_payload = search_response.json()
    assert search_payload["results"]
    first_result = search_payload["results"][0]
    assert first_result["retrieval_modes"]
    assert "why_this_result" in first_result
    assert first_result["snippets"]

    filtered_response = client.get("/search", params={"q": "budget", "ext": "xlsx", "top_k": 5})
    assert filtered_response.status_code == 200
    assert all(result["ext"] == ".xlsx" for result in filtered_response.json()["results"])

    facets_response = client.get("/facets")
    assert facets_response.status_code == 200
    facets_payload = facets_response.json()
    assert facets_payload["ext"]
    assert facets_payload["entities_by_type"]

    browse_response = client.get("/search", params={"q": "", "entity": entity_text})
    assert browse_response.status_code == 200
    assert browse_response.json()["results"]

    document_response = client.get(f"/documents/{doc_id}")
    assert document_response.status_code == 200
    assert document_response.json()["chunks"]

    graph_doc_response = client.get(f"/graph/doc/{doc_id}")
    assert graph_doc_response.status_code == 200
    assert graph_doc_response.json()["nodes"]

    graph_entity_response = client.get(f"/graph/entity/{entity_id}")
    assert graph_entity_response.status_code == 200
    assert graph_entity_response.json()["nodes"]

    graph_entity_text_response = client.get(f"/graph/entity/{entity_text}")
    assert graph_entity_text_response.status_code == 200
    assert graph_entity_text_response.json()["nodes"]


def test_upload_makes_new_document_searchable(isolated_environment):
    dataset_dir = isolated_environment["dataset_dir"]
    build_sample_corpus(dataset_dir)

    from backend.api import app
    from backend.ingest import run_ingest

    run_ingest(dataset_dir)
    client = TestClient(app)

    upload_payload = b"Quarterly board memo for Neptune with supplier escalations."
    response = client.post(
        "/upload",
        files={"file": ("neptune.txt", upload_payload, "text/plain")},
    )
    assert response.status_code == 200

    search_response = client.get("/search", params={"q": "Neptune escalations"})
    assert search_response.status_code == 200
    assert any(
        "neptune" in (result["filename"] + " " + (result.get("title") or "")).lower()
        for result in search_response.json()["results"]
    )
