"use client";

import { useState, useMemo } from "react";
import * as api from "@/lib/api";
import type { SearchResult, SearchFacets, GroupedResult, DocListItem } from "@/lib/types";
import type { SearchFilters } from "@/lib/api";
import { formatScore, formatHighlight, formatDateFacet, langLabel, typeColor } from "@/lib/utils";

interface Props {
    onViewDoc: (docId: string) => void;
    documents: DocListItem[];
}

function groupResults(results: SearchResult[]): GroupedResult[] {
    const map = new Map<string, GroupedResult>();
    for (const r of results) {
        if (!map.has(r.doc_id)) {
            map.set(r.doc_id, {
                doc_id: r.doc_id, title: r.title, filename: r.filename, doc_type: r.doc_type,
                chunks: [], best_score: 0, best_lexical: 0, best_semantic: 0,
                persons: [], organizations: [], expanded: false,
            });
        }
        const g = map.get(r.doc_id)!;
        g.chunks.push(r);
        const fused = r.scores?.fused ?? r.score ?? 0;
        if (fused > g.best_score) g.best_score = fused;
        const lex = r.scores?.whoosh_component ?? r.scores?.whoosh_norm ?? r.scores?.whoosh ?? 0;
        if (lex > g.best_lexical) g.best_lexical = lex;
        const sem = r.scores?.chroma_component ?? r.scores?.chroma_norm ?? r.scores?.chroma ?? 0;
        if (sem > g.best_semantic) g.best_semantic = sem;
        for (const p of r.persons || []) if (!g.persons.includes(p)) g.persons.push(p);
        for (const o of r.organizations || []) if (!g.organizations.includes(o)) g.organizations.push(o);
    }
    return Array.from(map.values());
}

