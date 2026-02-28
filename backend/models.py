"""
models.py — Estructuras de datos del proyecto.

Usamos dataclasses simples. Nada de ORMs complejos.
Cada clase tiene un método to_dict() para serializar a JSON fácilmente.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Document:
    """Un documento completo tal como se ingesta."""

    doc_id: str                              # Identificador único (hash del path)
    filename: str                            # Nombre del fichero original
    filepath: str                            # Ruta absoluta
    raw_text: str                            # Texto completo extraído
    doc_type: str = "documento"              # acta_reunion | email | memo | csv | ...
    language: str = "es"                     # Código ISO 639-1
    title: str = ""                          # Título inferido
    summary: str = ""                        # Resumen automático (2-3 frases)
    keywords: list[str] = field(default_factory=list)
    persons: list[str] = field(default_factory=list)       # NER: personas
    organizations: list[str] = field(default_factory=list)  # NER: organizaciones
    dates: list[str] = field(default_factory=list)          # Fechas encontradas
    category: str = ""                       # Departamento / área temática

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Chunk:
    """Un fragmento de un documento, listo para indexar."""

    chunk_id: str                # doc_id + sufijo secuencial
    doc_id: str = ""             # Referencia al documento padre (se rellena en chunk_document)
    text: str = ""               # Contenido del chunk
    chunk_index: int = 0         # Posición dentro del documento
    section: str = ""            # Nombre de sección si aplica
    level: str = "default"       # micro | meso | macro | default

    # Metadatos heredados del documento padre (denormalizados para búsqueda)
    doc_type: str = ""
    title: str = ""
    language: str = "es"
    filename: str = ""
    persons: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def metadata(self) -> dict:
        """Metadatos para ChromaDB / Whoosh (solo tipos simples)."""
        return {
            "doc_id": self.doc_id,
            "doc_type": self.doc_type,
            "title": self.title,
            "language": self.language,
            "filename": self.filename,
            "section": self.section,
            "level": self.level,
            "persons": ", ".join(self.persons),
            "organizations": ", ".join(self.organizations),
            "keywords": ", ".join(self.keywords),
            "dates": ", ".join(self.dates),
        }


@dataclass
class SearchResult:
    """Un resultado de búsqueda fusionado."""

    chunk_id: str
    doc_id: str
    text: str
    score: float = 0.0
    title: str = ""
    doc_type: str = ""
    filename: str = ""
    section: str = ""
    language: str = ""
    persons: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    highlight: str = ""          # Snippet con los términos resaltados

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EntityNode:
    """Un nodo del grafo de entidades."""

    name: str
    entity_type: str             # person | organization | product | project
    doc_ids: list[str] = field(default_factory=list)
    mentions: int = 0

    def to_dict(self) -> dict:
        return asdict(self)
