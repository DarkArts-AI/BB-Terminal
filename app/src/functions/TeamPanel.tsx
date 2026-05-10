import { useQuery } from "@tanstack/react-query";
import { fetchTeam, fetchResearch, fetchProposals, fetchExecutions, fetchReconciliation, fetchPipeline, fetchPositions,
         REFETCH, type TeamOverview, type PipelineStage, type Position } from "@/lib/cm_api";
import { cn } from "@/lib/cn";
import { useState, useEffect } from "react";

function fmtCurrency(v: number | null | undefined) { return v != null ? `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—"; }
function fmtTime(t: string | null) { if (!t) return "—"; try { return new Date(t).toLocaleString(); } catch { return t; } }

const STAGE_ICONS: Record<string, string> = {
  "Analysts": "◈", "Research (Bull/Bear)": "⚔", "Trader": "▲",
  "Risk Management": "◆", "Portfolio Manager": "◉", "Execution": "►",
};
const STATUS_COLORS: Record<string, string> = {
  "idle": "text-term-muted", "running": "text-term-amber", "complete": "up", "error": "down",
};

function RefreshBar({ dataUpdatedAt }: { dataUpdatedAt: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const ago = Math.floor((now - dataUpdatedAt) / 1000);
  const next = Math.max(0, 60 - ago);
  const pct = Math.min(100, (ago / 60) * 100);
  return (
    <div className="flex items-center gap-2 text-[10px] text-term-muted">
      <div className="flex-1 h-0.5 bg-term-border rounded overflow-hidden">
        <div className="h-full bg-term-amber transition-all duration-1000" style={{ width: `${pct}%` }} />
      </div>
      <span>REFRESH {next}s</span>
      <span className="text-term-amber">LIVE</span>
    </div>
  );
}

interface Props { agent: string; }

export function TeamPanel({ agent }: Props) {
  const { data: team, dataUpdatedAt } = useQuery({
    queryKey: ["cm-team", agent], queryFn: () => fetchTeam(agent), refetchInterval: REFETCH,
  });
  const { data: pipeline } = useQuery({
    queryKey: ["cm-pipeline", agent], queryFn: () => fetchPipeline(agent), refetchInterval: REFETCH,
  });
  const { data: research } = useQuery({
    queryKey: ["cm-research", agent], queryFn: () => fetchResearch(agent, 20), refetchInterval: REFETCH,
  });
  const { data: proposals } = useQuery({
    queryKey: ["cm-proposals", agent], queryFn: () => fetchProposals(agent, 15), refetchInterval: REFETCH,
  });
  const { data: executions } = useQuery({
    queryKey: ["cm-executions", agent], queryFn: () => fetchExecutions(agent, 20), refetchInterval: REFETCH,
  });
  const { data: recons } = useQuery({
    queryKey: ["cm-recon", agent], queryFn: () => fetchReconciliation(agent, 10), refetchInterval: REFETCH,
  });
  const { data: positions } = useQuery({
    queryKey: ["cm-positions", agent], queryFn: () => fetchPositions(agent), refetchInterval: REFETCH,
  });

  const color = team?.color || "#ff8c00";
  const stages = pipeline || [];
  const liveNav = team?.live_nav;
  const liveCash = team?.live_cash;

  return (
    <div className="p-3 grid gap-3 h-full" style={{
      gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)",
      gridTemplateRows: "auto auto minmax(0,1fr) minmax(0,1fr)",
    }}>
      {/* Refresh + Account Bar */}
      <div className="col-span-3 flex items-center gap-4">
        <RefreshBar dataUpdatedAt={dataUpdatedAt} />
        {liveNav != null && (
          <div className="flex items-center gap-3 text-xs">
            <span className="text-term-muted">NAV:</span>
            <span className="num text-term-heading font-bold">{fmtCurrency(liveNav)}</span>
            <span className="text-term-muted">Cash:</span>
            <span className="num">{fmtCurrency(liveCash)}</span>
            <span className="text-[9px] up bg-green-900/30 px-1 rounded">ALPACA LIVE</span>
          </div>
        )}
      </div>

      {/* Pipeline Status Bar */}
      <div className="panel col-span-3">
        <div className="panel-header">
          <span>{agent.toUpperCase()} PIPELINE</span>
          <span className="sub-header normal-case tracking-normal font-normal">
            {team?.portfolio || "—"} · {team?.llm || "—"} · CF: {team?.cf || "—"} · Medusa: {team?.medusa || "—"}
          </span>
        </div>
        <div className="flex gap-1 p-2">
          {stages.map((s, i) => (
            <div key={s.stage} className="flex-1 flex items-center gap-1">
              <div className="flex-1 p-2 rounded text-center" style={{ border: `1px solid ${color}50`, background: `${color}10` }}>
                <div className="text-term-amber text-xs">{STAGE_ICONS[s.stage] || "◇"}</div>
                <div className="text-[10px] font-bold text-term-heading">{s.stage}</div>
                <div className={cn("text-[9px] uppercase", STATUS_COLORS[s.status] || "text-term-muted")}>{s.status}</div>
                {s.last_run && <div className="text-[8px] text-term-muted">{fmtTime(s.last_run)}</div>}
              </div>
              {i < stages.length - 1 && <span className="text-term-muted text-xs">→</span>}
            </div>
          ))}
          {stages.length === 0 && (
            <div className="flex-1 text-center text-term-muted text-sm p-4">Pipeline stages will appear as data flows in</div>
          )}
        </div>
      </div>

      {/* Live Positions */}
      {positions && positions.length > 0 && (
        <div className="panel col-span-3 min-h-0">
          <div className="panel-header">
            <span>LIVE POSITIONS</span>
            <span className="sub-header normal-case tracking-normal font-normal">
              Alpaca Paper · {positions.length} holdings · Total: {fmtCurrency(positions.reduce((s, p) => s + p.market_value, 0))}
            </span>
          </div>
          <div className="overflow-auto scroll-thin" style={{ maxHeight: "180px" }}>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-term-muted text-[9px] uppercase tracking-wider sticky top-0 bg-term-bg">
                  <th className="text-left p-1">Symbol</th>
                  <th className="text-right p-1">Qty</th>
                  <th className="text-right p-1">Avg Entry</th>
                  <th className="text-right p-1">Current</th>
                  <th className="text-right p-1">Mkt Value</th>
                  <th className="text-right p-1">P&L $</th>
                  <th className="text-right p-1">P&L %</th>
                  <th className="text-right p-1">Today</th>
                </tr>
              </thead>
              <tbody>
                {positions.sort((a, b) => b.market_value - a.market_value).map(p => (
                  <tr key={p.symbol} className="border-t border-term-border/50 hover:bg-term-border/20">
                    <td className="p-1 num font-bold text-term-heading">{p.symbol}</td>
                    <td className="p-1 text-right num">{p.qty.toFixed(2)}</td>
                    <td className="p-1 text-right num text-term-muted">{fmtCurrency(p.avg_entry)}</td>
                    <td className="p-1 text-right num">{fmtCurrency(p.current_price)}</td>
                    <td className="p-1 text-right num">{fmtCurrency(p.market_value)}</td>
                    <td className={cn("p-1 text-right num font-bold", p.unrealized_pl >= 0 ? "up" : "down")}>{fmtCurrency(p.unrealized_pl)}</td>
                    <td className={cn("p-1 text-right num", p.unrealized_plpc >= 0 ? "up" : "down")}>{(p.unrealized_plpc * 100).toFixed(2)}%</td>
                    <td className={cn("p-1 text-right num", p.change_today >= 0 ? "up" : "down")}>{(p.change_today * 100).toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Research Notes */}
      <div className="panel min-h-0">
        <div className="panel-header">
          <span>RESEARCH</span>
          <span className="sub-header normal-case tracking-normal font-normal">Analyst reports · Bull/Bear debate</span>
        </div>
        <div className="overflow-auto scroll-thin flex-1 min-h-0">
          {research && research.length > 0 ? research.map((r, i) => (
            <div key={i} className="p-2 border-b border-term-border">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-term-amber text-[10px] font-bold uppercase">{r.stage}</span>
                {r.symbol && <span className="text-term-heading num text-xs">{r.symbol}</span>}
                <span className="text-term-muted text-[9px] ml-auto">{fmtTime(r.time)}</span>
              </div>
              {r.title && <div className="text-xs text-term-heading font-semibold">{r.title}</div>}
              <div className="text-[11px] text-term-body mt-1 whitespace-pre-wrap leading-relaxed max-h-24 overflow-hidden">{r.content}</div>
            </div>
          )) : <div className="p-4 text-term-muted text-sm text-center">Awaiting research data</div>}
        </div>
      </div>

      {/* Trade Proposals */}
      <div className="panel min-h-0">
        <div className="panel-header">
          <span>TRADE PROPOSALS</span>
          <span className="sub-header normal-case tracking-normal font-normal">Determinations from Trader agent</span>
        </div>
        <div className="overflow-auto scroll-thin flex-1 min-h-0">
          {proposals && proposals.length > 0 ? proposals.map((p, i) => (
            <div key={i} className="p-2 border-b border-term-border">
              <div className="flex items-center gap-2">
                <span className="num text-term-heading font-bold text-xs">{p.symbol}</span>
                <span className={cn("text-[10px] font-bold uppercase",
                  p.direction.toLowerCase().includes("buy") ? "up" : p.direction.toLowerCase().includes("sell") ? "down" : "text-term-amber"
                )}>{p.direction}</span>
                {p.confidence != null && <span className="text-[10px] text-term-muted">({(p.confidence * 100).toFixed(0)}%)</span>}
                <span className={cn("text-[9px] ml-auto px-1 rounded",
                  p.status === "approved" ? "up bg-green-900/30" : p.status === "rejected" ? "down bg-red-900/30" : "text-term-amber bg-amber-900/20"
                )}>{p.status}</span>
              </div>
              {p.rationale && <div className="text-[10px] text-term-body mt-1 max-h-16 overflow-hidden">{p.rationale}</div>}
              <div className="text-[9px] text-term-muted mt-1">{fmtTime(p.time)}</div>
            </div>
          )) : <div className="p-4 text-term-muted text-sm text-center">Awaiting trade proposals</div>}
        </div>
      </div>

      {/* Reconciliation */}
      <div className="panel min-h-0">
        <div className="panel-header">
          <span>RECONCILIATION</span>
          <span className="sub-header normal-case tracking-normal font-normal">Portfolio state · NAV · drift</span>
        </div>
        <div className="overflow-auto scroll-thin flex-1 min-h-0">
          {recons && recons.length > 0 ? recons.map((r, i) => (
            <div key={i} className="p-2 border-b border-term-border">
              <div className="flex items-center gap-3 mb-1">
                <span className="text-term-heading num text-sm font-bold">{fmtCurrency(r.nav)}</span>
                <span className="text-term-muted text-[10px]">Cash: {fmtCurrency(r.cash)}</span>
                {r.positions != null && <span className="text-term-muted text-[10px]">{r.positions} pos</span>}
              </div>
              {r.drift_pct != null && (
                <div className={cn("text-[10px]", Math.abs(r.drift_pct) > 5 ? "down" : "text-term-muted")}>
                  Drift: {r.drift_pct.toFixed(2)}%
                </div>
              )}
              {r.notes && <div className="text-[10px] text-term-body mt-1">{r.notes}</div>}
              <div className="text-[9px] text-term-muted mt-1">{fmtTime(r.time)}</div>
            </div>
          )) : <div className="p-4 text-term-muted text-sm text-center">Awaiting reconciliation data</div>}
        </div>
      </div>

      {/* Execution Log */}
      <div className="panel col-span-3 min-h-0">
        <div className="panel-header">
          <span>EXECUTION LOG</span>
          <span className="sub-header normal-case tracking-normal font-normal">Orders filled on Medusa → Alpaca</span>
        </div>
        <div className="overflow-auto scroll-thin flex-1 min-h-0">
          {executions && executions.length > 0 ? (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-term-muted text-[10px] uppercase tracking-wider">
                  <th className="text-left p-1.5">Time</th><th className="text-left p-1.5">Symbol</th>
                  <th className="text-center p-1.5">Side</th><th className="text-right p-1.5">Qty</th>
                  <th className="text-right p-1.5">Price</th><th className="text-center p-1.5">Status</th>
                  <th className="text-left p-1.5">Order ID</th>
                </tr>
              </thead>
              <tbody>
                {executions.map((e, i) => (
                  <tr key={i} className="border-t border-term-border">
                    <td className="p-1.5 text-term-muted text-[10px]">{fmtTime(e.time)}</td>
                    <td className="p-1.5 num text-term-heading font-bold">{e.symbol}</td>
                    <td className={cn("p-1.5 text-center font-bold uppercase", e.side.toLowerCase() === "buy" ? "up" : "down")}>{e.side}</td>
                    <td className="p-1.5 text-right num">{e.qty?.toFixed(4)}</td>
                    <td className="p-1.5 text-right num">{fmtCurrency(e.price)}</td>
                    <td className="p-1.5 text-center">
                      <span className={cn("text-[9px] px-1 rounded",
                        e.status === "filled" ? "up bg-green-900/30" : "text-term-amber bg-amber-900/20"
                      )}>{e.status}</span>
                    </td>
                    <td className="p-1.5 text-term-muted text-[9px] font-mono">{e.order_id || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="p-4 text-term-muted text-sm text-center">No executions recorded yet</div>}
        </div>
      </div>
    </div>
  );
}
