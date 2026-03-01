"use client";

import { useState, useMemo } from "react";
import { typeColor } from "@/lib/utils";
import type { Stats, DocListItem, EntityItem } from "@/lib/types";

interface Props {
    stats: Stats;
    documents: DocListItem[];
    entities: EntityItem[];
}

export function DashboardTab({ stats, documents, entities }: Props) {
    const maxDocType = Math.max(...Object.values(stats.documents_by_type || {}), 1);
    const maxEntityType = Math.max(...Object.values(stats.entities_by_type || {}), 1);
    const [showAllEntities, setShowAllEntities] = useState(false);

    // Top entities sorted by mentions
    const topEntities = useMemo(() => {
        const sorted = [...entities].sort((a, b) => b.mentions - a.mentions);
        return showAllEntities ? sorted : sorted.slice(0, 10);
    }, [entities, showAllEntities]);

    // Category distribution
    const categoryDist = useMemo(() => {
        const counts: Record<string, number> = {};
        for (const d of documents) {
            const cat = d.category || "Sin categoría";
            counts[cat] = (counts[cat] || 0) + 1;
        }
        return Object.entries(counts).sort((a, b) => b[1] - a[1]);
    }, [documents]);
    const maxCategory = Math.max(...categoryDist.map(([, c]) => c), 1);

    // Recent documents (last 5 by name heuristic — they're sorted as received)
    const recentDocs = useMemo(() => documents.slice(-8).reverse(), [documents]);

    return (
        <section className="fade-in">
            <div className="max-w-6xl mx-auto">
                <h2 className="text-lg font-semibold mb-6">Dashboard</h2>

                {/* ─── KPI Cards ───────────────────────────────────── */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
                    <KpiCard label="Documentos" value={stats.documents} icon={
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    } color="brand" />
                    <KpiCard label="Entidades" value={stats.entities} icon={
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                            d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                    } color="emerald" />
                    <KpiCard label="Relaciones" value={stats.edges} icon={
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                            d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                    } color="violet" />
                    <KpiCard label="Tipos" value={Object.keys(stats.documents_by_type || {}).length} icon={
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                            d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A2 2 0 013 12V7a4 4 0 014-4z" />
                    } color="amber" />
                </div>

                {/* ─── Main grid ───────────────────────────────────── */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Documents by type */}
                    <div className="bg-white border border-surface-3 rounded-lg p-5">
                        <h3 className="text-sm font-semibold text-ink-0 mb-4 flex items-center gap-2">
                            <svg className="w-4 h-4 text-brand-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                            </svg>
                            Distribución por tipo
                        </h3>
                        <div className="space-y-2.5">
                            {Object.entries(stats.documents_by_type || {}).sort(([, a], [, b]) => b - a).map(([type, count]) => (
                                <div key={type}>
                                    <div className="flex items-center justify-between mb-1">
                                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${typeColor(type)}`}>{type}</span>
                                        <span className="text-xs font-medium text-ink-1">{count}</span>
                                    </div>
                                    <div className="w-full bg-surface-2 rounded-full h-2">
                                        <div className="bg-brand-400 h-2 rounded-full transition-all" style={{ width: `${(count / maxDocType) * 100}%` }} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Categories */}
                    <div className="bg-white border border-surface-3 rounded-lg p-5">
                        <h3 className="text-sm font-semibold text-ink-0 mb-4 flex items-center gap-2">
                            <svg className="w-4 h-4 text-violet-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                    d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                            </svg>
                            Categorías
                        </h3>
                        <div className="space-y-2.5">
                            {categoryDist.map(([cat, count]) => (
                                <div key={cat}>
                                    <div className="flex items-center justify-between mb-1">
                                        <span className="text-sm text-ink-1 truncate">{cat}</span>
                                        <span className="text-xs font-medium text-ink-1 ml-2">{count}</span>
                                    </div>
                                    <div className="w-full bg-surface-2 rounded-full h-2">
                                        <div className="bg-violet-400 h-2 rounded-full transition-all" style={{ width: `${(count / maxCategory) * 100}%` }} />
                                    </div>
                                </div>
                            ))}
                            {categoryDist.length === 0 && <p className="text-sm text-ink-3">Sin datos.</p>}
                        </div>
                    </div>

                    {/* Entities by type */}
                    <div className="bg-white border border-surface-3 rounded-lg p-5">
                        <h3 className="text-sm font-semibold text-ink-0 mb-4 flex items-center gap-2">
                            <svg className="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                    d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                            </svg>
                            Entidades por tipo
                        </h3>
                        <div className="space-y-3">
                            {Object.entries(stats.entities_by_type || {}).sort(([, a], [, b]) => b - a).map(([type, count]) => (
                                <div key={type}>
                                    <div className="flex items-center justify-between mb-1">
                                        <div className="flex items-center gap-2">
                                            <span className={`w-2.5 h-2.5 rounded-full ${type === "person" ? "bg-green-400" : "bg-blue-400"}`} />
                                            <span className="text-sm text-ink-1 capitalize">{type === "person" ? "Personas" : "Organizaciones"}</span>
                                        </div>
                                        <span className="text-xs font-medium text-ink-1">{count}</span>
                                    </div>
                                    <div className="w-full bg-surface-2 rounded-full h-2">
                                        <div className={`h-2 rounded-full transition-all ${type === "person" ? "bg-green-400" : "bg-blue-400"}`}
                                            style={{ width: `${(count / maxEntityType) * 100}%` }} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

                {/* ─── Bottom row ──────────────────────────────────── */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
                    {/* Top entities */}
                    <div className="bg-white border border-surface-3 rounded-lg p-5">
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-sm font-semibold text-ink-0 flex items-center gap-2">
                                <svg className="w-4 h-4 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                        d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
                                </svg>
                                Entidades más mencionadas
                            </h3>
                            {entities.length > 10 && (
                                <button onClick={() => setShowAllEntities(!showAllEntities)}
                                    className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                                    {showAllEntities ? "Mostrar menos" : `Ver todas (${entities.length})`}
                                </button>
                            )}
                        </div>
                        <div className="space-y-2">
                            {topEntities.map((e) => (
                                <div key={e.name} className="flex items-center gap-3">
                                    <span className={`w-2 h-2 rounded-full shrink-0 ${e.type === "person" ? "bg-green-400" : "bg-blue-400"}`} />
                                    <span className="text-sm text-ink-1 flex-1 truncate">{e.name}</span>
                                    <span className="text-xs text-ink-3 shrink-0">{e.mentions} menciones</span>
                                    <span className="text-xs text-ink-3 shrink-0">{e.num_docs} docs</span>
                                </div>
                            ))}
                            {topEntities.length === 0 && <p className="text-sm text-ink-3">Sin entidades.</p>}
                        </div>
                    </div>

                    {/* Recent documents */}
                    <div className="bg-white border border-surface-3 rounded-lg p-5">
                        <h3 className="text-sm font-semibold text-ink-0 mb-4 flex items-center gap-2">
                            <svg className="w-4 h-4 text-cyan-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                    d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            Últimos documentos
                        </h3>
                        <div className="space-y-2">
                            {recentDocs.map((doc) => (
                                <div key={doc.doc_id} className="flex items-center gap-3 py-1">
                                    <span className={`shrink-0 inline-flex px-2 py-0.5 rounded text-xs font-medium ${typeColor(doc.doc_type)}`}>
                                        {doc.doc_type}
                                    </span>
                                    <span className="text-sm text-ink-1 flex-1 truncate">{doc.title || doc.filename}</span>
                                    {doc.category && (
                                        <span className="text-xs text-ink-3 shrink-0">{doc.category}</span>
                                    )}
                                </div>
                            ))}
                            {recentDocs.length === 0 && <p className="text-sm text-ink-3">Sin documentos.</p>}
                        </div>
                    </div>
                </div>
            </div>
        </section>
    );
}

function KpiCard({ label, value, icon, color }: { label: string; value: number; icon: React.ReactNode; color: string }) {
    return (
        <div className="bg-white border border-surface-3 rounded-lg p-5 flex items-start gap-4">
            <div className={`w-10 h-10 rounded-lg bg-${color}-50 flex items-center justify-center shrink-0`}>
                <svg className={`w-5 h-5 text-${color}-500`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    {icon}
                </svg>
            </div>
            <div>
                <div className="text-xs font-medium text-ink-3 uppercase tracking-wider">{label}</div>
                <div className="text-2xl font-semibold text-ink-0 mt-0.5">{value ?? 0}</div>
            </div>
        </div>
    );
}
