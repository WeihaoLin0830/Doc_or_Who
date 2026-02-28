"""
agent.py — Agente orquestador con tool-calling (Groq).

Un solo loop ReAct que decide qué herramientas usar para responder
cualquier pregunta sobre documentos, datos tabulares o el grafo de entidades.

Flujo:
  1. Recibe la pregunta del usuario (+ historial si hay sesión)
  2. Llama al LLM (70b) con las tools definidas
  3. Si el LLM pide una tool → la ejecuta → añade resultado como mensaje
  4. Repite hasta que el LLM genere respuesta final (sin tool_calls)
  5. Devuelve respuesta + pasos + fuentes
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from backend.config import GROQ_API_KEY, AGENT_MODEL
from backend.ai.agent_tools import TOOLS, execute_tool


# ─── Configuración ───────────────────────────────────────────────
MAX_ITERATIONS = 6        # Máximo de vueltas tool→observation antes de forzar respuesta
SESSION_MAX_TURNS = 10    # Turnos de usuario guardados en historial

SYSTEM_PROMPT = """\
Eres un asistente experto en documentación corporativa.
Tienes acceso a herramientas para buscar en documentos, consultar datos \
numéricos y explorar relaciones entre personas y organizaciones.

ESTRATEGIA — elige la herramienta según el tipo de pregunta:

• CONTENIDO DE DOCUMENTOS (acuerdos, decisiones, temas, resúmenes, \
qué dice un email/acta/memo):
  → search_documents. Escribe queries variadas y descriptivas.
  → Usa doc_type para filtrar cuando puedas inferir el tipo:
    - Acuerdos/decisiones de reunión → doc_type="acta_reunion"
    - Correos/comunicaciones → doc_type="email"
    - Normativas internas → doc_type="memo"
    - Fichas de proveedores → doc_type="listado"
  → Si una búsqueda devuelve resultados IRRELEVANTES, reformula la query \
con otros términos O usa un doc_type diferente. No respondas con info \
no relacionada a la pregunta del usuario.

• DATOS NUMÉRICOS / TABLAS (ventas, inventarios, incidencias, totales, \
conteos, comparativas):
  → list_available_tables → peek_table (para ver columnas y datos de ejemplo) \
→ query_data.

• RELACIONES ENTRE PERSONAS / ORGANIZACIONES (quién se relaciona con quién, \
qué hace una persona, en qué proyectos participa):
  → get_entity_info o find_connection.
  → SOLO cuando se pregunte EXPLÍCITAMENTE sobre una persona u organización.
  → NUNCA uses get_entity_info / find_connection para preguntas sobre \
contenido de documentos.

• PREGUNTAS MIXTAS (ej. "ventas + acuerdos reunión"):
  → Combina search_documents (para texto) + query_data (para cifras).
  → NO uses herramientas de grafo salvo que se pregunte por relaciones.

