"use client";

import { useState, useEffect, useCallback } from "react";

import { Navbar } from "@/components/Navbar";
import { AskTab } from "@/components/AskTab";
import { SearchTab } from "@/components/SearchTab";
import { DocumentsTab } from "@/components/DocumentsTab";
import { GraphTab } from "@/components/GraphTab";
import { DashboardTab } from "@/components/DashboardTab";
import { UploadModal } from "@/components/UploadModal";
import { Toast } from "@/components/Toast";

import * as api from "@/lib/api";
import type { DocListItem, EntityItem, Stats, IngestStatus } from "@/lib/types";

export type TabId = "ask" | "search" | "documents" | "graph" | "dashboard";

export default function Home() {
    const [activeTab, setActiveTab] = useState<TabId>("ask");
    const [showUpload, setShowUpload] = useState(false);

    // Shared data loaded once and refreshed on upload/ingest
    const [documents, setDocuments] = useState<DocListItem[]>([]);
    const [entities, setEntities] = useState<EntityItem[]>([]);
    const [stats, setStats] = useState<Stats>({ documents: 0, entities: 0, edges: 0, documents_by_type: {}, entities_by_type: {} });

    // Toast
    const [toast, setToast] = useState<{ msg: string; type: "ok" | "error" } | null>(null);
    const showToast = useCallback((msg: string, type: "ok" | "error" = "ok") => {
        setToast({ msg, type });
        setTimeout(() => setToast(null), 3500);
    }, []);

    // Ingest state (lifted here so Navbar can show progress)
    const [ingesting, setIngesting] = useState(false);
    const [ingestProgress, setIngestProgress] = useState<IngestStatus | null>(null);

    // ─── Data loading ────────────────────────────────────────────
    const loadDocs = useCallback(async () => {
        try { setDocuments(await api.listDocuments()); } catch { /* ignore */ }
    }, []);

    const loadEntities = useCallback(async () => {
        try { setEntities(await api.listEntities()); } catch { /* ignore */ }
    }, []);

    const loadStats = useCallback(async () => {
        try { setStats(await api.getStats()); } catch { /* ignore */ }
    }, []);

    /** Refresh everything — called after upload or ingest completes */
    const refreshAll = useCallback(() => {
        loadDocs();
        loadEntities();
        loadStats();
    }, [loadDocs, loadEntities, loadStats]);

    // Initial load
    useEffect(() => { refreshAll(); }, [refreshAll]);

    // Reload docs/stats when the tab changes
    useEffect(() => {
        if (activeTab === "documents") loadDocs();
        if (activeTab === "dashboard") loadStats();
    }, [activeTab, loadDocs, loadStats]);

    // ─── Ingest ──────────────────────────────────────────────────
    const runIngest = useCallback(async () => {
        if (ingesting) return;
        setIngesting(true);
        setIngestProgress(null);
        try {
            const resp = await api.startIngest();
            if (resp.status === "already_running") {
                // Already running — just start polling
            }
        } catch (e: unknown) {
            showToast("Error al iniciar la ingestión: " + (e instanceof Error ? e.message : "desconocido"), "error");
            setIngesting(false);
            return;
        }

        const poll = setInterval(async () => {
            try {
                const s = await api.getIngestStatus();
                setIngestProgress(s);
                if (!s.running) {
                    clearInterval(poll);
                    setIngesting(false);
                    setIngestProgress(null);
                    if (s.phase === "done") {
                        showToast(`Re-indexación completada: ${s.docs_processed} documentos en ${s.elapsed}s`);
                        refreshAll();
                    } else if (s.phase === "error") {
                        showToast("Error durante la ingestión: " + (s.error || "desconocido"), "error");
                    }
                }
            } catch { /* poll error */ }
        }, 1500);
    }, [ingesting, showToast, refreshAll]);

    // ─── Upload complete handler ─────────────────────────────────
    // Await loadDocs so the document count is guaranteed fresh before the
    // user closes the modal (fire the rest in parallel, they're not critical).
    const onUploadComplete = useCallback(async () => {
        await loadDocs();
        loadEntities();
        loadStats();
        showToast("Documento subido y procesado correctamente");
    }, [loadDocs, loadEntities, loadStats, showToast]);

    return (
        <>
            <Navbar
                activeTab={activeTab}
                setActiveTab={setActiveTab}
                onUpload={() => setShowUpload(true)}
                onIngest={runIngest}
                ingesting={ingesting}
                ingestProgress={ingestProgress}
            />

            <main className="flex-1 max-w-[1440px] mx-auto w-full px-6 py-6">
                {activeTab === "ask" && <AskTab />}
                {activeTab === "search" && <SearchTab documents={documents} onViewDoc={(id) => { setActiveTab("documents"); }} />}
                {activeTab === "documents" && <DocumentsTab documents={documents} />}
                {activeTab === "graph" && <GraphTab entities={entities} documents={documents} />}
                {activeTab === "dashboard" && <DashboardTab stats={stats} documents={documents} entities={entities} />}
            </main>

            {showUpload && (
                <UploadModal
                    ingesting={ingesting}
                    onClose={() => setShowUpload(false)}
                    onComplete={onUploadComplete}
                />
            )}

            <Toast toast={toast} />
        </>
    );
}
