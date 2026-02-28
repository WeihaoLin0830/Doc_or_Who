"use client";

import { useState, useMemo } from "react";
import * as api from "@/lib/api";
import type { DocListItem, DocDetail, DuplicatePair, DocCluster } from "@/lib/types";
import { typeColor } from "@/lib/utils";

interface Props {
    documents: DocListItem[];
}

type SortKey = "title" | "doc_type" | "category";
type SortDir = "asc" | "desc";
type ViewMode = "table" | "grid";

// ─── Cluster colors (rotate through) ────────────────────────────
const CLUSTER_COLORS = [
    { bg: "bg-blue-50", border: "border-blue-200", text: "text-blue-700", badge: "bg-blue-100 text-blue-700" },
    { bg: "bg-emerald-50", border: "border-emerald-200", text: "text-emerald-700", badge: "bg-emerald-100 text-emerald-700" },
    { bg: "bg-violet-50", border: "border-violet-200", text: "text-violet-700", badge: "bg-violet-100 text-violet-700" },
    { bg: "bg-amber-50", border: "border-amber-200", text: "text-amber-700", badge: "bg-amber-100 text-amber-700" },
    { bg: "bg-rose-50", border: "border-rose-200", text: "text-rose-700", badge: "bg-rose-100 text-rose-700" },
    { bg: "bg-cyan-50", border: "border-cyan-200", text: "text-cyan-700", badge: "bg-cyan-100 text-cyan-700" },
    { bg: "bg-fuchsia-50", border: "border-fuchsia-200", text: "text-fuchsia-700", badge: "bg-fuchsia-100 text-fuchsia-700" },
    { bg: "bg-lime-50", border: "border-lime-200", text: "text-lime-700", badge: "bg-lime-100 text-lime-700" },
];

