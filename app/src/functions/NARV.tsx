import { downloadCyclePdf, downloadCaseStudyPdf } from "@/lib/narrative_api";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, useMemo } from "react";
import { cn } from "@/lib/cn";

const BASE = "/api/v1";
const COLORS: Record<string, string> = { Alpha: "#1601D6", Bravo: "#8F3823", Charlie: "#747904" };
const AGENTS = ["Alpha", "Bravo", "Charlie"] as const;

const RATING_COLORS: Record<string, string> = {
  "STRONG BUY": "bg-emerald-900/60 text-emerald-200",
  BUY: "bg-green-900/50 text-green-300",
  HOLD: "bg-yellow-900/40 text-yellow-300",
  SELL: "bg-red-900/50 text-red-300",
  "STRONG SELL": "bg-red-900/70 text-red-200",
};

function ratingClass(r: string | null) {
  if (!r) return "bg-term-border text-term-muted";
  return RATING_COLORS[r.toUpperCase()] || "bg-term-border text-term-fg";
}

const SPEAKER_STYLES: Record<string, { color: string; label: string }> = {
  market_analyst: { color: "#17a2b8", label: "MKT" },
  fundamentals_analyst: { color: "#28a745", label: "FUND" },
  news_analyst: { color: "#fd7e14", label: "NEWS" },
  social_media_analyst: { color: "#e83e8c", label: "SENT" },
  bull: { color: "#28a745", label: "BULL" },
  bear: { color: "#dc3545", label: "BEAR" },
  research_manager: { color: "#04600B", label: "MGR" },
  trader: { color: "#fd7e14", label: "TRADE" },
  aggressive: { color: "#dc3545", label: "AGG" },
  conservative: { color: "#007bff", label: "CON" },
  neutral: { color: "#6c757d", label: "NEU" },
  portfolio_manager: { color: "#04600B", label: "PM" },
};

function getSpeakerStyle(role: string) {
  const key = role.toLowerCase().replace(/[^a-z_]/g, "");
  return SPEAKER_STYLES[key] || { color: "#999", label: role.substring(0, 4).toUpperCase() };
}

interface CycleRow {
  cycle_id: string; agent: string; symbol: string; status: string;
  final_rating: string | null; llm_backend: string | null;
  total_tokens: number | null; total_latency_ms: number | null;
  started_at: string; completed_at: string | null;
  company_name: string | null; source?: string;
}

interface PendingRequest {
  id: number; symbol: string; agents: string[]; requested_by: string;
  requested_at: string; status: string; notes?: string;
  picked_up_by?: string; picked_up_at?: string;
}

type SortKey = "agent" | "symbol" | "final_rating" | "status" | "duration" | "total_tokens" | "source" | "started_at";
type SortDir = "asc" | "desc";

function ChatMessage({ speaker, label, color, content, time }: { speaker: string; label: string; color: string; content: string; time?: string }) {
  const truncated = typeof content === "string" ? content : JSON.stringify(content);
  return (
    <div className="mb-2 pl-3" style={{ borderLeft: `3px solid ${color}` }}>
      <div className="flex items-center gap-2">
        <span className="text-[9px] font-bold px-1 rounded" style={{ backgroundColor: `${color}20`, color }}>[{label}]</span>
        <span className="text-[10px] font-bold" style={{ color }}>{speaker}</span>
        {time && <span className="text-[9px] text-term-muted">{new Date(time).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}</span>}
      </div>
      <div className="text-[10px] text-term-fg mt-0.5 whitespace-pre-wrap max-h-40 overflow-auto">{truncated.substring(0, 2000)}{truncated.length > 2000 ? "..." : ""}</div>
    </div>
  );
}

