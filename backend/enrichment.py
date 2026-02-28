"""
enrichment.py — Enriquecimiento automático de documentos.

Extrae: palabras clave (YAKE), entidades NER (spaCy),
fechas (regex), título inferido, y resumen extractivo simple.
"""

from __future__ import annotations

import re

from backend.config import YAKE_MAX_KEYWORDS, YAKE_LANGUAGE, SPACY_MODEL
from backend.models import Document

# ─── Lazy loading de modelos pesados ─────────────────────────────
_nlp = None
_kw_extractor = None


def _get_nlp():
    """Carga el modelo spaCy solo cuando se necesita (lazy)."""
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load(SPACY_MODEL)
        except OSError:
            print(f"⚠️  Modelo spaCy '{SPACY_MODEL}' no encontrado.")
            print(f"   Instálalo con: python -m spacy download {SPACY_MODEL}")
            _nlp = False  # Marcar como no disponible
    return _nlp if _nlp is not False else None


def _get_kw_extractor():
    """Carga YAKE solo cuando se necesita (lazy)."""
    global _kw_extractor
    if _kw_extractor is None:
        try:
            import yake
            _kw_extractor = yake.KeywordExtractor(
                lan=YAKE_LANGUAGE,
                n=2,              # Hasta bigramas
                top=YAKE_MAX_KEYWORDS,
                dedupLim=0.7,
            )
        except ImportError:
            print("⚠️  YAKE no instalado. Keywords no disponibles.")
            _kw_extractor = False
    return _kw_extractor if _kw_extractor is not False else None


# ─── Pipeline de enriquecimiento ─────────────────────────────────
def enrich_document(doc: Document) -> Document:
    """
    Enriquece un Document con metadatos extraídos automáticamente.
    Modifica el objeto in-place y lo devuelve.
    """
    text = doc.raw_text

    # 1. Título inferido
    doc.title = _extract_title(text, doc.filename)

    # 2. Fechas
    doc.dates = _extract_dates(text)

    # 3. Emails
    doc.emails = _extract_emails(text)

    # 4. Palabras clave (YAKE)
    doc.keywords = _extract_keywords(text)

    # 5. Entidades NER (spaCy): personas y organizaciones
    persons, orgs = _extract_entities(text)
    doc.persons = persons
    doc.organizations = orgs

    # 6. Resumen extractivo simple (primeras frases relevantes)
    doc.summary = _extract_summary(text)

    # 7. Categoría / departamento
    doc.category = _infer_category(doc)

    return doc


# ─── Funciones auxiliares ─────────────────────────────────────────

def _extract_title(text: str, filename: str) -> str:
    """Intenta extraer un título del contenido o usa el nombre del fichero."""
    # Patrones a ignorar: números de página, headers genéricos de PDF, fechas solas,
    # separadores visuales tipo "--- Página 1 ---" o "=== ... ==="
    _IGNORE_PATTERNS = re.compile(
        r'^[-=*_\s]*(p[aá]ginas?\s*\d+(\s*(?:de|of)\s*\d+)?[-=*_\s]*'
        r'|page\s*\d+(\s*of\s*\d+)?'
        r'|\d+\s*/\s*\d+'
        r'|\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}'
        r'|confidencial|privado|internal)\s*[-=*_]*\s*$',
        re.IGNORECASE
    )
    # También ignorar líneas que son puramente separadores: "---", "===", "***"
    _SEPARATOR = re.compile(r'^[-=*_\s]{3,}$')

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Saltar líneas de número de página o ruido de PDF
        if _IGNORE_PATTERNS.match(line):
            continue
        # Saltar separadores visuales (---, ===, ***)
        if _SEPARATOR.match(line):
            continue
        # Saltar líneas que son puramente números o muy cortas (<= 3 chars)
        if len(line) <= 3 or line.isdigit():
            continue
        # Líneas que son títulos típicos
        if len(line) < 120 and (line.isupper() or line.startswith("#") or
                                 re.match(r"^(ACTA|MEMO|CONTRATO|FACTURA|LISTADO|INFORME|De:)", line, re.IGNORECASE)):
            return line.lstrip("#").strip()
        # Si la primera línea informativa es corta, úsala como título
        if len(line) < 120:
            return line
        break

    # Fallback: nombre del fichero humanizado
    name = filename.rsplit(".", 1)[0]
    return name.replace("_", " ").replace("-", " ").title()


def _extract_dates(text: str) -> list[str]:
    """Extrae fechas del texto con varios formatos comunes."""
    patterns = [
        r"\d{1,2}/\d{1,2}/\d{4}",           # DD/MM/YYYY
        r"\d{4}-\d{2}-\d{2}",                # YYYY-MM-DD
        r"\d{1,2}\s+de\s+\w+\s+de\s+\d{4}",  # "10 de enero de 2025"
    ]
    dates = set()
    for pattern in patterns:
        for match in re.findall(pattern, text, re.IGNORECASE):
            dates.add(match)
    return sorted(dates)


def _extract_emails(text: str) -> list[str]:
    """Extrae direcciones de email del texto."""
    pattern = r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
    return sorted(set(re.findall(pattern, text)))


