"""
search/ — Capa de indexación y búsqueda híbrida.

  indexer.py  → indexación en ChromaDB (semántico) + Whoosh (BM25)
  searcher.py → búsqueda híbrida BM25 + embeddings con fusión RRF
"""