function duration(start: string, end: string | null) {
  if (!end) return "—";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

function durationMs(start: string, end: string | null) {
  if (!end) return -1;
  return new Date(end).getTime() - new Date(start).getTime();
}

function SortHeader({ label, sortKey: sk, current, dir, onSort }: { label: string; sortKey: SortKey; current: SortKey; dir: SortDir; onSort: (k: SortKey) => void }) {
  return (
    <th className="px-2 py-1.5 font-bold cursor-pointer select-none hover:text-term-fg transition-colors" onClick={() => onSort(sk)}>
      <span className="inline-flex items-center gap-0.5">
        {label}
        {current === sk && <span className="text-[8px]">{dir === "asc" ? "▲" : "▼"}</span>}
      </span>
    </th>
  );
}

export function NARV() {
  const [selectedCycle, setSelectedCycle] = useState<string | null>(null);
  const [agentFilter, setAgentFilter] = useState<string>("ALL");
  const [symbolFilter, setSymbolFilter] = useState("");
  const [ratingFilter, setRatingFilter] = useState<string>("ALL");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [hoursFilter, setHoursFilter] = useState(72);
  const [sourceFilter, setSourceFilter] = useState<string>("ALL");
  const [reqSymbol, setReqSymbol] = useState("");
  const [reqAgents, setReqAgents] = useState<Set<string>>(new Set(["Alpha", "Bravo", "Charlie"]));
  const [reqStatus, setReqStatus] = useState<string | null>(null);
  const [validatedName, setValidatedName] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const [showQueue, setShowQueue] = useState(false);
  const queryClient = useQueryClient();
  const [sortKey, setSortKey] = useState<SortKey>("started_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "started_at" ? "desc" : "asc");
    }
  };

  const { data: cyclesData, isLoading } = useQuery({
    queryKey: ["narv-cycles", hoursFilter],
    queryFn: async () => {
      const res = await fetch(`${BASE}/narrative/cycles?hours=${hoursFilter}&limit=500`);
      return res.json();
    },
    refetchInterval: 30_000,
  });

  const { data: requestsData } = useQuery({
    queryKey: ["narv-requests"],
    queryFn: async () => {
      const res = await fetch(`${BASE}/narrative/requests?limit=20`);
      return res.json();
    },
    refetchInterval: 15_000,
  });
  const activeRequests: PendingRequest[] = (requestsData?.requests || []).filter((r: PendingRequest) => r.status === "pending" || r.status === "running" || r.status === "timeout");

  const validateAndSubmit = async () => {
    const sym = reqSymbol.trim().toUpperCase();
    if (!sym) return;
    setValidating(true);
    setReqStatus(null);
    setValidatedName(null);
    try {
      const vRes = await fetch(`${BASE}/narrative/validate-symbol/${sym}`);
      const vData = await vRes.json();
      if (!vData.valid) {
        setReqStatus(`"${sym}" is not a valid ticker`);
        setValidating(false);
        setTimeout(() => setReqStatus(null), 4000);
        return;
      }
      setValidatedName(vData.name);
      setReqStatus(`✓ ${vData.name}`);
      const res = await fetch(`${BASE}/narrative/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: sym, agents: Array.from(reqAgents), requested_by: "operator" }),
      });
      if (!res.ok) throw new Error(await res.text());
      setReqStatus(`Submitted: ${sym} — ${vData.name}`);
      setReqSymbol("");
      setValidatedName(null);
      queryClient.invalidateQueries({ queryKey: ["narv-requests"] });
      setTimeout(() => setReqStatus(null), 4000);
    } catch (e: any) {
      setReqStatus(`Error: ${e.message}`);
      setTimeout(() => setReqStatus(null), 4000);
    } finally {
      setValidating(false);
    }
  };

  const cancelRequest = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${BASE}/narrative/requests/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["narv-requests"] });
    },
  });

  const toggleReqAgent = (a: string) => {
    setReqAgents(prev => {
      const next = new Set(prev);
      if (next.has(a)) { if (next.size > 1) next.delete(a); } else next.add(a);
      return next;
    });
  };

  const allCycles: CycleRow[] = cyclesData?.cycles || [];

  const caseStudyEligible = useMemo(() => {
    const symbolAgents: Record<string, Set<string>> = {};
    for (const c of allCycles) {
      if (c.status === "complete") {
        if (!symbolAgents[c.symbol]) symbolAgents[c.symbol] = new Set();
        symbolAgents[c.symbol].add(c.agent);
      }
    }
    const eligible = new Set<string>();
    for (const [sym, agents] of Object.entries(symbolAgents)) {
      if (agents.size >= 2) eligible.add(sym);
    }
    return eligible;
  }, [allCycles]);

  const ratings = ["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"];

  const filtered = useMemo(() => {
    return allCycles.filter((c) => {
      if (agentFilter !== "ALL" && c.agent !== agentFilter) return false;
      if (symbolFilter && !c.symbol.toUpperCase().includes(symbolFilter.toUpperCase())) return false;
      if (ratingFilter !== "ALL" && (c.final_rating || "").toUpperCase() !== ratingFilter) return false;
      if (statusFilter !== "ALL" && c.status !== statusFilter) return false;
      if (sourceFilter !== "ALL" && (c.source || "scheduled") !== sourceFilter) return false;
      return true;
    });
  }, [allCycles, agentFilter, symbolFilter, ratingFilter, statusFilter, sourceFilter]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    const dir = sortDir === "asc" ? 1 : -1;
    arr.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "agent": cmp = a.agent.localeCompare(b.agent); break;
        case "symbol": cmp = a.symbol.localeCompare(b.symbol); break;
        case "final_rating": cmp = (a.final_rating || "").localeCompare(b.final_rating || ""); break;
        case "status": cmp = a.status.localeCompare(b.status); break;
        case "duration": cmp = durationMs(a.started_at, a.completed_at) - durationMs(b.started_at, b.completed_at); break;
        case "total_tokens": cmp = (a.total_tokens || 0) - (b.total_tokens || 0); break;
        case "source": cmp = (a.source || "").localeCompare(b.source || ""); break;
        case "started_at": cmp = new Date(a.started_at).getTime() - new Date(b.started_at).getTime(); break;
      }
      return cmp * dir;
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  const agentCounts = useMemo(() => {
    const counts: Record<string, number> = { ALL: allCycles.length };
    for (const a of AGENTS) counts[a] = allCycles.filter((c) => c.agent === a).length;
    return counts;
  }, [allCycles]);

  const { data: conversation } = useQuery({
    queryKey: ["conversation", selectedCycle],
    queryFn: async () => {
      if (!selectedCycle) return null;
      const res = await fetch(`${BASE}/narrative/conversation/${selectedCycle}`);
      if (!res.ok) return null;
      return res.json();
    },
    enabled: !!selectedCycle,
  });

  return (
    <div className="p-3 flex flex-col gap-3 h-full overflow-hidden">
      {/* Filter Bar */}
      <div className="panel">
        <div className="panel-header">
          <span>PIPELINE NARRATIVE</span>
          <span className="sub-header normal-case tracking-normal font-normal">
            {sorted.length} cycle{sorted.length !== 1 ? "s" : ""} &middot; Last {hoursFilter}h
          </span>
        </div>
        <div className="p-2 flex flex-wrap gap-2 items-center">
          <div className="flex gap-0.5 border border-term-border rounded overflow-hidden">
            {(["ALL", ...AGENTS] as const).map((a) => (
              <button key={a}
                className={cn("px-2 py-1 text-[10px] font-bold transition-colors", agentFilter === a ? "text-black" : "text-term-muted hover:text-term-fg")}
                style={agentFilter === a ? { backgroundColor: a === "ALL" ? "#04600B" : COLORS[a] || "#04600B" } : undefined}
                onClick={() => setAgentFilter(a)}
              >
                {a} <span className="opacity-60">({agentCounts[a] || 0})</span>
              </button>
            ))}
          </div>
          <input type="text" placeholder="Symbol..." value={symbolFilter} onChange={(e) => setSymbolFilter(e.target.value)}
            className="w-24 bg-term-bg border border-term-border rounded px-2 py-1 text-[10px] text-term-fg font-mono focus:border-term-amber outline-none" />
          <select value={ratingFilter} onChange={(e) => setRatingFilter(e.target.value)}
            className="bg-term-bg border border-term-border rounded px-2 py-1 text-[10px] text-term-fg font-mono focus:border-term-amber outline-none">
            <option value="ALL">All Ratings</option>
            {ratings.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-term-bg border border-term-border rounded px-2 py-1 text-[10px] text-term-fg font-mono focus:border-term-amber outline-none">
            <option value="ALL">All Status</option>
            <option value="complete">Complete</option>
            <option value="running">Running</option>
          </select>
          <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}
            className="bg-term-bg border border-term-border rounded px-2 py-1 text-[10px] text-term-fg font-mono focus:border-term-amber outline-none">
            <option value="ALL">All Sources</option>
            <option value="scheduled">Scheduled</option>
            <option value="user-request">User Request</option>
          </select>
          <select value={hoursFilter} onChange={(e) => setHoursFilter(Number(e.target.value))}
            className="bg-term-bg border border-term-border rounded px-2 py-1 text-[10px] text-term-fg font-mono focus:border-term-amber outline-none">
            <option value={6}>6h</option>
            <option value={12}>12h</option>
            <option value={24}>24h</option>
            <option value={72}>3d</option>
            <option value={168}>7d</option>
          </select>
          <div className="ml-auto flex items-center gap-1.5 border border-term-amber/40 rounded px-2 py-1 bg-term-amber/5">
            <span className="text-[9px] text-term-amber font-bold tracking-wide">REQUEST:</span>
            <input type="text" placeholder="TICKER" value={reqSymbol}
              onChange={(e) => setReqSymbol(e.target.value.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 6))}
              onKeyDown={(e) => { if (e.key === "Enter" && reqSymbol.trim()) validateAndSubmit(); }}
              className="w-16 bg-term-bg border border-term-border rounded px-1.5 py-0.5 text-[10px] text-term-fg font-mono uppercase focus:border-term-amber outline-none" />
            <div className="flex gap-0.5">
              {AGENTS.map((a) => (
                <button key={a} onClick={() => toggleReqAgent(a)}
                  className={cn("px-1.5 py-0.5 text-[8px] font-bold rounded transition-colors",
                    reqAgents.has(a) ? "text-black" : "text-term-muted border border-term-border")}
                  style={reqAgents.has(a) ? { backgroundColor: COLORS[a] } : undefined}>
                  {a[0]}
                </button>
              ))}
            </div>
            <button onClick={() => { if (reqSymbol.trim()) validateAndSubmit(); }}
              disabled={!reqSymbol.trim() || validating}
              className="px-2 py-0.5 text-[9px] font-bold bg-term-amber text-black rounded hover:bg-term-amber/80 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
              {validating ? "..." : "GO"}
            </button>
            {reqStatus && <span className={cn("text-[9px] font-mono max-w-48 truncate",
              reqStatus.startsWith("Error") || reqStatus.includes("not a valid") ? "text-red-400" : "text-green-400")}>{reqStatus}</span>}
            {activeRequests.length > 0 && (
              <button onClick={() => setShowQueue(!showQueue)}
                className="text-[9px] text-term-amber font-mono hover:text-term-fg transition-colors">
                {activeRequests.length} queued {showQueue ? "▲" : "▼"}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Request Queue */}
      {showQueue && activeRequests.length > 0 && (
        <div className="panel">
          <div className="panel-header">
            <span>REQUEST QUEUE</span>
            <span className="sub-header normal-case tracking-normal font-normal">
              {activeRequests.length} active
            </span>
          </div>
          <div className="overflow-auto max-h-32">
            <table className="w-full text-[10px]">
              <thead>
                <tr className="text-term-amber text-left border-b border-term-border">
                  <th className="px-2 py-1">ID</th>
                  <th className="px-2 py-1">SYMBOL</th>
                  <th className="px-2 py-1">AGENT</th>
                  <th className="px-2 py-1">STATUS</th>
                  <th className="px-2 py-1">REQUESTED</th>
                  <th className="px-2 py-1">BY</th>
                  <th className="px-2 py-1 text-center">ACTION</th>
                </tr>
              </thead>
              <tbody>
                {activeRequests.map((r: any) => (
                  <tr key={r.id} className={cn("border-b border-term-border/30",
                    r.status === "timeout" ? "opacity-50" : "")}>
                    <td className="px-2 py-1 text-term-muted font-mono">{r.id}</td>
                    <td className="px-2 py-1 font-mono font-bold text-term-fg">{r.symbol}</td>
                    <td className="px-2 py-1">
                      {(r.agents || []).map((a: string) => (
                        <span key={a} className="font-bold mr-1" style={{ color: COLORS[a] || "#999" }}>{a}</span>
                      ))}
                    </td>
                    <td className="px-2 py-1">
                      <span className={cn("text-[9px]",
                        r.status === "running" ? "text-term-amber" :
                        r.status === "timeout" ? "text-red-400" : "text-term-muted"
                      )}>
                        {r.status === "running" ? "● running" :
                         r.status === "timeout" ? "✕ timeout" : "pending"}
                      </span>
                      {r.status === "running" && r.picked_up_at && (
                        <span className="text-[8px] text-term-muted ml-1">
                          {duration(r.picked_up_at, new Date().toISOString())}
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1 text-term-muted">
                      {new Date(r.requested_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}
                    </td>
                    <td className="px-2 py-1 text-term-muted">{r.requested_by}</td>
                    <td className="px-2 py-1 text-center">
                      {r.status !== "timeout" ? (
                        <button
                          onClick={() => cancelRequest.mutate(r.id)}
                          disabled={cancelRequest.isPending}
                          className="px-1.5 py-0.5 text-[8px] font-bold bg-red-900/40 text-red-400 border border-red-800/50 rounded hover:bg-red-900/60 disabled:opacity-30 transition-colors"
                        >CANCEL</button>
                      ) : (
                        <span className="text-[8px] text-red-400/50">expired</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Main Layout: Table + Detail */}
      <div className="flex gap-3 flex-1 min-h-0">
        <div className={cn("panel flex flex-col min-h-0", selectedCycle ? "w-[45%]" : "w-full")}>
          <div className="overflow-auto flex-1">
            <table className="w-full text-[10px]">
              <thead className="sticky top-0 bg-term-panel z-10">
                <tr className="text-term-amber text-left border-b border-term-border">
                  <SortHeader label="AGENT" sortKey="agent" current={sortKey} dir={sortDir} onSort={toggleSort} />
                  <SortHeader label="SYMBOL" sortKey="symbol" current={sortKey} dir={sortDir} onSort={toggleSort} />
                  <SortHeader label="RATING" sortKey="final_rating" current={sortKey} dir={sortDir} onSort={toggleSort} />
                  <SortHeader label="STATUS" sortKey="status" current={sortKey} dir={sortDir} onSort={toggleSort} />
                  <SortHeader label="DURATION" sortKey="duration" current={sortKey} dir={sortDir} onSort={toggleSort} />
                  <SortHeader label="TOKENS" sortKey="total_tokens" current={sortKey} dir={sortDir} onSort={toggleSort} />
                  <SortHeader label="SOURCE" sortKey="source" current={sortKey} dir={sortDir} onSort={toggleSort} />
                  <SortHeader label="STARTED" sortKey="started_at" current={sortKey} dir={sortDir} onSort={toggleSort} />
                  <th className="px-2 py-1.5 font-bold text-center">EXPORT</th>
                </tr>
              </thead>
              <tbody>
                {isLoading && (
                  <tr><td colSpan={9} className="px-2 py-4 text-center text-term-muted">Loading cycles...</td></tr>
                )}
                {!isLoading && sorted.length === 0 && (
                  <tr><td colSpan={9} className="px-2 py-4 text-center text-term-muted">No cycles match filters</td></tr>
                )}
                {sorted.map((c) => (
                  <tr key={c.cycle_id}
                    className={cn(
                      "border-b border-term-border/30 cursor-pointer transition-colors",
                      selectedCycle === c.cycle_id ? "bg-term-amber/10" : "hover:bg-term-border/20"
                    )}
                    onClick={() => setSelectedCycle(c.cycle_id)}
                  >
                    <td className="px-2 py-1.5">
                      <span className="font-bold" style={{ color: COLORS[c.agent] || "#999" }}>{c.agent}</span>
                    </td>
                    <td className="px-2 py-1.5">
                      <span className="font-mono font-bold text-term-fg">{c.symbol}</span>
                      {c.company_name && <span className="text-term-muted ml-1.5 text-[9px]">{c.company_name}</span>}
                    </td>
                    <td className="px-2 py-1.5">
                      {c.final_rating ? (
                        <span className={cn("px-1.5 py-0.5 rounded text-[9px] font-bold", ratingClass(c.final_rating))}>
                          {c.final_rating}
                        </span>
                      ) : <span className="text-term-muted">{"—"}</span>}
                    </td>
                    <td className="px-2 py-1.5">
                      <span className={cn("text-[9px]",
                        c.status === "complete" ? "text-green-400" :
                        c.status === "running" ? "text-term-amber" : "text-term-muted"
                      )}>
                        {c.status === "running" ? "● " : ""}{c.status}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-term-muted font-mono">{duration(c.started_at, c.completed_at)}</td>
                    <td className="px-2 py-1.5 text-term-muted font-mono">{c.total_tokens ? c.total_tokens.toLocaleString() : "—"}</td>
                    <td className="px-2 py-1.5">
                      {c.source === "user-request" ? (
                        <span className="px-1.5 py-0.5 rounded text-[8px] font-bold bg-term-amber/20 text-term-amber border border-term-amber/30">USER</span>
                      ) : (
                        <span className="text-[9px] text-term-muted">auto</span>
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-term-muted">{new Date(c.started_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false })}</td>
                    <td className="px-2 py-1 text-center" onClick={(e) => e.stopPropagation()}>
                      <div className="inline-flex gap-1">
                        <button
                          onClick={() => downloadCyclePdf(c.cycle_id)}
                          className="px-1.5 py-0.5 text-[9px] font-bold bg-term-amber/20 text-term-amber border border-term-amber/30 rounded hover:bg-term-amber/30"
                          title={`Download PDF for ${c.agent} ${c.symbol}`}
                        >PDF</button>
                        {caseStudyEligible.has(c.symbol) ? (
                          <button
                            onClick={() => downloadCaseStudyPdf(c.symbol)}
                            className="px-1.5 py-0.5 text-[9px] font-bold bg-[#04600B]/20 text-[#04600B] border border-[#04600B]/30 rounded hover:bg-[#04600B]/30"
                            title={`Case study: ${c.symbol} analyzed by 2+ agents`}
                          >CS</button>
                        ) : (
                          <span className="px-1.5 py-0.5 text-[9px] font-bold text-term-border cursor-not-allowed" title="Needs 2+ agents to generate case study">CS</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {selectedCycle && (
          <div className="w-[55%] flex flex-col gap-2 overflow-auto min-h-0">
            {conversation ? (
              <>
                <div className="panel">
                  <div className="panel-header">
                    <span style={{ color: COLORS[conversation.cycle?.agent] || "#fff" }}>
                      {conversation.cycle?.agent} &mdash; {conversation.cycle?.symbol}{conversation.cycle?.company_name && <span className="text-term-muted font-normal text-[11px] ml-2">{conversation.cycle.company_name}</span>}{conversation.cycle?.company_name && <span className="text-term-muted font-normal text-[11px] ml-2">{conversation.cycle.company_name}</span>}
                    </span>
                    <div className="flex items-center gap-2">
                      {conversation.cycle?.final_rating && (
                        <span className={cn("px-2 py-0.5 rounded font-bold text-[10px]", ratingClass(conversation.cycle.final_rating))}>
                          {conversation.cycle.final_rating}
                        </span>
                      )}
                      <button onClick={() => setSelectedCycle(null)}
                        className="px-2 py-0.5 text-[10px] text-term-muted hover:text-term-fg border border-term-border rounded">
                        {"✕"}
                      </button>
                    </div>
                  </div>
                  <div className="p-2 text-[10px] text-term-muted flex flex-wrap gap-x-4 gap-y-1">
                    <span>Cycle: <span className="text-term-fg font-mono">{conversation.cycle?.cycle_id}</span></span>
                    <span>Started: {conversation.cycle?.started_at ? new Date(conversation.cycle.started_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "—"}</span>
                    <span>Completed: {conversation.cycle?.completed_at ? new Date(conversation.cycle.completed_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "—"}</span>
                    <span>LLM: {conversation.cycle?.llm_backend || "—"}</span>
                    <div className="flex gap-1 ml-auto">
                      <button onClick={() => downloadCyclePdf(selectedCycle)} className="px-2 py-0.5 text-[10px] font-bold bg-term-amber/20 text-term-amber border border-term-amber/30 rounded hover:bg-term-amber/30">PDF</button>
                      <button onClick={() => downloadCaseStudyPdf(conversation.cycle?.symbol)} className="px-2 py-0.5 text-[10px] font-bold bg-[#04600B]/20 text-[#04600B] border border-[#04600B]/30 rounded hover:bg-[#04600B]/30">CASE STUDY</button>
                    </div>
                  </div>
                </div>

                {conversation.stages?.filter((s: any) => s.stage === "Analysts" || s.sub_stage?.includes("analyst")).length > 0 && (
                  <div className="panel">
                    <div className="panel-header"><span>#research-{conversation.cycle?.symbol}</span></div>
                    <div className="p-3 bg-term-bg/50">
                      {conversation.stages
                        .filter((s: any) => s.stage === "Analysts" || s.sub_stage?.includes("analyst"))
                        .map((s: any, i: number) => {
                          const style = getSpeakerStyle(s.speaker_role);
                          const content = typeof s.content === "object" ? JSON.stringify(s.content, null, 2) : String(s.content || "");
                          return <ChatMessage key={i} speaker={s.speaker_role} label={style.label} color={style.color} content={content} time={s.timestamp} />;
                        })}
                    </div>
                  </div>
                )}

                {conversation.debate_rounds?.length > 0 && (
                  <div className="panel">
                    <div className="panel-header"><span>#debate-{conversation.cycle?.symbol}</span></div>
                    <div className="p-3 bg-term-bg/50">
                      {conversation.debate_rounds.map((d: any, i: number) => {
                        const style = getSpeakerStyle(d.speaker_role);
                        return (
                          <div key={i}>
                            {(i === 0 || conversation.debate_rounds[i-1].round_number !== d.round_number || conversation.debate_rounds[i-1].debate_type !== d.debate_type) && (
                              <div className="text-[9px] text-term-amber font-bold uppercase tracking-wider my-2 pt-2 border-t border-term-border/50">
                                {d.debate_type === "bull_bear" ? "Bull-Bear Debate" : "Risk Debate"} &mdash; Round {d.round_number}
                              </div>
                            )}
                            <ChatMessage speaker={d.speaker_role} label={style.label} color={style.color} content={d.content} time={d.timestamp} />
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {conversation.stages
                  ?.filter((s: any) => !s.stage?.includes("Analyst") && !s.sub_stage?.includes("analyst"))
                  .map((s: any, i: number) => {
                    const style = getSpeakerStyle(s.speaker_role);
                    const content = typeof s.content === "object" ? JSON.stringify(s.content, null, 2) : String(s.content || "");
                    return (
                      <div key={i} className="panel">
                        <div className="panel-header"><span>#{s.stage?.toLowerCase()}-{conversation.cycle?.symbol}</span></div>
                        <div className="p-3 bg-term-bg/50">
                          <ChatMessage speaker={s.speaker_role} label={style.label} color={style.color} content={content} time={s.timestamp} />
                        </div>
                      </div>
                    );
                  })}

                {conversation.decision && (
                  <div className="panel">
                    <div className="panel-header"><span>#decision-{conversation.cycle?.symbol}</span></div>
                    <div className="p-3 bg-term-bg/50">
                      <ChatMessage speaker="Portfolio Manager" label="PM" color="#04600B"
                        content={`RATING: ${conversation.decision.rating || "—"}\nDIRECTION: ${conversation.decision.direction || "—"}\nCONVICTION: ${conversation.decision.conviction || "—"}\n\n${conversation.decision.executive_summary || ""}\n\nTHESIS: ${conversation.decision.investment_thesis || ""}\n\nRISK: ${conversation.decision.risk_notes || ""}`}
                      />
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="panel flex-1 flex items-center justify-center">
                <div className="text-term-muted text-sm">Loading cycle data...</div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
