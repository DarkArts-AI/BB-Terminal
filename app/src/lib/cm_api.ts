/** Cortex-Medusa API client v2 — 60s pseudo-realtime refresh */

const BASE = "/api/v1";

async function cmGet<T>(path: string, params: Record<string, string | number> = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  const res = await fetch(`${BASE}${path}?${qs.toString()}`);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || res.statusText);
  return body.results as T;
}

export interface CompetitionEntry {
  agent: string; color: string; portfolio: string; llm: string;
  nav: number; cash: number; cumulative_return: number; daily_return: number;
  sharpe: number; max_drawdown: number; trade_count: number;
  win_rate: number; as_of: string | null; source: string;
}

export interface PipelineStage {
  stage: string; status: string; last_run: string | null; output: string | null;
}

export interface ResearchNote {
  stage: string; symbol: string | null; title: string | null;
  content: string; source: string | null; time: string;
}

export interface TradeProposal {
  symbol: string; direction: string; rationale: string | null;
  confidence: number | null; holding_period: string | null;
  time: string; status: string;
}

export interface Execution {
  symbol: string; side: string; qty: number; price: number | null;
  order_id: string | null; portfolio: string | null;
  time: string; status: string;
}

export interface Reconciliation {
  portfolio: string; nav: number | null; cash: number | null;
  positions: number | null; drift_pct: number | null;
  notes: string | null; time: string;
}

export interface Position {
  symbol: string; qty: number; avg_entry: number; current_price: number;
  market_value: number; unrealized_pl: number; unrealized_plpc: number;
  change_today: number; side: string;
}

export interface TeamOverview {
  agent: string; color: string; portfolio: string; llm: string;
  cf: string; medusa: string;
  pipeline: PipelineStage[];
  recent_research: ResearchNote[];
  recent_trades: Execution[];
  latest_recon: Reconciliation | null;
  live_nav?: number; live_cash?: number;
}

export interface CompHistory {
  [agent: string]: { date: string; nav: number }[];
}

export const REFETCH = 60_000;

export const fetchCompetition = () => cmGet<CompetitionEntry[]>("/competition");
export const fetchCompHistory = (days = 30) => cmGet<CompHistory>("/competition/history", { days });
export const fetchTeam = (agent: string) => cmGet<TeamOverview>(`/team/${agent}`);
export const fetchResearch = (agent: string, limit = 50) => cmGet<ResearchNote[]>(`/research/${agent}`, { limit });
export const fetchProposals = (agent: string, limit = 25) => cmGet<TradeProposal[]>(`/proposals/${agent}`, { limit });
export const fetchExecutions = (agent: string, limit = 50) => cmGet<Execution[]>(`/executions/${agent}`, { limit });
export const fetchReconciliation = (agent: string, limit = 20) => cmGet<Reconciliation[]>(`/reconciliation/${agent}`, { limit });
export const fetchPipeline = (agent: string) => cmGet<PipelineStage[]>(`/pipeline/${agent}`);
export const fetchPositions = (agent: string) => cmGet<Position[]>(`/positions/${agent}`);

// ── Portfolio API ─────────────────────────────────────────────────

export interface Portfolio {
  id: number; name: string; slug: string; type: "system" | "user" | "webull";
  owner: string; starting_cash: number; cash: number;
  color: string; description: string; created_at: string | null;
}

export interface PortfolioHolding {
  symbol: string; qty: number; avg_cost: number;
  current_price?: number; market_value?: number;
  unrealized_pl?: number; unrealized_plpc?: number;
}

export interface PortfolioTxn {
  id: number; type: string; symbol: string | null;
  quantity: number | null; price: number | null;
  total: number; notes: string; time: string | null;
}

export interface PortfolioDetail extends Portfolio {
  holdings: PortfolioHolding[];
  transactions: PortfolioTxn[];
}

export interface PortfolioNav {
  portfolio_id: number; name: string; type: string;
  nav: number; cash: number; positions_value: number;
  starting_cash: number; total_return: number;
  positions: PortfolioHolding[];
  as_of: string;
}

export interface LeaderboardEntry {
  id: number; name: string; slug: string; type: string;
  color: string; nav: number; cash: number;
  total_return: number; trade_count: number; positions_count: number;
}

export const fetchPortfolios = () => cmGet<Portfolio[]>("/portfolio");
export const fetchPortfolioDetail = (id: number) => cmGet<PortfolioDetail>(`/portfolio/${id}`);
export const fetchPortfolioNav = (id: number) => cmGet<PortfolioNav>(`/portfolio/${id}/nav`);
export const fetchLeaderboard = () => cmGet<LeaderboardEntry[]>("/portfolio/all/leaderboard");

async function cmPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data.results as T;
}

async function cmDelete<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data.results as T;
}

export const createPortfolio = (body: { name: string; starting_cash: number; color: string; description?: string }) =>
  cmPost<{ id: number; slug: string }>("/portfolio", body);
export const deletePortfolio = (id: number) => cmDelete<string>(`/portfolio/${id}`);
export const executeTrade = (id: number, body: { symbol: string; quantity: number; side: string; price?: number }) =>
  cmPost<{ action: string; symbol: string; qty: number; price: number; total: number }>(`/portfolio/${id}/trade`, body);
