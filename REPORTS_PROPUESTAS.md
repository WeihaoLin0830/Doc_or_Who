# DocumentWho — Plan Técnico Definitivo

> Plataforma Inteligente de Búsqueda y Gestión Documental  
> Hackathon Fantasmada — Febrero 2026  
> NovaTech Solutions S.L. — corpus de referencia

---

## 0. ANÁLISIS DEL DATASET ACTUAL

| Archivo | Tipo real | Formato | Entidades relevantes |
|---|---|---|---|
| `acta_reunion_aurora_20250110.txt` | Acta de reunión | TXT semi-estructurado | Personas, Proyecto Aurora, fechas, tabla de acciones |
| `email_seguimiento_aurora.txt` | Hilo de correos | TXT con headers email | Personas, pedido PO-2024-0156, ShenTech, ESP32 |
| `incidencias_soporte_Q4_2024.csv` | Tickets soporte Q4 | CSV (coma, 152 filas) | Clientes, técnicos, categorías, prioridades, estados |
| `inventario_equipos_IT.csv` | Inventario hardware | CSV (coma, 122 filas) | Equipos, empleados, departamentos, estados |
| `memo_teletrabajo_2024.txt` | Memorándum interno | TXT con secciones | Política RRHH, fechas efectivas, criterios |
| `proveedores_activos.txt` | Directorio proveedores | TXT estructurado | 30 proveedores, CIFs, categorías, ratings |
| `ventas_enero_2025.csv` | Ventas mensuales | CSV (punto y coma, ~88 filas) | Clientes, productos, vendedores, regiones, importes |

**Relaciones cruzadas identificadas** (esto es el oro del dataset):
- Las mismas personas aparecen en acta, email, inventario y tickets (Pedro Suárez, Ana Belén, Iván Reyes…)
- Los mismos clientes aparecen en ventas, tickets e incidencias (Grupo Industrial Mares, OceanHarvest…)
- Los mismos productos aparecen en ventas y tickets (Sensor RX-400, Gateway GW-100, ESP32…)
- ShenTech (proveedor) → pedido PO-2024-0156 (email) → componentes ESP32 (ventas/tickets)

---

## 1. ARQUITECTURA LIMPIA Y DIRECTA

Sin agentes complejos ni sobre-ingeniería. El sistema tiene tres capas bien separadas:

