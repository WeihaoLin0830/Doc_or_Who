"use client";

import { typeColor } from "@/lib/utils";
import type { Stats } from "@/lib/types";

interface Props {
    stats: Stats;
}

export function DashboardTab({ stats }: Props) {
    const maxDocType = Math.max(...Object.values(stats.documents_by_type || {}), 1);

    return (
        <section className="fade-in">
            <div className="max-w-5xl mx-auto">
                <h2 className="text-lg font-semibold mb-4">Dashboard</h2>

                {/* Stat cards */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
                    <StatCard label="Documentos" value={stats.documents} />
                    <StatCard label="Entidades" value={stats.entities} />
                    <StatCard label="Relaciones" value={stats.edges} />
                </div>

                {/* Charts */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Documents by type */}
                    <div className="bg-white border border-surface-3 rounded-lg p-5">
                        <h3 className="text-sm font-semibold text-ink-0 mb-3">Documentos por tipo</h3>
                        <div className="space-y-2">
                            {Object.entries(stats.documents_by_type || {}).map(([type, count]) => (
                                <div key={type} className="flex items-center justify-between">
                                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${typeColor(type)}`}>{type}</span>
                                    <div className="flex items-center gap-2 flex-1 ml-3">
                                        <div className="flex-1 bg-surface-2 rounded-full h-2">
                                            <div className="bg-brand-400 h-2 rounded-full" style={{ width: `${(count / maxDocType) * 100}%` }} />
                                        </div>
                                        <span className="text-sm font-medium text-ink-1 w-6 text-right">{count}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Entities by type */}
                    <div className="bg-white border border-surface-3 rounded-lg p-5">
                        <h3 className="text-sm font-semibold text-ink-0 mb-3">Entidades por tipo</h3>
                        <div className="space-y-2">
                            {Object.entries(stats.entities_by_type || {}).map(([type, count]) => (
                                <div key={type} className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <span className={`w-2 h-2 rounded-full ${type === "person" ? "bg-green-400" : "bg-blue-400"}`} />
                                        <span className="text-sm text-ink-1 capitalize">{type === "person" ? "Personas" : "Organizaciones"}</span>
                                    </div>
                                    <span className="text-sm font-medium text-ink-1">{count}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </section>
    );
}

function StatCard({ label, value }: { label: string; value: number }) {
    return (
        <div className="bg-white border border-surface-3 rounded-lg p-5">
            <div className="text-xs font-medium text-ink-3 uppercase tracking-wider mb-1">{label}</div>
            <div className="text-3xl font-semibold text-ink-0">{value ?? 0}</div>
        </div>
    );
}
