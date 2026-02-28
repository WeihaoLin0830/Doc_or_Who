/* ─── API types mirroring the FastAPI backend ─── */

export interface SearchResult {
    doc_id: string;
    chunk_id: string;
    title: string;
    filename: string;
    doc_type: string;
    text: string;
    highlight?: string;
    section?: string;
    score: number;
    source: "lexical" | "semantic" | "hybrid";
    why_this_result?: string;
    persons: string[];
    organizations: string[];
    scores: {
        fused: number;
        whoosh_component?: number;
        whoosh_norm?: number;
        whoosh?: number;
        chroma_component?: number;
        chroma_norm?: number;
        chroma?: number;
    };
}

export interface FacetItem {
    value: string;
    count: number;
}

export interface SearchFacets {
    doc_type?: FacetItem[];
    language?: FacetItem[];
    dates?: FacetItem[];
    persons?: FacetItem[];
    organizations?: FacetItem[];
    keywords?: FacetItem[];
}

export interface SearchResponse {
    results: SearchResult[];
    facets?: SearchFacets;
}

export interface DocListItem {
    doc_id: string;
    title: string;
    filename: string;
    doc_type: string;
    category: string;
}

export interface DocDetail {
    doc_id: string;
    title: string;
    filename: string;
    doc_type: string;
    language: string;
    summary: string;
    persons: string[];
    organizations: string[];
    keywords: string[];
    dates: string[];
    chunks: { chunk_id: string; text: string; section?: string }[];
}

export interface SqlTable {
    name: string;
    row_count: number;
    columns: { name: string; type: string }[];
}

export interface SqlResult {
    columns: string[];
    rows: Record<string, unknown>[];
    row_count: number;
    error?: string;
    sql?: string;
    question?: string;
}

export interface EntityItem {
    name: string;
    type: string;
    mentions: number;
    num_docs: number;
}

export interface EntityDetail {
    entity: { name: string; entity_type: string; mentions: number };
    related: { name: string; type: string; weight: number }[];
    documents: { doc_id: string; title: string; filename: string; doc_type: string }[];
}

export interface GraphData {
    nodes: { id: string; label: string; group?: string; value?: number; color?: string; title?: string }[];
    edges: { from: string; to: string; value?: number; title?: string }[];
}

export interface Community {
    community_id: number;
    label?: string;
    color: string;
    members: string[];
}

export interface Broker {
    name: string;
    type: string;
    betweenness: number;
}

export interface PathConnection {
    from: string;
    to: string;
    weight: number;
    shared_documents: { doc_id: string; title: string; filename: string; doc_type: string }[];
}

export interface PathResult {
    found: boolean;
    hops?: number;
    path?: { name: string; type: string }[];
    connections?: PathConnection[];
    error?: string;
}

export interface DuplicatePair {
    doc_a: { doc_id: string; title: string; filename: string };
    doc_b: { doc_id: string; title: string; filename: string };
    similarity: number;
}

export interface IngestStatus {
    running: boolean;
    phase: string | null;
    current: number;
    total: number;
    current_file: string;
    docs_processed: number;
    elapsed: number;
    error: string | null;
}

export interface UploadResult {
    status: string;
    filename: string;
    doc_id: string;
    doc_type: string;
    title: string;
    language: string;
    chunks_indexed: number;
}

export interface Stats {
    documents: number;
    entities: number;
    edges: number;
    documents_by_type: Record<string, number>;
    entities_by_type: Record<string, number>;
}

export interface AgentStep {
    tool: string;
    args: Record<string, string>;
}

export interface ChatMessage {
    role: "user" | "assistant";
    content: string;
    sources?: { filename: string }[];
    steps?: AgentStep[];
}

// Grouped search result (frontend-only aggregation)
export interface GroupedResult {
    doc_id: string;
    title: string;
    filename: string;
    doc_type: string;
    chunks: SearchResult[];
    best_score: number;
    best_lexical: number;
    best_semantic: number;
    persons: string[];
    organizations: string[];
    expanded: boolean;
}

// ─── Chat sessions ───────────────────────────────────────────────
export interface ChatSession {
    id: string;
    title: string;
    messages: ChatMessage[];
    createdAt: number;
}

// ─── Document clustering ─────────────────────────────────────────
export interface DocCluster {
    cluster_id: number;
    label: string;
    keywords?: string[];
    categories?: string[];
    documents: DocListItem[];
}

export interface ClusterResult {
    n_clusters: number;
    clusters: DocCluster[];
}
