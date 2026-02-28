"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import * as api from "@/lib/api";
import type { DocListItem, DocDetail, DuplicatePair, DocCluster } from "@/lib/types";
import { typeColor } from "@/lib/utils";

interface Props {
    documents: DocListItem[];
}

// ─── Cluster colors (rotate) ────────────────────────────────────
const CC = [
    { bg: "bg-blue-50", border: "border-blue-200", text: "text-blue-700", badge: "bg-blue-100 text-blue-700", icon: "text-blue-500", bar: "bg-blue-400", line: "border-blue-300" },
    { bg: "bg-emerald-50", border: "border-emerald-200", text: "text-emerald-700", badge: "bg-emerald-100 text-emerald-700", icon: "text-emerald-500", bar: "bg-emerald-400", line: "border-emerald-300" },
    { bg: "bg-violet-50", border: "border-violet-200", text: "text-violet-700", badge: "bg-violet-100 text-violet-700", icon: "text-violet-500", bar: "bg-violet-400", line: "border-violet-300" },
    { bg: "bg-amber-50", border: "border-amber-200", text: "text-amber-700", badge: "bg-amber-100 text-amber-700", icon: "text-amber-500", bar: "bg-amber-400", line: "border-amber-300" },
    { bg: "bg-rose-50", border: "border-rose-200", text: "text-rose-700", badge: "bg-rose-100 text-rose-700", icon: "text-rose-500", bar: "bg-rose-400", line: "border-rose-300" },
    { bg: "bg-cyan-50", border: "border-cyan-200", text: "text-cyan-700", badge: "bg-cyan-100 text-cyan-700", icon: "text-cyan-500", bar: "bg-cyan-400", line: "border-cyan-300" },
    { bg: "bg-fuchsia-50", border: "border-fuchsia-200", text: "text-fuchsia-700", badge: "bg-fuchsia-100 text-fuchsia-700", icon: "text-fuchsia-500", bar: "bg-fuchsia-400", line: "border-fuchsia-300" },
    { bg: "bg-lime-50", border: "border-lime-200", text: "text-lime-700", badge: "bg-lime-100 text-lime-700", icon: "text-lime-500", bar: "bg-lime-400", line: "border-lime-300" },
];

type ViewMode = "tree" | "folders";

