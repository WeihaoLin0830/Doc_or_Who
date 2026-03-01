"use client";

import { useState } from "react";
import * as api from "@/lib/api";
import type { SqlTable, SqlResult } from "@/lib/types";

interface Props {
    tables: SqlTable[];
}

export function SqlTab({ tables }: Props) {
    const [question, setQuestion] = useState("");
    const [rawSql, setRawSql] = useState("");
    const [loading, setLoading] = useState(false);
    const [generated, setGenerated] = useState("");
    const [result, setResult] = useState<SqlResult | null>(null);

    async function ask() {
        if (!question.trim()) return;
        setLoading(true);
        setGenerated("");
        setResult(null);
        try {
            const data = await api.sqlAsk(question);
            setGenerated(data.sql || "");
            setResult(data);
        } catch { /* ignore */ }
        setLoading(false);
    }

    async function exec() {
        if (!rawSql.trim()) return;
        setLoading(true);
        setGenerated("");
        setResult(null);
        try { setResult(await api.sqlExec(rawSql)); } catch { /* ignore */ }
        setLoading(false);
    }

    return (
        <section className="fade-in">
            <div className="max-w-5xl mx-auto">
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div className="lg:col-span-2 space-y-4">
                        <div>
                            <h2 className="text-lg font-semibold mb-1">Consultas SQL</h2>
                            <p className="text-sm text-ink-2">Consulta datos tabulares (CSV/XLSX) con SQL o en lenguaje natural</p>
                        </div>

                        {/* Natural language */}
                        <form onSubmit={(e) => { e.preventDefault(); ask(); }} className="flex gap-2">
                            <input
                                value={question} onChange={(e) => setQuestion(e.target.value)}
                                placeholder="¿Cuál fue el total de ventas de enero?"
                                className="flex-1 px-3 py-2.5 text-sm border border-surface-3 rounded-lg bg-white focus:border-brand-400 outline-none"
                            />
                            <button type="submit" disabled={!question.trim() || loading}
                                className="px-4 py-2.5 bg-brand-600 hover:bg-brand-700 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors">
                                Preguntar
                            </button>
                        </form>

                        {/* Raw SQL */}
                        <div>
                            <label className="text-xs font-medium text-ink-2 uppercase tracking-wider">SQL directo</label>
                            <div className="mt-1 flex gap-2">
                                <textarea
                                    value={rawSql} onChange={(e) => setRawSql(e.target.value)} rows={3}
                                    placeholder="SELECT * FROM ventas_enero_2025 LIMIT 10"
                                    className="flex-1 px-3 py-2 text-sm font-mono border border-surface-3 rounded-lg bg-white focus:border-brand-400 outline-none resize-none"
                                />
                                <button onClick={exec} disabled={!rawSql.trim() || loading}
                                    className="self-end px-4 py-2 bg-ink-0 hover:bg-ink-1 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors">
                                    Ejecutar
                                </button>
                            </div>
                        </div>

                        {/* Generated SQL */}
                        {generated && (
                            <div className="bg-surface-2 rounded-lg p-3">
                                <p className="text-xs text-ink-3 mb-1">SQL generado:</p>
                                <code className="text-sm font-mono text-ink-0">{generated}</code>
                            </div>
                        )}

                        {/* Results table */}
                        {result && result.rows && result.rows.length > 0 && (
                            <div className="bg-white border border-surface-3 rounded-lg overflow-auto max-h-[400px]">
                                <table className="w-full text-sm">
                                    <thead className="sticky top-0 bg-surface-1 border-b border-surface-3">
                                        <tr>
                                            {(result.columns || []).map((col) => (
                                                <th key={col} className="text-left px-3 py-2 text-xs font-medium text-ink-2 uppercase tracking-wider whitespace-nowrap">{col}</th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-surface-3">
                                        {result.rows.map((row, i) => (
                                            <tr key={i} className="hover:bg-surface-1">
                                                {(result.columns || []).map((col) => (
                                                    <td key={col} className="px-3 py-2 whitespace-nowrap text-ink-1">{String(row[col] ?? "")}</td>
                                                ))}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}

                        {/* Error */}
                        {result?.error && (
                            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{result.error}</div>
                        )}
                    </div>

                    {/* Tables sidebar */}
                    <div>
                        <h3 className="text-sm font-semibold text-ink-0 mb-3">Tablas disponibles</h3>
                        <div className="space-y-2">
                            {tables.map((t) => (
                                <div key={t.name} className="bg-white border border-surface-3 rounded-lg p-3">
                                    <div className="flex items-center justify-between mb-1">
                                        <span className="text-sm font-medium text-ink-0">{t.name}</span>
                                        <span className="text-xs text-ink-3">{t.row_count} filas</span>
                                    </div>
                                    <div className="flex flex-wrap gap-1">
                                        {t.columns.map((c) => (
                                            <span key={c.name} className="text-xs bg-surface-2 text-ink-2 px-1.5 py-0.5 rounded">{c.name}</span>
                                        ))}
                                    </div>
                                </div>
                            ))}
                            {tables.length === 0 && <div className="text-sm text-ink-3">No hay tablas cargadas.</div>}
                        </div>
                    </div>
                </div>
            </div>
        </section>
    );
}