export const manageCash = (id: number, body: { amount: number; action: string; target_portfolio_id?: number; notes?: string }) =>
  cmPost<{ action: string; amount: number }>(`/portfolio/${id}/cash`, body);

export const fetchPortfolioHistory = (id: number) =>
  cmGet<{
    portfolio_id: number; name: string; type: string; starting_cash: number;
    positions: Array<{
      symbol: string; status: string; current_qty: number; avg_cost: number;
      current_price: number | null; market_value: number; cost_basis: number;
      unrealized_pl: number; unrealized_pct: number; realized_pl: number; total_pl: number;
      total_bought_qty: number; total_bought_cost: number;
      total_sold_qty: number; total_sold_proceeds: number;
      trade_count: number; first_trade: string | null; last_trade: string | null;
      trades: Array<{ side: string; symbol: string; qty: number; price: number; total: number; time: string | null }>;
    }>;
    summary: {
      total_positions: number; open_positions: number; closed_positions: number;
      total_trades: number; total_market_value: number;
      total_unrealized_pl: number; total_realized_pl: number; total_pl: number;
    };
  }>(`/portfolio/${id}/history`);

export const refreshPortfolio = (id: number) =>
  cmPost<{ name: string; source: string; nav: number | null; as_of: string }>(`/portfolio/${id}/refresh`, {});

export const fetchResearchNews = (symbol: string, refresh = false) =>
  cmGet<Array<{
    symbol: string; source: string; title: string; url: string | null;
    published_at: string | null; summary: string | null; event_type: string | null;
    fetched_at: string | null;
  }>>(`/market-research/news/${symbol}${refresh ? "?refresh=true" : ""}`);

export const fetchSecFilings = (symbol: string, refresh = false) =>
  cmGet<Array<{
    symbol: string; cik: string; accession_number: string; form_type: string;
    filing_date: string | null; primary_doc_url: string | null;
    description: string | null; company_name: string | null; fetched_at: string | null;
  }>>(`/market-research/filings/${symbol}${refresh ? "?refresh=true" : ""}`);

export const fetchResearchSummary = (symbol: string) =>
  cmGet<{
    symbol: string; cik: string | null; has_data: boolean;
    recent_filings: Array<{ form_type: string; filing_date: string | null; description: string | null; company_name: string | null }>;
    recent_news: Array<{ source: string; title: string; url: string | null; published_at: string | null; event_type: string | null }>;
  }>(`/market-research/summary/${symbol}`);

export const triggerResearchSync = () =>
  cmPost<{ filings: number; news: number; symbols: string[]; errors: string[] }>("/market-research/sync", {});

// Issued Stock Program
export const fetchIssuedStocks = () =>
  cmGet<{
    by_symbol: Array<{
      symbol: string; current_price: number | null;
      total_remaining_qty: number; total_cost_basis: number;
      total_market_value: number | null; total_unrealized_gain: number | null;
      lots: Array<{
        id: number; symbol: string; quantity: number; remaining_qty: number;
        issue_price: number; issue_date: string; notes: string | null; created_at: string;
        current_price: number | null; current_value: number | null;
        unrealized_gain: number | null; unrealized_gain_pct: number | null;
      }>;
    }>;
    summary: {
      total_cost_basis: number; total_market_value: number;
      total_unrealized_gain: number; total_realized_gain: number;
    };
    timestamp: string;
  }>("/issued-stocks");

export const addIssuedLot = (body: { symbol: string; quantity: number; issue_price: number; issue_date: string; notes?: string }) =>
  cmPost<{
    id: number; symbol: string; quantity: number; remaining_qty: number;
    issue_price: number; issue_date: string; notes: string | null; created_at: string;
  }>("/issued-stocks/lots", body);

export const deleteIssuedLot = (id: number) =>
  cmDelete<{ deleted: number }>(`/issued-stocks/lots/${id}`);

export const recordStockSale = (body: { lot_id: number; quantity: number; sale_price: number; sale_date: string; notes?: string }) =>
  cmPost<{
    id: number; lot_id: number; symbol: string; quantity: number;
    sale_price: number; sale_date: string; cost_basis: number; proceeds: number;
    realized_gain: number; holding_period: string; notes: string | null;
    created_at: string; days_held: number;
  }>("/issued-stocks/sales", body);

export const fetchStockSales = (symbol?: string) =>
  cmGet<{
    sales: Array<{
      id: number; lot_id: number; symbol: string; quantity: number;
      sale_price: number; sale_date: string; cost_basis: number;
      proceeds: number; realized_gain: number; holding_period: string; notes: string | null;
    }>;
    by_year: Record<string, any[]>;
    tax_summary: {
      total_short_term_gains: number; total_long_term_gains: number;
      total_proceeds: number; total_cost_basis: number;
    };
    timestamp: string;
  }>(`/issued-stocks/sales${symbol ? `?symbol=${symbol}` : ""}`);

export const fetchTaxSummary = (year?: number) =>
  cmGet<{
    year: number;
    short_term_total: number;
    long_term_total: number;
    combined_total: number;
    per_symbol: Record<string, {
      short_term: number; long_term: number;
      total_proceeds: number; total_cost_basis: number; sale_count: number;
    }>;
    timestamp: string;
  }>(`/issued-stocks/tax-summary${year ? `?year=${year}` : ""}`);
