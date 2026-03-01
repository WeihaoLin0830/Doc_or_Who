"use client";

import type { IngestStatus } from "@/lib/types";
import type { TabId } from "@/app/page";

const TABS: { id: TabId; label: string }[] = [
    { id: "ask", label: "Preguntar" },
    { id: "search", label: "Buscar" },
    { id: "documents", label: "Documentos" },
    { id: "graph", label: "Grafo" },
    { id: "dashboard", label: "Dashboard" },
];

interface Props {
    activeTab: TabId;
    setActiveTab: (t: TabId) => void;
    onUpload: () => void;
    onIngest: () => void;
    ingesting: boolean;
    ingestProgress: IngestStatus | null;
}

function ingestLabel(ingesting: boolean, p: IngestStatus | null): string {
    if (!ingesting) return "Re-indexar todo";
    if (!p || !p.phase || p.phase === "starting") return "Iniciando...";
    if (p.phase === "clearing") return "Limpiando índices...";
    if (p.phase === "graph") return "Construyendo grafo...";
    if (p.phase === "indexing" && p.total > 0) {
        const name = p.current_file ? p.current_file.replace(/\.[^.]+$/, "") : "...";
        return `${p.current + 1}/${p.total} – ${name}`;
    }
    return `Procesando... ${p?.elapsed ?? 0}s`;
}

export function Navbar({ activeTab, setActiveTab, onUpload, onIngest, ingesting, ingestProgress }: Props) {
    return (
        <header className="bg-white border-b border-surface-3 sticky top-0 z-50">
            <div className="max-w-[1440px] mx-auto px-6 h-14 flex items-center justify-between">
                {/* Logo */}
                <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center">
                        <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                    </div>
                    <span className="text-lg font-semibold tracking-tight text-ink-0">DocumentWho</span>
                </div>

                {/* Tabs */}
                <nav className="flex items-center gap-1">
                    {TABS.map((tab) => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`px-3 py-1.5 rounded-md text-sm transition-colors ${activeTab === tab.id
                                ? "bg-brand-50 text-brand-700 font-medium"
                                : "text-ink-2 hover:text-ink-0 hover:bg-surface-2"
                                }`}
                        >
                            {tab.label}
                        </button>
                    ))}
                </nav>

                {/* Actions */}
                <div className="flex items-center gap-2">
                    <button
                        onClick={onUpload}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-brand-700 bg-brand-50 hover:bg-brand-100 rounded-md transition-colors"
                    >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                        </svg>
                        Subir
                    </button>
                    <button
                        onClick={onIngest}
                        disabled={ingesting}
                        title="Re-indexa todos los documentos desde cero: borra los índices actuales y vuelve a procesar todos los archivos. Úsalo si hay errores de búsqueda o si añadiste archivos directamente en disco."
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white bg-brand-600 hover:bg-brand-700 disabled:opacity-60 rounded-md transition-colors"
                    >
                        <svg
                            className={`w-4 h-4 shrink-0 ${ingesting ? "animate-spin" : ""}`}
                            fill="none" stroke="currentColor" viewBox="0 0 24 24"
                        >
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        <span className="max-w-[200px] truncate">
                            {ingestLabel(ingesting, ingestProgress)}
                        </span>
                    </button>
                </div>
            </div>
        </header>
    );
}
