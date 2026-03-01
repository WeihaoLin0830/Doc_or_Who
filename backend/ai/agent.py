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
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from backend.config import GROQ_API_KEY, AGENT_MODEL, GROQ_MODEL
from backend.ai.agent_tools import TOOLS, execute_tool


# ─── Logger del agente ───────────────────────────────────────────
def _setup_agent_logger() -> logging.Logger:
    log_dir = Path(__file__).resolve().parents[2] / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "agent.log"

    logger = logging.getLogger("documentwho.agent")
    if logger.handlers:           # evitar duplicar handlers al recargar en --reload
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Fichero (DEBUG+)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    # Consola (WARNING+)
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger

log = _setup_agent_logger()


# ─── Configuración ───────────────────────────────────────────────
MAX_ITERATIONS = 6        # Máximo de vueltas tool→observation antes de forzar respuesta
SESSION_MAX_TURNS = 10    # Turnos de usuario guardados en historial

# Nombres de herramientas disponibles (para detectar tool calls simuladas)
_TOOL_NAMES = {"search_documents", "query_data", "get_entity_info",
               "find_connection", "list_available_tables", "peek_table"}


def _contains_simulated_tool_call(text: str) -> bool:
    """Detecta si el model ha escrito tool calls como texto en vez de invocarlas."""
    if not text:
        return False
    for name in _TOOL_NAMES:
        # Patron 1: en bloque ``` (```markdown\nquery_data...```)
        # Patron 2: seguido de ( como llamada a función
        # Patron 3: al inicio de línea como comando
        # Patron 4: entre backticks inline `query_data`
        pattern = (
            rf'```[\w]*\s*{name}'
            rf'|{name}\s*\('
            rf'|^{name}\b'
            rf'|`{name}`'
        )
        if re.search(pattern, text, re.MULTILINE):
            return True
    return False


# ─── Schema cache para inyección en system prompt ───────────────
_schema_cache: str = ""
_schema_cache_time: float = 0.0
_SCHEMA_CACHE_TTL = 120  # segundos; se refresca cuando se suban nuevos ficheros


def _get_schema_block() -> str:
    """Devuelve un bloque markdown con el schema de todas las tablas DuckDB."""
    global _schema_cache, _schema_cache_time
    now = time.time()
    if _schema_cache and (now - _schema_cache_time) < _SCHEMA_CACHE_TTL:
        return _schema_cache

    try:
        from backend.ai.sql_engine import get_table_list, load_tables
        load_tables()
        tables = get_table_list()
        if not tables:
            _schema_cache = ""
            return ""
        lines = ["\n## SCHEMA DE BASE DE DATOS (tablas disponibles)\n"]
        for t in tables:
            cols = ", ".join(f"`{c['name']}` {c['type']}" for c in t["columns"])
            lines.append(f"- **{t['name']}** ({t['row_count']} filas): {cols}")
        _schema_cache = "\n".join(lines)
        _schema_cache_time = now
    except Exception:
        _schema_cache = ""
    return _schema_cache


_SYSTEM_PROMPT_TEMPLATE = """\
Eres un asistente experto en documentación corporativa.
Tienes acceso a herramientas para buscar en documentos, consultar datos \
numéricos y explorar relaciones entre personas y organizaciones.

REGLA FUNDAMENTAL: NUNCA escribas llamadas a herramientas como texto o markdown. \
SIEMPRE invócalas usando el mecanismo de function-calling del API.

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
con otros términos O usa un doc_type diferente.

• DATOS NUMÉRICOS / TABLAS (ventas, inventarios, incidencias, totales, \
conteos, comparativas):
  → El SCHEMA COMPLETO está incluido al final de este prompt: úsalo \
DIRECTAMENTE sin llamar a list_available_tables ni peek_table.
  → Usa query_data(sql=...) con SQL DuckDB correcto en UN SOLO PASO.
  → Ejemplo:
    query_data(sql="SELECT cliente, SUM(CAST(REPLACE(total,',','.') AS DOUBLE)) \
AS total FROM ventas_enero_2025 GROUP BY cliente ORDER BY total DESC LIMIT 3")
  → Para diferencia de fechas: date_diff('day', fecha_inicio, fecha_fin) \
con 3 argumentos (NUNCA 2).
  → Si la pregunta pide CONTAR, incluye COUNT(*) AS total en el SELECT.
  → Si query_data falla con error de columna, USA peek_table para verificar \
el nombre exacto, luego reintenta. Esa es la ÚNICA razón para usar peek_table.

• RELACIONES ENTRE PERSONAS / ORGANIZACIONES (quién se relaciona con quién, \
qué hace una persona, en qué proyectos participa):
  → get_entity_info o find_connection.
  → SOLO cuando se pregunte EXPLÍCITAMENTE sobre una persona u organización.

• PREGUNTAS MIXTAS (ej. "ventas + acuerdos reunión"):
  → Combina search_documents (para texto) + query_data (para cifras).

REGLAS:
- Responde SIEMPRE en español.
- Cita los documentos entre corchetes: [nombre_fichero].
- Si los datos son numéricos, incluye las cifras exactas.
- Si no hay información suficiente, dilo en vez de inventar.
- Responde DE FORMA CONCISA: ve al grano con la información pedida.
- Usa formato Markdown.
{schema_block}"""


