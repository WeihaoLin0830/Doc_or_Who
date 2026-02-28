"""
backend — DocumentWho search & management platform.

Módulos:
  config      → Rutas y constantes
  models      → Dataclasses (Document, Chunk, SearchResult, EntityNode)
  parsers     → Extracción de texto (TXT, CSV, PDF, DOCX)
  cleaning    → Normalización y detección de idioma
  classifier  → Clasificación por tipo de documento
  chunker     → Fragmentación adaptativa
  enrichment  → NER, keywords, resumen, título
  indexer     → Indexación dual (ChromaDB + Whoosh)
  searcher    → Búsqueda híbrida BM25 + semántica + RRF
  graph       → Grafo de entidades
  ingest      → Orquestador del pipeline
"""