```
┌──────────────────────────────────────────────────────────────────┐
│  CAPA 1 — INGESTA Y PROCESAMIENTO                               │
│                                                                  │
│  Fichero entrante (PDF, TXT, CSV, DOCX, imagen, email…)         │
│       │                                                          │
│       ▼                                                          │
│  [PARSER]  pdfminer.six / PyMuPDF / python-docx / csv reader   │
│       │                                                          │
│       ▼                                                          │
│  [OCR FALLBACK]  ¿Es PDF escaneado / imagen sin texto?          │
│       │          Sí → EasyOCR / Tesseract 5                     │
│       │          No → texto ya extraído, continúa               │
│       │                                                          │
│       ▼                                                          │
│  [LIMPIEZA]  quitar ruido, normalizar espacios, unicode         │
│  [IDIOMA]    langdetect → detectar ES/CA/EN/PT                  │
│       │                                                          │
│       ▼                                                          │
│  [CLASIFICACIÓN] → tipo de documento (acta/email/memo/CSV…)     │
│  [CHUNKING]      → estrategia específica por tipo               │
│       │                                                          │
│       ▼                                                          │
│  [ENRIQUECIMIENTO por chunk/documento]                           │
│    • Palabras clave (YAKE / KeyBERT)                            │
│    • Resumen automático (mT5 / LLM API)                         │
│    • Entidades NER (spaCy es_core_news_lg)                      │
│    • Metadatos: fechas, personas, org., categorías              │
│                                                                  │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  CAPA 2 — ÍNDICES DE BÚSQUEDA                                   │
│                                                                  │
│  ┌─────────────────────┐     ┌──────────────────────────────┐   │
│  │  ÍNDICE LÉXICO      │     │  ÍNDICE VECTORIAL            │   │
│  │  BM25 / full-text   │     │  Embeddings semánticos       │   │
│  │                     │     │                              │   │
│  │  Whoosh (Python,    │     │  ChromaDB                    │   │
│  │  sin servidor)      │     │  paraphrase-multilingual-    │   │
│  │  ó Meilisearch      │     │  MiniLM-L12-v2               │   │
│  │  (Docker, REST API) │     │  ó multilingual-e5-large     │   │
│  │                     │     │                              │   │
│  │  Búsquedas exactas: │     │  Búsquedas por significado,  │   │
│  │  IDs, CIFs, nombres │     │  paráfrasis, preguntas en    │   │
│  │  propios, fechas    │     │  lenguaje natural            │   │
│  └──────────┬──────────┘     └──────────────┬───────────────┘   │
│             │                               │                    │
│             └───────────────┬───────────────┘                    │
│                             ▼                                    │
│             FUSIÓN DE RESULTADOS (RRF)                          │
│             Reciprocal Rank Fusion:                              │
│             score = Σ 1/(k + rank_i) para cada índice           │
│             → lista única ordenada por relevancia combinada     │
│                                                                  │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  CAPA 3 — WEB APP (FastAPI backend + Next.js frontend)          │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. PIPELINE DE INGESTA DETALLADO

### 2.1. Parsing por formato de entrada

| Parser | Librería | Cuándo |
|---|---|---|
| **PDF digital** (tiene capa de texto) | `PyMuPDF` (fitz) | Extracción limpia, tablas, metadatos PDF |
| **PDF escaneado** (sin texto, solo imágenes) | `EasyOCR` + `pdf2image` | PDF que es foto: contratos firmados, albaranes, facturas escaneadas |
| **DOCX/DOC** | `python-docx` | Documentos Word |
| **CSV/Excel** | `pandas` + detección de separador automática | Datos tabulares (coma, punto y coma, tabulador) |
| **Email (.eml)** | `email` (stdlib Python) | Cabeceras + cuerpo del mensaje |
| **Imagen pura** | `EasyOCR` | PNG, JPG, TIFF escaneados |
| **TXT** | lectura directa con fallback de encoding | Texto plano ya limpio |

**¿Por qué PyMuPDF sobre pdfminer?**  
PyMuPDF es ~5× más rápido, extrae tablas y metadatos PDF (autor, fecha, título) y tiene fallback de renderizado página a imagen. pdfminer.six es más preciso en documentos legales con layouts muy complejos pero más lento. Para este proyecto: **PyMuPDF primario, pdfminer.six como fallback en PDFs problemáticos**.

**¿Por qué EasyOCR sobre Tesseract?**  
EasyOCR soporta español/catalán nativamente con modelos deep learning, sin instalar datos de idioma manualmente, funciona sin GPU. Tesseract 5 es más rápido pero peor con documentos con ruido/rotación. **EasyOCR recomendado. Tesseract como fallback en entornos sin dependencias pesadas.**

### 2.2. Limpieza del texto extraído

```python
import ftfy, re

