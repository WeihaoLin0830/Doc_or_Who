"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import * as api from "@/lib/api";
import { typeColor } from "@/lib/utils";
import type {
  DocListItem, EntityItem, EntityDetail,
  GraphData, Community, Broker, PathResult,
} from "@/lib/types";

interface Props {
  entities: EntityItem[];
  documents: DocListItem[];
}

export function GraphTab({ entities, documents }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  const [filterType, setFilterType] = useState("");
  const [filterDoc, setFilterDoc] = useState("");

  const [communities, setCommunities] = useState<Community[]>([]);
  const [brokers, setBrokers] = useState<Broker[]>([]);
  const [entityDetail, setEntityDetail] = useState<EntityDetail | null>(null);

  // Path finder
  const [pathFrom, setPathFrom] = useState("");
  const [pathTo, setPathTo] = useState("");
  const [pathResult, setPathResult] = useState<PathResult | null>(null);
  const [suggestionsA, setSuggestionsA] = useState<EntityItem[]>([]);
  const [suggestionsB, setSuggestionsB] = useState<EntityItem[]>([]);

  /* ── vis-network (loaded dynamically to avoid SSR issues) ── */
  const networkRef = useRef<unknown>(null);
  const visRef = useRef<{ Network: unknown; DataSet: unknown } | null>(null);

  const renderGraph = useCallback(async () => {
    if (!containerRef.current) return;

    // Lazy-load vis-network
    if (!visRef.current) {
      const vis = await import("vis-network/standalone");
      visRef.current = vis as unknown as { Network: unknown; DataSet: unknown };
    }
    const vis = visRef.current as Record<string, unknown>;

    try {
      const data: GraphData = await api.getGraphData(filterType, filterDoc);

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const Network = (vis as any).Network;
      const network = new Network(containerRef.current, data, {
        nodes: {
          shape: "dot",
          font: { size: 12, face: "Inter", color: "#334155" },
          borderWidth: 0,
          scaling: { min: 8, max: 28 },
        },
        edges: {
          color: { color: "#cbd5e1", highlight: "#3b82f6" },
          smooth: { type: "continuous" },
          scaling: { min: 1, max: 4 },
        },
        physics: {
          solver: "forceAtlas2Based",
          forceAtlas2Based: { gravitationalConstant: -40, centralGravity: 0.005, springLength: 120 },
          stabilization: { iterations: 100 },
        },
        interaction: { hover: true, tooltipDelay: 100 },
      });

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      network.on("click", (params: any) => {
        if (params.nodes.length > 0) {
          const nodeId = params.nodes[0];
          const node = data.nodes.find((n) => n.id === nodeId);
          if (node) showEntity(node.label || node.id);
        }
      });

      networkRef.current = network;
    } catch { /* ignore */ }
  }, [filterType, filterDoc]);

  // Render graph on mount and when filters change
  useEffect(() => { renderGraph(); }, [renderGraph]);

  // Load communities & brokers once
  useEffect(() => {
    api.listCommunities().then(setCommunities).catch(() => {});
    api.listBrokers().then(setBrokers).catch(() => {});
  }, []);

  /* ── Entity detail ── */
  async function showEntity(name: string) {
    try { setEntityDetail(await api.getEntityDetail(name)); } catch { /* ignore */ }
  }

  /* ── Path finder ── */
  async function findPath() {
    if (!pathFrom.trim() || !pathTo.trim()) return;
    setSuggestionsA([]);
    setSuggestionsB([]);
    try { setPathResult(await api.findPath(pathFrom.trim(), pathTo.trim())); }
    catch (e) { setPathResult({ found: false, error: e instanceof Error ? e.message : "Error" }); }
  }

  async function fetchSuggestions(q: string, side: "A" | "B") {
    if (!q.trim()) { side === "A" ? setSuggestionsA([]) : setSuggestionsB([]); return; }
    try {
      const items = await api.searchEntities(q.trim());
      side === "A" ? setSuggestionsA(items) : setSuggestionsB(items);
    } catch { /* ignore */ }
  }

  function resetFilters() {
    setFilterType("");
    setFilterDoc("");
  }

  return (
    <section className="fade-in">
      <div className="max-w-6xl mx-auto">
        {/* Header & filters */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <div>
            <h2 className="text-lg font-semibold">Grafo de Entidades</h2>
            <p className="text-sm text-ink-2">Relaciones entre personas y organizaciones</p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <select value={filterType} onChange={(e) => setFilterType(e.target.value)}
              className="px-2 py-1.5 text-sm border border-surface-3 rounded-lg bg-white focus:border-brand-400 outline-none">
              <option value="">Todas las entidades</option>
              <option value="person">Solo personas</option>
              <option value="organization">Solo organizaciones</option>
            </select>
            <select value={filterDoc} onChange={(e) => setFilterDoc(e.target.value)}
              className="px-2 py-1.5 text-sm border border-surface-3 rounded-lg bg-white focus:border-brand-400 outline-none max-w-[200px]">
              <option value="">Todos los documentos</option>
              {documents.map((doc) => (
                <option key={doc.doc_id} value={doc.doc_id}>{doc.title || doc.filename}</option>
              ))}
            </select>
            {(filterType || filterDoc) && (
              <button onClick={resetFilters} className="text-xs text-red-500 hover:text-red-700 font-medium">Reset</button>
            )}
          </div>
        </div>

        {/* Graph + entity sidebar */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          <div className="lg:col-span-3 bg-white border border-surface-3 rounded-lg" style={{ height: 500 }}>
            <div ref={containerRef} className="w-full h-full rounded-lg" />
          </div>

          {/* Entity list */}
          <div className="space-y-2 max-h-[500px] overflow-y-auto">
            <h3 className="text-sm font-semibold text-ink-0 sticky top-0 bg-surface-1 py-1">Entidades</h3>
            {entities.map((e) => (
              <div key={e.name} onClick={() => showEntity(e.name)}
                className="bg-white border border-surface-3 rounded-lg p-2.5 hover:border-brand-200 transition-colors cursor-pointer">
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${e.type === "person" ? "bg-green-400" : "bg-blue-400"}`} />
                  <span className="text-sm font-medium text-ink-0 truncate">{e.name}</span>
                </div>
                <div className="text-xs text-ink-3 mt-0.5 pl-4">{e.mentions} menciones · {e.num_docs} docs</div>
              </div>
            ))}
          </div>
        </div>

        {/* Community + Brokers */}
        <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Communities */}
          <div className="bg-white border border-surface-3 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-ink-0 mb-3">Comunidades</h3>
            {communities.length === 0 && <p className="text-xs text-ink-3 text-center py-2">Cargando comunidades...</p>}
            <div className="space-y-1.5 max-h-40 overflow-y-auto">
              {communities.map((c) => (
                <div key={c.community_id} className="flex items-start gap-2 text-xs">
                  <span className="w-3 h-3 rounded-full mt-0.5 shrink-0" style={{ backgroundColor: c.color }} />
                  <div>
                    <span className="font-medium text-ink-0">{c.label || `Comunidad ${c.community_id}`}</span>
                    <span className="text-ink-3 ml-1">({c.members.length} entidades)</span>
                    <div className="text-ink-3 truncate max-w-xs">
                      {c.members.slice(0, 4).join(", ")}{c.members.length > 4 ? " ..." : ""}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Brokers */}
          <div className="bg-white border border-surface-3 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-ink-0 mb-3">Brokers de Información</h3>
            {brokers.length === 0 && <p className="text-xs text-ink-3 text-center py-2">Cargando brokers...</p>}
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {brokers.map((b) => (
                <div key={b.name} onClick={() => showEntity(b.name)}
                  className="flex items-center justify-between text-xs cursor-pointer hover:bg-surface-1 rounded px-1 py-0.5">
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${b.type === "person" ? "bg-green-400" : "bg-blue-400"}`} />
                    <span className="font-medium text-ink-0">{b.name}</span>
                  </div>
                  <span className="text-ink-3 tabular-nums">{(b.betweenness * 100).toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Connection Path Finder */}
        <div className="mt-4 bg-white border border-surface-3 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-ink-0 mb-3">¿Qué conecta dos entidades?</h3>
          <form onSubmit={(e) => { e.preventDefault(); findPath(); }} className="flex items-center gap-2">
            {/* Entity A */}
            <AutocompleteInput value={pathFrom} onChange={setPathFrom}
              suggestions={suggestionsA} onSearch={(q) => fetchSuggestions(q, "A")}
              onSelect={(name) => { setPathFrom(name); setSuggestionsA([]); }}
              onDismiss={() => setSuggestionsA([])} placeholder="Entidad A..." />

            <svg className="w-4 h-4 text-ink-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
            </svg>

            {/* Entity B */}
            <AutocompleteInput value={pathTo} onChange={setPathTo}
              suggestions={suggestionsB} onSearch={(q) => fetchSuggestions(q, "B")}
              onSelect={(name) => { setPathTo(name); setSuggestionsB([]); }}
              onDismiss={() => setSuggestionsB([])} placeholder="Entidad B..." />

            <button type="submit" disabled={!pathFrom.trim() || !pathTo.trim()}
              className="px-4 py-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors">
              Buscar conexión
            </button>
          </form>

          {/* Path result */}
          {pathResult && !pathResult.found && (
            <div className="mt-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{pathResult.error}</div>
          )}
          {pathResult?.found && (
            <div className="mt-3 space-y-3">
              <p className="text-xs text-ink-3">
                Camino encontrado en <span className="font-semibold text-ink-0">{pathResult.hops}</span> salto(s):
              </p>
              {/* Path chain */}
              <div className="flex flex-wrap items-center gap-1">
                {(pathResult.path || []).map((node, i) => (
                  <div key={node.name} className="flex items-center gap-1">
                    <span onClick={() => showEntity(node.name)}
                      className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium cursor-pointer hover:opacity-80 transition-opacity ${
                        node.type === "person" ? "bg-green-100 text-green-800" : "bg-blue-100 text-blue-800"
                      }`}>{node.name}</span>
                    {i < (pathResult.path?.length ?? 0) - 1 && (
                      <svg className="w-3 h-3 text-ink-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    )}
                  </div>
                ))}
              </div>
              {/* Connection details */}
              <div className="space-y-2">
                {(pathResult.connections || []).map((conn) => (
                  <div key={conn.from + conn.to} className="bg-surface-1 rounded-lg p-2.5 text-xs">
                    <div className="font-medium text-ink-0 mb-1">
                      {conn.from} <span className="text-ink-3 mx-1">↔</span> {conn.to}
                      <span className="text-brand-600 ml-1">({conn.weight} co-ocurrencias)</span>
                    </div>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {conn.shared_documents.map((doc) => (
                        <span key={doc.doc_id} className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ${typeColor(doc.doc_type)}`}>
                          {doc.title || doc.filename}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Entity detail modal */}
        {entityDetail && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
            onClick={(e) => { if (e.target === e.currentTarget) setEntityDetail(null); }}>
            <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 p-6 fade-in max-h-[80vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <span className={`w-3 h-3 rounded-full ${entityDetail.entity.entity_type === "person" ? "bg-green-400" : "bg-blue-400"}`} />
                  <h3 className="text-lg font-semibold text-ink-0">{entityDetail.entity.name}</h3>
                </div>
                <button onClick={() => setEntityDetail(null)} className="text-ink-3 hover:text-ink-0">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <p className="text-sm text-ink-2 mb-3">{entityDetail.entity.mentions} menciones</p>

              {entityDetail.related.length > 0 && (
                <div className="mb-4">
                  <h4 className="text-xs font-semibold text-ink-2 uppercase tracking-wider mb-2">Relacionadas</h4>
                  <div className="flex flex-wrap gap-1">
                    {entityDetail.related.map((r) => (
                      <span key={r.name} onClick={() => showEntity(r.name)}
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs cursor-pointer hover:opacity-80 ${
                          r.type === "person" ? "bg-green-50 text-green-700" : "bg-blue-50 text-blue-700"
                        }`}>{r.name} ({r.weight})</span>
                    ))}
                  </div>
                </div>
              )}

              {entityDetail.documents.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold text-ink-2 uppercase tracking-wider mb-2">Documentos</h4>
                  <div className="space-y-1">
                    {entityDetail.documents.map((doc) => (
                      <div key={doc.doc_id} className="flex items-center gap-2 text-sm">
                        <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ${typeColor(doc.doc_type)}`}>
                          {doc.doc_type}
                        </span>
                        <span className="text-ink-1">{doc.title || doc.filename}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

/* ── Autocomplete input sub-component ── */
function AutocompleteInput({
  value, onChange, suggestions, onSearch, onSelect, onDismiss, placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  suggestions: EntityItem[];
  onSearch: (q: string) => void;
  onSelect: (name: string) => void;
  onDismiss: () => void;
  placeholder: string;
}) {
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function handleChange(val: string) {
    onChange(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => onSearch(val), 300);
  }

  return (
    <div className="flex-1 relative">
      <input value={value} onChange={(e) => handleChange(e.target.value)}
        onFocus={() => onSearch(value)}
        onKeyDown={(e) => { if (e.key === "Escape") onDismiss(); }}
        placeholder={placeholder}
        className="w-full px-3 py-2 text-sm border border-surface-3 rounded-lg bg-white focus:border-brand-400 outline-none" />
      {suggestions.length > 0 && (
        <ul className="absolute z-20 top-full left-0 right-0 mt-1 bg-white border border-surface-3 rounded-lg shadow-lg max-h-40 overflow-y-auto">
          {suggestions.map((s) => (
            <li key={s.name} onClick={() => onSelect(s.name)}
              className="px-3 py-2 text-sm cursor-pointer hover:bg-surface-1 flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full shrink-0 ${s.type === "person" ? "bg-green-400" : "bg-blue-400"}`} />
              <span>{s.name}</span>
              <span className="text-ink-3 text-xs ml-auto">{s.mentions} menciones</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
