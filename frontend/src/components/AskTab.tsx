"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import * as api from "@/lib/api";
import { renderMarkdown } from "@/lib/utils";
import type { ChatMessage, ChatSession } from "@/lib/types";

// ─── helpers ─────────────────────────────────────────────────────
function newSessionId(): string {
    return "s_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
}

function newSession(): ChatSession {
    return { id: newSessionId(), title: "Nueva conversación", messages: [], createdAt: Date.now() };
}

/** Derive a short title from the first user message */
function deriveTitle(msg: string): string {
    const clean = msg.replace(/\n/g, " ").trim();
    return clean.length > 50 ? clean.slice(0, 47) + "…" : clean;
}

// ─── Component ───────────────────────────────────────────────────
export function AskTab() {
    const [sessions, setSessions] = useState<ChatSession[]>(() => [newSession()]);
    const [activeId, setActiveId] = useState<string>(() => sessions[0]?.id ?? "");
    const [query, setQuery] = useState("");
    const [loading, setLoading] = useState(false);
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const containerRef = useRef<HTMLDivElement>(null);

    const active = sessions.find((s) => s.id === activeId) ?? sessions[0];
    const messages = active?.messages ?? [];

    // Scroll to bottom on new messages
    useEffect(() => {
        containerRef.current?.scrollTo({ top: containerRef.current.scrollHeight, behavior: "smooth" });
    }, [messages.length]);

    // ─── Session management ──────────────────────────────────────
    const createSession = useCallback(() => {
        const s = newSession();
        setSessions((prev) => [s, ...prev]);
        setActiveId(s.id);
        setQuery("");
    }, []);

    const selectSession = useCallback((id: string) => {
        setActiveId(id);
        setQuery("");
    }, []);

    const deleteSession = useCallback(
        (id: string) => {
            setSessions((prev) => {
                const next = prev.filter((s) => s.id !== id);
                if (next.length === 0) {
                    const s = newSession();
                    setActiveId(s.id);
                    return [s];
                }
                if (id === activeId) setActiveId(next[0].id);
                return next;
            });
        },
        [activeId],
    );

    // ─── Ask handler ─────────────────────────────────────────────
    async function ask() {
        const q = query.trim();
        if (!q || loading || !active) return;

        const userMsg: ChatMessage = { role: "user", content: q };
        setSessions((prev) =>
            prev.map((s) => {
                if (s.id !== active.id) return s;
                const updated = { ...s, messages: [...s.messages, userMsg] };
                // Auto-title from first message
                if (s.messages.length === 0) updated.title = deriveTitle(q);
                return updated;
            }),
        );
        setQuery("");
        setLoading(true);

        try {
            const data = await api.agentAsk(q, active.id);
            const assistantMsg: ChatMessage = {
                role: "assistant",
                content: data.answer,
                sources: data.sources,
                steps: data.steps,
            };
            setSessions((prev) =>
                prev.map((s) => (s.id === active.id ? { ...s, messages: [...s.messages, assistantMsg] } : s)),
            );
        } catch {
            const errMsg: ChatMessage = { role: "assistant", content: "Error al procesar la consulta." };
            setSessions((prev) =>
                prev.map((s) => (s.id === active.id ? { ...s, messages: [...s.messages, errMsg] } : s)),
            );
        }
        setLoading(false);
    }

    return (
        <section className="fade-in flex h-[calc(100vh-6rem)]">
            {/* ─── Sidebar ──────────────────────────────────────── */}
            <aside
                className={`${sidebarOpen ? "w-64" : "w-0"
                    } shrink-0 transition-all duration-200 overflow-hidden border-r border-surface-3 bg-surface-1 flex flex-col`}
            >
                <div className="flex items-center justify-between p-3 border-b border-surface-3">
                    <span className="text-xs font-semibold text-ink-2 uppercase tracking-wider">Conversaciones</span>
                    <button
                        onClick={createSession}
                        title="Nueva conversación"
                        className="w-7 h-7 flex items-center justify-center rounded-md text-brand-600 hover:bg-brand-50 transition-colors"
                    >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                        </svg>
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto py-1">
                    {sessions.map((s) => (
                        <div
                            key={s.id}
                            onClick={() => selectSession(s.id)}
                            className={`group flex items-center gap-2 mx-1.5 my-0.5 px-3 py-2 rounded-md cursor-pointer text-sm transition-colors ${s.id === activeId
                                    ? "bg-brand-50 text-brand-700 font-medium"
                                    : "text-ink-1 hover:bg-surface-2"
                                }`}
                        >
                            <svg className="w-3.5 h-3.5 shrink-0 text-ink-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                    d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                            </svg>
                            <span className="flex-1 truncate">{s.title}</span>
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    deleteSession(s.id);
                                }}
                                className="opacity-0 group-hover:opacity-100 w-5 h-5 flex items-center justify-center rounded text-ink-3 hover:text-red-500 hover:bg-red-50 transition-all"
                                title="Eliminar conversación"
                            >
                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </button>
                        </div>
                    ))}
                </div>
            </aside>

            {/* ─── Main chat area ───────────────────────────────── */}
            <div className="flex-1 flex flex-col min-w-0">
                {/* Toggle sidebar + header */}
                <div className="flex items-center gap-2 px-4 py-2 border-b border-surface-3">
                    <button
                        onClick={() => setSidebarOpen((v) => !v)}
                        className="w-7 h-7 flex items-center justify-center rounded-md text-ink-3 hover:text-ink-0 hover:bg-surface-2 transition-colors"
                        title={sidebarOpen ? "Ocultar panel" : "Mostrar panel"}
                    >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                        </svg>
                    </button>
                    <h2 className="text-sm font-medium text-ink-1 truncate">{active?.title ?? "Chat"}</h2>
                </div>

                {/* Messages */}
                <div ref={containerRef} className="flex-1 overflow-y-auto px-4 py-4">
                    {messages.length === 0 && (
                        <div className="flex flex-col items-center justify-center h-full text-center">
                            <div className="w-12 h-12 rounded-full bg-brand-50 flex items-center justify-center mb-4">
                                <svg className="w-6 h-6 text-brand-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                                        d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                                </svg>
                            </div>
                            <h3 className="text-base font-semibold text-ink-0 mb-1">Pregunta a tus documentos</h3>
                            <p className="text-sm text-ink-2 max-w-md">
                                Respuestas generadas con IA a partir de tu base documental corporativa
                            </p>
                        </div>
                    )}

                    <div className="max-w-3xl mx-auto space-y-4">
                        {messages.map((msg, idx) => (
                            <div key={idx} className={`fade-in flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                                <div
                                    className={`max-w-[85%] rounded-xl px-4 py-3 text-sm leading-relaxed ${msg.role === "user"
                                            ? "bg-brand-600 text-white"
                                            : "bg-white border border-surface-3 text-ink-0"
                                        }`}
                                >
                                    {msg.role === "user" ? (
                                        <div>{msg.content}</div>
                                    ) : (
                                        <div dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }} />
                                    )}

                                    {/* Agent steps */}
                                    {msg.steps && msg.steps.length > 0 && (
                                        <details className="mt-3 pt-2 border-t border-surface-3">
                                            <summary className="text-xs font-medium text-ink-3 cursor-pointer hover:text-ink-1">
                                                {msg.steps.length} herramienta{msg.steps.length > 1 ? "s" : ""} usada{msg.steps.length > 1 ? "s" : ""}
                                            </summary>
                                            <div className="mt-1 space-y-1">
                                                {msg.steps.map((step, si) => (
                                                    <div key={si} className="flex items-center gap-1.5 text-xs text-ink-2">
                                                        <span className="inline-block w-1.5 h-1.5 rounded-full bg-brand-400" />
                                                        <span className="font-mono">{step.tool}</span>
                                                        <span className="text-ink-3">
                                                            ({Object.values(step.args).join(", ").substring(0, 60)})
                                                        </span>
                                                    </div>
                                                ))}
                                            </div>
                                        </details>
                                    )}

                                    {/* Sources */}
                                    {msg.sources && msg.sources.length > 0 && (
                                        <div className={`mt-3 pt-2 border-t ${msg.role === "user" ? "border-brand-500" : "border-surface-3"}`}>
                                            <p className={`text-xs font-medium mb-1 ${msg.role === "user" ? "text-brand-200" : "text-ink-3"}`}>
                                                Fuentes:
                                            </p>
                                            <div className="flex flex-wrap gap-1">
                                                {msg.sources.map((src) => (
                                                    <span
                                                        key={src.filename}
                                                        className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${msg.role === "user" ? "bg-brand-500 text-brand-100" : "bg-surface-2 text-ink-2"
                                                            }`}
                                                    >
                                                        {src.filename}
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>
                        ))}

                        {loading && (
                            <div className="flex justify-start">
                                <div className="max-w-[85%] bg-white border border-surface-3 rounded-xl px-4 py-3">
                                    <div className="flex items-center gap-2 text-sm text-ink-2">
                                        <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                        </svg>
                                        Analizando documentos...
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Input bar */}
                <div className="px-4 pb-4 pt-2">
                    <form onSubmit={(e) => { e.preventDefault(); ask(); }} className="max-w-3xl mx-auto">
                        <div className="flex gap-2 bg-white border border-surface-3 rounded-xl p-2 shadow-sm focus-within:border-brand-400 focus-within:ring-2 focus-within:ring-brand-100 transition-all">
                            <input
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                                type="text"
                                placeholder="¿Cuáles fueron los acuerdos de la última reunión?"
                                className="flex-1 px-3 py-2 text-sm bg-transparent outline-none placeholder:text-ink-3"
                            />
                            <button
                                type="submit"
                                disabled={!query.trim() || loading}
                                className="px-4 py-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors"
                            >
                                Preguntar
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        </section>
    );
}