REGLAS:
- Responde SIEMPRE en español.
- Cita los documentos entre corchetes: [nombre_fichero].
- Si los datos son numéricos, incluye las cifras exactas.
- Si no hay información suficiente, dilo en vez de inventar.
- Responde DE FORMA CONCISA: ve al grano con la información pedida.
- Usa formato Markdown.
- Máximo 2 llamadas consecutivas a la misma herramienta con la misma query."""


# ─── Tipos de resultado ─────────────────────────────────────────
@dataclass
class AgentStep:
    """Un paso del loop: herramienta invocada + resultado."""
    tool_name: str
    tool_args: dict
    result_preview: str  # primeros 200 chars del resultado


@dataclass
class AgentResult:
    """Respuesta completa del agente."""
    answer: str
    sources: list[dict] = field(default_factory=list)
    steps: list[AgentStep] = field(default_factory=list)
    model: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "sources": self.sources,
            "steps": [
                {"tool": s.tool_name, "args": s.tool_args, "preview": s.result_preview}
                for s in self.steps
            ],
            "model": self.model,
            "error": self.error,
        }


# ─── Memoria de sesión (en memoria, por session_id) ─────────────
_sessions: dict[str, list[dict]] = {}


def _get_history(session_id: str | None) -> list[dict]:
    """Obtiene el historial de mensajes de una sesión."""
    if not session_id:
        return []
    return _sessions.get(session_id, [])


def _save_turn(session_id: str | None, user_msg: str, assistant_msg: str):
    """Guarda un turno usuario/asistente en el historial."""
    if not session_id:
        return
    if session_id not in _sessions:
        _sessions[session_id] = []
    history = _sessions[session_id]
    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": assistant_msg})
    # Recortar para no saturar el contexto
    max_msgs = SESSION_MAX_TURNS * 2
    if len(history) > max_msgs:
        _sessions[session_id] = history[-max_msgs:]


# ─── Loop principal del agente ───────────────────────────────────

def run_agent(question: str, session_id: str | None = None) -> AgentResult:
    """
    Ejecuta el loop agéntico completo.

    Args:
        question:   Pregunta del usuario en lenguaje natural.
        session_id: ID de sesión para mantener contexto conversacional.

    Returns:
        AgentResult con respuesta, fuentes y pasos intermedios.
    """
    if not GROQ_API_KEY:
        return AgentResult(
            answer="Error: GROQ_API_KEY no configurada en .env",
            model=AGENT_MODEL,
            error="no_api_key",
        )

    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)

    # Construir mensajes: system + historial + pregunta actual
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_get_history(session_id))
    messages.append({"role": "user", "content": question})

    steps: list[AgentStep] = []
    collected_sources: list[dict] = []

    # ── ReAct loop ───────────────────────────────────────────────
    for iteration in range(MAX_ITERATIONS):
        try:
            response = client.chat.completions.create(
                model=AGENT_MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                parallel_tool_calls=False,   # evitar llamadas paralelas malformadas
                temperature=0.15,
                max_tokens=2048,
            )
        except Exception as e:
            # Groq a veces falla con tool_use_failed; reintentar sin tools
            if "tool_use_failed" in str(e) and iteration < MAX_ITERATIONS - 1:
                # Reintentar: el LLM generó una tool call malformada,
                # le pedimos que responda directamente con lo que tiene
                messages.append({
                    "role": "user",
                    "content": (
                        "La herramienta no se pudo ejecutar. "
                        "Responde con la información que tengas hasta ahora, "
                        "o intenta usar una sola herramienta a la vez."
                    ),
                })
                continue
            return AgentResult(
                answer=f"Error al llamar al LLM: {e}",
                steps=steps,
                model=AGENT_MODEL,
                error=str(e),
            )

        choice = response.choices[0]
        msg = choice.message

        # ── Sin tool calls → respuesta final ─────────────────────
        if choice.finish_reason == "stop" or not msg.tool_calls:
            answer = msg.content or "No se pudo generar una respuesta."
            _save_turn(session_id, question, answer)
            return AgentResult(
                answer=answer,
                sources=_dedupe_sources(collected_sources),
                steps=steps,
                model=AGENT_MODEL,
            )

        # ── Hay tool calls → ejecutar cada una ───────────────────
        # Añadir el mensaje del asistente (con tool_calls) al historial
        messages.append(msg.to_dict())

        for tool_call in msg.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = json.loads(tool_call.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                fn_args = {}

            # Ejecutar la herramienta
            observation = execute_tool(fn_name, fn_args)

            # Registrar el paso
            steps.append(AgentStep(
                tool_name=fn_name,
                tool_args=fn_args,
                result_preview=observation[:200],
            ))

            # Extraer fuentes de search_documents
            if fn_name == "search_documents":
                _extract_sources(observation, collected_sources)

            # Añadir resultado como mensaje tool para el LLM
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": observation,
            })

    # Si se agotan las iteraciones, forzar respuesta con lo que hay
    _save_turn(session_id, question, "")
    return AgentResult(
        answer="He agotado el máximo de pasos sin llegar a una conclusión. "
               "Intenta reformular la pregunta.",
        steps=steps,
        sources=_dedupe_sources(collected_sources),
        model=AGENT_MODEL,
        error="max_iterations",
    )


# ─── Helpers ─────────────────────────────────────────────────────

def _extract_sources(observation: str, sources: list[dict]):
    """Extrae filenames de la observación de search_documents."""
    try:
        data = json.loads(observation)
        for chunk in data.get("chunks", []):
            fn = chunk.get("filename", "")
            if fn:
                sources.append({
                    "filename": fn,
                    "title": chunk.get("title", ""),
                    "doc_type": chunk.get("doc_type", ""),
                })
    except (json.JSONDecodeError, AttributeError):
        pass


def _dedupe_sources(sources: list[dict]) -> list[dict]:
    """Elimina fuentes duplicadas por filename."""
    seen: set[str] = set()
    unique: list[dict] = []
    for s in sources:
        fn = s.get("filename", "")
        if fn and fn not in seen:
            seen.add(fn)
            unique.append(s)
    return unique[:8]
