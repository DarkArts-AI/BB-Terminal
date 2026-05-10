const BASE = "/api/v1/narrative";

async function nGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || res.statusText);
  return body as T;
}

export const REFETCH_NARRATIVE = 30_000;

export interface WatchlistSummary {
  per_agent: Record<string, { total: number; high: number; medium: number; low: number }>;
  total_unique_symbols: number;
  overlap: { alpha_bravo: string[]; alpha_charlie: string[]; bravo_charlie: string[]; triple: string[] };
  top_convergence: { symbol: string; agent_count: number; agents: string[] }[];
  timestamp: string;
}

export interface WatchlistEntry {
  symbol: string; priority: string; source: string | null;
  thesis_summary: string | null; catalyst_date: string | null;
  last_analyzed: string | null; added_at: string | null;
}

export interface AgentWatchlist {
  agent: string; entries: WatchlistEntry[]; count: number;
}

export interface KPIs {
  watchlist_snapshots: Record<string, {
    snapshot_date: string; active_count: number;
    high_priority: number; medium_priority: number; low_priority: number;
    additions_7d: number; removals_7d: number; cycles_24h: number;
  }>;
  pipeline_cycles_24h: Record<string, number>;
  unique_symbols_all_time: Record<string, number>;
  unique_symbols_7d: Record<string, number>;
  timestamp: string;
}

export interface CoverageMap {
  per_agent: Record<string, string[]>;
  venn: {
    alpha_only: string[]; bravo_only: string[]; charlie_only: string[];
    alpha_bravo: string[]; alpha_charlie: string[]; bravo_charlie: string[];
    all_three: string[];
  };
  convergence_alerts: string[];
  timestamp: string;
}

export interface ConversationData {
  cycle: Record<string, unknown>;
  stages: Array<{
    stage: string; sub_stage: string; speaker_role: string;
    content: unknown; timestamp: string | null;
  }>;
  debate_rounds: Array<{
    debate_type: string; round_number: number; speaker_role: string;
    content: string; timestamp: string | null;
  }>;
  decision: Record<string, unknown> | null;
  trades: Array<{ symbol: string; side: string; qty: number; price: number; time: string | null; status: string }>;
}

export const fetchWatchlistSummary = () => nGet<WatchlistSummary>("/watchlist");
export const fetchAgentWatchlist = (agent: string) => nGet<AgentWatchlist>(`/watchlist/${agent}`);
export const fetchKPIs = () => nGet<KPIs>("/kpis");
export const fetchCoverageMap = () => nGet<CoverageMap>("/coverage-map");
export const fetchConversation = (cycleId: string) => nGet<ConversationData>(`/conversation/${cycleId}`);

// Report PDF downloads
const REPORT_BASE = "/api/v1/reports";

export function downloadCyclePdf(cycleId: string) {
  window.open(`${REPORT_BASE}/cycle/${cycleId}`, "_blank");
}

export function downloadCoveragePdf() {
  window.open(`${REPORT_BASE}/coverage`, "_blank");
}

export function downloadCaseStudyPdf(symbol: string) {
  window.open(`${REPORT_BASE}/case-study/${symbol}`, "_blank");
}
