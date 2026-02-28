/**
 * api.ts — Thin wrapper around fetch() for calling the FastAPI backend.
 *
 * In dev, Next.js rewrites /api/* to http://localhost:8000/api/* (see next.config.ts).
 * In production the backend URL can be set via NEXT_PUBLIC_API_URL.
 */

class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
        super(message);
        this.status = status;
    }
}

async function request<T>(url: string, opts: RequestInit = {}): Promise<T> {
    // cache: "no-store" disables Next.js's built-in fetch caching so every call
    // hits the live backend (important after uploads/ingest).
    const res = await fetch(url, { cache: "no-store", ...opts });
    if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new ApiError(body.detail || res.statusText, res.status);
    }
    return res.json() as Promise<T>;
}

// ─── Search ──────────────────────────────────────────────────────
import type {
    SearchResponse,
    DocListItem,
    DocDetail,
    SqlTable,
    SqlResult,
    EntityItem,
    EntityDetail,
    GraphData,
    Community,
    Broker,
    PathResult,
    DuplicatePair,
    IngestStatus,
    UploadResult,
    Stats,
    ClusterResult,
} from "./types";

export interface SearchFilters {
    type?: string;
    language?: string;
    person?: string;
    organization?: string;
    date?: string;
}

export async function search(query: string, filters: SearchFilters = {}, topK = 30): Promise<SearchResponse> {
    const p = new URLSearchParams({ q: query, top_k: String(topK) });
    if (filters.type) p.set("type", filters.type);
    if (filters.language) p.set("language", filters.language);
    if (filters.person) p.set("person", filters.person);
    if (filters.organization) p.set("organization", filters.organization);
    if (filters.date) p.set("date", filters.date);
    return request<SearchResponse>(`/api/search?${p}`);
}

// ─── Documents ───────────────────────────────────────────────────
export async function listDocuments(): Promise<DocListItem[]> {
    const d = await request<{ documents: DocListItem[] }>("/api/documents");
    return d.documents || [];
}

export async function getDocument(docId: string): Promise<DocDetail> {
    return request<DocDetail>(`/api/documents/${docId}`);
}

export async function summarizeDocument(docId: string): Promise<string> {
    const d = await request<{ summary: string }>(`/api/documents/${docId}/summary`, { method: "POST" });
    return d.summary;
}

export async function getDocumentRaw(docId: string): Promise<string> {
    const d = await request<{ text: string }>(`/api/documents/${docId}/raw`);
    return d.text;
}

export function getDocumentFileUrl(docId: string): string {
    return `/api/documents/${docId}/file`;
}

export async function getDocumentTable(docId: string): Promise<{ columns: string[]; rows: unknown[][]; total_rows: number; filename: string }> {
    return request(`/api/documents/${docId}/table`);
}

// ─── SQL ─────────────────────────────────────────────────────────
export async function listSqlTables(): Promise<SqlTable[]> {
    const d = await request<{ tables: SqlTable[] }>("/api/sql/tables");
    return d.tables || [];
}

export async function sqlAsk(question: string): Promise<SqlResult> {
    return request<SqlResult>("/api/sql/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
    });
}

export async function sqlExec(query: string): Promise<SqlResult> {
    return request<SqlResult>("/api/sql/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
    });
}

// ─── Graph ───────────────────────────────────────────────────────
export async function getGraphData(entityType?: string, docId?: string): Promise<GraphData> {
    const p = new URLSearchParams();
    if (entityType) p.set("entity_type", entityType);
    if (docId) p.set("doc_id", docId);
    return request<GraphData>(`/api/graph${p.toString() ? "?" + p : ""}`);
}

export async function listEntities(): Promise<EntityItem[]> {
    const d = await request<{ entities: EntityItem[] }>("/api/graph/entities");
    return d.entities || [];
}

export async function getEntityDetail(name: string): Promise<EntityDetail> {
    return request<EntityDetail>(`/api/graph/entity/${encodeURIComponent(name)}`);
}

export async function searchEntities(q: string): Promise<EntityItem[]> {
    const d = await request<{ entities: EntityItem[] }>(`/api/graph/search?q=${encodeURIComponent(q)}`);
    return d.entities || [];
}

export async function findPath(from: string, to: string): Promise<PathResult> {
    const p = new URLSearchParams({ from, to });
    return request<PathResult>(`/api/graph/path?${p}`);
}

export async function listCommunities(): Promise<Community[]> {
    const d = await request<{ communities: Community[] }>("/api/graph/communities");
    return d.communities || [];
}

export async function listBrokers(topK = 10): Promise<Broker[]> {
    const d = await request<{ brokers: Broker[] }>(`/api/graph/brokers?top_k=${topK}`);
    return d.brokers || [];
}

// ─── Duplicates ──────────────────────────────────────────────────
export async function findDuplicates(threshold = 0.85): Promise<DuplicatePair[]> {
    const d = await request<{ duplicates: DuplicatePair[] }>(`/api/duplicates?threshold=${threshold}`);
    return d.duplicates || [];
}

// ─── Clustering ──────────────────────────────────────────────────
export async function clusterDocuments(nClusters?: number): Promise<ClusterResult> {
    const p = new URLSearchParams();
    if (nClusters != null) p.set("n_clusters", String(nClusters));
    return request<ClusterResult>(`/api/documents/clusters${p.toString() ? "?" + p : ""}`);
}

// ─── Ingest & Upload ─────────────────────────────────────────────
export async function startIngest(): Promise<{ status: string; running: boolean }> {
    return request("/api/ingest", { method: "POST" });
}

export async function getIngestStatus(): Promise<IngestStatus> {
    return request<IngestStatus>("/api/ingest/status");
}

export async function uploadFile(file: File): Promise<UploadResult> {
    const fd = new FormData();
    fd.append("file", file);
    return request<UploadResult>("/api/upload", { method: "POST", body: fd });
}

// ─── Agent ───────────────────────────────────────────────────────
export async function agentAsk(question: string, sessionId: string) {
    return request<{
        answer: string;
        sources?: { filename: string }[];
        steps?: { tool: string; args: Record<string, string> }[];
    }>("/api/agent/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, session_id: sessionId }),
    });
}

// ─── Stats ───────────────────────────────────────────────────────
export async function getStats(): Promise<Stats> {
    return request<Stats>("/api/stats");
}

export { ApiError };