export function DocumentsTab({ documents }: Props) {
    const [clusters, setClusters] = useState<DocCluster[]>([]);
    const [clusterLoading, setClusterLoading] = useState(false);
    const [initialized, setInitialized] = useState(false);
    const [expandedClusters, setExpandedClusters] = useState<Set<string>>(new Set());
    const [clusterSummaries, setClusterSummaries] = useState<Record<string, string>>({});
    const [summaryLoadingId, setSummaryLoadingId] = useState<string | null>(null);

    const [viewMode, setViewMode] = useState<ViewMode>("tree");

    // Detail modal
    const [detail, setDetail] = useState<DocDetail | null>(null);
    const [docSummary, setDocSummary] = useState<string | null>(null);
    const [docSummaryLoading, setDocSummaryLoading] = useState(false);

    // Duplicates
    const [duplicates, setDuplicates] = useState<DuplicatePair[]>([]);
    const [dupLoading, setDupLoading] = useState(false);
    const [dupChecked, setDupChecked] = useState(false);

    // ─── Auto-load clusters on mount ─────────────────────────────
    const loadClusters = useCallback(async () => {
        setClusterLoading(true);
        try {
            const data = await api.clusterDocuments();
            setClusters(data.clusters);
            // Expand all parent clusters by default
            const keys = new Set<string>();
            data.clusters.forEach((c) => {
                keys.add(`p-${c.cluster_id}`);
                c.children?.forEach((ch) => keys.add(`c-${c.cluster_id}-${ch.cluster_id}`));
            });
            setExpandedClusters(keys);
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

    const totalDocs = documents.length;

    // ─── Actions ─────────────────────────────────────────────────
    function toggleNode(key: string) {
        setExpandedClusters((prev) => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key); else next.add(key);
            return next;
        });
    }

    function expandAll() {
        const keys = new Set<string>();
        clusters.forEach((c) => {
            keys.add(`p-${c.cluster_id}`);
            c.children?.forEach((ch) => keys.add(`c-${c.cluster_id}-${ch.cluster_id}`));
        });
        setExpandedClusters(keys);
    }
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

    async function summarizeCluster(cluster: DocCluster, key: string) {
        setSummaryLoadingId(key);
        try {
            const docNames = cluster.documents.map((d) => d.title || d.filename).join(", ");
            const kwList = cluster.keywords?.join(", ") || "";
            const prompt = `Genera un resumen breve (2-3 oraciones) del siguiente grupo de documentos llamado "${cluster.label}". Documentos: ${docNames}. Palabras clave del grupo: ${kwList}. Describe de qué trata este grupo temáticamente.`;
            const res = await api.agentAsk(prompt, `cluster-summary-${key}`);
            setClusterSummaries((prev) => ({ ...prev, [key]: res.answer }));
        } catch {
            setClusterSummaries((prev) => ({ ...prev, [key]: "No se pudo generar el resumen." }));
        }
        setSummaryLoadingId(null);
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
                {/* ─── Header ──────────────────────────────────── */}
                <div className="flex items-center justify-between mb-2">
                    <h2 className="text-lg font-semibold">Organización de documentos</h2>
                    <span className="text-sm text-ink-3">{totalDocs} documentos · {clusters.length} temas</span>
                </div>
                <p className="text-sm text-ink-3 mb-5">
                    Los documentos se agrupan automáticamente por similitud temática en carpetas y subcarpetas.
                </p>

                {/* ─── Toolbar ──────────────────────────────────── */}
                <div className="flex flex-wrap items-center gap-2 mb-5">
                    <button onClick={loadClusters} disabled={clusterLoading}
                        className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-brand-700 bg-brand-50 border border-brand-200 rounded-lg hover:bg-brand-100 disabled:opacity-50 transition-colors">
                        <svg className={`w-4 h-4 ${clusterLoading ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        {clusterLoading ? "Reagrupando..." : "Reagrupar"}
                    </button>

                    {/* View mode toggle */}
                    <div className="flex items-center border border-surface-3 rounded-lg overflow-hidden">
                        <button onClick={() => setViewMode("tree")}
                            className={`px-3 py-2 text-xs font-medium transition-colors ${viewMode === "tree" ? "bg-brand-50 text-brand-700" : "text-ink-3 hover:text-ink-0"}`}>
                            Diagrama
                        </button>
                        <button onClick={() => setViewMode("folders")}
                            className={`px-3 py-2 text-xs font-medium transition-colors ${viewMode === "folders" ? "bg-brand-50 text-brand-700" : "text-ink-3 hover:text-ink-0"}`}>
                            Carpetas
                        </button>
                    </div>

                    <button onClick={expandAll} className="text-xs text-ink-2 hover:text-ink-0 px-2 py-2 transition-colors">Expandir</button>
                    <button onClick={collapseAll} className="text-xs text-ink-2 hover:text-ink-0 px-2 py-2 transition-colors">Colapsar</button>

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

                {/* ─── Distribution bar ────────────────────────── */}
                {clusters.length > 0 && (
                    <div className="flex items-center gap-0.5 mb-5 h-3 rounded-full overflow-hidden bg-surface-2">
                        {clusters.map((cluster) => {
                            const c = CC[cluster.cluster_id % CC.length];
                            const pct = (cluster.documents.length / totalDocs) * 100;
                            return (
                                <div key={cluster.cluster_id}
                                    className={`${c.bar} h-full transition-all cursor-pointer hover:opacity-80`}
                                    style={{ width: `${pct}%` }}
                                    title={`${cluster.label}: ${cluster.documents.length} docs (${pct.toFixed(0)}%)`}
                                    onClick={() => {
                                        const el = document.getElementById(`cluster-${cluster.cluster_id}`);
                                        el?.scrollIntoView({ behavior: "smooth", block: "start" });
                                    }}
                                />
                            );
                        })}
                    </div>
                )}

                {/* ═══ TREE DIAGRAM VIEW ═══════════════════════════ */}
                {viewMode === "tree" && clusters.length > 0 && (
                    <div className="bg-white border border-surface-3 rounded-xl overflow-hidden shadow-sm mb-6">
                        <div className="px-5 py-3 border-b border-surface-3 bg-surface-1 flex items-center gap-2">
                            <svg className="w-4 h-4 text-brand-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                    d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                            </svg>
                            <span className="text-sm font-semibold text-ink-0">Estructura jerárquica</span>
                            <span className="text-xs text-ink-3 ml-auto">{totalDocs} documentos · {clusters.length} temas</span>
                        </div>
                        <div className="px-5 py-4 text-sm">
                            {/* Root node */}
                            <div className="flex items-center gap-2 font-semibold text-brand-700 mb-2">
                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                        d="M5 19a2 2 0 01-2-2V7a2 2 0 012-2h4l2 2h4a2 2 0 012 2v1M5 19h14a2 2 0 002-2v-5a2 2 0 00-2-2H9a2 2 0 00-2 2v5a2 2 0 01-2 2z" />
                                </svg>
                                <span className="font-mono">DocumentWho/</span>
                                <span className="text-xs text-ink-3 font-normal font-sans ml-1">({totalDocs} docs)</span>
                            </div>

                            {clusters.map((cluster, ci) => {
                                const c = CC[cluster.cluster_id % CC.length];
                                const isLastCluster = ci === clusters.length - 1;
                                const pKey = `p-${cluster.cluster_id}`;
                                const pOpen = expandedClusters.has(pKey);
                                const children = cluster.children || [];
                                const hasChildren = children.length > 1 || (children.length === 1 && children[0].documents.length !== cluster.documents.length);

                                return (
                                    <div key={cluster.cluster_id} id={`cluster-${cluster.cluster_id}`}>
                                        {/* Parent cluster line */}
                                        <div className="flex items-center ml-3 group/pnode cursor-pointer" onClick={() => toggleNode(pKey)}>
                                            <span className="font-mono text-ink-3 w-5 text-center shrink-0 select-none">
                                                {isLastCluster ? "└" : "├"}
                                            </span>
                                            <span className="font-mono text-ink-3 shrink-0 select-none">── </span>
                                            {/* Expand arrow */}
                                            <svg className={`w-3 h-3 ${c.icon} shrink-0 mr-1 transition-transform ${pOpen ? "rotate-90" : ""}`}
                                                fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                            </svg>
                                            <svg className={`w-4 h-4 ${c.icon} shrink-0 mr-1.5`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                    d={pOpen
                                                        ? "M5 19a2 2 0 01-2-2V7a2 2 0 012-2h4l2 2h4a2 2 0 012 2v1M5 19h14a2 2 0 002-2v-5a2 2 0 00-2-2H9a2 2 0 00-2 2v5a2 2 0 01-2 2z"
                                                        : "M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
                                                    } />
                                            </svg>
                                            <span className={`font-semibold font-mono ${c.text}`}>{cluster.label}/</span>
                                            <span className={`text-xs ml-2 px-2 py-0.5 rounded-full font-sans ${c.badge}`}>
                                                {cluster.documents.length}
                                            </span>
                                            {cluster.categories && cluster.categories.length > 0 && (
                                                <span className="text-[10px] text-ink-3 ml-2 font-sans opacity-70 hidden sm:inline">
                                                    {cluster.categories.slice(0, 2).join(", ")}
                                                </span>
                                            )}
                                        </div>

                                        {/* Expanded: show children or direct docs */}
                                        {pOpen && (
                                            <div className="ml-3">
                                                {hasChildren ? (
                                                    // Sub-clusters
                                                    children.map((child, sci) => {
                                                        const isLastChild = sci === children.length - 1;
                                                        const cKey = `c-${cluster.cluster_id}-${child.cluster_id}`;
                                                        const cOpen = expandedClusters.has(cKey);
                                                        const subColor = CC[(cluster.cluster_id * 3 + child.cluster_id + 1) % CC.length];

                                                        return (
                                                            <div key={child.cluster_id}>
                                                                {/* Sub-cluster line */}
                                                                <div className="flex items-center group/snode cursor-pointer" onClick={() => toggleNode(cKey)}>
                                                                    <span className="font-mono text-ink-3 w-5 text-center shrink-0 select-none">
                                                                        {isLastCluster ? " " : "│"}
                                                                    </span>
                                                                    <span className="font-mono text-ink-3 w-5 text-center shrink-0 select-none">
                                                                        {isLastChild ? "└" : "├"}
                                                                    </span>
                                                                    <span className="font-mono text-ink-3 shrink-0 select-none">── </span>
                                                                    <svg className={`w-2.5 h-2.5 ${subColor.icon} shrink-0 mr-1 transition-transform ${cOpen ? "rotate-90" : ""}`}
                                                                        fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                                                    </svg>
                                                                    <svg className={`w-3.5 h-3.5 ${subColor.icon} shrink-0 mr-1`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                                            d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                                                                    </svg>
                                                                    <span className={`font-medium font-mono text-[13px] ${subColor.text}`}>{child.label}/</span>
                                                                    <span className="text-xs text-ink-3 ml-1.5 font-sans">
                                                                        ({child.documents.length})
                                                                    </span>
                                                                </div>

                                                                {/* Sub-cluster documents */}
                                                                {cOpen && child.documents.map((doc, di) => {
                                                                    const isLastDoc = di === child.documents.length - 1;
                                                                    return (
                                                                        <div key={doc.doc_id} className="flex items-center group/doc">
                                                                            <span className="font-mono text-ink-3 w-5 text-center shrink-0 select-none">
                                                                                {isLastCluster ? " " : "│"}
                                                                            </span>
                                                                            <span className="font-mono text-ink-3 w-5 text-center shrink-0 select-none">
                                                                                {isLastChild ? " " : "│"}
                                                                            </span>
                                                                            <span className="font-mono text-ink-3 w-5 text-center shrink-0 select-none">
                                                                                {isLastDoc ? "└" : "├"}
                                                                            </span>
                                                                            <span className="font-mono text-ink-3 shrink-0 select-none">── </span>
                                                                            <svg className="w-3 h-3 text-ink-3 shrink-0 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                                                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                                                            </svg>
                                                                            <span className="text-ink-1 truncate max-w-xs text-[13px]">{doc.title || doc.filename}</span>
                                                                            <span className={`text-[10px] ml-1.5 px-1.5 py-0 rounded ${typeColor(doc.doc_type)}`}>{doc.doc_type}</span>
                                                                            <button onClick={(e) => { e.stopPropagation(); viewDoc(doc.doc_id); }}
                                                                                className="opacity-0 group-hover/doc:opacity-100 text-[10px] text-brand-600 hover:text-brand-700 font-medium ml-2 transition-opacity">
                                                                                ver
                                                                            </button>
                                                                        </div>
                                                                    );
                                                                })}
                                                            </div>
                                                        );
                                                    })
                                                ) : (
                                                    // Direct documents (no sub-clusters)
                                                    cluster.documents.map((doc, di) => {
                                                        const isLastDoc = di === cluster.documents.length - 1;
                                                        return (
                                                            <div key={doc.doc_id} className="flex items-center group/doc">
                                                                <span className="font-mono text-ink-3 w-5 text-center shrink-0 select-none">
                                                                    {isLastCluster ? " " : "│"}
                                                                </span>
                                                                <span className="font-mono text-ink-3 w-5 text-center shrink-0 select-none">
                                                                    {isLastDoc ? "└" : "├"}
                                                                </span>
                                                                <span className="font-mono text-ink-3 shrink-0 select-none">── </span>
                                                                <svg className="w-3 h-3 text-ink-3 shrink-0 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                                        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                                                </svg>
                                                                <span className="text-ink-1 truncate max-w-xs text-[13px]">{doc.title || doc.filename}</span>
                                                                <span className={`text-[10px] ml-1.5 px-1.5 py-0 rounded ${typeColor(doc.doc_type)}`}>{doc.doc_type}</span>
                                                                <button onClick={(e) => { e.stopPropagation(); viewDoc(doc.doc_id); }}
                                                                    className="opacity-0 group-hover/doc:opacity-100 text-[10px] text-brand-600 hover:text-brand-700 font-medium ml-2 transition-opacity">
                                                                    ver
                                                                </button>
                                                            </div>
                                                        );
                                                    })
                                                )}
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}

                {/* ═══ FOLDER CARD VIEW ════════════════════════════ */}
                {viewMode === "folders" && (
                    <div className="space-y-4 mb-6">
                        {clusters.map((cluster) => {
                            const c = CC[cluster.cluster_id % CC.length];
                            const pKey = `p-${cluster.cluster_id}`;
                            const isOpen = expandedClusters.has(pKey);
                            const children = cluster.children || [];
                            const hasChildren = children.length > 1 || (children.length === 1 && children[0].documents.length !== cluster.documents.length);
                            const summary = clusterSummaries[pKey];
                            const isSummarizing = summaryLoadingId === pKey;
                            const maxSize = Math.max(...clusters.map((cl) => cl.documents.length), 1);
                            const sizeBar = (cluster.documents.length / maxSize) * 100;

                            return (
                                <div key={cluster.cluster_id} id={`cluster-${cluster.cluster_id}`}
                                    className={`${c.bg} border ${c.border} rounded-xl overflow-hidden transition-shadow ${isOpen ? "shadow-sm" : ""}`}>
                                    {/* Folder header */}
                                    <button onClick={() => toggleNode(pKey)}
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
                                                    <button onClick={(e) => { e.stopPropagation(); summarizeCluster(cluster, pKey); }}
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
                                                            </svg>Generar resumen</>
                                                        )}
                                                    </button>
                                                )}
                                            </div>

                                            {/* Sub-clusters as nested cards, or direct docs */}
                                            {hasChildren ? (
                                                <div className="space-y-3">
                                                    {children.map((child) => {
                                                        const cKey = `c-${cluster.cluster_id}-${child.cluster_id}`;
                                                        const cOpen = expandedClusters.has(cKey);
                                                        const subColor = CC[(cluster.cluster_id * 3 + child.cluster_id + 1) % CC.length];
                                                        return (
                                                            <div key={child.cluster_id}
                                                                className="bg-white/70 border border-white/80 rounded-lg overflow-hidden">
                                                                <button onClick={() => toggleNode(cKey)}
                                                                    className="w-full flex items-center gap-2 px-4 py-2.5 text-left">
                                                                    <svg className={`w-3 h-3 ${subColor.icon} shrink-0 transition-transform ${cOpen ? "rotate-90" : ""}`}
                                                                        fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                                                    </svg>
                                                                    <svg className={`w-4 h-4 ${subColor.icon} shrink-0`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                                            d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                                                                    </svg>
                                                                    <span className={`text-sm font-medium ${subColor.text}`}>{child.label}</span>
                                                                    <span className="text-xs text-ink-3 ml-auto">
                                                                        {child.documents.length} doc{child.documents.length !== 1 ? "s" : ""}
                                                                    </span>
                                                                </button>
                                                                {cOpen && (
                                                                    <div className="px-4 pb-3 space-y-1">
                                                                        {child.documents.map((doc) => (
                                                                            <DocRow key={doc.doc_id} doc={doc} onView={viewDoc} />
                                                                        ))}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        );
                                                    })}
                                                </div>
                                            ) : (
                                                <div className="space-y-1">
                                                    {cluster.documents.map((doc) => (
                                                        <DocRow key={doc.doc_id} doc={doc} onView={viewDoc} />
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}

                {/* ─── Empty state ──────────────────────────────── */}
                {clusters.length === 0 && !clusterLoading && initialized && (
                    <div className="text-center py-12 bg-white border border-surface-3 rounded-xl">
                        <svg className="w-12 h-12 text-ink-3 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                                d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                        </svg>
                        <p className="text-sm text-ink-2">No hay documentos para organizar.</p>
                        <p className="text-xs text-ink-3 mt-1">Sube documentos para verlos agrupados automáticamente.</p>
                    </div>
                )}

                {/* ─── Duplicates ──────────────────────────────── */}
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

                {/* ─── Document detail modal ──────────────────── */}
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

/* ─── Doc row component ─────────────────────────────────────────── */
function DocRow({ doc, onView }: { doc: DocListItem; onView: (id: string) => void }) {
    return (
        <div className="flex items-center gap-3 px-4 py-2.5 bg-white/70 hover:bg-white rounded-lg transition-colors group/doc cursor-pointer"
            onClick={() => onView(doc.doc_id)}>
            <svg className="w-4 h-4 text-ink-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <span className="text-sm text-ink-0 flex-1 truncate group-hover/doc:text-brand-700 transition-colors">{doc.title || doc.filename}</span>
            <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${typeColor(doc.doc_type)}`}>{doc.doc_type}</span>
            {doc.category && <span className="hidden sm:inline text-xs text-ink-3">{doc.category}</span>}
        </div>
    );
}
