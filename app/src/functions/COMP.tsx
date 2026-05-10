import { useQuery } from "@tanstack/react-query";
import { fetchCompetition, fetchCompHistory, fetchPositions, fetchLeaderboard, REFETCH, type CompetitionEntry, type LeaderboardEntry, type Position } from "@/lib/cm_api";
import { cn } from "@/lib/cn";
import { useState, useEffect } from "react";

function fmtCurrency(v: number | null | undefined) { return v != null ? `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—"; }
function fmtPct(v: number | null | undefined) { if (v == null) return "—"; const p = v * 100; return `${p >= 0 ? "+" : ""}${p.toFixed(2)}%`; }

function RefreshBar({ dataUpdatedAt }: { dataUpdatedAt: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const ago = Math.floor((now - dataUpdatedAt) / 1000);
  const next = Math.max(0, 30 - ago);
  const pct = Math.min(100, (ago / 30) * 100);
  return (
    <div className="flex items-center gap-2 text-[10px] text-term-muted px-3 py-1">
      <div className="flex-1 h-0.5 bg-term-border rounded overflow-hidden">
        <div className="h-full bg-term-amber transition-all duration-1000" style={{ width: `${pct}%` }} />
      </div>
      <span>REFRESH {next}s</span>
      <span className="text-term-amber">LIVE</span>
    </div>
  );
}

function Spark({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return null;
  const min = Math.min(...values), max = Math.max(...values);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 120},${32 - ((v - min) / (max - min || 1)) * 28}`).join(" ");
  return <svg viewBox="0 0 120 32" className="w-full h-10"><polyline fill="none" stroke={color} strokeWidth="1.5" points={pts} /></svg>;
}

function RankBadge({ rank }: { rank: number }) {
  const colors = ["text-[#ffd700]", "text-[#c0c0c0]", "text-[#cd7f32]"];
  const labels = ["1ST", "2ND", "3RD"];
  return <span className={cn("font-bold text-lg num", colors[rank] || "text-term-muted")}>{labels[rank] || `${rank + 1}TH`}</span>;
}

