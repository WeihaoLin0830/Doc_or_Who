"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import * as api from "@/lib/api";
import type { DocListItem, DuplicatePair, DocCluster } from "@/lib/types";
import { typeColor } from "@/lib/utils";
import { DocumentModal } from "@/components/DocumentModal";

interface Props {
    documents: DocListItem[];
}

// ─── Cluster colors (rotate) ────────────────────────────────────
const CC = [
    { bg: "bg-blue-50", border: "border-blue-200", text: "text-blue-700", badge: "bg-blue-100 text-blue-700", icon: "text-blue-500", bar: "bg-blue-400", line: "border-blue-300", dropBg: "bg-blue-100" },
    { bg: "bg-emerald-50", border: "border-emerald-200", text: "text-emerald-700", badge: "bg-emerald-100 text-emerald-700", icon: "text-emerald-500", bar: "bg-emerald-400", line: "border-emerald-300", dropBg: "bg-emerald-100" },
    { bg: "bg-violet-50", border: "border-violet-200", text: "text-violet-700", badge: "bg-violet-100 text-violet-700", icon: "text-violet-500", bar: "bg-violet-400", line: "border-violet-300", dropBg: "bg-violet-100" },
    { bg: "bg-amber-50", border: "border-amber-200", text: "text-amber-700", badge: "bg-amber-100 text-amber-700", icon: "text-amber-500", bar: "bg-amber-400", line: "border-amber-300", dropBg: "bg-amber-100" },
    { bg: "bg-rose-50", border: "border-rose-200", text: "text-rose-700", badge: "bg-rose-100 text-rose-700", icon: "text-rose-500", bar: "bg-rose-400", line: "border-rose-300", dropBg: "bg-rose-100" },
    { bg: "bg-cyan-50", border: "border-cyan-200", text: "text-cyan-700", badge: "bg-cyan-100 text-cyan-700", icon: "text-cyan-500", bar: "bg-cyan-400", line: "border-cyan-300", dropBg: "bg-cyan-100" },
    { bg: "bg-fuchsia-50", border: "border-fuchsia-200", text: "text-fuchsia-700", badge: "bg-fuchsia-100 text-fuchsia-700", icon: "text-fuchsia-500", bar: "bg-fuchsia-400", line: "border-fuchsia-300", dropBg: "bg-fuchsia-100" },
    { bg: "bg-lime-50", border: "border-lime-200", text: "text-lime-700", badge: "bg-lime-100 text-lime-700", icon: "text-lime-500", bar: "bg-lime-400", line: "border-lime-300", dropBg: "bg-lime-100" },
];

type ViewMode = "tree" | "folders";

// Drop target identifier: "parentClusterId" or "parentClusterId-childClusterId"
type DropTarget = string;

