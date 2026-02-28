# DocumentWho — Plataforma Inteligente de Búsqueda Documental

**Busca, localiza y comprende documentación corporativa en segundos.**

DocumentWho es una plataforma web que permite importar documentos empresariales (PDF, TXT, CSV, DOCX, XLSX), indexarlos automáticamente y buscarlos de forma inteligente combinando búsqueda tradicional por palabras clave con búsqueda semántica por contexto.

---

## Inicio rápido (3 pasos)

```bash
# 1. Instalar dependencias
pip install -r requirements.txt
python -m spacy download es_core_news_md

# 2. Configurar API key de Groq (para funciones de IA)
echo "GROQ_API_KEY=tu_clave_aquí" > .env

# 3. Arrancar el servidor
uvicorn backend.api:app --host 0.0.0.0 --port 8000
```

Abre **http://localhost:8000** en el navegador. Pulsa **"Re-ingestar"** para procesar los documentos de ejemplo incluidos.

---

## Funcionalidades principales

### Búsqueda Híbrida (Léxica + Semántica)
- **BM25** (Whoosh) para coincidencias exactas por palabras clave
- **Embeddings vectoriales** (ChromaDB + MiniLM multilingual) para búsqueda por significado
- **Fusión ponderada** que combina ambos sistemas de forma transparente
- Buscar *"acuerdos de teletrabajo"* encuentra documentos que digan *"política de trabajo remoto"*

### Resultados agrupados por documento
- Los fragmentos relevantes del mismo documento se agrupan en un único card
- Score visual con barras: componente léxica (verde) y semántica (violeta)
- Cada resultado explica **por qué** apareció: campos coincidentes, tipo de match, entidades del grafo

### Filtros dinámicos (Facets)
- Tipo de documento, idioma, persona, organización, fecha
- Los conteos se actualizan en tiempo real según la búsqueda
- Click para filtrar, click de nuevo para quitar

### Vista completa de documento
- Click en cualquier resultado → modal con todos los chunks del documento
- Previsualización del archivo original (PDF inline, tablas CSV/XLSX, texto TXT)
- Resumen automático con IA (LLM)

### Chat con documentos (Agente IA)
- Pregunta en lenguaje natural sobre tu base documental
- El agente decide automáticamente qué herramientas usar:
  - Búsqueda textual en documentos
  - Consultas SQL sobre datos tabulares (CSV/XLSX)
  - Grafo de entidades (personas, organizaciones)
- Muestra las herramientas usadas y las fuentes citadas

### Motor SQL sobre datos tabulares
- Los archivos CSV y XLSX se cargan automáticamente como tablas SQL (DuckDB)
- Consultas en lenguaje natural: *"¿Cuántas incidencias de prioridad alta hay?"*
- O SQL directo para usuarios avanzados

### Grafo de Entidades
- Extracción automática de personas y organizaciones (spaCy NER)
- Visualización interactiva de relaciones (vis-network)
- Detección de comunidades y brokers de información
- Buscador de conexiones: *"¿Qué conecta a Ana García con NovatechSolutions?"*

### Detección de duplicados
- Identifica documentos near-duplicados por similitud de embeddings
- Umbral configurable (por defecto 85%)

---

## Arquitectura

```
Frontend (Alpine.js + Tailwind CSS)
    │
    ├── /api/search       → Búsqueda híbrida BM25 + semántica
    ├── /api/agent/ask    → Agente IA con tool-calling
    ├── /api/sql/ask      → Lenguaje natural → SQL → resultado
    ├── /api/documents    → CRUD de documentos
    ├── /api/graph        → Grafo de entidades (vis-network)
    └── /api/upload       → Subir y procesar nuevos documentos
    │
Backend (FastAPI + Python)
    │
    ├── Whoosh        → Índice BM25 (full-text)
    ├── ChromaDB      → Índice vectorial (cosine similarity)
    ├── DuckDB        → Motor SQL sobre CSV/XLSX
    ├── spaCy         → NER (personas, organizaciones)
    ├── Groq LLM      → Agente IA (llama-3.3-70b)
    └── fastText      → Expansión de sinónimos por corpus
```

---

## Stack tecnológico

| Componente | Tecnología |
|---|---|
| Backend | Python, FastAPI, uvicorn |
| Búsqueda léxica | Whoosh (BM25) |
| Búsqueda semántica | ChromaDB + `paraphrase-multilingual-MiniLM-L12-v2` |
| SQL Engine | DuckDB |
| NER | spaCy `es_core_news_md` |
| LLM | Groq API (`llama-3.3-70b-versatile`) |
| Sinónimos | fastText CC-es-300 |
| Frontend | Alpine.js, Tailwind CSS, vis-network |
| Parsing | pdfminer, python-docx, pytesseract (OCR) |

---

## Formatos soportados

| Formato | Soporte |
|---|---|
| PDF | Extracción de texto + OCR para escaneados |
| TXT | Directo |
| CSV | Búsqueda + motor SQL |
| XLSX / XLS | Búsqueda + motor SQL |
| DOCX | Extracción con python-docx |

---

## Dataset de ejemplo

El repositorio incluye 25 documentos corporativos de ejemplo en `dataset_default/`:
actas de reunión, emails, memos, contratos, facturas, informes financieros, inventarios, fichas técnicas, presupuestos y más.

---

## Equipo

**Fantasmada** — Hackathon 2025