def _build_system_prompt() -> str:
    """Construye el system prompt con el schema de tablas inyectado."""
    schema = _get_schema_block()
    return _SYSTEM_PROMPT_TEMPLATE.format(schema_block=schema)


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


# ─── Retry con backoff para rate limits ──────────────────────────

def _call_with_retry(client, model, messages, tools=None, tool_choice=None,
                     temperature=0.15, max_tokens=2048, max_retries=3):
    """
    Llama a Groq con reintentos automáticos si hay rate limit (429).
    Si el rate limit es largo (>30s), cae al modelo rápido como fallback.
    """
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"
        kwargs["parallel_tool_calls"] = False

    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err:
                # Extraer tiempo de espera sugerido
                wait_match = re.search(r'try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s', err)
                if wait_match:
                    minutes = int(wait_match.group(1) or 0)
                    seconds = float(wait_match.group(2))
                    total_wait = minutes * 60 + seconds
                else:
                    total_wait = 5 * (attempt + 1)

                log.warning(
                    "[RATE_LIMIT] modelo=%s intento=%d/%d espera=%.1fs msg=%s",
                    model, attempt + 1, max_retries, total_wait, err[:200],
                )

                # Si la espera es corta (<= 10s), esperar y reintentar
                if total_wait <= 10:
                    time.sleep(total_wait + 0.5)
                    continue

                # Si la espera es larga, caer al modelo rápido (8b)
                if model != GROQ_MODEL:
                    log.warning("[RATE_LIMIT] Cambiando a modelo rápido fallback: %s", GROQ_MODEL)
                    kwargs["model"] = GROQ_MODEL
                    try:
                        return client.chat.completions.create(**kwargs)
                    except Exception as e2:
                        log.error("[RATE_LIMIT] Fallback también falló: %s", e2)
                # Si también falla el fallback, esperar un poco y reintentar
                time.sleep(min(total_wait, 15))
                continue
            log.error("[LLM_ERROR] modelo=%s intento=%d error=%s", model, attempt + 1, err)
            raise  # re-raise si no es rate limit
    # Último intento sin catch
    log.debug("[LLM_CALL] último intento sin catch, modelo=%s", kwargs.get('model', model))
    return client.chat.completions.create(**kwargs)


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
    log.info("[AGENT_START] session=%s pregunta=%r", session_id, question[:200])

    if not GROQ_API_KEY:
        log.error("[AGENT_ERROR] GROQ_API_KEY no configurada")
        return AgentResult(
            answer="Error: GROQ_API_KEY no configurada en .env",
            model=AGENT_MODEL,
            error="no_api_key",
        )

    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)

    # Construir mensajes: system + historial + pregunta actual
    messages: list[dict] = [{"role": "system", "content": _build_system_prompt()}]
    messages.extend(_get_history(session_id))
    messages.append({"role": "user", "content": question})

    steps: list[AgentStep] = []
    collected_sources: list[dict] = []

    # Exponer la pregunta actual a agent_tools para COUNT injection en SQL directo
    from backend.ai import agent_tools as _at
    _at._current_question = question

    # ── ReAct loop ───────────────────────────────────────────────
    for iteration in range(MAX_ITERATIONS):
        log.debug("[ITER_%d] tool_choice=%s mensajes_en_contexto=%d", iteration, 'required' if iteration == 0 else 'auto', len(messages))
        # Primera iteración: forzar uso de herramienta (el agente no tiene
        # conocimiento propio, SIEMPRE debe buscar/consultar primero).
        # Iteraciones siguientes: auto (puede responder o seguir con tools).
        tc = "required" if iteration == 0 else "auto"

        try:
            response = _call_with_retry(
                client, AGENT_MODEL, messages, TOOLS, tc, temperature=0.15,
            )
        except Exception as e:
            err_str = str(e)
            log.error("[ITER_%d] Excepción en LLM call: %s", iteration, err_str[:500])
            # Groq a veces genera tool calls malformadas (args embebidos en el nombre).
            # En ese caso llamamos de nuevo SIN tools para forzar una respuesta textual
            # con el contexto que ya se ha recopilado.
            if "tool_use_failed" in err_str or "Failed to call a function" in err_str:
                log.warning("[ITER_%d] tool_use_failed detectado, intentando fallback sin tools", iteration)
                try:
                    fallback = _call_with_retry(
                        client, AGENT_MODEL, messages,
                        tools=None, tool_choice=None, temperature=0.15,
                    )
                    answer = fallback.choices[0].message.content or "No se pudo completar la respuesta."
                    log.info("[ITER_%d] Fallback exitoso, respuesta=%r", iteration, answer[:200])
                    _save_turn(session_id, question, answer)
                    return AgentResult(
                        answer=answer,
                        sources=_dedupe_sources(collected_sources),
                        steps=steps,
                        model=AGENT_MODEL,
                    )
                except Exception as e2:
                    log.error("[ITER_%d] Fallback sin tools también falló: %s", iteration, e2)
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
            answer = msg.content or ""

            # Detectar si el modelo simuló tool calls como texto en vez de invocarlas.
            # En ese caso añadimos una corrección y continuamos el loop.
            if _contains_simulated_tool_call(answer) and iteration < MAX_ITERATIONS - 1:
                log.warning("[ITER_%d] Simulación de tool call detectada en texto. Corrigiendo. Respuesta=%r", iteration, answer[:300])
                messages.append(msg.to_dict())
                messages.append({
                    "role": "user",
                    "content": (
                        "Has escrito llamadas a herramientas como texto en lugar de "
                        "invocarlas con function-calling. Esto hace que las herramientas "
                        "NO se ejecuten y los datos sean inventados. "
                        "Invoca las herramientas usando el mecanismo de function-calling "
                        "del API, no escribas sus nombres en bloques de código."
                    ),
                })
                continue

            answer = answer or "No se pudo generar una respuesta."
            log.info("[AGENT_END] iter=%d fuentes=%d pasos=%d respuesta=%r", iteration, len(collected_sources), len(steps), answer[:200])
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

            # Detectar llamadas repetidas idénticas solo para query_data.
            # peek_table y list_available_tables son idempotentes y pueden repetirse
            # legítimamente (el agente puede necesitar re-consultar el schema).
            _BLOCK_IF_REPEATED = {"query_data", "search_documents"}
            call_key = f"{fn_name}:{json.dumps(fn_args, sort_keys=True)}"
            prev_failed_keys = {
                f"{s.tool_name}:{json.dumps(s.tool_args, sort_keys=True)}"
                for s in steps
                if s.tool_name in _BLOCK_IF_REPEATED and "error" in s.result_preview
            }
            if fn_name in _BLOCK_IF_REPEATED and call_key in prev_failed_keys:
                log.warning("[TOOL_BLOCKED] %s args=%s (llamada repetida que ya falló)", fn_name, json.dumps(fn_args)[:200])
                observation = json.dumps({
                    "error": (
                        f"Ya llamaste a {fn_name} con estos mismos argumentos y falló. "
                        "Reformula usando el parámetro 'sql' con los nombres de columna "
                        "exactos que viste en peek_table, o cambia la pregunta."
                    ),
                })
            else:
                # Ejecutar la herramienta
                log.debug("[TOOL_CALL] %s args=%s", fn_name, json.dumps(fn_args)[:300])
                t0 = time.time()
                observation = execute_tool(fn_name, fn_args)
                elapsed = time.time() - t0
                try:
                    obs_parsed = json.loads(observation)
                    has_error = "error" in obs_parsed
                    result_count = len(obs_parsed.get("chunks", obs_parsed.get("rows", [])))
                except Exception:
                    has_error = False
                    result_count = -1
                if has_error:
                    log.warning("[TOOL_ERROR] %s args=%s error=%s", fn_name, json.dumps(fn_args)[:200], observation[:400])
                else:
                    log.debug("[TOOL_OK] %s resultados=%d tiempo=%.2fs preview=%s", fn_name, result_count, elapsed, observation[:200])

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

    # Se agotaron las iteraciones: pedir al LLM que sintetice con lo recopilado
    log.warning("[MAX_ITER] Se agotaron %d iteraciones. pasos=%d fuentes=%d", MAX_ITERATIONS, len(steps), len(collected_sources))
    try:
        synthesis = _call_with_retry(
            client, AGENT_MODEL,
            messages=messages + [{
                "role": "user",
                "content": (
                    "Con toda la información recopilada hasta ahora, "
                    "responde la pregunta original de la forma más completa posible. "
                    "Si algunos datos no están disponibles, indícalo."
                ),
            }],
            tools=None, tool_choice=None,
            temperature=0.15, max_tokens=1024,
        )
        answer = synthesis.choices[0].message.content or "No se encontró información suficiente."
    except Exception:
        log.error("[MAX_ITER] Síntesis final también falló", exc_info=True)
        answer = (
            "No se pudo completar la búsqueda en el número de pasos permitidos. "
            "Intenta reformular la pregunta o descomponerla en partes."
        )
    _save_turn(session_id, question, answer)
    return AgentResult(
        answer=answer,
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
