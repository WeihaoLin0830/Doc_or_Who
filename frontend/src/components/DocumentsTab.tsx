"use client";

import { useState, useEffect } from "react";
import * as api from "@/lib/api";
import type { DocListItem, DocDetail, DuplicatePair } from "@/lib/types";
import { typeColor } from "@/lib/utils";

interface Props {
    documents: DocListItem[];
    onRefresh?: () => void;
}

export function DocumentsTab({ documents: initialDocuments, onRefresh }: Props) {
    // Keep a local copy so the tab always shows the freshest data,
    // even if the parent hasn't re-fetched yet.
    const [documents, setDocuments] = useState<DocListItem[]>(initialDocuments);
    const [detail, setDetail] = useState<DocDetail | null>(null);
    const [summary, setSummary] = useState<string | null>(null);
    const [summaryLoading, setSummaryLoading] = useState(false);
    const [duplicates, setDuplicates] = useState<DuplicatePair[]>([]);
    const [dupLoading, setDupLoading] = useState(false);
    const [dupChecked, setDupChecked] = useState(false);

    // Fetch fresh data every time this tab mounts (guarantees post-upload count is correct).
    useEffect(() => {
        api.listDocuments().then(setDocuments).catch(() => {});
    }, []);

    // Also sync if parent refreshes (e.g. after ingest completes).
    useEffect(() => {
        if (initialDocuments.length > 0) setDocuments(initialDocuments);
    }, [initialDocuments]);

    async function viewDoc(docId: string) {
        setSummary(null);
        try {
            const data = await api.getDocument(docId);
            setDetail(data);
        } catch { /* ignore */ }
    }

    async function summarize(docId: string) {
        setSummaryLoading(true);
        setSummary(null);
        try { setSummary(await api.summarizeDocument(docId)); } catch { /* ignore */ }
        setSummaryLoading(false);
    }

    async function loadDuplicates() {
        setDupLoading(true);
        setDupChecked(true);
        try { setDuplicates(await api.findDuplicates()); } catch { setDuplicates([]); }
        setDupLoading(false);
    }

    return (
        <section className="fade-in">
            <div className="max-w-5xl mx-auto">
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold">Documentos indexados</h2>
                    <span className="text-sm text-ink-3">{documents.length} documentos</span>
                </div>

                {/* Documents table */}
                <div className="bg-white border border-surface-3 rounded-lg overflow-hidden">
                    <table className="w-full">
                        <thead>
                            <tr className="border-b border-surface-3 bg-surface-1">
                                <th className="text-left text-xs font-medium text-ink-2 uppercase tracking-wider px-4 py-3">Documento</th>
                                <th className="text-left text-xs font-medium text-ink-2 uppercase tracking-wider px-4 py-3">Tipo</th>
                                <th className="text-left text-xs font-medium text-ink-2 uppercase tracking-wider px-4 py-3">Categoría</th>
                                <th className="text-right text-xs font-medium text-ink-2 uppercase tracking-wider px-4 py-3">Acciones</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-surface-3">
                            {documents.map((doc) => (
                                <tr key={doc.doc_id} className="hover:bg-surface-1 transition-colors">
                                    <td className="px-4 py-3">
                                        <div className="text-sm font-medium text-ink-0">{doc.title || doc.filename}</div>
                                        <div className="text-xs text-ink-3">{doc.filename}</div>
                                    </td>
                                    <td className="px-4 py-3">
                                        <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${typeColor(doc.doc_type)}`}>{doc.doc_type}</span>
                                    </td>
                                    <td className="px-4 py-3 text-sm text-ink-2">{doc.category || "—"}</td>
                                    <td className="px-4 py-3 text-right">
                                        <button onClick={() => viewDoc(doc.doc_id)} className="text-xs text-brand-600 hover:text-brand-700 font-medium">Ver detalle</button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                {/* Duplicates */}
                <div className="mt-6">
                    <div className="flex items-center justify-between mb-3">
                        <h3 className="text-sm font-semibold text-ink-0 flex items-center gap-2">
                            <svg className="w-4 h-4 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                    d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-4 10h6a2 2 0 002-2v-8a2 2 0 00-2-2h-6a2 2 0 00-2 2v8a2 2 0 002 2z" />
                            </svg>
                            Documentos Duplicados
                        </h3>
                        <button onClick={loadDuplicates} disabled={dupLoading}
                            className="text-xs px-3 py-1.5 bg-amber-50 text-amber-700 border border-amber-200 rounded-lg hover:bg-amber-100 disabled:opacity-50 transition-colors">
                            {dupLoading ? "Analizando..." : "Detectar duplicados"}
                        </button>
                    </div>
                    {dupChecked && duplicates.length === 0 && !dupLoading && (
                        <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-3">
                            ✓ No se encontraron documentos near-duplicados (umbral 85%).
                        </div>
                    )}
                    {duplicates.length > 0 && (
                        <div className="space-y-2">
                            {duplicates.map((pair, i) => (
                                <div key={i} className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-start gap-3">
                                    <svg className="w-4 h-4 text-amber-500 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                            d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                                    </svg>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="text-sm font-medium text-amber-800 truncate">{pair.doc_a.title || pair.doc_a.filename}</span>
                                            <span className="text-amber-400">↔</span>
                                            <span className="text-sm font-medium text-amber-800 truncate">{pair.doc_b.title || pair.doc_b.filename}</span>
                                        </div>
                                        <div className="text-xs text-amber-600 mt-0.5">Similitud: {(pair.similarity * 100).toFixed(1)}%</div>
                                    </div>
                                    <div className="flex gap-2 shrink-0">
                                        <button onClick={() => viewDoc(pair.doc_a.doc_id)} className="text-xs text-brand-600 hover:text-brand-700 font-medium">Ver A</button>
                                        <button onClick={() => viewDoc(pair.doc_b.doc_id)} className="text-xs text-brand-600 hover:text-brand-700 font-medium">Ver B</button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Document detail modal */}
                {detail && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
                        onClick={(e) => { if (e.target === e.currentTarget) setDetail(null); }}>
                        <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl mx-4 max-h-[80vh] flex flex-col fade-in">
                            <div className="flex items-center justify-between p-5 border-b border-surface-3 shrink-0">
                                <div>
                                    <h3 className="text-base font-semibold">{detail.title || detail.filename}</h3>
                                    <div className="flex items-center gap-2 mt-1">
                                        <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${typeColor(detail.doc_type)}`}>{detail.doc_type}</span>
                                        <span className="text-xs text-ink-3">{detail.filename}</span>
                                        {detail.language && <span className="text-xs text-ink-3">· {detail.language}</span>}
                                    </div>
                                </div>
                                <button onClick={() => setDetail(null)} className="text-ink-3 hover:text-ink-0">
                                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                    </svg>
                                </button>
                            </div>
                            <div className="flex-1 overflow-y-auto p-5 space-y-4">
                                {/* Summary */}
                                <div>
                                    <div className="flex items-center justify-between mb-2">
                                        <h4 className="text-xs font-medium text-ink-3 uppercase tracking-wider">Resumen</h4>
                                        <button onClick={() => summarize(detail.doc_id)} disabled={summaryLoading}
                                            className="text-xs text-brand-600 hover:text-brand-700 font-medium disabled:opacity-50">
                                            {summaryLoading ? "Generando..." : "Generar resumen"}
                                        </button>
                                    </div>
                                    {summary && <p className="text-sm text-ink-1 leading-relaxed bg-surface-1 rounded-lg p-3">{summary}</p>}
                                </div>

                                {/* Entities */}
                                {(detail.persons?.length > 0 || detail.organizations?.length > 0) && (
                                    <div>
                                        <h4 className="text-xs font-medium text-ink-3 uppercase tracking-wider mb-2">Entidades</h4>
                                        <div className="flex flex-wrap gap-1">
                                            {detail.persons?.map((p) => <span key={p} className="px-2 py-0.5 rounded text-xs bg-green-50 text-green-700">{p}</span>)}
                                            {detail.organizations?.map((o) => <span key={o} className="px-2 py-0.5 rounded text-xs bg-blue-50 text-blue-700">{o}</span>)}
                                        </div>
                                    </div>
                                )}

                                {/* Keywords */}
                                {detail.keywords?.length > 0 && (
                                    <div>
                                        <h4 className="text-xs font-medium text-ink-3 uppercase tracking-wider mb-2">Palabras clave</h4>
                                        <div className="flex flex-wrap gap-1">
                                            {detail.keywords.map((k) => <span key={k} className="px-2 py-0.5 rounded text-xs bg-surface-2 text-ink-2">{k}</span>)}
                                        </div>
                                    </div>
                                )}

                                {/* Chunks */}
                                {detail.chunks?.length > 0 && (
                                    <div>
                                        <h4 className="text-xs font-medium text-ink-3 uppercase tracking-wider mb-2">Fragmentos ({detail.chunks.length})</h4>
                                        <div className="space-y-2">
                                            {detail.chunks.map((c, i) => (
                                                <div key={c.chunk_id} className="bg-surface-1 rounded-lg p-3">
                                                    <div className="text-[10px] font-mono text-ink-3 mb-1">#{i + 1}{c.section ? ` — ${c.section}` : ""}</div>
                                                    <p className="text-sm text-ink-1 leading-relaxed whitespace-pre-wrap line-clamp-4">{c.text}</p>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </section>
    );
}
