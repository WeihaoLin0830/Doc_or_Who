"use client";

import { useState, useEffect, useCallback } from "react";
import * as api from "@/lib/api";
import type { DocDetail } from "@/lib/types";
import { typeColor } from "@/lib/utils";

interface Props {
    docId: string | null;
    onClose: () => void;
}

type Tab = "overview" | "content" | "file";

function fileExt(filename: string): string {
    return filename.split(".").pop()?.toLowerCase() || "";
}

export function DocumentModal({ docId, onClose }: Props) {
    const [detail, setDetail] = useState<DocDetail | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Summary — manual only
    const [summary, setSummary] = useState<string | null>(null);
    const [summaryLoading, setSummaryLoading] = useState(false);

    // CSV/XLS table data
    const [tableData, setTableData] = useState<{ columns: string[]; rows: unknown[][] } | null>(null);
    const [tableLoading, setTableLoading] = useState(false);

    // Tab
    const [tab, setTab] = useState<Tab>("overview");

    const loadDoc = useCallback(async (id: string) => {
        setLoading(true);
        setError(null);
        setSummary(null);
        setTableData(null);
        setTab("overview");
        try {
            const d = await api.getDocument(id);
            setDetail(d);
        } catch {
            setError("No se pudo cargar el documento.");
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        if (docId) loadDoc(docId);
    }, [docId, loadDoc]);

    async function generateSummary() {
        if (!docId || summaryLoading) return;
        setSummaryLoading(true);
        try {
            const s = await api.summarizeDocument(docId);
            setSummary(s);
        } catch { /* ignore */ }
        setSummaryLoading(false);
    }

    async function openFileTab() {
        if (!detail) return;
        setTab("file");
        const ext = fileExt(detail.filename);
        if ((ext === "csv" || ext === "xlsx" || ext === "xls") && !tableData && !tableLoading) {
            setTableLoading(true);
            try {
                const t = await api.getDocumentTable(docId!);
                setTableData({ columns: t.columns, rows: t.rows });
            } catch { /* ignore */ }
            setTableLoading(false);
        }
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

    const ext = detail ? fileExt(detail.filename) : "";
    const isPdf = ext === "pdf";
    const isTabular = ext === "csv" || ext === "xlsx" || ext === "xls";
    const isTxt = ext === "txt" || ext === "docx" || ext === "doc";

    // Make modal fullscreen-ish when viewing a file
    const isFileView = tab === "file";

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
            onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
            <div className={`bg-white rounded-2xl shadow-2xl flex flex-col fade-in overflow-hidden transition-all duration-200
                ${isFileView ? "w-full h-full max-w-6xl max-h-[96vh]" : "w-full max-w-4xl max-h-[90vh]"}`}>

                {/* ─── Header ──────────────────────────────────── */}
                <div className="shrink-0 border-b border-surface-3">
                    <div className="flex items-start justify-between px-5 pt-4 pb-3">
                        <div className="flex-1 min-w-0">
                            {loading ? (
                                <div className="h-6 w-48 bg-surface-2 rounded animate-pulse" />
                            ) : detail ? (
                                <>
                                    <h2 className="text-base font-semibold text-ink-0 truncate pr-4">
                                        {detail.title || detail.filename}
                                    </h2>
                                    <div className="flex items-center gap-2 mt-1 flex-wrap">
                                        <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${typeColor(detail.doc_type)}`}>
                                            {detail.doc_type}
                                        </span>
                                        <span className="text-xs text-ink-3">{detail.filename}</span>
                                        {detail.language && <span className="text-xs text-ink-3">· {detail.language}</span>}
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
                            className="p-1.5 rounded-lg text-ink-3 hover:text-ink-0 hover:bg-surface-2 transition-colors shrink-0 ml-2">
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>

                    {/* Tabs + actions */}
                    {detail && (
                        <div className="flex items-center gap-2 px-5 pb-3">
                            {/* Tabs */}
                            <div className="flex items-center border border-surface-3 rounded-lg overflow-hidden">
                                <button onClick={() => setTab("overview")}
                                    className={`px-3 py-1.5 text-xs font-medium transition-colors ${tab === "overview" ? "bg-brand-50 text-brand-700" : "text-ink-3 hover:text-ink-0"}`}>
                                    Resumen
                                </button>
                                <button onClick={() => setTab("content")}
                                    className={`px-3 py-1.5 text-xs font-medium transition-colors ${tab === "content" ? "bg-brand-50 text-brand-700" : "text-ink-3 hover:text-ink-0"}`}>
                                    Contenido
                                </button>
                                {detail.has_file && (
                                    <button onClick={openFileTab}
                                        className={`px-3 py-1.5 text-xs font-medium transition-colors flex items-center gap-1 ${tab === "file" ? "bg-brand-50 text-brand-700" : "text-ink-3 hover:text-ink-0"}`}>
                                        {isPdf ? (
                                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                            </svg>
                                        ) : isTabular ? (
                                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M3 14h18M10 3v18M14 3v18M5 3h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z" />
                                            </svg>
                                        ) : (
                                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                                            </svg>
                                        )}
                                        Ver archivo
                                    </button>
                                )}
                            </div>

                            {/* Actions */}
                            <div className="ml-auto flex items-center gap-2">
                                {detail.has_file && tab === "file" && (
                                    <a href={api.getDocumentFileUrl(docId)} target="_blank" rel="noopener noreferrer"
                                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-ink-2 bg-surface-1 border border-surface-3 rounded-lg hover:bg-surface-2 transition-colors">
                                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                                        </svg>
                                        Nueva pestaña
                                    </a>
                                )}
                                <button onClick={downloadFile}
                                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-ink-2 bg-surface-1 border border-surface-3 rounded-lg hover:bg-surface-2 transition-colors">
                                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                                    </svg>
                                    Descargar
                                </button>
                            </div>
                        </div>
                    )}
                </div>

                {/* ─── Body ────────────────────────────────────── */}
                <div className="flex-1 min-h-0 overflow-y-auto">
                    {loading && (
                        <div className="flex items-center justify-center py-12">
                            <svg className="w-5 h-5 animate-spin text-brand-500" fill="none" viewBox="0 0 24 24">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                            </svg>
                            <span className="ml-2 text-sm text-ink-2">Cargando documento...</span>
                        </div>
                    )}

                    {/* ── Overview tab ────────────────────────── */}
                    {!loading && detail && tab === "overview" && (
                        <div className="p-5 space-y-5">
                            {/* Summary — manual generate */}
                            <div>
                                <div className="flex items-center justify-between mb-2">
                                    <h4 className="text-xs font-semibold text-ink-3 uppercase tracking-wider">Resumen IA</h4>
                                    {!summary && !summaryLoading && (
                                        <button onClick={generateSummary}
                                            className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700 transition-colors">
                                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                    d="M13 10V3L4 14h7v7l9-11h-7z" />
                                            </svg>
                                            Generar resumen
                                        </button>
                                    )}
                                </div>
                                {summaryLoading ? (
                                    <div className="flex items-center gap-2 text-sm text-ink-2 bg-surface-1 rounded-lg p-4">
                                        <svg className="w-4 h-4 animate-spin text-brand-500 shrink-0" fill="none" viewBox="0 0 24 24">
                                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                        </svg>
                                        Generando resumen con IA...
                                    </div>
                                ) : summary ? (
                                    <div>
                                        <p className="text-sm text-ink-1 leading-relaxed bg-brand-50/50 border border-brand-100 rounded-lg p-4">
                                            {summary}
                                        </p>
                                        <button onClick={generateSummary}
                                            className="mt-1.5 text-xs text-ink-3 hover:text-ink-1 transition-colors">
                                            ↺ Regenerar
                                        </button>
                                    </div>
                                ) : (
                                    <p className="text-sm text-ink-3 bg-surface-1 rounded-lg p-3 italic">
                                        Pulsa &quot;Generar resumen&quot; para crear un resumen con IA.
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

                            {/* Snippet preview */}
                            {(detail.chunks?.length || 0) > 0 && (
                                <div>
                                    <div className="flex items-center justify-between mb-2">
                                        <h4 className="text-xs font-semibold text-ink-3 uppercase tracking-wider">
                                            Vista previa ({detail.chunks.length} fragmentos)
                                        </h4>
                                        {detail.has_file && (
                                            <button onClick={openFileTab}
                                                className="text-xs text-brand-600 hover:text-brand-700 font-medium transition-colors">
                                                Ver archivo completo →
                                            </button>
                                        )}
                                    </div>
                                    <div className="space-y-2">
                                        {detail.chunks.slice(0, 3).map((ch, i) => (
                                            <div key={ch.chunk_id} className="bg-surface-1 rounded-lg p-3">
                                                <div className="text-[10px] font-mono text-ink-3 mb-1">
                                                    #{i + 1}{ch.section ? ` — ${ch.section}` : ""}
                                                </div>
                                                <p className="text-sm text-ink-1 leading-relaxed whitespace-pre-wrap line-clamp-3">
                                                    {ch.text}
                                                </p>
                                            </div>
                                        ))}
                                        {detail.chunks.length > 3 && (
                                            <button onClick={() => setTab("content")}
                                                className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                                                Ver {detail.chunks.length - 3} fragmentos más →
                                            </button>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {/* ── Content tab (chunks) ─────────────────── */}
                    {!loading && detail && tab === "content" && (
                        <div className="p-5 space-y-2">
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

                    {/* ── File viewer tab ──────────────────────── */}
                    {!loading && detail && tab === "file" && (
                        <div className="flex flex-col h-full min-h-[500px]">
                            {/* PDF inline viewer */}
                            {isPdf && (
                                <iframe
                                    src={`${api.getDocumentFileUrl(docId)}#toolbar=1&navpanes=1&scrollbar=1`}
                                    className="flex-1 w-full border-0"
                                    style={{ minHeight: "600px" }}
                                    title={detail.filename}
                                />
                            )}

                            {/* CSV / XLS table viewer */}
                            {isTabular && (
                                <div className="flex-1 overflow-auto p-4">
                                    {tableLoading ? (
                                        <div className="flex items-center justify-center py-12 gap-2 text-sm text-ink-2">
                                            <svg className="w-4 h-4 animate-spin text-brand-500" fill="none" viewBox="0 0 24 24">
                                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                            </svg>
                                            Cargando tabla...
                                        </div>
                                    ) : tableData ? (
                                        <div className="overflow-auto rounded-lg border border-surface-3 shadow-sm">
                                            <table className="min-w-full text-sm divide-y divide-surface-3">
                                                <thead className="bg-surface-1 sticky top-0 z-10">
                                                    <tr>
                                                        {tableData.columns.map((col) => (
                                                            <th key={col} className="px-4 py-2.5 text-left text-xs font-semibold text-ink-2 uppercase tracking-wider whitespace-nowrap border-r border-surface-3 last:border-r-0">
                                                                {col}
                                                            </th>
                                                        ))}
                                                    </tr>
                                                </thead>
                                                <tbody className="bg-white divide-y divide-surface-2">
                                                    {tableData.rows.map((row, ri) => (
                                                        <tr key={ri} className="hover:bg-surface-1 transition-colors">
                                                            {(row as unknown[]).map((cell, ci) => (
                                                                <td key={ci}
                                                                    className="px-4 py-2 text-xs text-ink-1 border-r border-surface-2 last:border-r-0 max-w-[200px] truncate"
                                                                    title={String(cell ?? "")}>
                                                                    {cell === null || cell === undefined || cell === "" ? (
                                                                        <span className="text-ink-3/50 italic">—</span>
                                                                    ) : String(cell)}
                                                                </td>
                                                            ))}
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                            <div className="px-4 py-2 bg-surface-1 border-t border-surface-3 text-xs text-ink-3">
                                                {tableData.rows.length} filas · {tableData.columns.length} columnas
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="flex flex-col items-center justify-center py-12 gap-2 text-ink-3">
                                            <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                                            </svg>
                                            <p className="text-sm">No se pudo cargar la tabla.</p>
                                        </div>
                                    )}
                                </div>
                            )}

                            {/* TXT / DOCX viewer */}
                            {isTxt && (
                                <div className="flex-1 overflow-auto p-5">
                                    {(ext === "docx" || ext === "doc") && (
                                        <div className="mb-3 flex items-center gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                                            <svg className="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                            </svg>
                                            Texto extraído del documento Word (sin formato)
                                        </div>
                                    )}
                                    <pre className="text-sm text-ink-1 whitespace-pre-wrap leading-relaxed font-sans">
                                        {detail.chunks.map((ch) => ch.text).join("\n\n")}
                                    </pre>
                                </div>
                            )}

                            {/* Other file types */}
                            {!isPdf && !isTabular && !isTxt && (
                                <div className="flex flex-col items-center justify-center flex-1 gap-4 p-8">
                                    <svg className="w-14 h-14 text-ink-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                                            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                    </svg>
                                    <p className="text-sm text-ink-2 text-center">
                                        Vista previa no disponible para archivos <strong>.{ext || "desconocido"}</strong>.
                                    </p>
                                    <button onClick={() => { const a = document.createElement("a"); a.href = api.getDocumentFileUrl(docId!); a.download = detail.filename; document.body.appendChild(a); a.click(); document.body.removeChild(a); }}
                                        className="inline-flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-700 text-white text-sm font-medium rounded-lg transition-colors">
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                                        </svg>
                                        Descargar archivo
                                    </button>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