export function SearchTab({ onViewDoc, documents }: Props) {
    const [query, setQuery] = useState("");
    const [lastQuery, setLastQuery] = useState("");
    const [results, setResults] = useState<SearchResult[]>([]);
    const [facets, setFacets] = useState<SearchFacets | null>(null);
    const [filters, setFilters] = useState<SearchFilters>({});
    const [grouped, setGrouped] = useState<GroupedResult[]>([]);

    // Document browser filters (always visible in sidebar)
    const [browseType, setBrowseType] = useState("");
    const [browseCategory, setBrowseCategory] = useState("");

    const docTypes = useMemo(() => [...new Set(documents.map((d) => d.doc_type).filter(Boolean))].sort(), [documents]);
    const categories = useMemo(() => [...new Set(documents.map((d) => d.category).filter(Boolean))].sort(), [documents]);

    const isSearchMode = lastQuery.length > 0;

    // Type/category counts for sidebar
    const typeCounts = useMemo(() => {
        const counts: Record<string, number> = {};
        for (const d of documents) if (d.doc_type) counts[d.doc_type] = (counts[d.doc_type] || 0) + 1;
        return counts;
    }, [documents]);
    const categoryCounts = useMemo(() => {
        const counts: Record<string, number> = {};
        for (const d of documents) if (d.category) counts[d.category] = (counts[d.category] || 0) + 1;
        return counts;
    }, [documents]);

    // Browsed docs when not searching (filtered by sidebar selections)
    const browsed = useMemo(() => {
        let docs = [...documents];
        if (browseType) docs = docs.filter((d) => d.doc_type === browseType);
        if (browseCategory) docs = docs.filter((d) => d.category === browseCategory);
        docs.sort((a, b) => (a.title || a.filename).localeCompare(b.title || b.filename));
        return docs;
    }, [documents, browseType, browseCategory]);

    async function doSearch(overrideFilters?: SearchFilters) {
        const q = query.trim();
        if (!q) return;
        const f = overrideFilters ?? filters;
        try {
            const data = await api.search(q, f);
            setResults(data.results || []);
            setFacets(data.facets || null);
            setLastQuery(q);
            setGrouped(groupResults(data.results || []));
        } catch {
            setResults([]);
            setFacets(null);
            setGrouped([]);
        }
    }

    function toggleFilter(key: keyof SearchFilters, value: string) {
        const next = { ...filters, [key]: filters[key] === value ? "" : value };
        setFilters(next);
        doSearch(next);
    }

    function clearSearch() {
        setLastQuery("");
        setResults([]);
        setGrouped([]);
        setFacets(null);
        setQuery("");
        setFilters({});
    }

    const hasFilters = Object.values(filters).some(Boolean);

    function toggleExpand(docId: string) {
        setGrouped((prev) => prev.map((g) => (g.doc_id === docId ? { ...g, expanded: !g.expanded } : g)));
    }

    return (
        <section className="fade-in">
            <div className="max-w-6xl mx-auto">
                {/* Search bar */}
                <div className="mb-5">
                    <form onSubmit={(e) => { e.preventDefault(); doSearch(); }} className="flex gap-2">
                        <div className="flex-1 relative">
                            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                            </svg>
                            <input value={query} onChange={(e) => setQuery(e.target.value)}
                                placeholder="Buscar en documentos..."
                                className="w-full pl-10 pr-4 py-2.5 text-sm border border-surface-3 rounded-lg bg-white focus:border-brand-400 focus:ring-2 focus:ring-brand-100 outline-none transition-all" />
                        </div>
                        <button type="submit" disabled={!query.trim()}
                            className="px-5 py-2.5 bg-brand-600 hover:bg-brand-700 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors">
                            Buscar
                        </button>
                        {isSearchMode && (
                            <button type="button" onClick={clearSearch}
                                className="px-3 py-2.5 text-sm text-ink-2 hover:text-ink-0 border border-surface-3 rounded-lg hover:bg-surface-1 transition-colors">
                                ✕
                            </button>
                        )}
                    </form>

                    {/* Active search filters */}
                    {hasFilters && (
                        <div className="flex flex-wrap items-center gap-2 mt-3">
                            <span className="text-xs text-ink-3">Filtros:</span>
                            {filters.type && <FilterBadge label={`Tipo: ${filters.type}`} color="purple" onClear={() => toggleFilter("type", filters.type!)} />}
                            {filters.language && <FilterBadge label={`Idioma: ${filters.language}`} color="cyan" onClear={() => toggleFilter("language", filters.language!)} />}
                            {filters.person && <FilterBadge label={`Persona: ${filters.person}`} color="green" onClear={() => toggleFilter("person", filters.person!)} />}
                            {filters.organization && <FilterBadge label={`Org: ${filters.organization}`} color="blue" onClear={() => toggleFilter("organization", filters.organization!)} />}
                            {filters.date && <FilterBadge label={`Fecha: ${filters.date}`} color="amber" onClear={() => toggleFilter("date", filters.date!)} />}
                            <button onClick={() => { setFilters({}); doSearch({}); }} className="text-xs text-red-500 hover:text-red-700 font-medium">Limpiar</button>
                        </div>
                    )}
                </div>

                {/* Main layout: sidebar + content (always) */}
                <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
                    {/* ─── Sidebar (always visible) ──────────────── */}
                    <div className="lg:col-span-1 space-y-3">
                        {/* Status */}
                        <div className="bg-white border border-surface-3 rounded-lg p-3">
                            <div className="flex items-center justify-between mb-1">
                                <h4 className="text-xs font-semibold text-ink-2 uppercase tracking-wider">Documentos</h4>
                                <span className="text-xs text-ink-3 tabular-nums">{documents.length}</span>
                            </div>
                            {isSearchMode && (
                                <div className="text-xs text-brand-600 font-medium mt-1">
                                    {grouped.length} resultado{grouped.length !== 1 ? "s" : ""} · {results.length} fragmento{results.length !== 1 ? "s" : ""}
                                </div>
                            )}
                            {!isSearchMode && (browseType || browseCategory) && (
                                <div className="text-xs text-ink-2 mt-1">Mostrando {browsed.length} de {documents.length}</div>
                            )}
                        </div>

                        {/* Dynamic facets from search results */}
                        {isSearchMode && facets && (
                            <>
                                <FacetBlock title="Tipo" items={facets.doc_type} activeValue={filters.type}
                                    onToggle={(v) => toggleFilter("type", v)}
                                    renderLabel={(v) => <span className={`inline-flex px-1.5 py-0.5 rounded text-xs ${typeColor(v)}`}>{v}</span>} />
                                <FacetBlock title="Idioma" items={facets.language} activeValue={filters.language}
                                    onToggle={(v) => toggleFilter("language", v)} renderLabel={(v) => <span>{langLabel(v)}</span>} />
                                <FacetBlock title="Fecha" items={facets.dates} activeValue={filters.date}
                                    onToggle={(v) => toggleFilter("date", v)} renderLabel={(v) => <span className="truncate">{formatDateFacet(v)}</span>} />
                                <FacetBlock title="Personas" items={facets.persons} activeValue={filters.person}
                                    onToggle={(v) => toggleFilter("person", v)} renderLabel={(v) => <span className="truncate">{v}</span>} />
                                <FacetBlock title="Organizaciones" items={facets.organizations} activeValue={filters.organization}
                                    onToggle={(v) => toggleFilter("organization", v)} renderLabel={(v) => <span className="truncate">{v}</span>} />
                                {facets.keywords && facets.keywords.length > 0 && (
                                    <div className="bg-white border border-surface-3 rounded-lg p-3">
                                        <h4 className="text-xs font-semibold text-ink-2 uppercase tracking-wider mb-2">Palabras clave</h4>
                                        <div className="flex flex-wrap gap-1">
                                            {facets.keywords.map((f) => (
                                                <span key={f.value} className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-surface-2 text-ink-2">
                                                    {f.value} ({f.count})
                                                </span>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </>
                        )}

                        {/* Static filters when browsing (no search) */}
                        {!isSearchMode && (
                            <>
                                <div className="bg-white border border-surface-3 rounded-lg p-3">
                                    <h4 className="text-xs font-semibold text-ink-2 uppercase tracking-wider mb-2">Tipo de documento</h4>
                                    <div className="space-y-0.5 max-h-40 overflow-y-auto">
                                        {docTypes.map((t) => (
                                            <button key={t} onClick={() => setBrowseType(browseType === t ? "" : t)}
                                                className={`w-full flex items-center justify-between px-2 py-1 rounded text-sm transition-colors ${browseType === t ? "bg-brand-50 text-brand-700 font-medium" : "text-ink-1 hover:bg-surface-2"}`}>
                                                <span className={`inline-flex px-1.5 py-0.5 rounded text-xs ${typeColor(t)}`}>{t}</span>
                                                <span className="text-xs text-ink-3 tabular-nums">{typeCounts[t] || 0}</span>
                                            </button>
                                        ))}
                                    </div>
                                </div>
                                <div className="bg-white border border-surface-3 rounded-lg p-3">
                                    <h4 className="text-xs font-semibold text-ink-2 uppercase tracking-wider mb-2">Categoría</h4>
                                    <div className="space-y-0.5 max-h-40 overflow-y-auto">
                                        {categories.map((c) => (
                                            <button key={c} onClick={() => setBrowseCategory(browseCategory === c ? "" : c)}
                                                className={`w-full flex items-center justify-between px-2 py-1 rounded text-sm transition-colors ${browseCategory === c ? "bg-brand-50 text-brand-700 font-medium" : "text-ink-1 hover:bg-surface-2"}`}>
                                                <span className="truncate">{c}</span>
                                                <span className="text-xs text-ink-3 tabular-nums">{categoryCounts[c] || 0}</span>
                                            </button>
                                        ))}
                                    </div>
                                </div>
                                {(browseType || browseCategory) && (
                                    <button onClick={() => { setBrowseType(""); setBrowseCategory(""); }}
                                        className="w-full text-xs text-red-500 hover:text-red-700 font-medium py-1 transition-colors">
                                        Limpiar filtros
                                    </button>
                                )}
                            </>
                        )}
                    </div>

                    {/* ─── Content area ───────────────────────────── */}
                    <div className="lg:col-span-3">
                        {/* Search results */}
                        {isSearchMode && (
                            <>
                                {grouped.length > 0 && (
                                    <div className="space-y-3">
                                        {grouped.map((group) => (
                                            <ResultCard key={group.doc_id} group={group} onView={onViewDoc} onToggle={toggleExpand} />
                                        ))}
                                    </div>
                                )}
                                {results.length === 0 && lastQuery && (
                                    <div className="text-center py-16 text-ink-3 text-sm">
                                        Sin resultados para &quot;{lastQuery}&quot;
                                    </div>
                                )}
                            </>
                        )}

                        {/* Document listing (no search active) */}
                        {!isSearchMode && (
                            <div className="space-y-1.5">
                                {browsed.length > 0 ? browsed.map((doc) => (
                                    <div key={doc.doc_id} onClick={() => onViewDoc(doc.doc_id)}
                                        className="flex items-center gap-3 px-4 py-3 bg-white border border-surface-3 rounded-lg hover:border-brand-200 hover:shadow-sm transition-all cursor-pointer group">
                                        <svg className="w-4 h-4 text-ink-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                        </svg>
                                        <div className="flex-1 min-w-0">
                                            <div className="text-sm font-medium text-ink-0 truncate group-hover:text-brand-700 transition-colors">
                                                {doc.title || doc.filename}
                                            </div>
                                            <div className="text-xs text-ink-3 truncate">{doc.filename}</div>
                                        </div>
                                        <span className={`shrink-0 inline-flex px-2 py-0.5 rounded text-xs font-medium ${typeColor(doc.doc_type)}`}>
                                            {doc.doc_type}
                                        </span>
                                        {doc.category && <span className="hidden sm:inline text-xs text-ink-3">{doc.category}</span>}
                                    </div>
                                )) : (
                                    <div className="text-center py-16 text-sm text-ink-3">Sin documentos.</div>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </section>
    );
}

/* ─── Sub-components ────────────────────────────────────────────── */

function FilterBadge({ label, color, onClear }: { label: string; color: string; onClear: () => void }) {
    return (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-${color}-50 text-${color}-700`}>
            {label}
            <button onClick={onClear} className={`hover:text-${color}-900`}>&times;</button>
        </span>
    );
}

function FacetBlock({ title, items, activeValue, onToggle, renderLabel }: {
    title: string; items?: { value: string; count: number }[]; activeValue?: string;
    onToggle: (v: string) => void; renderLabel: (v: string) => React.ReactNode;
}) {
    if (!items || items.length === 0) return null;
    return (
        <div className="bg-white border border-surface-3 rounded-lg p-3">
            <h4 className="text-xs font-semibold text-ink-2 uppercase tracking-wider mb-2">{title}</h4>
            <div className="space-y-1 max-h-40 overflow-y-auto">
                {items.map((f) => (
                    <button key={f.value} onClick={() => onToggle(f.value)}
                        className={`w-full flex items-center justify-between px-2 py-1 rounded text-sm transition-colors ${activeValue === f.value ? "bg-brand-50 text-brand-700 font-medium" : "text-ink-1 hover:bg-surface-2"}`}>
                        <div className="flex items-center gap-2">{renderLabel(f.value)}</div>
                        <span className="text-xs text-ink-3 font-mono">{f.count}</span>
                    </button>
                ))}
            </div>
        </div>
    );
}

function ResultCard({ group, onView, onToggle }: { group: GroupedResult; onView: (id: string) => void; onToggle: (id: string) => void }) {
    const first = group.chunks[0];
    return (
        <div className="bg-white border border-surface-3 rounded-lg hover:border-brand-200 hover:shadow-sm transition-all fade-in overflow-hidden">
            <div className="p-4 cursor-pointer" onClick={() => onView(group.doc_id)}>
                <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                        <h3 className="text-sm font-semibold text-ink-0 truncate">{group.title || group.filename}</h3>
                        <div className="flex items-center gap-2 mt-1">
                            <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${typeColor(group.doc_type)}`}>{group.doc_type}</span>
                            <span className="text-xs text-ink-3">{group.filename}</span>
                            <span className="text-xs text-ink-3">&middot; {group.chunks.length} coincidencia{group.chunks.length > 1 ? "s" : ""}</span>
                        </div>
                    </div>
                    <div className="shrink-0 flex items-center gap-1.5">
                        <div className="w-20 h-1.5 bg-surface-2 rounded-full overflow-hidden" title={`Relevancia: ${formatScore(group.best_score)}`}>
                            <div className="h-full bg-brand-500 rounded-full" style={{ width: `${Math.min(group.best_score * 100, 100)}%` }} />
                        </div>
                        <span className="text-[11px] font-semibold text-brand-700 tabular-nums">{formatScore(group.best_score)}</span>
                    </div>
                </div>

                {/* Score breakdown */}
                <div className="mt-2 flex items-center gap-3">
                    {group.best_lexical > 0 && (
                        <div className="flex items-center gap-1">
                            <span className="text-[10px] text-ink-3 font-medium">Lex</span>
                            <div className="w-12 h-1 bg-surface-2 rounded-full overflow-hidden">
                                <div className="h-full bg-emerald-400 rounded-full" style={{ width: `${Math.min(group.best_lexical * 100 / 0.55, 100)}%` }} />
                            </div>
                            <span className="text-[10px] text-ink-3 tabular-nums">{formatScore(group.best_lexical)}</span>
                        </div>
                    )}
                    {group.best_semantic > 0 && (
                        <div className="flex items-center gap-1">
                            <span className="text-[10px] text-ink-3 font-medium">Sem</span>
                            <div className="w-12 h-1 bg-surface-2 rounded-full overflow-hidden">
                                <div className="h-full bg-violet-400 rounded-full" style={{ width: `${Math.min(group.best_semantic * 100 / 0.45, 100)}%` }} />
                            </div>
                            <span className="text-[10px] text-ink-3 tabular-nums">{formatScore(group.best_semantic)}</span>
                        </div>
                    )}
                    {first?.source === "hybrid" && <span className="text-[10px] text-brand-600 font-medium">Híbrido</span>}
                    {first?.source === "lexical" && <span className="text-[10px] text-emerald-600 font-medium">Léxico</span>}
                    {first?.source === "semantic" && <span className="text-[10px] text-violet-600 font-medium">Semántico</span>}
                </div>

                <p className="mt-2 text-sm text-ink-1 leading-relaxed line-clamp-2"
                    dangerouslySetInnerHTML={{ __html: formatHighlight(first?.highlight || first?.text || "") }} />

                {/* Entity tags */}
                {(group.persons.length > 0 || group.organizations.length > 0) && (
                    <div className="flex flex-wrap gap-1 mt-2">
                        {group.persons.slice(0, 3).map((p) => (
                            <span key={p} className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-green-50 text-green-700">{p}</span>
                        ))}
                        {group.organizations.slice(0, 3).map((o) => (
                            <span key={o} className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-blue-50 text-blue-700">{o}</span>
                        ))}
                    </div>
                )}
                {first?.why_this_result && (
                    <p className="mt-1 text-[11px] leading-relaxed text-ink-2">{first.why_this_result}</p>
                )}
            </div>

            {/* Expandable chunks */}
            <div className="border-t border-surface-3">
                <button onClick={(e) => { e.stopPropagation(); onToggle(group.doc_id); }}
                    className="w-full px-4 py-2 flex items-center justify-between text-xs text-brand-600 hover:bg-surface-1 transition-colors">
                    <span>
                        {group.expanded
                            ? (group.chunks.length > 1 ? "Ocultar fragmentos" : "Ocultar texto completo")
                            : (group.chunks.length > 1 ? `Ver ${group.chunks.length - 1} fragmento${group.chunks.length > 2 ? "s" : ""} más` : "Ver texto completo")}
                    </span>
                    <svg className={`w-3 h-3 transition-transform ${group.expanded ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                </button>
                {group.expanded && (
                    <div className="px-4 pb-3 space-y-2">
                        {group.chunks.length > 1
                            ? group.chunks.slice(1).map((chunk, ci) => (
                                <div key={chunk.chunk_id} className="bg-surface-1 rounded-lg p-3">
                                    <div className="flex items-center gap-2 mb-1">
                                        <span className="text-[10px] font-mono text-ink-3">#{ci + 2}</span>
                                        {chunk.section && <span className="text-xs text-ink-2">{chunk.section}</span>}
                                        <span className="text-[10px] text-ink-3 ml-auto tabular-nums">{formatScore(chunk.scores?.fused ?? chunk.score)}</span>
                                    </div>
                                    <p className="text-sm text-ink-1 leading-relaxed line-clamp-3"
                                        dangerouslySetInnerHTML={{ __html: formatHighlight(chunk.highlight || chunk.text) }} />
                                </div>
                            ))
                            : <p className="text-sm text-ink-1 leading-relaxed whitespace-pre-wrap">{first?.text}</p>
                        }
                    </div>
                )}
            </div>
        </div>
    );
}