def _extract_keywords(text: str) -> list[str]:
    """Extrae palabras clave con YAKE."""
    extractor = _get_kw_extractor()
    if extractor is None:
        return []

    # YAKE funciona mejor con texto limitado
    sample = text[:5000]
    try:
        kws = extractor.extract_keywords(sample)
        return [kw for kw, _score in kws]
    except Exception:
        return []


def _extract_entities(text: str) -> tuple[list[str], list[str]]:
    """
    Extrae personas y organizaciones con spaCy NER.
    Devuelve (lista_personas, lista_organizaciones).
    """
    nlp = _get_nlp()
    if nlp is None:
        return _extract_entities_fallback(text)

    # Limitar texto para rendimiento
    doc = nlp(text[:10000])

    persons = set()
    orgs = set()

    for ent in doc.ents:
        name = ent.text.strip()
        if len(name) < 3 or len(name) > 60:
            continue
        # Filtrar ruido común de spaCy
        if name.lower() in _NER_STOPWORDS:
            continue
        if re.match(r'^[A-Z]{2,3}-\d', name):  # Códigos como TK-2024
            continue
        # Filtrar entidades con caracteres de separador o puramente numéricas
        if re.search(r'[-=*_]{2,}|^\d+$', name):
            continue
        # Filtrar nombres que parecen fragmentos de frases (contienen verbos comunes)
        if re.search(r'\b(de|del|la|el|los|las|en|con|por|para|que|se)\b', name.lower()):
            if len(name.split()) > 3:  # OK si es "Ministerio de Economía"
                continue
        if ent.label_ == "PER":
            persons.add(name)
        elif ent.label_ == "ORG":
            orgs.add(name)

    return sorted(persons), sorted(orgs)


_NER_STOPWORDS = {
    # Términos técnicos y de metodología
    "eta", "iva", "memorándum", "atentamente", "disponer", "mantener",
    "elegibilidad", "producto", "sprint", "backend", "frontend",
    "scrum", "demo", "api", "formacion", "formación",
    # Días y meses (spaCy los extrae como PER a veces)
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo",
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    # Roles y cargos que no son nombres propios
    "director", "directora", "gerente", "responsable", "coordinador",
    "jefe", "jefa", "técnico", "técnica", "ingeniero", "ingeniera",
    "analista", "consultor", "consultora", "desarrollador", "desarrolladora",
    # Palabras de documentos legales/notariales que spaCy confunde
    "número", "escritura", "constitución", "notario", "registrador",
    "santiago", "galicia", "artículo", "cláusula", "párrafo",
    "sociedad", "responsabilidad", "limitada", "anónima",
    # Otros falsos positivos frecuentes
    "teletrabajo", "reunión", "acta", "orden", "del", "que", "los",
    "incidencia", "resolución", "fichero", "sistema", "equipo",
}


def _extract_entities_fallback(text: str) -> tuple[list[str], list[str]]:
    """
    Extracción de entidades sin spaCy (regex patterns comunes).
    Busca patrones como "Nombre Apellido" y empresas por sufijos.
    """
    # Personas: patrón "Nombre Apellido" con mayúscula
    person_pattern = r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)?)\b"
    persons = set(re.findall(person_pattern, text))

    # Organizaciones: empresas con sufijos típicos
    org_pattern = r"\b([A-ZÁÉÍÓÚÑ][\w\s&]+(?:S\.L\.|S\.A\.|S\.L\.U\.|Inc\.|Ltd\.|GmbH|B\.V\.))"
    orgs = set(re.findall(org_pattern, text))

    # Filtrar falsos positivos comunes
    stopwords = {"Sprint Review", "Tech Lead", "Product Owner", "Scrum Master",
                 "Backend Developer", "Frontend Developer", "Sala Servidores"}
    persons = {p for p in persons if p not in stopwords and len(p) > 4}

    return sorted(persons)[:20], sorted(orgs)[:15]


def _extract_summary(text: str, num_sentences: int = 3) -> str:
    """
    Resumen extractivo simple: las N frases más informativas.
    Usa heurísticas (longitud, posición, palabras clave) sin LLM.
    """
    # Dividir en frases
    sentences = re.split(r"[.!?]\s+", text[:3000])
    sentences = [s.strip() for s in sentences if len(s.strip()) > 30]

    if not sentences:
        return text[:300] + "..."

    # Puntuación: preferir frases largas pero no excesivas, en posición temprana
    scored = []
    for i, sent in enumerate(sentences):
        words = len(sent.split())
        # Longitud ideal: 10-40 palabras
        length_score = min(words, 40) / 40
        # Posición temprana = mejor
        position_score = 1.0 / (1 + i * 0.3)
        # Penalizar frases muy cortas
        if words < 8:
            length_score *= 0.3
        scored.append((length_score + position_score, sent))

    scored.sort(reverse=True)
    top = [s for _, s in scored[:num_sentences]]

    return ". ".join(top) + "."


def _infer_category(doc: Document) -> str:
    """Infiere la categoría/departamento del documento."""
    type_to_category = {
        "acta_reunion": "Gestión de Proyectos",
        "email": "Comunicaciones",
        "memo": "RRHH / Dirección",
        "tickets": "Soporte Técnico",
        "inventario": "IT",
        "ventas": "Comercial",
        "listado": "Compras",
        "contrato": "Legal",
        "factura": "Finanzas",
    }
    return type_to_category.get(doc.doc_type, "General")