function PositionsTable({ agent, color }: { agent: string; color: string }) {
  const { data: positions } = useQuery({
    queryKey: ["cm-positions", agent], queryFn: () => fetchPositions(agent), refetchInterval: REFETCH,
  });
  if (!positions || positions.length === 0) return <div className="text-term-muted text-[10px] p-2">No positions</div>;
  const totalValue = positions.reduce((s, p) => s + p.market_value, 0);
  const totalPL = positions.reduce((s, p) => s + p.unrealized_pl, 0);
  return (
    <div className="text-[10px]">
      <div className="flex justify-between px-1 mb-1">
        <span className="font-bold" style={{ color }}>{positions.length} positions</span>
        <span className={cn("num font-bold", totalPL >= 0 ? "up" : "down")}>{fmtCurrency(totalPL)} P&L</span>
      </div>
      <table className="w-full">
        <thead>
          <tr className="text-term-muted text-[9px] uppercase">
            <th className="text-left p-0.5">Sym</th>
            <th className="text-right p-0.5">Qty</th>
            <th className="text-right p-0.5">Entry</th>
            <th className="text-right p-0.5">Last</th>
            <th className="text-right p-0.5">Mkt Val</th>
            <th className="text-right p-0.5">P&L</th>
            <th className="text-right p-0.5">%</th>
          </tr>
        </thead>
        <tbody>
          {positions.sort((a, b) => b.market_value - a.market_value).map(p => (
            <tr key={p.symbol} className="border-t border-term-border/50">
              <td className="p-0.5 num font-bold text-term-heading">{p.symbol}</td>
              <td className="p-0.5 text-right num">{p.qty.toFixed(2)}</td>
              <td className="p-0.5 text-right num text-term-muted">{fmtCurrency(p.avg_entry)}</td>
              <td className="p-0.5 text-right num">{fmtCurrency(p.current_price)}</td>
              <td className="p-0.5 text-right num">{fmtCurrency(p.market_value)}</td>
              <td className={cn("p-0.5 text-right num", p.unrealized_pl >= 0 ? "up" : "down")}>{fmtCurrency(p.unrealized_pl)}</td>
              <td className={cn("p-0.5 text-right num", p.unrealized_plpc >= 0 ? "up" : "down")}>{fmtPct(p.unrealized_plpc)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-term-border font-bold">
            <td className="p-0.5" colSpan={4}>TOTAL</td>
            <td className="p-0.5 text-right num">{fmtCurrency(totalValue)}</td>
            <td className={cn("p-0.5 text-right num", totalPL >= 0 ? "up" : "down")}>{fmtCurrency(totalPL)}</td>
            <td className="p-0.5"></td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

interface UnifiedRow {
  rank: number;
  name: string;
  slug: string;
  color: string;
  type: "system" | "user" | "webull";
  nav: number;
  cash: number;
  total_return: number;
  daily_return: number | null;
  sharpe: number | null;
  max_drawdown: number | null;
  trade_count: number;
  positions_count: number;
  llm: string | null;
  source: string;
  agent: string | null;
}

function buildUnifiedLeaderboard(teams: CompetitionEntry[], portfolios: LeaderboardEntry[]): UnifiedRow[] {
  const agentMap = new Map<string, CompetitionEntry>();
  for (const t of teams) agentMap.set(t.agent, t);

  const slugToAgent: Record<string, string> = { "2A": "Alpha", "2B": "Bravo", "2C": "Charlie" };
  const seen = new Set<string>();
  const rows: UnifiedRow[] = [];

  for (const p of portfolios) {
    const agent = slugToAgent[p.slug] || null;
    const comp = agent ? agentMap.get(agent) : null;
    seen.add(p.slug);

    rows.push({
      rank: 0,
      name: p.name,
      slug: p.slug,
      color: comp?.color || p.color,
      type: p.type as any,
      nav: comp?.nav ?? p.nav,
      cash: comp?.cash ?? p.cash,
      total_return: comp?.cumulative_return ?? p.total_return,
      daily_return: comp?.daily_return ?? (p as any).daily_return ?? null,
      sharpe: comp?.sharpe ?? null,
      max_drawdown: comp?.max_drawdown ?? null,
      trade_count: comp?.trade_count ?? p.trade_count,
      positions_count: p.positions_count,
      llm: comp?.llm ?? null,
      source: comp?.source ?? (p as any).source ?? "local",
      agent,
    });
  }

  rows.sort((a, b) => b.total_return - a.total_return);
  rows.forEach((r, i) => r.rank = i + 1);
  return rows;
}

export function COMP() {
  const REFRESH = 30_000;

  const { data: teams, isLoading: teamsLoading, dataUpdatedAt } = useQuery({
    queryKey: ["cm-competition"], queryFn: fetchCompetition, refetchInterval: REFRESH,
  });
  const { data: portfolios, isLoading: portsLoading } = useQuery({
    queryKey: ["leaderboard"], queryFn: fetchLeaderboard, refetchInterval: REFRESH,
  });
  const { data: history } = useQuery({
    queryKey: ["cm-comp-history"], queryFn: () => fetchCompHistory(30), refetchInterval: REFRESH,
  });

  const unified = buildUnifiedLeaderboard(teams || [], portfolios || []);
  const aiRows = unified.filter(r => r.type === "system");
  const isLoading = teamsLoading || portsLoading;

  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  return (
    <div className="p-3 flex flex-col gap-3 h-full">
      <RefreshBar dataUpdatedAt={dataUpdatedAt} />

      {/* Unified Leaderboard */}
      <div className="panel">
        <div className="panel-header">
          <span>COMPETITION LEADERBOARD</span>
          <span className="sub-header normal-case tracking-normal font-normal">All Portfolios · Alpaca Live + User Simulated · Auto-refresh 30s</span>
        </div>
        {isLoading ? (
          <div className="p-4 text-term-muted">Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-term-muted text-[10px] uppercase tracking-wider">
                <th className="text-left p-2">Rank</th>
                <th className="text-left p-2">Portfolio</th>
                <th className="text-left p-2">Type</th>
                <th className="text-right p-2">NAV</th>
                <th className="text-right p-2">Cash</th>
                <th className="text-right p-2">Total Return</th>
                <th className="text-right p-2">Daily</th>
                <th className="text-right p-2">Sharpe</th>
                <th className="text-right p-2">Max DD</th>
                <th className="text-right p-2">Trades</th>
                <th className="text-left p-2">Engine</th>
                <th className="text-center p-2">Source</th>
              </tr>
            </thead>
            <tbody>
              {unified.map((r) => (
                <tr key={r.slug}
                    className={cn("border-t border-term-border transition-colors",
                      r.agent ? "cursor-pointer" : "",
                      selectedAgent === r.agent ? "bg-term-border/40" : "hover:bg-term-border/20")}
                    onClick={() => r.agent && setSelectedAgent(selectedAgent === r.agent ? null : r.agent)}>
                  <td className="p-2"><RankBadge rank={r.rank - 1} /></td>
                  <td className="p-2">
                    <span className="inline-block w-2 h-2 rounded-full mr-1.5 align-middle" style={{ backgroundColor: r.color }} />
                    <span className="font-bold" style={{ color: r.color }}>{r.name}</span>
                    <span className="text-term-muted text-xs ml-1">({r.slug})</span>
                  </td>
                  <td className="p-2">
                    <span className={cn("text-[9px] px-1.5 py-0.5 rounded font-bold",
                      r.type === "system" ? "bg-blue-900/50 text-blue-300" :
                      r.type === "webull" ? "bg-purple-900/50 text-purple-300" :
                      "bg-term-border text-term-fg"
                    )}>
                      {r.type === "system" ? "AI" : r.type === "webull" ? "WEBULL" : "USER"}
                    </span>
                  </td>
                  <td className="p-2 text-right num text-term-heading font-bold">{fmtCurrency(r.nav)}</td>
                  <td className="p-2 text-right num text-term-muted">{fmtCurrency(r.cash)}</td>
                  <td className={cn("p-2 text-right num font-bold", r.total_return >= 0 ? "up" : "down")}>{fmtPct(r.total_return)}</td>
                  <td className={cn("p-2 text-right num", r.daily_return != null && r.daily_return >= 0 ? "up" : r.daily_return != null ? "down" : "")}>{r.daily_return != null ? fmtPct(r.daily_return) : "—"}</td>
                  <td className="p-2 text-right num">{r.sharpe != null ? r.sharpe.toFixed(2) : "—"}</td>
                  <td className={cn("p-2 text-right num", r.max_drawdown != null ? "down" : "")}>{r.max_drawdown != null ? fmtPct(r.max_drawdown) : "—"}</td>
                  <td className="p-2 text-right num">{r.trade_count}</td>
                  <td className="p-2 text-term-muted text-xs">{r.llm || (r.type === "webull" ? "Webull" : "Manual")}</td>
                  <td className="p-2 text-center">
                    <span className={cn("text-[9px] px-1 rounded font-bold",
                      r.source === "alpaca_live" ? "bg-green-900/40 text-green-300" :
                      r.type === "webull" ? "bg-purple-900/40 text-purple-300" :
                      "bg-term-border text-term-muted"
                    )}>{r.source === "alpaca_live" ? "LIVE" : r.type === "webull" ? "WEBULL" : "LOCAL"}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Expandable positions for selected agent */}
      {selectedAgent && (
        <div className="panel">
          <div className="panel-header">
            <span>{selectedAgent.toUpperCase()} LIVE POSITIONS</span>
            <span className="sub-header normal-case tracking-normal font-normal">Alpaca Paper Portfolio · Click row above to toggle</span>
          </div>
          <div className="p-2">
            <PositionsTable agent={selectedAgent} color={unified.find(s => s.agent === selectedAgent)?.color || "#ff8c00"} />
          </div>
        </div>
      )}

      <div className="grid gap-3 flex-1 min-h-0" style={{ gridTemplateColumns: "1fr 1fr" }}>
        {/* Agent Cards */}
        <div className="panel min-h-0">
          <div className="panel-header"><span>AI AGENT PERFORMANCE</span></div>
          <div className="p-3 grid grid-cols-3 gap-3">
            {aiRows.map((r) => {
              const hist = history?.[r.agent!] || [];
              return (
                <div key={r.slug} className="p-3 rounded" style={{ border: `1px solid ${r.color}40`, background: `${r.color}10` }}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-bold text-term-heading" style={{ color: r.color }}>{r.name}</span>
                    <span className="text-[10px] text-term-muted">{r.slug}</span>
                  </div>
                  <div className="num text-xl text-term-heading">{fmtCurrency(r.nav)}</div>
                  <div className={cn("num text-sm", r.total_return >= 0 ? "up" : "down")}>
                    {fmtPct(r.total_return)}
                  </div>
                  <Spark values={hist.map((h: any) => h.nav)} color={r.color} />
                  <div className="grid grid-cols-2 gap-1 mt-1 text-[10px] text-term-muted">
                    <span>Sharpe: {r.sharpe?.toFixed(2) ?? "—"}</span>
                    <span>Trades: {r.trade_count}</span>
                    <span>Daily: {fmtPct(r.daily_return)}</span>
                    <span>Max DD: {fmtPct(r.max_drawdown)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Pipeline Status Overview */}
        <div className="panel min-h-0">
          <div className="panel-header"><span>TRADING PIPELINE STATUS</span></div>
          <div className="p-3">
            <div className="text-[10px] text-term-muted mb-2 uppercase tracking-wider">
              TradingAgents 5-Stage Pipeline (Xiao et al., arXiv:2412.20138)
            </div>
            {["Alpha", "Bravo", "Charlie"].map((agent) => {
              const r = aiRows.find(s => s.agent === agent);
              const color = r?.color || "#666";
              return (
                <div key={agent} className="mb-3">
                  <div className="font-bold text-xs mb-1" style={{ color }}>{agent}</div>
                  <div className="flex gap-1">
                    {["Analysts", "Research", "Trader", "Risk Mgmt", "PM", "Exec"].map((stage) => (
                      <div key={stage} className="flex-1 text-center p-1 rounded text-[9px]"
                        style={{ border: `1px solid ${color}60`, background: `${color}15` }}>
                        <div className="text-term-muted">{stage}</div>
                        <div className="text-term-amber text-[8px] mt-0.5">READY</div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
            <div className="text-[9px] text-term-muted mt-3 italic">
              Strategy: 6/12/24+ month holds · $100/mo API cap · Cerberus + native LLM
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
