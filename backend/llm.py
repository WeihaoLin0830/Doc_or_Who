"""
llm.py — Generación de respuestas con LLM (Groq).

Implementa RAG (Retrieval-Augmented Generation):
1. Busca chunks relevantes con hybrid_search
2. Construye un prompt con el contexto
3. Llama a Groq API para obtener respuesta en lenguaje natural
"""

from __future__ import annotations

from backend.config import GROQ_API_KEY, GROQ_MODEL

# ─── Lazy loading ────────────────────────────────────────────────
_client = None


def _get_client():
    """Inicializa el cliente Groq solo cuando se necesita."""
    global _client
    if _client is None:
        if not GROQ_API_KEY:
            print("⚠️  GROQ_API_KEY no configurada en .env")
            return None
        try:
            from groq import Groq
            _client = Groq(api_key=GROQ_API_KEY)
        except ImportError:
            print("⚠️  groq no instalado. pip install groq")
            return None
    return _client


# ─── Prompt templates ────────────────────────────────────────────
SYSTEM_PROMPT = """Eres un asistente experto en documentación corporativa.
Tu trabajo es responder preguntas basándote EXCLUSIVAMENTE en los fragmentos
de documentos proporcionados como contexto. No inventes nada.

Reglas:
- Responde en español, de forma concisa y profesional.
- Cita las fuentes: menciona el nombre del documento entre corchetes [nombre].
- Si el contexto no contiene información suficiente, dilo claramente.
- Si la pregunta es sobre datos numéricos, sé preciso con las cifras.
- Usa formato Markdown cuando mejore la legibilidad."""


def _expand_query(query: str) -> str:
    """
    Usa el LLM para expandir la query con sinónimos/términos relacionados.
    Solo para preguntas conceptuales — mejora el recall del retrieval.
    Retorna la query original si falla o si el LLM no está disponible.
    """
    client = _get_client()
    if client is None:
        return query
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{
                "role": "user",
                "content": (
                    f'Término de búsqueda: "{query}"\n'
                    "Genera 3-4 sinónimos o términos relacionados en español "
                    "para mejorar la búsqueda documental corporativa.\n"
                    "Responde SOLO las palabras separadas por espacios, sin explicaciones."
                ),
            }],
            temperature=0.1,
            max_tokens=40,
        )
        extras = response.choices[0].message.content.strip()
        # Combinar original + expansión, deduplicar manteniendo orden
        seen: set[str] = set()
        combined: list[str] = []
        for word in (query + " " + extras).split():
            low = word.lower()
            if low not in seen:
                seen.add(low)
                combined.append(word)
        return " ".join(combined)
    except Exception:
        return query


def _build_context(chunks: list[dict], max_tokens: int = 4000) -> str:
    """Construye el bloque de contexto a partir de chunks de búsqueda."""
    context_parts = []
    approx_tokens = 0

    for i, chunk in enumerate(chunks):
        filename = chunk.get("filename", "")
        title = chunk.get("title", "")
        text = chunk.get("text", "")
        section = chunk.get("section", "")

        header = f"[Fuente: {filename}"
        if section:
            header += f" — {section}"
        header += "]"

        block = f"{header}\n{text}\n"
        block_tokens = len(block.split()) * 1.3  # estimate

        if approx_tokens + block_tokens > max_tokens:
            break

        context_parts.append(block)
        approx_tokens += block_tokens

    return "\n---\n".join(context_parts)


def ask(question: str, doc_type: str | None = None, top_k: int = 8) -> dict:
    """
    RAG completo: búsqueda + generación.

    Args:
        question: Pregunta del usuario en lenguaje natural.
        doc_type: Filtro opcional por tipo de documento.
        top_k: Número de chunks a usar como contexto.

    Returns:
        dict con 'answer', 'sources', 'model'.
    """
    client = _get_client()
    if client is None:
        return {
            "answer": "Error: LLM no disponible (falta GROQ_API_KEY o paquete groq).",
            "sources": [],
            "model": GROQ_MODEL,
        }

    # 1. Expandir query (solo para preguntas conceptuales, no nombres propios)
    from backend.searcher import _is_entity_query
    expanded_question = question
    if not _is_entity_query(question):
        expanded_question = _expand_query(question)

    # 2. Buscar chunks relevantes
    from backend.searcher import hybrid_search
    results = hybrid_search(query=expanded_question, doc_type=doc_type, top_k=top_k)

    if not results:
        return {
            "answer": "No se encontraron documentos relevantes para tu pregunta.",
            "sources": [],
            "model": GROQ_MODEL,
        }

    # 2. Preparar contexto
    chunks_data = [r.to_dict() for r in results]
    context = _build_context(chunks_data)

    # 3. Construir prompt
    user_prompt = f"""Contexto (fragmentos de documentos de la empresa):

{context}

---
Pregunta del usuario: {question}

Responde basándote SOLO en el contexto anterior."""

    # 4. Llamar a Groq
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        answer = response.choices[0].message.content
    except Exception as e:
        return {
            "answer": f"Error al consultar el LLM: {str(e)}",
            "sources": [],
            "model": GROQ_MODEL,
        }

    # 5. Extraer fuentes únicas
    seen_filenames: set[str] = set()
    sources = []
    for r in results:
        if r.filename not in seen_filenames:
            seen_filenames.add(r.filename)
            sources.append({
                "filename": r.filename,
                "title": r.title,
                "doc_type": r.doc_type,
                "doc_id": r.doc_id,
            })

    return {
        "answer": answer,
        "sources": sources[:6],
        "model": GROQ_MODEL,
    }


def summarize_document(doc_id: str) -> dict:
    """
    Genera un resumen de un documento usando el LLM.
    """
    client = _get_client()
    if client is None:
        return {"summary": "LLM no disponible.", "model": GROQ_MODEL}

    # Obtener chunks del documento
    from backend.indexer import _get_chroma_collection
    collection = _get_chroma_collection()

    try:
        results = collection.get(
            where={"doc_id": doc_id},
            include=["documents", "metadatas"],
        )
    except Exception:
        return {"summary": "Documento no encontrado.", "model": GROQ_MODEL}

    if not results["ids"]:
        return {"summary": "Documento no encontrado.", "model": GROQ_MODEL}

    # Concatenar chunks
    full_text = "\n\n".join(results["documents"][:10])  # Limite 10 chunks
    title = results["metadatas"][0].get("title", "") if results["metadatas"] else ""

    prompt = f"""Resume el siguiente documento corporativo de forma profesional y concisa
(máximo 5 frases). Extrae los puntos clave.

Título: {title}

Contenido:
{full_text[:6000]}"""

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "Eres un asistente que resume documentos corporativos de forma concisa y profesional. Responde en español."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=500,
        )
        summary = response.choices[0].message.content
    except Exception as e:
        summary = f"Error al generar resumen: {str(e)}"

    return {"summary": summary, "model": GROQ_MODEL}
