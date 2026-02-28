"""
ingestion/ — Pipeline de ingestión de documentos.

Fases:
  parsers.py    → extracción de texto crudo (PDF, DOCX, CSV, XLSX, TXT)
  ocr.py        → OCR para PDFs escaneados (EasyOCR)
  cleaning.py   → normalización y limpieza de texto
  classifier.py → clasificación del tipo de documento
  enrichment.py → enriquecimiento (NER, keywords, resumen, título, emails)
  chunker.py    → fragmentación adaptativa por tipo
  ingest.py     → orquestador del pipeline completo
"""
