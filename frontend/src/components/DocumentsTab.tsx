"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import * as api from "@/lib/api";
import type { DocListItem, DocDetail, DuplicatePair, DocCluster } from "@/lib/types";
import { typeColor } from "@/lib/utils";

interface Props {
    documents: DocListItem[];
}

// ─── Cluster colors (rotate) ────────────────────────────────────
const CLUSTER_COLORS = [
    { bg: "bg-blue-50", border: "border-blue-200", text: "text-blue-700", badge: "bg-blue-100 text-blue-700", icon: "text-blue-500", bar: "bg-blue-400" },
    { bg: "bg-emerald-50", border: "border-emerald-200", text: "text-emerald-700", badge: "bg-emerald-100 text-emerald-700", icon: "text-emerald-500", bar: "bg-emerald-400" },
    { bg: "bg-violet-50", border: "border-violet-200", text: "text-violet-700", badge: "bg-violet-100 text-violet-700", icon: "text-violet-500", bar: "bg-violet-400" },
    { bg: "bg-amber-50", border: "border-amber-200", text: "text-amber-700", badge: "bg-amber-100 text-amber-700", icon: "text-amber-500", bar: "bg-amber-400" },
    { bg: "bg-rose-50", border: "border-rose-200", text: "text-rose-700", badge: "bg-rose-100 text-rose-700", icon: "text-rose-500", bar: "bg-rose-400" },
    { bg: "bg-cyan-50", border: "border-cyan-200", text: "text-cyan-700", badge: "bg-cyan-100 text-cyan-700", icon: "text-cyan-500", bar: "bg-cyan-400" },
    { bg: "bg-fuchsia-50", border: "border-fuchsia-200", text: "text-fuchsia-700", badge: "bg-fuchsia-100 text-fuchsia-700", icon: "text-fuchsia-500", bar: "bg-fuchsia-400" },
    { bg: "bg-lime-50", border: "border-lime-200", text: "text-lime-700", badge: "bg-lime-100 text-lime-700", icon: "text-lime-500", bar: "bg-lime-400" },
];