export function DocumentsTab({ documents }: Props) {
    // ─── Detail modal state ──────────────────────────────────────
    const [detail, setDetail] = useState<DocDetail | null>(null);
    const [summary, setSummary] = useState<string | null>(null);
    const [summaryLoading, setSummaryLoading] = useState(false);

    // ─── Duplicates ──────────────────────────────────────────────
    const [duplicates, setDuplicates] = useState<DuplicatePair[]>([]);
    const [dupLoading, setDupLoading] = useState(false);
    const [dupChecked, setDupChecked] = useState(false);

    // ─── Filters & sorting ───────────────────────────────────────
    const [searchText, setSearchText] = useState("");
    const [filterType, setFilterType] = useState("");
    const [filterCategory, setFilterCategory] = useState("");
    const [sortKey, setSortKey] = useState<SortKey>("title");
    const [sortDir, setSortDir] = useState<SortDir>("asc");
    const [viewMode, setViewMode] = useState<ViewMode>("table");

    // ─── Clustering ──────────────────────────────────────────────
    const [clusters, setClusters] = useState<DocCluster[]>([]);
    const [clusterLoading, setClusterLoading] = useState(false);
    const [showClusters, setShowClusters] = useState(false);
    const [expandedClusters, setExpandedClusters] = useState<Set<number>>(new Set());

    // ─── Derived data ────────────────────────────────────────────
    const docTypes = useMemo(() => [...new Set(documents.map((d) => d.doc_type).filter(Boolean))].sort(), [documents]);
    const categories = useMemo(() => [...new Set(documents.map((d) => d.category).filter(Boolean))].sort(), [documents]);

    const filtered = useMemo(() => {
        let docs = [...documents];
        // Text search
        if (searchText.trim()) {
            const q = searchText.toLowerCase();
            docs = docs.filter(
                (d) =>
                    d.title?.toLowerCase().includes(q) ||
                    d.filename?.toLowerCase().includes(q) ||
                    d.doc_type?.toLowerCase().includes(q) ||
                    d.category?.toLowerCase().includes(q),
            );
        }
        // Type filter
        if (filterType) docs = docs.filter((d) => d.doc_type === filterType);
        // Category filter
        if (filterCategory) docs = docs.filter((d) => d.category === filterCategory);
        // Sort
        docs.sort((a, b) => {
            const va = (a[sortKey] || "").toLowerCase();
            const vb = (b[sortKey] || "").toLowerCase();
            return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
        });
        return docs;
    }, [documents, searchText, filterType, filterCategory, sortKey, sortDir]);

    // ─── Actions ─────────────────────────────────────────────────
    async function viewDoc(docId: string) {
        setSummary(null);
        try { setDetail(await api.getDocument(docId)); } catch { /* ignore */ }
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

    async function loadClusters() {
        setClusterLoading(true);
        try {
            const data = await api.clusterDocuments();
            setClusters(data.clusters);
            setShowClusters(true);
            // Expand all by default
            setExpandedClusters(new Set(data.clusters.map((c) => c.cluster_id)));
        } catch { setClusters([]); }
        setClusterLoading(false);
    }

    function toggleCluster(id: number) {
        setExpandedClusters((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    }

    function toggleSort(key: SortKey) {
        if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
        else { setSortKey(key); setSortDir("asc"); }
    }

    const sortIcon = (key: SortKey) =>
        sortKey !== key ? "↕" : sortDir === "asc" ? "↑" : "↓";

    const activeFilters = [filterType, filterCategory, searchText.trim()].filter(Boolean).length;

    return (
        <section className="fade-in">
            <div className="max-w-6xl mx-auto">
                {/* ─── Header ─────────────────────────────────────── */}
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold">Documentos indexados</h2>
                    <span className="text-sm text-ink-3">{filtered.length} de {documents.length} documentos</span>
                </div>

                {/* ─── Toolbar ─────────────────────────────────────── */}
                <div className="flex flex-wrap items-center gap-2 mb-4">
                    {/* Search */}
                    <div className="relative flex-1 min-w-[200px] max-w-sm">
                        <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                        </svg>
                        <input
                            type="text"
                            value={searchText}
                            onChange={(e) => setSearchText(e.target.value)}
                            placeholder="Buscar documentos..."
                            className="w-full pl-9 pr-3 py-2 text-sm border border-surface-3 rounded-lg bg-white outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 transition-all"
                        />
                    </div>

                    {/* Type filter */}
                    <select
                        value={filterType}
                        onChange={(e) => setFilterType(e.target.value)}
                        className="px-3 py-2 text-sm border border-surface-3 rounded-lg bg-white outline-none focus:border-brand-400 transition-colors"
                    >
                        <option value="">Todos los tipos</option>
                        {docTypes.map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>

                    {/* Category filter */}
                    <select
                        value={filterCategory}
                        onChange={(e) => setFilterCategory(e.target.value)}
                        className="px-3 py-2 text-sm border border-surface-3 rounded-lg bg-white outline-none focus:border-brand-400 transition-colors"
                    >
                        <option value="">Todas las categorías</option>
                        {categories.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>

                    {/* Clear filters */}
                    {activeFilters > 0 && (
                        <button
                            onClick={() => { setSearchText(""); setFilterType(""); setFilterCategory(""); }}
                            className="text-xs text-ink-3 hover:text-ink-0 px-2 py-2 transition-colors"
                        >
                            Limpiar filtros ({activeFilters})
                        </button>
                    )}

                    <div className="flex-1" />

                    {/* Cluster button */}
                    <button
                        onClick={() => showClusters ? setShowClusters(false) : loadClusters()}
                        disabled={clusterLoading}
                        className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-violet-700 bg-violet-50 border border-violet-200 rounded-lg hover:bg-violet-100 disabled:opacity-50 transition-colors"
                    >
                        <svg className={`w-4 h-4 ${clusterLoading ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                        </svg>
                        {clusterLoading ? "Agrupando..." : showClusters ? "Ocultar clusters" : "Auto-organizar"}
                    </button>

                    {/* View toggle */}
                    <div className="flex items-center border border-surface-3 rounded-lg overflow-hidden">
                        <button
                            onClick={() => setViewMode("table")}
                            className={`p-2 transition-colors ${viewMode === "table" ? "bg-brand-50 text-brand-600" : "text-ink-3 hover:text-ink-0"}`}
                            title="Vista tabla"
                        >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                            </svg>
                        </button>
                        <button
                            onClick={() => setViewMode("grid")}
                            className={`p-2 transition-colors ${viewMode === "grid" ? "bg-brand-50 text-brand-600" : "text-ink-3 hover:text-ink-0"}`}
                            title="Vista tarjetas"
                        >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                    d="M4 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1V5zm10 0a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM4 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1v-4zm10 0a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" />
                            </svg>
                        </button>
                    </div>
                </div>

                {/* ─── Cluster view ───────────────────────────────── */}
                {showClusters && clusters.length > 0 && (
                    <div className="mb-6 space-y-3">
                        <div className="flex items-center gap-2 mb-2">
                            <h3 className="text-sm font-semibold text-ink-0">Organización automática</h3>
                            <span className="text-xs text-ink-3">{clusters.length} grupos detectados</span>
                        </div>
                        {clusters.map((cluster) => {
                            const c = CLUSTER_COLORS[cluster.cluster_id % CLUSTER_COLORS.length];
                            const isOpen = expandedClusters.has(cluster.cluster_id);
                            return (
                                <div key={cluster.cluster_id} className={`${c.bg} border ${c.border} rounded-lg overflow-hidden`}>
                                    <button
                                        onClick={() => toggleCluster(cluster.cluster_id)}
                                        className="w-full flex items-center gap-3 px-4 py-3 text-left"
                                    >
                                        <svg className={`w-4 h-4 ${c.text} shrink-0 transition-transform ${isOpen ? "rotate-90" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                        </svg>
                                        <svg className={`w-5 h-5 ${c.text} shrink-0`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                                        </svg>
                                        <span className={`text-sm font-medium ${c.text}`}>{cluster.label}</span>
                                        <span className={`ml-auto text-xs px-2 py-0.5 rounded-full ${c.badge}`}>
                                            {cluster.documents.length} doc{cluster.documents.length !== 1 ? "s" : ""}
                                        </span>
                                    </button>
                                    {isOpen && (
                                        <div className="px-4 pb-3">
                                            <div className="space-y-1">
                                                {cluster.documents.map((doc) => (
                                                    <div key={doc.doc_id} className="flex items-center gap-3 px-3 py-2 bg-white/70 rounded-md">
                                                        <span className="text-sm text-ink-0 flex-1 truncate">{doc.title || doc.filename}</span>
                                                        <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${typeColor(doc.doc_type)}`}>{doc.doc_type}</span>
                                                        <button onClick={() => viewDoc(doc.doc_id)} className="text-xs text-brand-600 hover:text-brand-700 font-medium shrink-0">
                                                            Ver
                                                        </button>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}

                {/* ─── Table view ──────────────────────────────────── */}
                {!showClusters && viewMode === "table" && (
                    <div className="bg-white border border-surface-3 rounded-lg overflow-hidden">
                        <table className="w-full">
                            <thead>
                                <tr className="border-b border-surface-3 bg-surface-1">
                                    <th onClick={() => toggleSort("title")} className="text-left text-xs font-medium text-ink-2 uppercase tracking-wider px-4 py-3 cursor-pointer hover:text-ink-0 select-none">
                                        Documento {sortIcon("title")}
                                    </th>
                                    <th onClick={() => toggleSort("doc_type")} className="text-left text-xs font-medium text-ink-2 uppercase tracking-wider px-4 py-3 cursor-pointer hover:text-ink-0 select-none">
                                        Tipo {sortIcon("doc_type")}
                                    </th>
                                    <th onClick={() => toggleSort("category")} className="text-left text-xs font-medium text-ink-2 uppercase tracking-wider px-4 py-3 cursor-pointer hover:text-ink-0 select-none">
                                        Categoría {sortIcon("category")}
                                    </th>
                                    <th className="text-right text-xs font-medium text-ink-2 uppercase tracking-wider px-4 py-3">Acciones</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-surface-3">
                                {filtered.map((doc) => (
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
                                {filtered.length === 0 && (
                                    <tr>
                                        <td colSpan={4} className="px-4 py-8 text-center text-sm text-ink-3">
                                            No se encontraron documentos con los filtros seleccionados.
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                )}

                {/* ─── Grid view ──────────────────────────────────── */}
                {!showClusters && viewMode === "grid" && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                        {filtered.map((doc) => (
                            <div
                                key={doc.doc_id}
                                onClick={() => viewDoc(doc.doc_id)}
                                className="bg-white border border-surface-3 rounded-lg p-4 hover:shadow-md hover:border-brand-200 transition-all cursor-pointer group"
                            >
                                <div className="flex items-start justify-between gap-2 mb-2">
                                    <h3 className="text-sm font-medium text-ink-0 line-clamp-2 group-hover:text-brand-700 transition-colors">
                                        {doc.title || doc.filename}
                                    </h3>
                                    <span className={`shrink-0 inline-flex px-2 py-0.5 rounded text-xs font-medium ${typeColor(doc.doc_type)}`}>
                                        {doc.doc_type}
                                    </span>
                                </div>
                                <p className="text-xs text-ink-3 truncate">{doc.filename}</p>
                                {doc.category && (
                                    <span className="inline-flex mt-2 px-2 py-0.5 rounded-full text-xs bg-surface-2 text-ink-2">
                                        {doc.category}
                                    </span>
                                )}
                            </div>
                        ))}
                        {filtered.length === 0 && (
                            <div className="col-span-full text-center py-8 text-sm text-ink-3">
                                No se encontraron documentos con los filtros seleccionados.
                            </div>
                        )}
                    </div>
                )}

                {/* ─── Duplicates ──────────────────────────────────── */}
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

                {/* ─── Document detail modal ──────────────────────── */}
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

                                {/* Dates */}
                                {detail.dates?.length > 0 && (
                                    <div>
                                        <h4 className="text-xs font-medium text-ink-3 uppercase tracking-wider mb-2">Fechas</h4>
                                        <div className="flex flex-wrap gap-1">
                                            {detail.dates.map((d) => <span key={d} className="px-2 py-0.5 rounded text-xs bg-indigo-50 text-indigo-700">{d}</span>)}
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