export function DocumentsTab({ documents }: Props) {
    const [clusters, setClusters] = useState<DocCluster[]>([]);
    const [clusterLoading, setClusterLoading] = useState(false);
    const [initialized, setInitialized] = useState(false);
    const [expandedClusters, setExpandedClusters] = useState<Set<string>>(new Set());
    const [clusterSummaries, setClusterSummaries] = useState<Record<string, string>>({});
    const [summaryLoadingId, setSummaryLoadingId] = useState<string | null>(null);

    const [viewMode, setViewMode] = useState<ViewMode>("tree");

    // Document modal
    const [modalDocId, setModalDocId] = useState<string | null>(null);

    // Duplicates
    const [duplicates, setDuplicates] = useState<DuplicatePair[]>([]);
    const [dupLoading, setDupLoading] = useState(false);
    const [dupChecked, setDupChecked] = useState(false);

    // Drag & drop state — documents
    const [dragDocId, setDragDocId] = useState<string | null>(null);
    const [dragOverTarget, setDragOverTarget] = useState<DropTarget | null>(null);
    const [moveToast, setMoveToast] = useState<string | null>(null);
    const dragCounterRef = useRef(0);

    // Drag & drop state — clusters (folder reorder)
    const [dragClusterId, setDragClusterId] = useState<number | null>(null);
    const [dragOverClusterId, setDragOverClusterId] = useState<number | null>(null);
    const clusterDragCounterRef = useRef(0);

    // ─── Auto-load clusters on mount ─────────────────────────────
    const loadClusters = useCallback(async () => {
        setClusterLoading(true);
        try {
            const data = await api.clusterDocuments();
            setClusters(data.clusters);
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

    const totalDocs = clusters.reduce((sum, c) => sum + c.documents.length, 0) || documents.length;

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

    // ─── Drag & drop logic ───────────────────────────────────────
    function handleDragStart(e: React.DragEvent, docId: string) {
        setDragDocId(docId);
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", docId);
        // Make the drag image slightly transparent
        if (e.currentTarget instanceof HTMLElement) {
            e.currentTarget.style.opacity = "0.5";
        }
    }

    function handleDragEnd(e: React.DragEvent) {
        if (e.currentTarget instanceof HTMLElement) {
            e.currentTarget.style.opacity = "1";
        }
        setDragDocId(null);
        setDragOverTarget(null);
        dragCounterRef.current = 0;
    }

    function handleDragEnter(e: React.DragEvent, target: DropTarget) {
        e.preventDefault();
        e.stopPropagation();
        dragCounterRef.current++;
        setDragOverTarget(target);
    }

    function handleDragOver(e: React.DragEvent) {
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = "move";
    }

    function handleDragLeave(e: React.DragEvent) {
        e.preventDefault();
        e.stopPropagation();
        dragCounterRef.current--;
        if (dragCounterRef.current === 0) {
            setDragOverTarget(null);
        }
    }

    // ─── Cluster drag handlers ──────────────────────────────────
    function handleClusterDragStart(e: React.DragEvent, clusterId: number) {
        setDragClusterId(clusterId);
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("dragType", "cluster");
        e.dataTransfer.setData("clusterId", String(clusterId));
        if (e.currentTarget instanceof HTMLElement) e.currentTarget.style.opacity = "0.5";
    }

    function handleClusterDragEnd(e: React.DragEvent) {
        if (e.currentTarget instanceof HTMLElement) e.currentTarget.style.opacity = "1";
        setDragClusterId(null);
        setDragOverClusterId(null);
        clusterDragCounterRef.current = 0;
    }

    function handleClusterDragEnter(e: React.DragEvent, clusterId: number) {
        e.preventDefault();
        e.stopPropagation();
        clusterDragCounterRef.current++;
        setDragOverClusterId(clusterId);
    }

    function handleClusterDragOver(e: React.DragEvent) {
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = "move";
    }

    function handleClusterDragLeave(e: React.DragEvent) {
        e.stopPropagation();
        clusterDragCounterRef.current--;
        if (clusterDragCounterRef.current <= 0) {
            clusterDragCounterRef.current = 0;
            setDragOverClusterId(null);
        }
    }

    function handleClusterDrop(e: React.DragEvent, targetClusterId: number) {
        e.preventDefault();
        e.stopPropagation();
        const type = e.dataTransfer.getData("dragType");
        if (type !== "cluster") return;
        const srcId = parseInt(e.dataTransfer.getData("clusterId") || String(dragClusterId));
        setDragClusterId(null);
        setDragOverClusterId(null);
        clusterDragCounterRef.current = 0;
        if (isNaN(srcId) || srcId === targetClusterId) return;
        setClusters((prev) => {
            const next = [...prev];
            const fromIdx = next.findIndex((c) => c.cluster_id === srcId);
            const toIdx = next.findIndex((c) => c.cluster_id === targetClusterId);
            if (fromIdx === -1 || toIdx === -1) return prev;
            const [item] = next.splice(fromIdx, 1);
            next.splice(toIdx, 0, item);
            return next;
        });
    }

    function handleDrop(e: React.DragEvent, targetKey: DropTarget) {
        e.preventDefault();
        e.stopPropagation();
        const docId = e.dataTransfer.getData("text/plain") || dragDocId;
        if (!docId) return;

        setDragDocId(null);
        setDragOverTarget(null);
        dragCounterRef.current = 0;

        // Move document in cluster state
        moveDocToTarget(docId, targetKey);
    }

    function moveDocToTarget(docId: string, targetKey: DropTarget) {
        setClusters((prev) => {
            const next = structuredClone(prev);

            // Find the doc and remove it from its current location
            let movedDoc: DocListItem | null = null;
            for (const cluster of next) {
                // Check parent-level documents
                const parentIdx = cluster.documents.findIndex((d) => d.doc_id === docId);
                if (parentIdx !== -1) {
                    movedDoc = cluster.documents[parentIdx];
                    cluster.documents.splice(parentIdx, 1);
                }
                // Check children
                if (cluster.children) {
                    for (const child of cluster.children) {
                        const childIdx = child.documents.findIndex((d) => d.doc_id === docId);
                        if (childIdx !== -1) {
                            movedDoc = child.documents[childIdx];
                            child.documents.splice(childIdx, 1);
                        }
                    }
                }
            }

            if (!movedDoc) return prev; // Not found

            // Parse target key: "p-{parentId}" or "c-{parentId}-{childId}"
            const parts = targetKey.split("-");
            if (parts[0] === "p") {
                const parentId = parseInt(parts[1]);
                const targetCluster = next.find((c) => c.cluster_id === parentId);
                if (targetCluster) {
                    // If cluster has children, add to first child. Otherwise add to documents.
                    if (targetCluster.children && targetCluster.children.length > 0) {
                        targetCluster.children[0].documents.push(movedDoc);
                    }
                    // Always update parent doc list
                    if (!targetCluster.documents.find((d) => d.doc_id === movedDoc!.doc_id)) {
                        targetCluster.documents.push(movedDoc);
                    }
                }
            } else if (parts[0] === "c") {
                const parentId = parseInt(parts[1]);
                const childId = parseInt(parts[2]);
                const parentCluster = next.find((c) => c.cluster_id === parentId);
                if (parentCluster?.children) {
                    const targetChild = parentCluster.children.find((ch) => ch.cluster_id === childId);
                    if (targetChild) {
                        targetChild.documents.push(movedDoc);
                        // Update parent doc list too
                        if (!parentCluster.documents.find((d) => d.doc_id === movedDoc!.doc_id)) {
                            parentCluster.documents.push(movedDoc);
                        }
                    }
                }
            }

            // Remove empty children
            for (const cluster of next) {
                if (cluster.children) {
                    cluster.children = cluster.children.filter((ch) => ch.documents.length > 0);
                }
            }

            // Show toast
            const targetCluster = next.find((c) =>
                targetKey === `p-${c.cluster_id}` ||
                c.children?.some((ch) => targetKey === `c-${c.cluster_id}-${ch.cluster_id}`)
            );
            if (targetCluster) {
                setMoveToast(`"${movedDoc.title || movedDoc.filename}" movido a "${targetCluster.label}"`);
                setTimeout(() => setMoveToast(null), 3000);
            }

            return next;
        });
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
                    Los documentos se agrupan automáticamente por similitud temática. Arrastra documentos entre carpetas para reorganizarlos.
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
                                    style={{ width: `${Math.max(pct, 2)}%` }}
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
                                const isDropTarget = dragOverTarget === pKey && dragDocId !== null;

                                return (
                                    <div key={cluster.cluster_id} id={`cluster-${cluster.cluster_id}`}>
                                        {/* Parent cluster line — drop target */}
                                        <div
                                            className={`flex items-center ml-3 group/pnode cursor-pointer rounded-md px-1 -mx-1 transition-colors ${isDropTarget ? `${c.dropBg} ring-2 ring-${c.text.replace("text-", "")}` : ""}`}
                                            onClick={() => toggleNode(pKey)}
                                            onDragEnter={(e) => handleDragEnter(e, pKey)}
                                            onDragOver={handleDragOver}
                                            onDragLeave={handleDragLeave}
                                            onDrop={(e) => handleDrop(e, pKey)}
                                        >
                                            <span className="font-mono text-ink-3 w-5 text-center shrink-0 select-none">
                                                {isLastCluster ? "└" : "├"}
                                            </span>
                                            <span className="font-mono text-ink-3 shrink-0 select-none">── </span>
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
                                                    children.map((child, sci) => {
                                                        const isLastChild = sci === children.length - 1;
                                                        const cKey = `c-${cluster.cluster_id}-${child.cluster_id}`;
                                                        const cOpen = expandedClusters.has(cKey);
                                                        const subColor = CC[(cluster.cluster_id * 3 + child.cluster_id + 1) % CC.length];
                                                        const isSubDropTarget = dragOverTarget === cKey && dragDocId !== null;

                                                        return (
                                                            <div key={child.cluster_id}>
                                                                {/* Sub-cluster line — drop target */}
                                                                <div
                                                                    className={`flex items-center group/snode cursor-pointer rounded-md px-1 -mx-1 transition-colors ${isSubDropTarget ? `${subColor.dropBg} ring-2` : ""}`}
                                                                    onClick={() => toggleNode(cKey)}
                                                                    onDragEnter={(e) => handleDragEnter(e, cKey)}
                                                                    onDragOver={handleDragOver}
                                                                    onDragLeave={handleDragLeave}
                                                                    onDrop={(e) => handleDrop(e, cKey)}
                                                                >
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
                                                                        <div key={doc.doc_id}
                                                                            className={`flex items-center group/doc cursor-grab active:cursor-grabbing ${dragDocId === doc.doc_id ? "opacity-40" : ""}`}
                                                                            draggable
                                                                            onDragStart={(e) => handleDragStart(e, doc.doc_id)}
                                                                            onDragEnd={handleDragEnd}
                                                                        >
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
                                                                            {/* Drag handle */}
                                                                            <svg className="w-3 h-3 text-ink-3/40 shrink-0 mr-0.5 group-hover/doc:text-ink-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8h16M4 16h16" />
                                                                            </svg>
                                                                            <svg className="w-3 h-3 text-ink-3 shrink-0 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                                                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                                                            </svg>
                                                                            <button onClick={(e) => { e.stopPropagation(); setModalDocId(doc.doc_id); }}
                                                                                className="text-ink-1 truncate max-w-xs text-[13px] hover:text-brand-700 transition-colors text-left">
                                                                                {doc.title || doc.filename}
                                                                            </button>
                                                                            <span className={`text-[10px] ml-1.5 px-1.5 py-0 rounded ${typeColor(doc.doc_type)}`}>{doc.doc_type}</span>
                                                                        </div>
                                                                    );
                                                                })}
                                                            </div>
                                                        );
                                                    })
                                                ) : (
                                                    cluster.documents.map((doc, di) => {
                                                        const isLastDoc = di === cluster.documents.length - 1;
                                                        return (
                                                            <div key={doc.doc_id}
                                                                className={`flex items-center group/doc cursor-grab active:cursor-grabbing ${dragDocId === doc.doc_id ? "opacity-40" : ""}`}
                                                                draggable
                                                                onDragStart={(e) => handleDragStart(e, doc.doc_id)}
                                                                onDragEnd={handleDragEnd}
                                                            >
                                                                <span className="font-mono text-ink-3 w-5 text-center shrink-0 select-none">
                                                                    {isLastCluster ? " " : "│"}
                                                                </span>
                                                                <span className="font-mono text-ink-3 w-5 text-center shrink-0 select-none">
                                                                    {isLastDoc ? "└" : "├"}
                                                                </span>
                                                                <span className="font-mono text-ink-3 shrink-0 select-none">── </span>
                                                                <svg className="w-3 h-3 text-ink-3/40 shrink-0 mr-0.5 group-hover/doc:text-ink-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8h16M4 16h16" />
                                                                </svg>
                                                                <svg className="w-3 h-3 text-ink-3 shrink-0 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                                        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                                                </svg>
                                                                <button onClick={(e) => { e.stopPropagation(); setModalDocId(doc.doc_id); }}
                                                                    className="text-ink-1 truncate max-w-xs text-[13px] hover:text-brand-700 transition-colors text-left">
                                                                    {doc.title || doc.filename}
                                                                </button>
                                                                <span className={`text-[10px] ml-1.5 px-1.5 py-0 rounded ${typeColor(doc.doc_type)}`}>{doc.doc_type}</span>
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
                            const isDocDropTarget = dragOverTarget === pKey && dragDocId !== null;
                            const isClusterDragOver = dragOverClusterId === cluster.cluster_id && dragClusterId !== null && dragClusterId !== cluster.cluster_id;
                            const isBeingDragged = dragClusterId === cluster.cluster_id;

                            return (
                                <div key={cluster.cluster_id} id={`cluster-${cluster.cluster_id}`}
                                    draggable
                                    onDragStart={(e) => handleClusterDragStart(e, cluster.cluster_id)}
                                    onDragEnd={handleClusterDragEnd}
                                    onDragEnter={(e) => { handleClusterDragEnter(e, cluster.cluster_id); if (dragDocId) handleDragEnter(e, pKey); }}
                                    onDragOver={(e) => { handleClusterDragOver(e); if (dragDocId) handleDragOver(e); }}
                                    onDragLeave={(e) => { handleClusterDragLeave(e); handleDragLeave(e); }}
                                    onDrop={(e) => { if (e.dataTransfer.getData("dragType") === "cluster") { handleClusterDrop(e, cluster.cluster_id); } else { handleDrop(e, pKey); } }}
                                    className={`${c.bg} border ${c.border} rounded-xl overflow-hidden transition-all
                                        ${isOpen ? "shadow-sm" : ""}
                                        ${isBeingDragged ? "opacity-50 scale-[0.98]" : ""}
                                        ${isDocDropTarget ? "ring-2 ring-offset-1 ring-brand-400 scale-[1.005]" : ""}
                                        ${isClusterDragOver ? `ring-2 ring-offset-2 ${c.border} scale-[1.01] shadow-md` : ""}`}
                                >
                                    {/* Folder header */}
                                    <div className="w-full flex items-center gap-3 px-5 py-4 text-left group">
                                    {/* Drag handle */}
                                    <span className="cursor-grab active:cursor-grabbing text-ink-3 opacity-40 hover:opacity-70 shrink-0 -ml-2 pr-0.5"
                                        title="Arrastrar para reordenar">
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                                        </svg>
                                    </span>
                                    <button onClick={() => toggleNode(pKey)} className="flex items-center gap-3 flex-1 min-w-0 text-left">
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
                                    </div>

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

                                            {/* Sub-clusters or documents */}
                                            {hasChildren ? (
                                                <div className="space-y-3">
                                                    {children.map((child) => {
                                                        const cKey = `c-${cluster.cluster_id}-${child.cluster_id}`;
                                                        const cOpen = expandedClusters.has(cKey);
                                                        const subColor = CC[(cluster.cluster_id * 3 + child.cluster_id + 1) % CC.length];
                                                        const isSubDropTarget = dragOverTarget === cKey && dragDocId !== null;
                                                        return (
                                                            <div key={child.cluster_id}
                                                                className={`bg-white/70 border border-white/80 rounded-lg overflow-hidden transition-all ${isSubDropTarget ? "ring-2 ring-brand-300 bg-brand-50/30" : ""}`}
                                                                onDragEnter={(e) => { e.stopPropagation(); handleDragEnter(e, cKey); }}
                                                                onDragOver={(e) => { e.stopPropagation(); handleDragOver(e); }}
                                                                onDragLeave={(e) => { e.stopPropagation(); handleDragLeave(e); }}
                                                                onDrop={(e) => { e.stopPropagation(); handleDrop(e, cKey); }}
                                                            >
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
                                                                            <DraggableDocRow key={doc.doc_id} doc={doc}
                                                                                onView={setModalDocId}
                                                                                isDragging={dragDocId === doc.doc_id}
                                                                                onDragStart={handleDragStart}
                                                                                onDragEnd={handleDragEnd} />
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
                                                        <DraggableDocRow key={doc.doc_id} doc={doc}
                                                            onView={setModalDocId}
                                                            isDragging={dragDocId === doc.doc_id}
                                                            onDragStart={handleDragStart}
                                                            onDragEnd={handleDragEnd} />
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
                                            <button onClick={() => setModalDocId(pair.doc_a.doc_id)} className="text-xs text-brand-600 hover:text-brand-700 font-medium">Ver A</button>
                                            <button onClick={() => setModalDocId(pair.doc_b.doc_id)} className="text-xs text-brand-600 hover:text-brand-700 font-medium">Ver B</button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* ─── Move toast notification ─────────────────────── */}
            {moveToast && (
                <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 bg-ink-0 text-white px-4 py-2.5 rounded-lg shadow-lg text-sm flex items-center gap-2 fade-in">
                    <svg className="w-4 h-4 text-green-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    {moveToast}
                </div>
            )}

            {/* ─── Document modal ─────────────────────────────── */}
            <DocumentModal docId={modalDocId} onClose={() => setModalDocId(null)} />
        </section>
    );
}

/* ─── Draggable doc row component ───────────────────────────────── */
function DraggableDocRow({ doc, onView, isDragging, onDragStart, onDragEnd }: {
    doc: DocListItem;
    onView: (id: string) => void;
    isDragging: boolean;
    onDragStart: (e: React.DragEvent, docId: string) => void;
    onDragEnd: (e: React.DragEvent) => void;
}) {
    return (
        <div
            className={`flex items-center gap-3 px-4 py-2.5 bg-white/70 hover:bg-white rounded-lg transition-colors group/doc cursor-grab active:cursor-grabbing ${isDragging ? "opacity-40" : ""}`}
            draggable
            onDragStart={(e) => onDragStart(e, doc.doc_id)}
            onDragEnd={onDragEnd}
        >
            {/* Drag handle */}
            <svg className="w-4 h-4 text-ink-3/30 shrink-0 group-hover/doc:text-ink-3/60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8h16M4 16h16" />
            </svg>
            <svg className="w-4 h-4 text-ink-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <button onClick={(e) => { e.stopPropagation(); onView(doc.doc_id); }}
                className="text-sm text-ink-0 flex-1 truncate group-hover/doc:text-brand-700 transition-colors text-left">
                {doc.title || doc.filename}
            </button>
            <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${typeColor(doc.doc_type)}`}>{doc.doc_type}</span>
            {doc.category && <span className="hidden sm:inline text-xs text-ink-3">{doc.category}</span>}
        </div>
    );
}