export function DocumentsTab({ documents }: Props) {
    // ─── Clusters (primary view) ─────────────────────────────────
    const [clusters, setClusters] = useState<DocCluster[]>([]);
    const [clusterLoading, setClusterLoading] = useState(false);
    const [initialized, setInitialized] = useState(false);
    const [expandedClusters, setExpandedClusters] = useState<Set<number>>(new Set());
    const [clusterSummaries, setClusterSummaries] = useState<Record<number, string>>({});
    const [summaryLoadingId, setSummaryLoadingId] = useState<number | null>(null);

    // ─── Custom organization (reassignment overrides) ────────────
    const [reassignments, setReassignments] = useState<Record<string, number>>({});
    const [movingDocId, setMovingDocId] = useState<string | null>(null);

    // ─── Detail modal ────────────────────────────────────────────
    const [detail, setDetail] = useState<DocDetail | null>(null);
    const [docSummary, setDocSummary] = useState<string | null>(null);
    const [docSummaryLoading, setDocSummaryLoading] = useState(false);

    // ─── Diagram toggle ──────────────────────────────────────────
    const [showDiagram, setShowDiagram] = useState(false);

    // ─── Duplicates ──────────────────────────────────────────────
    const [duplicates, setDuplicates] = useState<DuplicatePair[]>([]);
    const [dupLoading, setDupLoading] = useState(false);
    const [dupChecked, setDupChecked] = useState(false);

    // ─── Auto-load clusters on mount ─────────────────────────────
    const loadClusters = useCallback(async () => {
        setClusterLoading(true);
        try {
            const data = await api.clusterDocuments();
            setClusters(data.clusters);
            setExpandedClusters(new Set(data.clusters.map((c) => c.cluster_id)));
            setReassignments({});
            setClusterSummaries({});
        } catch {
            setClusters([]);
        }
        setClusterLoading(false);
        setInitialized(true);
    }, []);

    useEffect(() => {
        if (documents.length > 0 && !initialized) loadClusters();
    }, [documents, initialized, loadClusters]);

    // ─── Apply reassignments to get effective clusters ───────────
    const effectiveClusters = useMemo(() => {
        if (Object.keys(reassignments).length === 0) return clusters;
        const clusterMap = new Map<number, DocCluster>();
        for (const c of clusters) {
            clusterMap.set(c.cluster_id, { ...c, documents: c.documents.filter((d) => reassignments[d.doc_id] === undefined) });
        }
        for (const [docId, targetClusterId] of Object.entries(reassignments)) {
            const doc = clusters.flatMap((c) => c.documents).find((d) => d.doc_id === docId);
            if (doc && clusterMap.has(targetClusterId)) {
                clusterMap.get(targetClusterId)!.documents.push(doc);
            }
        }
        return Array.from(clusterMap.values()).filter((c) => c.documents.length > 0);
    }, [clusters, reassignments]);

    const totalDocs = documents.length;
    const maxClusterSize = Math.max(...effectiveClusters.map((c) => c.documents.length), 1);

    // ─── Actions ─────────────────────────────────────────────────
    function toggleCluster(id: number) {
        setExpandedClusters((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    }

    function expandAll() { setExpandedClusters(new Set(effectiveClusters.map((c) => c.cluster_id))); }
    function collapseAll() { setExpandedClusters(new Set()); }

    async function viewDoc(docId: string) {
        setDocSummary(null);
        try { setDetail(await api.getDocument(docId)); } catch { /* ignore */ }
    }

    async function summarizeDoc(docId: string) {
        setDocSummaryLoading(true);
        setDocSummary(null);
        try { setDocSummary(await api.summarizeDocument(docId)); } catch { /* ignore */ }
        setDocSummaryLoading(false);
    }

    async function summarizeCluster(cluster: DocCluster) {
        setSummaryLoadingId(cluster.cluster_id);
        try {
            const docNames = cluster.documents.map((d) => d.title || d.filename).join(", ");
            const kwList = cluster.keywords?.join(", ") || "";
            const prompt = `Genera un resumen breve (2-3 oraciones) del siguiente grupo de documentos llamado "${cluster.label}". Documentos: ${docNames}. Palabras clave del grupo: ${kwList}. Describe de qué trata este grupo temáticamente.`;
            const res = await api.agentAsk(prompt, `cluster-summary-${cluster.cluster_id}`);
            setClusterSummaries((prev) => ({ ...prev, [cluster.cluster_id]: res.answer }));
        } catch {
            setClusterSummaries((prev) => ({ ...prev, [cluster.cluster_id]: "No se pudo generar el resumen." }));
        }
        setSummaryLoadingId(null);
    }

    function moveDoc(docId: string, targetClusterId: number) {
        setReassignments((prev) => ({ ...prev, [docId]: targetClusterId }));
        setMovingDocId(null);
    }

    async function loadDuplicates() {
        setDupLoading(true);
        setDupChecked(true);
        try { setDuplicates(await api.findDuplicates()); } catch { setDuplicates([]); }
        setDupLoading(false);
    }

    // ─── Loading state ───────────────────────────────────────────
    if (clusterLoading && !initialized) {
        return (
            <section className="fade-in">
                <div className="max-w-6xl mx-auto">
                    <div className="flex items-center justify-center py-16 gap-3">
                        <svg className="w-5 h-5 animate-spin text-brand-500" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        <span className="text-sm text-ink-2">Organizando documentos por temas...</span>
                    </div>
                </div>
            </section>
        );
    }

    return (
        <section className="fade-in">
            <div className="max-w-6xl mx-auto">
                {/* ─── Header ──────────────────────────────────────── */}
                <div className="flex items-center justify-between mb-2">
                    <h2 className="text-lg font-semibold">Organización de documentos</h2>
                    <span className="text-sm text-ink-3">{totalDocs} documentos · {effectiveClusters.length} carpetas</span>
                </div>
                <p className="text-sm text-ink-3 mb-5">
                    Los documentos se agrupan automáticamente por similitud temática. Puedes explorar cada carpeta, generar resúmenes y reorganizar.
                </p>

                {/* ─── Toolbar ──────────────────────────────────────── */}
                <div className="flex flex-wrap items-center gap-2 mb-5">
                    <button onClick={loadClusters} disabled={clusterLoading}
                        className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-brand-700 bg-brand-50 border border-brand-200 rounded-lg hover:bg-brand-100 disabled:opacity-50 transition-colors">
                        <svg className={`w-4 h-4 ${clusterLoading ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        {clusterLoading ? "Reagrupando..." : "Reagrupar"}
                    </button>
                    <button onClick={expandAll} className="text-xs text-ink-2 hover:text-ink-0 px-2 py-2 transition-colors">Expandir todo</button>
                    <button onClick={collapseAll} className="text-xs text-ink-2 hover:text-ink-0 px-2 py-2 transition-colors">Colapsar todo</button>
                    <button onClick={() => setShowDiagram((p) => !p)}
                        className={`inline-flex items-center gap-1.5 text-xs px-2 py-2 transition-colors ${showDiagram ? "text-brand-700 font-medium" : "text-ink-2 hover:text-ink-0"}`}>
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                        </svg>
                        {showDiagram ? "Ocultar diagrama" : "Ver diagrama"}
                    </button>
                    {Object.keys(reassignments).length > 0 && (
                        <button onClick={() => setReassignments({})}
                            className="text-xs text-amber-700 hover:text-amber-800 px-2 py-2 transition-colors">
                            ↩ Deshacer reorganización ({Object.keys(reassignments).length} movidos)
                        </button>
                    )}
                    <div className="flex-1" />
                    <button onClick={loadDuplicates} disabled={dupLoading}
                        className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-lg hover:bg-amber-100 disabled:opacity-50 transition-colors">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-4 10h6a2 2 0 002-2v-8a2 2 0 00-2-2h-6a2 2 0 00-2 2v8a2 2 0 002 2z" />
                        </svg>
                        {dupLoading ? "Analizando..." : "Detectar duplicados"}
                    </button>
                </div>

                {/* ─── Cluster overview bar ─────────────────────── */}
                {effectiveClusters.length > 0 && (
                    <div className="flex items-center gap-0.5 mb-5 h-3 rounded-full overflow-hidden bg-surface-2">
                        {effectiveClusters.map((cluster) => {
                            const c = CLUSTER_COLORS[cluster.cluster_id % CLUSTER_COLORS.length];
                            const pct = (cluster.documents.length / totalDocs) * 100;
                            return (
                                <div key={cluster.cluster_id}
                                    className={`${c.bar} h-full transition-all cursor-pointer hover:opacity-80`}
                                    style={{ width: `${pct}%` }}
                                    title={`${cluster.label}: ${cluster.documents.length} docs (${pct.toFixed(0)}%)`}
                                    onClick={() => {
                                        setExpandedClusters(new Set([cluster.cluster_id]));
                                        document.getElementById(`cluster-${cluster.cluster_id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
                                    }}
                                />
                            );
                        })}
                    </div>
                )}

                {/* ─── Folder structure diagram ────────────────── */}
                {showDiagram && effectiveClusters.length > 0 && (
                    <div className="mb-6 bg-white border border-surface-3 rounded-xl overflow-hidden shadow-sm fade-in">
                        <div className="px-5 py-3 border-b border-surface-3 bg-surface-1 flex items-center gap-2">
                            <svg className="w-4 h-4 text-brand-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                    d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                            </svg>
                            <span className="text-sm font-semibold text-ink-0">Estructura de carpetas</span>
                            <span className="text-xs text-ink-3 ml-auto">{totalDocs} documentos · {effectiveClusters.length} carpetas</span>
                        </div>
                        <div className="px-5 py-4 font-mono text-sm">
                            {/* Root */}
                            <div className="flex items-center gap-2 text-brand-700 font-semibold mb-1">
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                        d="M5 19a2 2 0 01-2-2V7a2 2 0 012-2h4l2 2h4a2 2 0 012 2v1M5 19h14a2 2 0 002-2v-5a2 2 0 00-2-2H9a2 2 0 00-2 2v5a2 2 0 01-2 2z" />
                                </svg>
                                <span>DocumentWho/</span>
                            </div>
                            {effectiveClusters.map((cluster, ci) => {
                                const c = CLUSTER_COLORS[cluster.cluster_id % CLUSTER_COLORS.length];
                                const isLast = ci === effectiveClusters.length - 1;
                                return (
                                    <div key={cluster.cluster_id}>
                                        {/* Cluster folder line */}
                                        <div className="flex items-center gap-0 ml-2">
                                            <span className="text-ink-3 select-none w-5 text-center shrink-0">
                                                {isLast ? "└" : "├"}
                                            </span>
                                            <span className="text-ink-3 select-none shrink-0">── </span>
                                            <svg className={`w-3.5 h-3.5 ${c.icon} shrink-0 mr-1`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                    d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                                            </svg>
                                            <span className={`${c.text} font-semibold`}>{cluster.label}/</span>
                                            <span className="text-ink-3 text-xs ml-2 font-sans">
                                                ({cluster.documents.length} doc{cluster.documents.length !== 1 ? "s" : ""})
                                            </span>
                                            {cluster.categories && cluster.categories.length > 0 && (
                                                <span className="text-ink-3 text-[10px] ml-2 font-sans opacity-60">
                                                    [{cluster.categories.join(", ")}]
                                                </span>
                                            )}
                                        </div>
                                        {/* Documents inside cluster */}
                                        {cluster.documents.map((doc, di) => {
                                            const isLastDoc = di === cluster.documents.length - 1;
                                            return (
                                                <div key={doc.doc_id} className="flex items-center gap-0 ml-2 group/tree">
                                                    <span className="text-ink-3 select-none w-5 text-center shrink-0">
                                                        {isLast ? " " : "│"}
                                                    </span>
                                                    <span className="text-ink-3 select-none w-5 text-center shrink-0">
                                                        {isLastDoc ? "└" : "├"}
                                                    </span>
                                                    <span className="text-ink-3 select-none shrink-0">── </span>
                                                    <svg className="w-3 h-3 text-ink-3 shrink-0 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                                    </svg>
                                                    <span className="text-ink-1 truncate max-w-xs">{doc.title || doc.filename}</span>
                                                    <span className={`text-[10px] ml-2 px-1.5 py-0 rounded font-sans ${typeColor(doc.doc_type)}`}>{doc.doc_type}</span>
                                                    <button onClick={() => viewDoc(doc.doc_id)}
                                                        className="opacity-0 group-hover/tree:opacity-100 text-[10px] text-brand-600 hover:text-brand-700 font-sans font-medium ml-2 transition-opacity">
                                                        ver
                                                    </button>
                                                </div>
                                            );
                                        })}
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}

                {/* ─── Folder cards ────────────────────────────────── */}
                <div className="space-y-4">
                    {effectiveClusters.map((cluster) => {
                        const c = CLUSTER_COLORS[cluster.cluster_id % CLUSTER_COLORS.length];
                        const isOpen = expandedClusters.has(cluster.cluster_id);
                        const summary = clusterSummaries[cluster.cluster_id];
                        const isSummarizing = summaryLoadingId === cluster.cluster_id;
                        const sizeBar = (cluster.documents.length / maxClusterSize) * 100;

                        return (
                            <div key={cluster.cluster_id} id={`cluster-${cluster.cluster_id}`}
                                className={`${c.bg} border ${c.border} rounded-xl overflow-hidden transition-shadow ${isOpen ? "shadow-sm" : ""}`}>
                                {/* Folder header */}
                                <button onClick={() => toggleCluster(cluster.cluster_id)}
                                    className="w-full flex items-center gap-3 px-5 py-4 text-left group">
                                    <svg className={`w-4 h-4 ${c.text} shrink-0 transition-transform duration-200 ${isOpen ? "rotate-90" : ""}`}
                                        fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                    </svg>
                                    <svg className={`w-5 h-5 ${c.icon} shrink-0`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                            d={isOpen
                                                ? "M5 19a2 2 0 01-2-2V7a2 2 0 012-2h4l2 2h4a2 2 0 012 2v1M5 19h14a2 2 0 002-2v-5a2 2 0 00-2-2H9a2 2 0 00-2 2v5a2 2 0 01-2 2z"
                                                : "M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
                                            } />
                                    </svg>
                                    <div className="flex-1 min-w-0">
                                        <span className={`text-sm font-semibold ${c.text}`}>{cluster.label}</span>
                                        {cluster.keywords && cluster.keywords.length > 0 && (
                                            <div className="flex flex-wrap gap-1 mt-1">
                                                {cluster.keywords.slice(0, 5).map((kw) => (
                                                    <span key={kw} className={`text-[10px] px-1.5 py-0.5 rounded ${c.badge} opacity-70`}>{kw}</span>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                    <div className="flex items-center gap-3 shrink-0">
                                        <div className="hidden sm:flex items-center gap-2 w-24">
                                            <div className="flex-1 bg-white/50 rounded-full h-1.5">
                                                <div className={`${c.bar} h-1.5 rounded-full transition-all`} style={{ width: `${sizeBar}%` }} />
                                            </div>
                                        </div>
                                        <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${c.badge}`}>
                                            {cluster.documents.length} doc{cluster.documents.length !== 1 ? "s" : ""}
                                        </span>
                                    </div>
                                </button>

                                {/* Expanded content */}
                                {isOpen && (
                                    <div className="px-5 pb-4">
                                        {/* Summary */}
                                        <div className="mb-3 flex items-start gap-2">
                                            {summary ? (
                                                <div className="flex-1 text-sm text-ink-1 bg-white/60 rounded-lg px-4 py-3 leading-relaxed">{summary}</div>
                                            ) : (
                                                <button onClick={(e) => { e.stopPropagation(); summarizeCluster(cluster); }}
                                                    disabled={isSummarizing}
                                                    className={`inline-flex items-center gap-1.5 text-xs font-medium ${c.text} hover:opacity-80 disabled:opacity-50 transition-opacity`}>
                                                    {isSummarizing ? (
                                                        <><svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                                                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                                        </svg>Generando resumen...</>
                                                    ) : (
                                                        <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                                        </svg>Generar resumen del grupo</>
                                                    )}
                                                </button>
                                            )}
                                        </div>

                                        {/* Categories */}
                                        {cluster.categories && cluster.categories.length > 0 && (
                                            <div className="flex flex-wrap gap-1 mb-3">
                                                {cluster.categories.map((cat) => (
                                                    <span key={cat} className="text-[10px] px-2 py-0.5 rounded-full bg-white/60 text-ink-2 border border-white/80">{cat}</span>
                                                ))}
                                            </div>
                                        )}

                                        {/* Documents list */}
                                        <div className="space-y-1.5">
                                            {cluster.documents.map((doc) => (
                                                <div key={doc.doc_id}
                                                    className="flex items-center gap-3 px-4 py-2.5 bg-white/70 hover:bg-white rounded-lg transition-colors group/doc">
                                                    <svg className="w-4 h-4 text-ink-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                                    </svg>
                                                    <span className="text-sm text-ink-0 flex-1 truncate">{doc.title || doc.filename}</span>
                                                    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${typeColor(doc.doc_type)}`}>{doc.doc_type}</span>
                                                    {doc.category && <span className="hidden sm:inline text-xs text-ink-3">{doc.category}</span>}

                                                    {/* Move button */}
                                                    <div className="relative">
                                                        {movingDocId === doc.doc_id ? (
                                                            <div className="absolute right-0 top-full mt-1 z-20 bg-white border border-surface-3 rounded-lg shadow-lg py-1 min-w-[180px]">
                                                                <div className="px-3 py-1.5 text-[10px] font-medium text-ink-3 uppercase tracking-wider">Mover a...</div>
                                                                {effectiveClusters.filter((tc) => tc.cluster_id !== cluster.cluster_id).map((tc) => {
                                                                    const tc_c = CLUSTER_COLORS[tc.cluster_id % CLUSTER_COLORS.length];
                                                                    return (
                                                                        <button key={tc.cluster_id}
                                                                            onClick={(e) => { e.stopPropagation(); moveDoc(doc.doc_id, tc.cluster_id); }}
                                                                            className="w-full text-left px-3 py-1.5 text-sm hover:bg-surface-1 transition-colors flex items-center gap-2">
                                                                            <span className={`w-2 h-2 rounded-full ${tc_c.bar}`} />
                                                                            {tc.label}
                                                                        </button>
                                                                    );
                                                                })}
                                                                <button onClick={() => setMovingDocId(null)}
                                                                    className="w-full text-left px-3 py-1.5 text-xs text-ink-3 hover:bg-surface-1 transition-colors border-t border-surface-3 mt-1">
                                                                    Cancelar
                                                                </button>
                                                            </div>
                                                        ) : (
                                                            <button onClick={(e) => { e.stopPropagation(); setMovingDocId(doc.doc_id); }}
                                                                className="opacity-0 group-hover/doc:opacity-100 text-xs text-ink-3 hover:text-ink-0 p-1 transition-all"
                                                                title="Mover a otra carpeta">
                                                                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                                        d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
                                                                </svg>
                                                            </button>
                                                        )}
                                                    </div>

                                                    <button onClick={() => viewDoc(doc.doc_id)}
                                                        className="text-xs text-brand-600 hover:text-brand-700 font-medium shrink-0">Ver</button>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>

                {/* ─── Empty state ──────────────────────────────────── */}
                {effectiveClusters.length === 0 && !clusterLoading && initialized && (
                    <div className="text-center py-12 bg-white border border-surface-3 rounded-xl">
                        <svg className="w-12 h-12 text-ink-3 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                                d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                        </svg>
                        <p className="text-sm text-ink-2">No hay documentos para organizar.</p>
                        <p className="text-xs text-ink-3 mt-1">Sube documentos para verlos agrupados automáticamente.</p>
                    </div>
                )}

                {/* ─── Duplicates ──────────────────────────────────── */}
                {(dupChecked || duplicates.length > 0) && (
                    <div className="mt-6">
                        <h3 className="text-sm font-semibold text-ink-0 flex items-center gap-2 mb-3">
                            <svg className="w-4 h-4 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                    d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-4 10h6a2 2 0 002-2v-8a2 2 0 00-2-2h-6a2 2 0 00-2 2v8a2 2 0 002 2z" />
                            </svg>
                            Documentos duplicados
                        </h3>
                        {dupChecked && duplicates.length === 0 && !dupLoading && (
                            <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-3">
                                No se encontraron documentos near-duplicados (umbral 85%).
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
                )}

                {/* ─── Document detail modal ──────────────────────── */}
                {detail && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
                        onClick={(e) => { if (e.target === e.currentTarget) { setDetail(null); setMovingDocId(null); } }}>
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
                                <div>
                                    <div className="flex items-center justify-between mb-2">
                                        <h4 className="text-xs font-medium text-ink-3 uppercase tracking-wider">Resumen</h4>
                                        <button onClick={() => summarizeDoc(detail.doc_id)} disabled={docSummaryLoading}
                                            className="text-xs text-brand-600 hover:text-brand-700 font-medium disabled:opacity-50">
                                            {docSummaryLoading ? "Generando..." : "Generar resumen"}
                                        </button>
                                    </div>
                                    {docSummary && <p className="text-sm text-ink-1 leading-relaxed bg-surface-1 rounded-lg p-3">{docSummary}</p>}
                                </div>
                                {(detail.persons?.length > 0 || detail.organizations?.length > 0) && (
                                    <div>
                                        <h4 className="text-xs font-medium text-ink-3 uppercase tracking-wider mb-2">Entidades</h4>
                                        <div className="flex flex-wrap gap-1">
                                            {detail.persons?.map((p) => <span key={p} className="px-2 py-0.5 rounded text-xs bg-green-50 text-green-700">{p}</span>)}
                                            {detail.organizations?.map((o) => <span key={o} className="px-2 py-0.5 rounded text-xs bg-blue-50 text-blue-700">{o}</span>)}
                                        </div>
                                    </div>
                                )}
                                {detail.keywords?.length > 0 && (
                                    <div>
                                        <h4 className="text-xs font-medium text-ink-3 uppercase tracking-wider mb-2">Palabras clave</h4>
                                        <div className="flex flex-wrap gap-1">
                                            {detail.keywords.map((k) => <span key={k} className="px-2 py-0.5 rounded text-xs bg-surface-2 text-ink-2">{k}</span>)}
                                        </div>
                                    </div>
                                )}
                                {detail.dates?.length > 0 && (
                                    <div>
                                        <h4 className="text-xs font-medium text-ink-3 uppercase tracking-wider mb-2">Fechas</h4>
                                        <div className="flex flex-wrap gap-1">
                                            {detail.dates.map((d) => <span key={d} className="px-2 py-0.5 rounded text-xs bg-indigo-50 text-indigo-700">{d}</span>)}
                                        </div>
                                    </div>
                                )}
                                {detail.chunks?.length > 0 && (
                                    <div>
                                        <h4 className="text-xs font-medium text-ink-3 uppercase tracking-wider mb-2">Fragmentos ({detail.chunks.length})</h4>
                                        <div className="space-y-2">
                                            {detail.chunks.map((ch, i) => (
                                                <div key={ch.chunk_id} className="bg-surface-1 rounded-lg p-3">
                                                    <div className="text-[10px] font-mono text-ink-3 mb-1">#{i + 1}{ch.section ? ` — ${ch.section}` : ""}</div>
                                                    <p className="text-sm text-ink-1 leading-relaxed whitespace-pre-wrap line-clamp-4">{ch.text}</p>
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
