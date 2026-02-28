"use client";

import { useState, useRef, useEffect } from "react";
import * as api from "@/lib/api";
import { renderMarkdown } from "@/lib/utils";
import type { ChatMessage } from "@/lib/types";

export function AskTab() {
    const [query, setQuery] = useState("");
    const [loading, setLoading] = useState(false);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [sessionId] = useState(() => "s_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8));
    const containerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        containerRef.current?.scrollTo({ top: containerRef.current.scrollHeight, behavior: "smooth" });
    }, [messages]);

    async function ask() {
        const q = query.trim();
        if (!q || loading) return;
        setMessages((prev) => [...prev, { role: "user", content: q }]);
        setQuery("");
        setLoading(true);
        try {
            const data = await api.agentAsk(q, sessionId);
            setMessages((prev) => [
                ...prev,
                { role: "assistant", content: data.answer, sources: data.sources, steps: data.steps },
            ]);
        } catch {
            setMessages((prev) => [...prev, { role: "assistant", content: "Error al procesar la consulta." }]);
        }
        setLoading(false);
    }

    return (
        <section className="fade-in">
            <div className="max-w-3xl mx-auto">
                <div className="text-center mb-8">
                    <h1 className="text-2xl font-semibold text-ink-0 mb-2">Pregunta a tus documentos</h1>
                    <p className="text-sm text-ink-2">Respuestas generadas con IA a partir de tu base documental corporativa</p>
                </div>

                <div ref={containerRef} className="space-y-4 mb-6 min-h-[200px] max-h-[60vh] overflow-y-auto">
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

                <form onSubmit={(e) => { e.preventDefault(); ask(); }} className="sticky bottom-6">
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
        </section>
    );
}
