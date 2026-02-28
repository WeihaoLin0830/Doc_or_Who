"use client";

import { useState, useEffect, useCallback } from "react";
import * as api from "@/lib/api";
import type { DocDetail } from "@/lib/types";
import { typeColor } from "@/lib/utils";

interface Props {
    docId: string | null;
    onClose: () => void;
}

export function DocumentModal({ docId, onClose }: Props) {
    const [detail, setDetail] = useState<DocDetail | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Summary
    const [summary, setSummary] = useState<string | null>(null);
    const [summaryLoading, setSummaryLoading] = useState(false);

    // Raw text
    const [showFullText, setShowFullText] = useState(false);
    const [rawText, setRawText] = useState<string | null>(null);
    const [rawLoading, setRawLoading] = useState(false);

    // Tab
    const [tab, setTab] = useState<"overview" | "content">("overview");

    const loadDoc = useCallback(async (id: string) => {
        setLoading(true);
        setError(null);
        setSummary(null);
        setRawText(null);
        setShowFullText(false);
        setTab("overview");
        try {
            const d = await api.getDocument(id);
            setDetail(d);
            // Auto-generate summary
            setSummaryLoading(true);
            try {
                const s = await api.summarizeDocument(id);
                setSummary(s);
            } catch { /* summary optional */ }
            setSummaryLoading(false);
        } catch {
            setError("No se pudo cargar el documento.");
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        if (docId) loadDoc(docId);
    }, [docId, loadDoc]);

    async function loadRawText() {
        if (!docId || rawText) { setShowFullText(true); return; }
        setRawLoading(true);
        try {
            const t = await api.getDocumentRaw(docId);
            setRawText(t);
            setShowFullText(true);
        } catch { /* ignore */ }
        setRawLoading(false);
    }

    function openFile() {
        if (!docId) return;
        window.open(api.getDocumentFileUrl(docId), "_blank");
    }

    function downloadFile() {
        if (!docId || !detail) return;
        const a = document.createElement("a");
        a.href = api.getDocumentFileUrl(docId);
        a.download = detail.filename || "document";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    if (!docId) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
            onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl mx-4 max-h-[85vh] flex flex-col fade-in overflow-hidden">

                {/* ─── Header ──────────────────────────────────── */}
                <div className="shrink-0 border-b border-surface-3">
                    <div className="flex items-start justify-between p-5 pb-3">
                        <div className="flex-1 min-w-0">
                            {loading ? (
                                <div className="h-6 w-48 bg-surface-2 rounded animate-pulse" />
                            ) : detail ? (
                                <>
                                    <h2 className="text-lg font-semibold text-ink-0 truncate pr-4">
                                        {detail.title || detail.filename}
                                    </h2>
                                    <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                                        <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${typeColor(detail.doc_type)}`}>
                                            {detail.doc_type}
                                        </span>
                                        <span className="text-xs text-ink-3">{detail.filename}</span>
                                        {detail.language && (
                                            <span className="text-xs text-ink-3">· {detail.language}</span>
                                        )}
                                        <span className="text-xs text-ink-3">
                                            · {detail.chunks?.length || 0} fragmento{(detail.chunks?.length || 0) !== 1 ? "s" : ""}
                                        </span>
                                    </div>
                                </>
                            ) : error ? (
                                <p className="text-sm text-red-600">{error}</p>
                            ) : null}
                        </div>
                        <button onClick={onClose}
                            className="p-1.5 rounded-lg text-ink-3 hover:text-ink-0 hover:bg-surface-2 transition-colors shrink-0">
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>

                    {/* Action bar */}
                    {detail && (
                        <div className="flex items-center gap-2 px-5 pb-3">
                            {detail.has_file && (
                                <>
                                    <button onClick={openFile}
                                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-brand-700 bg-brand-50 border border-brand-200 rounded-lg hover:bg-brand-100 transition-colors">
                                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                                        </svg>
                                        Abrir archivo
                                    </button>
                                    <button onClick={downloadFile}
                                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-ink-2 bg-surface-1 border border-surface-3 rounded-lg hover:bg-surface-2 transition-colors">
                                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                                        </svg>
                                        Descargar
                                    </button>
                                </>
                            )}
                            {/* Tab toggle */}
                            <div className="ml-auto flex items-center border border-surface-3 rounded-lg overflow-hidden">
                                <button onClick={() => setTab("overview")}
                                    className={`px-3 py-1.5 text-xs font-medium transition-colors ${tab === "overview" ? "bg-brand-50 text-brand-700" : "text-ink-3 hover:text-ink-0"}`}>
                                    Resumen
                                </button>
                                <button onClick={() => { setTab("content"); if (!rawText) loadRawText(); }}
                                    className={`px-3 py-1.5 text-xs font-medium transition-colors ${tab === "content" ? "bg-brand-50 text-brand-700" : "text-ink-3 hover:text-ink-0"}`}>
                                    Contenido
                                </button>
                            </div>
                        </div>
                    )}
                </div>

                {/* ─── Body ────────────────────────────────────── */}
                <div className="flex-1 overflow-y-auto p-5">
                    {loading && (
                        <div className="flex items-center justify-center py-12">
                            <svg className="w-5 h-5 animate-spin text-brand-500" fill="none" viewBox="0 0 24 24">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                            </svg>
                            <span className="ml-2 text-sm text-ink-2">Cargando documento...</span>
                        </div>
                    )}

                    {!loading && detail && tab === "overview" && (
                        <div className="space-y-5">
                            {/* Summary */}
                            <div>
                                <h4 className="text-xs font-semibold text-ink-3 uppercase tracking-wider mb-2">
                                    Resumen
                                </h4>
                                {summaryLoading ? (
                                    <div className="flex items-center gap-2 text-sm text-ink-2 bg-surface-1 rounded-lg p-4">
                                        <svg className="w-4 h-4 animate-spin text-brand-500 shrink-0" fill="none" viewBox="0 0 24 24">
                                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                        </svg>
                                        Generando resumen con IA...
                                    </div>
                                ) : summary ? (
                                    <p className="text-sm text-ink-1 leading-relaxed bg-brand-50/50 border border-brand-100 rounded-lg p-4">
                                        {summary}
                                    </p>
                                ) : (
                                    <p className="text-sm text-ink-3 bg-surface-1 rounded-lg p-4">
                                        No se pudo generar un resumen automático.
                                    </p>
                                )}
                            </div>

                            {/* Entities */}
                            {((detail.persons?.length || 0) > 0 || (detail.organizations?.length || 0) > 0) && (
                                <div>
                                    <h4 className="text-xs font-semibold text-ink-3 uppercase tracking-wider mb-2">Entidades</h4>
                                    <div className="flex flex-wrap gap-1.5">
                                        {detail.persons?.map((p) => (
                                            <span key={p} className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs bg-green-50 text-green-700 border border-green-100">
                                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                                                </svg>
                                                {p}
                                            </span>
                                        ))}
                                        {detail.organizations?.map((o) => (
                                            <span key={o} className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs bg-blue-50 text-blue-700 border border-blue-100">
                                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                                                </svg>
                                                {o}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Keywords */}
                            {(detail.keywords?.length || 0) > 0 && (
                                <div>
                                    <h4 className="text-xs font-semibold text-ink-3 uppercase tracking-wider mb-2">Palabras clave</h4>
                                    <div className="flex flex-wrap gap-1.5">
                                        {detail.keywords.map((k) => (
                                            <span key={k} className="px-2 py-1 rounded-lg text-xs bg-surface-2 text-ink-2 border border-surface-3">{k}</span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Dates */}
                            {(detail.dates?.length || 0) > 0 && (
                                <div>
                                    <h4 className="text-xs font-semibold text-ink-3 uppercase tracking-wider mb-2">Fechas</h4>
                                    <div className="flex flex-wrap gap-1.5">
                                        {detail.dates.map((d) => (
                                            <span key={d} className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs bg-indigo-50 text-indigo-700 border border-indigo-100">
                                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                                                </svg>
                                                {d}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Chunks preview */}
                            {(detail.chunks?.length || 0) > 0 && (
                                <div>
                                    <h4 className="text-xs font-semibold text-ink-3 uppercase tracking-wider mb-2">
                                        Fragmentos ({detail.chunks.length})
                                    </h4>
                                    <div className="space-y-2">
                                        {detail.chunks.slice(0, 5).map((ch, i) => (
                                            <div key={ch.chunk_id} className="bg-surface-1 rounded-lg p-3">
                                                <div className="text-[10px] font-mono text-ink-3 mb-1">
                                                    #{i + 1}{ch.section ? ` — ${ch.section}` : ""}
                                                </div>
                                                <p className="text-sm text-ink-1 leading-relaxed whitespace-pre-wrap line-clamp-3">
                                                    {ch.text}
                                                </p>
                                            </div>
                                        ))}
                                        {detail.chunks.length > 5 && (
                                            <button onClick={() => setTab("content")}
                                                className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                                                Ver los {detail.chunks.length - 5} fragmentos restantes →
                                            </button>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Content tab — full text */}
                    {!loading && detail && tab === "content" && (
                        <div>
                            {rawLoading ? (
                                <div className="flex items-center gap-2 text-sm text-ink-2 py-8 justify-center">
                                    <svg className="w-4 h-4 animate-spin text-brand-500" fill="none" viewBox="0 0 24 24">
                                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                    </svg>
                                    Cargando contenido...
                                </div>
                            ) : rawText ? (
                                <div className="bg-surface-1 rounded-lg p-4">
                                    <pre className="text-sm text-ink-1 whitespace-pre-wrap leading-relaxed font-sans">
                                        {rawText}
                                    </pre>
                                </div>
                            ) : (
                                /* Fallback: show all chunks */
                                <div className="space-y-2">
                                    {detail.chunks.map((ch, i) => (
                                        <div key={ch.chunk_id} className="bg-surface-1 rounded-lg p-3">
                                            <div className="text-[10px] font-mono text-ink-3 mb-1">
                                                #{i + 1}{ch.section ? ` — ${ch.section}` : ""}
                                            </div>
                                            <p className="text-sm text-ink-1 leading-relaxed whitespace-pre-wrap">
                                                {ch.text}
                                            </p>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
