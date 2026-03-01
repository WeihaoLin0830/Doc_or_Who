# Doc or Who — Plataforma Inteligente de Búsqueda Documental

**Busca, localiza y comprende documentación corporativa en segundos.**

Doc or Who es una plataforma web que permite importar documentos empresariales (PDF, TXT, CSV, DOCX, XLSX), indexarlos automáticamente y buscarlos de forma inteligente combinando búsqueda tradicional por palabras clave con búsqueda semántica por contexto.

---

## Inicio rápido

```bash
# 1. Backend — instalar dependencias Python
pip install -r requirements.txt
python -m spacy download es_core_news_md

# 2. Configurar API key de Groq (para funciones de IA)
echo "GROQ_API_KEY=tu_clave_aquí" > .env

# 3. Arrancar el backend (FastAPI)
uvicorn backend.api:app --host 0.0.0.0 --port 8000

# 4. Frontend — instalar y arrancar (nueva terminal)
cd frontend
npm install
npm run dev          # → http://localhost:3000
```

Abre **http://localhost:3000** en el navegador. Pulsa **"Re-indexar todo"** para procesar los documentos de ejemplo incluidos.

---

## Funcionalidades principales

### Búsqueda Híbrida (Léxica + Semántica)
- **BM25** (Whoosh) para coincidencias exactas por palabras clave
- **Embeddings vectoriales** (ChromaDB + MiniLM multilingual) para búsqueda por significado
- **Fusión ponderada** (Reciprocal Rank Fusion) que combina ambos sistemas de forma transparente
- **Stopwords en español** filtradas automáticamente (preposiciones, conjunciones, artículos) para evitar resultados irrelevantes
- **Sinónimos corporativos** y expansión de vocabulario para mejorar el recall
- Buscar *"acuerdos de teletrabajo"* encuentra documentos que digan *"política de trabajo remoto"*

### Resultados agrupados por documento
- Los fragmentos relevantes del mismo documento se agrupan en un único card
- Score visual con barras: componente léxica (verde) y semántica (violeta)
- Cada resultado explica **por qué** apareció: campos coincidentes, tipo de match, entidades del grafo

### Filtros dinámicos en cascada (Facets)
- **En modo búsqueda**: Tipo, Idioma, Fecha, Personas y Organizaciones — los conteos se recalculan según los filtros activos
- **En modo navegación** (sin búsqueda activa): idénticos filtros disponibles con conteos en tiempo real
- Los filtros son en cascada: marcar una fecha solo muestra personas/organizaciones presentes en esos documentos
- Click para filtrar, click de nuevo para quitar; botón "Limpiar filtros"

### Vista completa de documento
- Click en cualquier resultado → modal con todos los chunks del documento
- Previsualización inline del archivo original: PDF en iframe, tablas CSV/XLSX, texto TXT, extracción DOCX
- Botón **"Generar resumen"** por demanda (IA)

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
- Click en entidad → detalle, documentos relacionados y entidades conectadas
- Click en documento desde el grafo → abre el visor completo de documento
- Buscador de conexiones: *"¿Qué conecta a Ana García con NovatechSolutions?"*

### Gestión de Documentos (carpetas inteligentes)
- **Clustering automático** en 2 niveles: carpetas temáticas → subcarpetas más específicas
- Etiquetas generadas por IA basadas en contenido (no solo tipo de documento)
- **Resúmenes de carpeta y subcarpeta** generados bajo demanda por LLM
- **Drag & drop** de documentos entre carpetas para reorganización manual
- **Drag & drop** de carpetas para reordenar grupos
- **Crear carpeta nueva** con nombre personalizado
- Vista árbol o vista carpetas
- Detección de **duplicados** por similitud de embeddings

### Subida de documentos
- Drag & drop o selector de archivo
- Procesamiento automático: parsing → chunks → embeddings → grafo
- Soporte para múltiples formatos simultáneos

---

## Arquitectura

```
Frontend (Next.js + TypeScript + Tailwind CSS)     ← http://localhost:3000
    │  (proxy /api/* → backend)
    │
    ├── /api/search          → Búsqueda híbrida BM25 + semántica
    ├── /api/agent/ask       → Agente IA con tool-calling
    ├── /api/sql/ask         → Lenguaje natural → SQL → resultado
    ├── /api/documents       → Lista y detalle de documentos
    ├── /api/documents/clusters → Clustering jerárquico
    ├── /api/graph           → Grafo de entidades (vis-network)
    └── /api/upload          → Subir y procesar nuevos documentos
    │
Backend (FastAPI + Python)                          ← http://localhost:8000
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
| Frontend | Next.js (App Router), React, TypeScript, Tailwind CSS v4, vis-network |
| Parsing | pdfminer, python-docx, pytesseract (OCR) |

---

## Estructura del proyecto

```
├── backend/                 # FastAPI — lógica de negocio
│   ├── api.py               # Endpoints REST
│   ├── config.py            # Constantes y umbrales
│   ├── models.py            # Modelos de datos
│   ├── search/              # Módulo de búsqueda
│   │   ├── searcher.py      # Fusión híbrida BM25 + semántica + stopwords
│   │   ├── indexer.py       # Indexación Whoosh + ChromaDB
│   │   └── text_normalize.py# Normalización de texto
│   ├── graph/               # Módulo de grafo
│   │   └── graph.py         # Entidades, comunidades, brokers
│   ├── ai/                  # Módulo IA
│   │   └── llm.py           # Integración con Groq LLM
│   └── ingestion/           # Pipeline de ingestión
├── frontend/                # Next.js — interfaz de usuario
│   ├── src/app/             # App Router (layout, page)
│   ├── src/components/      # Componentes React (tabs, modales)
│   │   ├── SearchTab.tsx    # Búsqueda + filtros siempre visibles
│   │   ├── DocumentsTab.tsx # Carpetas, clustering, resúmenes
│   │   ├── GraphTab.tsx     # Grafo de entidades interactivo
│   │   ├── AskTab.tsx       # Chat con documentos
│   │   ├── DocumentModal.tsx# Visor de documento (PDF/CSV/DOCX)
│   │   └── Navbar.tsx       # Navegación + ingestión
│   ├── src/lib/             # API client, tipos, utilities
│   └── next.config.ts       # Proxy /api/* → backend
├── dataset_default/         # Documentos de ejemplo
├── uploads/                 # Documentos subidos por el usuario
├── data/                    # Índices generados (gitignored)
├── requirements.txt         # Dependencias Python
└── README.md
```

---

## Formatos soportados

| Formato | Soporte |
|---|---|
| PDF | Extracción de texto + OCR para escaneados |
| TXT | Directo |
| CSV | Búsqueda + motor SQL + vista tabla |
| XLSX / XLS | Búsqueda + motor SQL + vista tabla |
| DOCX | Extracción con python-docx |

---

## Dataset de ejemplo

El repositorio incluye documentos corporativos de ejemplo en `dataset_default/`:
actas de reunión, emails, memos, contratos, inventarios, informes de ventas e incidencias de soporte.

---

## Equipo
Sergi Flores 
Weihao Lin 
Paula Esteve 

HackUDC 2026 - Universidade da Coruña 