def clean_text(raw: str) -> str:
    # 1. Fix encoding (FinPay → FinPay, caracteres rotos del OCR)
    text = ftfy.fix_text(raw)

    # 2. Normalizar whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)      # máx 2 saltos de línea
    text = re.sub(r"[ \t]{2,}", " ", text)      # múltiples espacios → 1
    text = re.sub(r"[ \t]+\n", "\n", text)      # trailing spaces

    # 3. Quitar ruido de PDF: "Página 1 de 5", números de página solos
    text = re.sub(r"Página \d+ de \d+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)

    return text.strip()
```

**Detección de idioma** con `langdetect`:
```python
from langdetect import detect
lang = detect(text[:500])  # "es" / "ca" / "en" / "pt"
# → para elegir el modelo NER correcto
```

### 2.3. Clasificador de tipo de documento (por reglas, sin LLM)

```python
def classify_document(text: str, filename: str) -> str:
    if filename.endswith(".csv"):
        cols = pd.read_csv(filename, nrows=0).columns.tolist()
        if "id_ticket" in cols:                       return "tickets"
        if "id_equipo" in cols:                       return "inventario"
        if "vendedor" in cols and "cliente" in cols:  return "ventas"
        return "tabla"

    t = text.lower()
    if re.search(r"acta de reuni|sprint review|asistentes:", t): return "acta_reunion"
    if re.search(r"^de:.*\npara:", t, re.MULTILINE):             return "email"
    if re.search(r"memorándum|circular interna|memorando", t):   return "memo"
    if re.search(r"contrato|cláusula|firmado|otorgante", t):     return "contrato"
    if re.search(r"factura|base imponible|iva|importe total", t): return "factura"
    if re.search(r"proveedor|cif:|rating:", t):                  return "listado"
    return "documento"
```

### 2.4. Chunking adaptativo por tipo

#### ACTAS DE REUNIÓN → Section-based con header como contexto
```
Cada sección del acta = 1 chunk (200–400 tokens)
Header del acta (proyecto, fecha, asistentes) incluido como prefijo de contexto en cada chunk

✓ "¿Qué acciones quedaron pendientes en Aurora?" → chunk "Acciones Pendientes"
✓ "¿Qué problemas hay con FinPay?" → chunk "Problemas Identificados"
```

#### EMAILS (hilos) → Message-level + thread summary
```
1 chunk por mensaje individual (con headers De/Para/Fecha conservados)
1 chunk extra: resumen del hilo completo (generado por LLM)

✓ "¿Cuándo llegan los ESP32?" → mensaje de Raúl con la nueva ETA
✓ "¿Qué pasó con el pedido?" → thread summary con la historia completa
```

#### FICHEROS CSV → Triple nivel
```
NIVEL 1 (micro) — Fila convertida a texto natural:
  "Ticket TK-2024-0401, abierto 01/10/2024, cliente Grupo Industrial Mares,
   prioridad media, categoría software. Descripción: Panel IoT no carga datos
   en tiempo real. Técnico: Iván Reyes. Estado: resuelto."

NIVEL 2 (meso) — Agrupación por entidad:
  "Incidencias de Grupo Industrial Mares Q4 2024 (8 tickets):
   TK-0401 panel IoT media resuelto, TK-0411 teclado baja resuelto,
   TK-0441 firewall alta escalado..."

NIVEL 3 (macro) — Resumen estadístico del fichero:
  "152 tickets Q4 2024. 72% resueltos, 12 escalados. Cliente con más
   incidencias: Grupo Industrial Mares. Categoría dominante: software (42%)."

✓ Los 3 niveles cubren queries exactas, analíticas agregadas y de resumen global
```

#### MEMOS / COMUNICADOS → Full document si < 800 tokens, secciones si es largo
```
Fragmentar un memo corto destruye el contexto.
"¿Cuándo entra en vigor el teletrabajo?" necesita ver el memo completo.
```

#### LISTADOS (Proveedores) → Entity-block (1 chunk por entidad) + chunk por categoría
```
Chunk por proveedor:
  "ShenTech Electronics Co. Ltd | Electrónica | Rating: A (preferente) |
   Contacto: sales@shentech-elec.cn | CIF: CN-4403210987"

Chunk por categoría:
  "Proveedores Electrónica (4): ShenTech (A), ElectroSelect (A),
   ComponentWorld (B), TechParts Ibérica (B)"
```

### 2.5. Enriquecimiento automático

Para cada documento procesado se calculan automáticamente:

| Campo | Cómo | Librería |
|---|---|---|
| `titulo` | Primer H1 ó nombre de fichero limpio | regex |
| `resumen` | 2–3 frases del contenido | LLM API (GPT-4o-mini) ó `transformers` (mT5) |
| `keywords` | Top 8 términos relevantes | `yake` (rápido, local, sin GPU) |
| `tipo_doc` | Clasificador por reglas | ver 2.3 |
| `idioma` | Primeros 500 chars | `langdetect` |
| `fechas` | Regex sobre patrones DD/MM/YYYY, YYYY-MM-DD | `dateparser` |
| `personas` | Reconocimiento de entidades | `spacy` + modelo `es_core_news_lg` |
| `organizaciones` | Idem | `spacy` |
| `categorias` | Departamento inferido (RRHH, IT, Ventas…) | reglas sobre tipo_doc + keywords |

---

## 3. STACK DE BÚSQUEDA

### 3.1. Búsqueda léxica (BM25)

**Whoosh** — pure Python, sin servidor, perfecto para el hackathon:
```python
from whoosh import index, fields
from whoosh.qparser import MultifieldParser

schema = fields.Schema(
    doc_id    = fields.ID(stored=True, unique=True),
    titulo    = fields.TEXT(stored=True),
    contenido = fields.TEXT(stored=False),
    keywords  = fields.KEYWORD(stored=True, commas=True),
    tipo      = fields.TEXT(stored=True),
    fecha     = fields.DATETIME(stored=True),
    personas  = fields.TEXT(stored=True),
)
```

**Meilisearch** (alternativa, mejor UX): servidor Docker en un comando, REST API, typo-tolerant, facets nativos, < 20ms.
```bash
docker run -d -p 7700:7700 getmeili/meilisearch
```

**Para búsqueda instantánea en el frontend** (sin latencia de red): `Fuse.js` o `Lunr.js` — índice JSON cargado en el navegador, búsqueda en < 5ms. Ideal para corpus < 5000 docs.

### 3.2. Búsqueda semántica (embeddings + ChromaDB)

**Modelo recomendado**: `paraphrase-multilingual-MiniLM-L12-v2`
- Español nativo + 50 idiomas
- 128MB, rápido en CPU, sin GPU requerida
- 384 dimensiones, calidad suficiente para el corpus

Si se quiere más calidad: `intfloat/multilingual-e5-large` (560MB, mejor calidad, más lento).

```python
from sentence_transformers import SentenceTransformer
import chromadb

model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_or_create_collection("documentwho")

# Indexar
embedding = model.encode(chunk_text).tolist()
collection.add(
    documents=[chunk_text],
    embeddings=[embedding],
    metadatas=[{"doc_id": doc_id, "tipo": tipo, "fecha": fecha, "personas": personas}],
    ids=[chunk_id]
)

# Buscar (soporta filtros de metadatos)
results = collection.query(
    query_embeddings=[model.encode(query).tolist()],
    n_results=10,
    where={"tipo": "acta_reunion"}  # filtro opcional
)
```

**¿Qué añade la búsqueda semántica que no da BM25?**

Con BM25 (solo palabras): buscar "retraso entrega" no encuentra "el proveedor no ha cumplido el plazo" ni "el paquete sigue en tránsito".

Con embeddings: buscar "retraso entrega" también encuentra "paquete aún en aduanas", "la API de FinPay lleva 2 semanas sin entregar documentación", "nueva ETA el 15 de febrero". El vector captura el significado, no solo las palabras exactas.

### 3.3. Fusión de resultados (Hybrid Search con RRF)

```python
def hybrid_search(query: str, filters: dict = None) -> list:
    bm25_results   = whoosh_search(query, filters, top_k=20)
    vector_results = chroma_search(query, filters, top_k=20)

    scores = {}
    k = 60  # constante estándar RRF

    for rank, r in enumerate(bm25_results):
        scores[r.id] = scores.get(r.id, 0) + 1 / (k + rank + 1)
    for rank, r in enumerate(vector_results):
        scores[r.id] = scores.get(r.id, 0) + 1 / (k + rank + 1)

    ranked = sorted(scores, key=scores.get, reverse=True)
    return [get_result(id) for id in ranked[:10]]
```

BM25 gana en búsquedas exactas (IDs de ticket, CIFs, nombres propios). Embeddings ganan en búsquedas conceptuales. RRF combina ambos sin pesos manuales.

---

## 4. SOBRE EL "AGENTE" — ACLARACIÓN

Un agente LLM es simplemente una forma de que el modelo de lenguaje decida qué herramienta usar para responder una pregunta. La implementación más simple (y suficiente para el hackathon) es:

```
query del usuario
    │
    ├── ¿Contiene "cuánto", "total", "suma", "promedio", "ventas de"?
    │       └──▶ Query SQL sobre DuckDB (análisis numérico de CSVs)
    │
    └── Cualquier otra búsqueda de información
            └──▶ Hybrid Search (BM25 + semántico)
                     └──▶ Top 5 chunks relevantes
                              └──▶ LLM genera respuesta en lenguaje natural
                                   (opcional pero muy impactante en demo)
```

La parte LLM es opcional. Sin ella ya tienes un buscador muy bueno. Con ella añades la capa conversacional: el usuario pregunta en lenguaje natural y recibe una respuesta en lenguaje natural en vez de solo links a documentos.

---

## 5. WEB APP — ESPECIFICACIÓN UI/UX

### 5.1. Stack tecnológico

| Capa | Opción rápida (hackathon) | Opción pulida |
|---|---|---|
| Backend | FastAPI (Python) | FastAPI |
| Búsqueda rápida en frontend | Fuse.js | Fuse.js + Meilisearch |
| Frontend | **Streamlit** (2h, todo Python) | **Next.js 14** + TailwindCSS |
| Componentes UI | Streamlit nativo | shadcn/ui |
| Gráficos dashboard | `st.bar_chart` / Plotly | Recharts |
| Grafo de entidades | — | vis-network.js |

**Recomendación**: Si el equipo sabe React/Next → ir a Next.js, el resultado es mucho más impresionante visualmente. Si el equipo es todo Python → Streamlit con `streamlit-extras` da un resultado más que digno en la mitad de tiempo.

### 5.2. Diseño de la interfaz

#### PÁGINA PRINCIPAL — Búsqueda

```
╔══════════════════════════════════════════════════════════════════╗
║  🔎  DocumentWho                            [+ Subir documento]  ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║   ┌────────────────────────────────────────────────────────┐    ║
║   │  Busca en todos los documentos...                  ⌕  │    ║
║   └────────────────────────────────────────────────────────┘    ║
║                                                                  ║
║  FILTROS RÁPIDOS (actualizan resultados al instante):            ║
║  [Todos]  [Actas]  [Emails]  [Memos]  [Datos/CSV]  [Contratos]  ║
║                                                                  ║
║  FILTROS AVANZADOS ▾ (colapsable):                               ║
║    Fecha: [ desde ─────────────── hasta ]                        ║
║    Persona: [ nombre...      ▼ ]    Tipo: [ Todos ▼ ]            ║
║    Estado:  [ Todos ▼ ]             Idioma: [ ES ▼ ]             ║
║                                                                  ║
╠══════════════════════════════════════════════════════════════════╣
║  RESULTADOS  (3 resultados · 180ms)                              ║
║                                                                  ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │ 📄  Acta de Reunión — Proyecto Aurora Sprint #14         │   ║
║  │     10 ene 2025 · Acta · Español · Carlos Méndez         │   ║
║  │                                                           │   ║
║  │  "···el servicio de **facturación** tiene una dependencia │   ║
║  │  bloqueante con la **API del proveedor de pagos (FinPay)**│   ║
║  │  que aún no ha entregado la documentación···"             │   ║
║  │                                                           │   ║
║  │  🏷 aurora  finpay  microservicios  sprint  facturación   │   ║
║  │                                    [Ver doc]  [Resumen]   │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                                                                  ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │ 📧  Email: Seguimiento entrega PO-2024-0156              │   ║
║  │     20 ene 2025 · Email · Pedro Suárez → Raúl Domínguez  │   ║
║  │                                                           │   ║
║  │  "···Los **ESP32** tenían que haber llegado la semana     │   ║
║  │  pasada y seguimos sin noticias del **almacén**···"       │   ║
║  │                                                           │   ║
║  │  🏷 shentech  esp32  pedido  aurora  retraso  aduanas     │   ║
║  │                                    [Ver doc]  [Resumen]   │   ║
║  └──────────────────────────────────────────────────────────┘   ║
╚══════════════════════════════════════════════════════════════════╝
```

**Comportamientos clave:**
- Resultados con debounce de 300ms (no hay que pulsar Enter)
- Keywords del documento en negrita (**highlight**)
- El snippet muestra el fragmento más relevante, no necesariamente el inicio del doc
- Los chips de tipo filtran instantáneamente en el frontend (Fuse.js, sin llamada al backend)
- Typo-tolerance: "grup industrial" encuentra "Grupo Industrial Mares"

#### PÁGINA DE DOCUMENTO — Vista detalle

```
╔══════════════════════════════════════════════════════════════════╗
║  ← Volver     Acta de Reunión — Proyecto Aurora Sprint #14      ║
╠══════╦═══════════════════════════════════════════════════════════╣
║      ║  ACTA DE REUNIÓN — PROYECTO AURORA                       ║
║ META ║  Sprint Review #14 · 10 enero 2025                       ║
║      ║  ─────────────────────────────────────────────           ║
║ 📅   ║                                                           ║
║ 10/01║  [texto completo del documento con los términos de        ║
║      ║   búsqueda resaltados en amarillo]                       ║
║ 📁   ║                                                           ║
║ Acta ║                                                           ║
║      ║                                                           ║
║ 🌐   ║                                                           ║
║ ES   ║                                                           ║
║      ╠═══════════════════════════════════════════════════════════╣
║ 👤   ║  DOCUMENTOS RELACIONADOS (comparten entidades)           ║
║ Carlos M.   ║  📧 Email seguimiento Aurora (20/01/2025)          ║
║ Ana Belén   ║  📊 Ventas Enero 2025                              ║
║ Pedro S.    ║  📋 Incidencias Q4 — Grupo Industrial Mares        ║
║ ...   ║                                                          ║
║      ╚═══════════════════════════════════════════════════════════╣
║ 🏷   ║                                                           ║
║ aurora      ║  [Descargar original]  [Copiar texto]              ║
║ sprint      ║                                                    ║
║ finpay      ║                                                    ║
║      ║                                                           ║
║ 📝 RESUMEN  ║                                                    ║
║ Reunión Q14 ║                                                    ║
║ del proyecto║                                                    ║
║ Aurora con  ║                                                    ║
║ retraso en  ║                                                    ║
║ FinPay y    ║                                                    ║
║ staging.    ║                                                    ║
╚══════╩═══════════════════════════════════════════════════════════╝
```

#### DASHBOARD / INICIO (si no hay búsqueda activa)

```
╔══════════════════════════════════════════════════════════════════╗
║  Tu Colección — NovaTech Solutions                               ║
║                                                                  ║
║  30 documentos   ·   42 personas   ·   15 empresas   ·   3 MB   ║
║                                                                  ║
║  DISTRIBUCIÓN POR TIPO          TIMELINE TEMPORAL               ║
║  ┌──────────────────────┐       ┌─────────────────────────────┐ ║
║  │ ████████ CSV (3)     │       │ ▂▄▆█▅▃▁ oct'24 → ene'25     │ ║
║  │ ████████ TXT (4)     │       └─────────────────────────────┘ ║
║  │ ████████ PDF (23)    │                                        ║
║  └──────────────────────┘       PERSONAS MÁS MENCIONADAS        ║
║                                 1. Ana Belén Rivas (6 docs)     ║
║  RECIENTES                      2. Pedro Suárez (5 docs)        ║
║  • Acta Sprint #14 (10/01)      3. Iván Reyes (4 docs)          ║
║  • Email PO-0156 (20/01)        4. Raúl Domínguez (3 docs)      ║
║  • Ventas Enero (31/01)                                          ║
║                                 EMPRESAS CLIENTE MÁS ACTIVAS    ║
║  EXPLORAR POR ETIQUETA:         1. Grupo Industrial Mares        ║
║  [aurora] [sprint] [finpay]     2. OceanHarvest Foods            ║
║  [teletrabajo] [shentech]       3. Autoridad Portuaria Marbravo  ║
║  [incidencia-alta] [+más]                                        ║
╚══════════════════════════════════════════════════════════════════╝
```

### 5.3. Principios UX no negociables

1. **< 200ms de respuesta** en la búsqueda (caché, prefetch, debounce)
2. **El snippet responde la pregunta** sin abrir el documento completo
3. **Filtros no bloquean**: chips de tipo filtran en cliente (JS), sin round-trip al backend
4. **Subida de documentos**: drag & drop, barra de progreso, disponible en < 10s
5. **Typo-tolerance**: "grup industrial" → "Grupo Industrial Mares"
6. **Mobile-friendly**: funcional en tablet (pantallas de presentación)

---

## 6. EXPANSIÓN DEL DATASET

### 6.1. Método recomendado: generación con LLM + conversión a PDF

El método más rápido y coherente: generar documentos con GPT-4o/Claude dentro del universo NovaTech y convertirlos a diferentes formatos, incluyendo PDFs escaneados simulados para probar el OCR.

**Documentos a generar (objetivo: ~25 docs totales):**

| Documento | Descripción | Formato final | Para probar |
|---|---|---|---|
| Acta Sprint #15 | Continuación del #14, ref. a acciones pendientes | PDF digital | Chunking actas, continuidad |
| Contrato marco Grupo Mares | 2 páginas con cláusulas SLA, forma de pago | PDF con logo | OCR en texto limpio |
| Contrato ShenTech (escaneado) | Misma plantilla pero simulando un scan | PDF escaneado ← imagen | **OCR real** |
| Factura NovaTech → Mares | Factura con tabla de productos del CSV ventas | PDF con tablas | Layout + tables |
| Factura recibida de ShenTech | Albarán de entrega, sello de aduana | **Imagen JPG** + PDF | **OCR en imagen** |
| Informe KPI Q4 2024 | Métricas de incidencias y ventas, con gráficas | PDF con imágenes | Multi-sección PDF |
| Ficha técnica Sensor RX-400 | Especificaciones técnicas, diagrama de conexión | PDF | Chunking docs técnicos |
| Presupuesto para PetroNova | Oferta de proyecto IoT industrial, 3 páginas | PDF | Documento largo |
| Email contrato Autoridad Portuaria | Cadena de emails sobre renovación soporte | TXT email | Clasificación email |
| Política seguridad IT 2025 | Memorándum: contraseñas, VPN, incidentes | TXT memo | Chunking memo |
| Acta junta socios Q4 2024 | Aprobación cuentas, proyectos 2025 | PDF | Doc legal |
| Ventas febrero 2025 | CSV igual al de enero pero mes siguiente | CSV | Corpus tabular más rico |
| Incidencias Q1 2025 | CSV igual a Q4 pero trimestre nuevo | CSV | Más datos para análisis |
| Ficha técnica Gateway GW-100 | Especificaciones del producto | PDF | Chunking técnico |
| Manual de usuario Panel IoT | Guía paso a paso con capturas | PDF con imágenes | Multi-imagen + text |

**Script de conversión a PDF:**
```python
from weasyprint import HTML

def text_to_pdf(text: str, title: str, output_path: str):
    html = f"""
    <html><head>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 50px; }}
      h1   {{ color: #003366; border-bottom: 2px solid #003366; }}
      .logo {{ float: right; font-weight: bold; color: #003366; font-size: 20px; }}
    </style>
    </head><body>
    <div class="logo">NovaTech Solutions</div>
    <h1>{title}</h1>
    <pre style="white-space: pre-wrap; font-size: 11px;">{text}</pre>
    </body></html>
    """
    HTML(string=html).write_pdf(output_path)
```

**Para simular PDFs escaneados** (que requieran OCR):
```python
from pdf2image import convert_from_path
from PIL import Image, ImageFilter
import numpy as np

def simulate_scan(pdf_path: str, output_path: str):
    pages = convert_from_path(pdf_path, dpi=150)
    result = []
    for page in pages:
        img = page.rotate(np.random.uniform(-1.5, 1.5), expand=False)
        img = img.filter(ImageFilter.GaussianBlur(radius=0.4))
        img = img.convert("L")  # escala de grises (aspecto de fotocopia)
        result.append(img)
    result[0].save(output_path, save_all=True, append_images=result[1:])
```

### 6.2. Dónde encontrar documentos reales (si quieres autenticidad)

| Fuente | Qué tiene | URL | Cómo usar |
|---|---|---|---|
| **BOE** (Boletín Oficial del Estado) | Contratos públicos, resoluciones, normativa. PDFs reales en español de alta calidad. | `boe.es` / API REST disponible | Descargar contratos de servicios IT de administraciones |
| **Portal de Contratación del Estado** | Pliegos de condiciones, presupuestos, facturas de proveedores públicos | `contrataciondelestado.es` | Documentos de licitaciones con precios reales |
| **Transparencia.gob.es** | Memorias anuales de organismos públicos, informes de actividad | `transparencia.gob.es` | Informes anuales reales, bien estructurados |
| **Datos Abertos Xunta de Galicia** | CSVs de la administración gallega (coherente con NovaTech en Vigo) | `abertos.xunta.gal/catalogo` | CSVs reales en español |
| **datos.gob.es** | Miles de datasets CSV de toda España | `datos.gob.es` | Ampliar corpus tabular |
| **HuggingFace: FUNSD** | 199 formularios escaneados anotados con texto | `datasets.load_dataset("nielsr/funsd")` | Probar OCR con formularios reales |
| **HuggingFace: RVL-CDIP** | 400K imágenes de documentos (16 tipos clasificados) | `datasets.load_dataset("rvl_cdip")` | Validar clasificador de tipo de documento |
| **DocLayNet (IBM)** | 80K+ páginas con bounding boxes para layout analysis | `github.com/DS4SD/DocLayNet` | Si se implementa LayoutLM |

### 6.3. Estructura del corpus expandido

```
dataset_expanded/
├── actas/
│   ├── acta_sprint14_aurora_20250110.txt        ← existente
│   ├── acta_sprint15_aurora_20250124.pdf        ← generar LLM
│   └── acta_junta_socios_2024Q4.pdf             ← generar LLM
├── emails/
│   ├── email_seguimiento_aurora.txt             ← existente
│   └── email_contrato_portuaria.txt             ← generar LLM
├── contratos/
│   ├── contrato_marco_mares_2024.pdf            ← generar LLM → PDF
│   └── contrato_shentech_scan.pdf               ← PDF escaneado simulado
├── facturas/
│   ├── factura_001_mares_20250115.pdf           ← generar LLM → PDF
│   └── albaran_shentech_PO20240156.jpg          ← imagen, probar OCR
├── informes/
│   ├── informe_kpi_Q4_2024.pdf                 ← generar LLM → PDF con tablas
│   └── informe_estado_aurora_20250120.pdf       ← generar LLM
├── fichas_tecnicas/
│   ├── ficha_sensor_rx400.pdf                   ← generar LLM + specs
│   └── ficha_gateway_gw100.pdf                  ← generar LLM + specs
├── memos/
│   ├── memo_teletrabajo_2024.txt                ← existente
│   └── memo_seguridad_IT_2025.txt               ← generar LLM
├── datos/
│   ├── incidencias_soporte_Q4_2024.csv          ← existente
│   ├── inventario_equipos_IT.csv                ← existente
│   ├── ventas_enero_2025.csv                    ← existente
│   ├── ventas_febrero_2025.csv                  ← generar sintético
│   └── incidencias_Q1_2025.csv                  ← generar sintético
└── directorio/
    └── proveedores_activos.txt                  ← existente
```

---

## 7. PLAN DE EJECUCIÓN

### Prioridades absolutas (sin esto no hay demo)

| # | Qué | Tecnología | Tiempo est. |
|---|---|---|---|
| 1 | Parser TXT/CSV/PDF → texto limpio → chunking → ChromaDB + Whoosh | PyMuPDF, pandas, sentence-transformers, ChromaDB, Whoosh | 4h |
| 2 | Endpoint `/search` con hybrid search (BM25 + semántico + RRF) | FastAPI, Python | 2h |
| 3 | Web básica: barra de búsqueda + resultados con snippet + filtros por tipo | Next.js ó Streamlit | 3h |

### Segunda capa (hace ganar el hackathon)

| # | Qué | Tecnología | Tiempo est. |
|---|---|---|---|
| 4 | NER → personas/org como metadatos filtrables | spaCy `es_core_news_lg` | 1h |
| 5 | Keywords automáticos → tags bajo cada resultado | YAKE | 30min |
| 6 | Resumen automático al abrir un documento | LLM API (GPT-4o-mini) | 1h |
| 7 | "Documentos relacionados" por entidades compartidas | grafo de entidades en memoria | 2h |
| 8 | Dashboard: distribución por tipo, timeline, top personas | Recharts / Plotly | 2h |

### Extras (si sobra tiempo)

| # | Qué | Para qué |
|---|---|---|
| 9 | OCR para PDFs escaneados | EasyOCR como fallback en el parser |
| 10 | SQL sobre CSVs vía DuckDB | Preguntas analíticas numéricas |
| 11 | Subida drag & drop con barra de progreso | UX de administración |
| 12 | Grafo visual de entidades interactivo | Wow factor demo |

### Lo que NO merece tiempo

- ❌ CLIP / búsqueda por imagen (escaso valor para documentos de texto empresarial)
- ❌ Graph Chunking tipo Microsoft GraphRAG (overkill con < 50 docs)
- ❌ Fine-tuning de modelos (sin tiempo, sin datos suficientes)
- ❌ pdfminer.six como parser principal (PyMuPDF es superior para este caso)
- ❌ Autenticación robusta / multi-tenancy (es una demo)

---

## 8. STACK FINAL

```
Backend (Python 3.11+)                Frontend
──────────────────────────            ──────────────────────────────
FastAPI                                Next.js 14 (App Router)
SQLite + SQLAlchemy                    TailwindCSS
DuckDB (SQL sobre CSVs)               shadcn/ui
ChromaDB (vector search)              Fuse.js (búsqueda live local)
Whoosh (BM25 full-text)               Recharts (dashboard)
sentence-transformers                 vis-network.js (grafo)
spaCy es_core_news_lg (NER)
YAKE (keyword extraction)
PyMuPDF (PDF parser)
EasyOCR (OCR fallback)
python-docx (DOCX)
langdetect (detección idioma)
ftfy (limpieza unicode)
pandas (CSV)
weasyprint (generar PDFs demo)
```

---

*Plan definitivo para DocumentWho — Hackathon Fantasmada 2026*
