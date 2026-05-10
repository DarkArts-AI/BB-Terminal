import { useQuery } from "@tanstack/react-query";
import { fetchWatchlistSummary, fetchKPIs, fetchCoverageMap, REFETCH_NARRATIVE, downloadCoveragePdf } from "@/lib/narrative_api";
import { cn } from "@/lib/cn";
import { useState } from "react";

const COLORS: Record<string, string> = { Alpha: "#1601D6", Bravo: "#8F3823", Charlie: "#747904" };

function fmtN(v: number) { return v.toLocaleString(); }

function PriorityBar({ high, med, low, total, color }: { high: number; med: number; low: number; total: number; color: string }) {
  if (total === 0) return null;
  const hp = (high / total) * 100, mp = (med / total) * 100, lp = (low / total) * 100;
  return (
    <div className="flex h-2 rounded overflow-hidden gap-px">
      <div style={{ width: `${hp}%`, background: "#dc3545" }} title={`HIGH: ${high}`} />
      <div style={{ width: `${mp}%`, background: color }} title={`MEDIUM: ${med}`} />
      <div style={{ width: `${lp}%`, background: "#6c757d" }} title={`LOW: ${low}`} />
    </div>
  );
}

export function COV() {
  const { data: summary } = useQuery({ queryKey: ["watchlist-summary"], queryFn: fetchWatchlistSummary, refetchInterval: REFETCH_NARRATIVE });
  const { data: kpis } = useQuery({ queryKey: ["narrative-kpis"], queryFn: fetchKPIs, refetchInterval: REFETCH_NARRATIVE });
  const { data: coverage } = useQuery({ queryKey: ["coverage-map"], queryFn: fetchCoverageMap, refetchInterval: REFETCH_NARRATIVE });
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  const agents = ["Alpha", "Bravo", "Charlie"];
  const triple = summary?.overlap.triple || [];

  return (
    <div className="p-3 flex flex-col gap-3 h-full overflow-auto">
      {/* Fleet Coverage Summary */}
      <div className="panel">
        <div className="panel-header">
          <span>FLEET COVERAGE MAP</span>
          <span className="sub-header normal-case tracking-normal font-normal">Dynamic Watchlist Protocol &middot; Auto-refresh 30s</span>
          <button onClick={() => downloadCoveragePdf()} className="px-2 py-0.5 text-[10px] font-bold bg-term-amber/20 text-term-amber border border-term-amber/30 rounded hover:bg-term-amber/30" title="Download coverage report as PDF">PDF</button>
        </div>
        <div className="p-3">
          <div className="grid grid-cols-4 gap-4 mb-4">
            {agents.map(a => {
              const d = summary?.per_agent[a];
              const color = COLORS[a];
              return (
                <div key={a} className="p-3 rounded cursor-pointer transition-all" 
                     style={{ border: `1px solid ${color}60`, background: selectedAgent === a ? `${color}25` : `${color}10` }}
                     onClick={() => setSelectedAgent(selectedAgent === a ? null : a)}>
                  <div className="font-bold text-sm mb-1" style={{ color }}>{a}</div>
                  <div className="num text-2xl text-term-heading">{fmtN(d?.total || 0)}</div>
                  <div className="text-[10px] text-term-muted">stocks on watchlist</div>
                  <PriorityBar high={d?.high||0} med={d?.medium||0} low={d?.low||0} total={d?.total||0} color={color} />
                  <div className="grid grid-cols-3 gap-1 mt-2 text-[9px] text-term-muted">
                    <span className="text-red-400">H:{d?.high||0}</span>
                    <span style={{color}}>M:{d?.medium||0}</span>
                    <span>L:{d?.low||0}</span>
                  </div>
                </div>
              );
            })}
            <div className="p-3 rounded" style={{ border: "1px solid #04600B60", background: "#04600B10" }}>
              <div className="font-bold text-sm mb-1 text-[#04600B]">FLEET TOTAL</div>
              <div className="num text-2xl text-term-heading">{fmtN(summary?.total_unique_symbols || 0)}</div>
              <div className="text-[10px] text-term-muted">unique securities</div>
              <div className="mt-2 text-[9px]">
                <span className="text-term-amber font-bold">{triple.length}</span>
                <span className="text-term-muted"> triple convergence</span>
              </div>
            </div>
          </div>

          {/* Venn Overlap Stats */}
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: "Alpha-Bravo", key: "alpha_bravo" as const, colors: [COLORS.Alpha, COLORS.Bravo] },
              { label: "Alpha-Charlie", key: "alpha_charlie" as const, colors: [COLORS.Alpha, COLORS.Charlie] },
              { label: "Bravo-Charlie", key: "bravo_charlie" as const, colors: [COLORS.Bravo, COLORS.Charlie] },
            ].map(({ label, key, colors }) => (
              <div key={key} className="p-2 rounded bg-term-border/20 text-center">
                <div className="text-[10px] text-term-muted uppercase">{label} Overlap</div>
                <div className="num text-lg text-term-heading">{coverage?.venn[key]?.length || 0}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Convergence Watchlist */}
      <div className="panel">
        <div className="panel-header">
          <span>CONVERGENCE WATCHLIST</span>
          <span className="sub-header normal-case tracking-normal font-normal">Stocks independently discovered by all 3 agents &middot; High-conviction signal</span>
        </div>
        <div className="p-3">
          {triple.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {triple.map(sym => (
                <span key={sym} className="px-2 py-0.5 rounded text-xs font-bold bg-term-amber/20 text-term-amber border border-term-amber/30">{sym}</span>
              ))}
            </div>
          ) : (
            <div className="text-term-muted text-sm">No triple convergence stocks yet</div>
          )}
        </div>
      </div>

      {/* KPI Dashboard */}
      <div className="panel">
        <div className="panel-header">
          <span>WATCHLIST KPIs</span>
          <span className="sub-header normal-case tracking-normal font-normal">Pipeline utilization &middot; Research depth</span>
        </div>
        <div className="p-3">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-term-muted text-[10px] uppercase tracking-wider">
                <th className="text-left p-2">Agent</th>
                <th className="text-right p-2">Watchlist</th>
                <th className="text-right p-2">Cycles/24h</th>
                <th className="text-right p-2">Symbols (All)</th>
                <th className="text-right p-2">Symbols (7d)</th>
                <th className="text-right p-2">Additions/7d</th>
                <th className="text-right p-2">Removals/7d</th>
              </tr>
            </thead>
            <tbody>
              {agents.map(a => {
                const snap = kpis?.watchlist_snapshots[a];
                const wl = summary?.per_agent[a];
                return (
                  <tr key={a} className="border-t border-term-border">
                    <td className="p-2 font-bold" style={{ color: COLORS[a] }}>{a}</td>
                    <td className="p-2 text-right num text-term-heading font-bold">{fmtN(wl?.total || 0)}</td>
                    <td className={cn("p-2 text-right num", (kpis?.pipeline_cycles_24h[a] || 0) >= 8 ? "up" : "text-term-amber")}>{kpis?.pipeline_cycles_24h[a] || 0}</td>
                    <td className="p-2 text-right num">{kpis?.unique_symbols_all_time[a] || 0}</td>
                    <td className="p-2 text-right num">{kpis?.unique_symbols_7d[a] || 0}</td>
                    <td className="p-2 text-right num up">{snap?.additions_7d != null ? `+${snap.additions_7d}` : "—"}</td>
                    <td className="p-2 text-right num down">{snap?.removals_7d != null ? `-${snap.removals_7d}` : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Multi-agent convergence detail */}
      {summary && summary.top_convergence.length > 0 && (
        <div className="panel">
          <div className="panel-header">
            <span>CONVERGENCE DETAIL</span>
            <span className="sub-header normal-case tracking-normal font-normal">Stocks on 2+ agent watchlists &middot; {summary.top_convergence.length} total</span>
          </div>
          <div className="p-3 max-h-60 overflow-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-term-muted text-[9px] uppercase">
                  <th className="text-left p-1">Symbol</th>
                  <th className="text-center p-1">Agents</th>
                  <th className="text-left p-1">Coverage</th>
                </tr>
              </thead>
              <tbody>
                {summary.top_convergence.slice(0, 50).map(c => (
                  <tr key={c.symbol} className="border-t border-term-border/50">
                    <td className="p-1 num font-bold text-term-heading">{c.symbol}</td>
                    <td className="p-1 text-center">
                      <span className={cn("px-1 rounded text-[9px] font-bold", c.agent_count >= 3 ? "bg-term-amber/20 text-term-amber" : "bg-term-border text-term-fg")}>{c.agent_count}</span>
                    </td>
                    <td className="p-1">
                      <div className="flex gap-1">
                        {c.agents.map(a => (
                          <span key={a} className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: COLORS[a] || "#666" }} title={a} />
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
