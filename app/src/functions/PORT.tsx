import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  fetchLeaderboard, fetchPortfolioHistory,
  createPortfolio, deletePortfolio, executeTrade, manageCash, refreshPortfolio,
  type Portfolio, type PortfolioNav, type LeaderboardEntry,
} from "@/lib/cm_api";
import { cn } from "@/lib/cn";

const REFRESH = 30_000;

function fmt$(v: number | null | undefined) {
  return v != null ? `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—";
}
function fmtPct(v: number | null | undefined) {
  if (v == null) return "—";
  const p = v * 100;
  return `${p >= 0 ? "+" : ""}${p.toFixed(2)}%`;
}

function CreateForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [cash, setCash] = useState("10000");
  const [color, setColor] = useState("#4A90D9");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const qc = useQueryClient();

  const submit = async () => {
    if (!name.trim()) { setErr("Name required"); return; }
    setLoading(true);
    setErr("");
    try {
      await createPortfolio({ name: name.trim(), starting_cash: cash.trim() === "" ? 10000 : parseFloat(cash), color });
      qc.invalidateQueries({ queryKey: ["portfolios"] });
      qc.invalidateQueries({ queryKey: ["leaderboard"] });
      qc.invalidateQueries({ queryKey: ["all-portfolio-navs"] });
      onDone();
    } catch (e: any) { setErr(e.message); }
    setLoading(false);
  };

  return (
    <div className="border border-term-border p-3 space-y-2 bg-term-bg-secondary rounded">
      <div className="text-term-amber text-xs font-bold uppercase">Create Portfolio</div>
      <div className="flex gap-2 items-center flex-wrap">
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 flex-1 rounded" placeholder="Portfolio Name" value={name} onChange={(e) => setName(e.target.value)} />
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 w-28 rounded" placeholder="Starting Cash" value={cash} onChange={(e) => setCash(e.target.value)} />
        <input type="color" className="w-8 h-7 border-0 bg-transparent cursor-pointer" value={color} onChange={(e) => setColor(e.target.value)} />
        <button className="px-3 py-1 bg-term-amber text-black text-xs font-bold rounded hover:opacity-80 disabled:opacity-40" onClick={submit} disabled={loading}>{loading ? "..." : "CREATE"}</button>
        <button className="px-2 py-1 text-term-muted text-xs hover:text-term-fg" onClick={onDone}>CANCEL</button>
      </div>
      {err && <div className="text-red-400 text-[10px]">{err}</div>}
    </div>
  );
}

function TradeForm({ portfolioId, onDone }: { portfolioId: number; onDone: () => void }) {
  const [symbol, setSymbol] = useState("");
  const [qty, setQty] = useState("");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [result, setResult] = useState<string>("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const qc = useQueryClient();

  const submit = async () => {
    if (!symbol.trim() || !qty) { setErr("Symbol and quantity required"); return; }
    setLoading(true); setErr(""); setResult("");
    try {
      const payload: any = { symbol: symbol.trim().toUpperCase(), quantity: parseFloat(qty), side };
      const r = await executeTrade(portfolioId, payload);
      setResult(`${r.action.toUpperCase()} ${r.qty} ${r.symbol} @ $${r.price.toFixed(2)} = $${r.total.toFixed(2)}`);
      qc.invalidateQueries({ queryKey: ["all-portfolio-navs"] });
      qc.invalidateQueries({ queryKey: ["leaderboard"] });
      setSymbol(""); setQty("");
    } catch (e: any) { setErr(e.message); }
    setLoading(false);
  };

  return (
    <div className="border border-term-border p-2 bg-term-bg-secondary rounded space-y-1">
      <div className="flex gap-2 items-center flex-wrap">
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 w-24 rounded uppercase" placeholder="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 w-20 rounded" placeholder="Qty" type="number" value={qty} onChange={(e) => setQty(e.target.value)} />
        <button className={cn("px-2 py-1 text-xs font-bold rounded", side === "buy" ? "bg-green-700 text-white" : "bg-term-bg text-term-muted border border-term-border")} onClick={() => setSide("buy")}>BUY</button>
        <button className={cn("px-2 py-1 text-xs font-bold rounded", side === "sell" ? "bg-red-700 text-white" : "bg-term-bg text-term-muted border border-term-border")} onClick={() => setSide("sell")}>SELL</button>
        <button className="px-3 py-1 bg-term-amber text-black text-xs font-bold rounded hover:opacity-80 disabled:opacity-40" onClick={submit} disabled={loading}>{loading ? "..." : "EXECUTE"}</button>
        <button className="px-2 py-1 text-term-muted text-xs hover:text-term-fg" onClick={onDone}>CLOSE</button>
      </div>
      {err && <div className="text-red-400 text-[10px]">{err}</div>}
      {result && <div className="text-green-400 text-[10px]">{result}</div>}
    </div>
  );
}

function CashForm({ portfolioId, onDone }: { portfolioId: number; onDone: () => void }) {
  const [amount, setAmount] = useState("");
  const [action, setAction] = useState<"deposit" | "withdrawal">("deposit");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const qc = useQueryClient();

  const submit = async () => {
    if (!amount) { setErr("Amount required"); return; }
    setLoading(true); setErr("");
    try {
      await manageCash(portfolioId, { amount: parseFloat(amount), action });
      qc.invalidateQueries({ queryKey: ["all-portfolio-navs"] });
      qc.invalidateQueries({ queryKey: ["leaderboard"] });
      onDone();
    } catch (e: any) { setErr(e.message); }
    setLoading(false);
  };

  return (
    <div className="border border-term-border p-2 bg-term-bg-secondary rounded space-y-1">
      <div className="flex gap-2 items-center flex-wrap">
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 w-28 rounded" placeholder="Amount" type="number" value={amount} onChange={(e) => setAmount(e.target.value)} />
        <button className={cn("px-2 py-1 text-xs font-bold rounded", action === "deposit" ? "bg-green-700 text-white" : "bg-term-bg text-term-muted border border-term-border")} onClick={() => setAction("deposit")}>DEPOSIT</button>
        <button className={cn("px-2 py-1 text-xs font-bold rounded", action === "withdrawal" ? "bg-red-700 text-white" : "bg-term-bg text-term-muted border border-term-border")} onClick={() => setAction("withdrawal")}>WITHDRAW</button>
        <button className="px-3 py-1 bg-term-amber text-black text-xs font-bold rounded hover:opacity-80 disabled:opacity-40" onClick={submit} disabled={loading}>{loading ? "..." : "SUBMIT"}</button>
        <button className="px-2 py-1 text-term-muted text-xs hover:text-term-fg" onClick={onDone}>CANCEL</button>
      </div>
      {err && <div className="text-red-400 text-[10px]">{err}</div>}
    </div>
  );
}

function HistoryPanel({ portfolioId, onClose }: { portfolioId: number; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["portfolio-history", portfolioId],
    queryFn: () => fetchPortfolioHistory(portfolioId),
  });

  if (isLoading) return <div className="p-3 text-term-muted text-xs">Loading history...</div>;
  if (!data) return <div className="p-3 text-red-400 text-xs">Failed to load history</div>;

  const s = data.summary;

  return (
    <div className="border border-term-border rounded bg-term-bg p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-term-amber text-xs font-bold uppercase">Trading History — {data.name}</span>
        <button className="text-[9px] px-2 py-0.5 border border-term-border text-term-muted hover:text-term-fg rounded" onClick={onClose}>CLOSE</button>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-2 text-[10px]">
        <div className="border border-term-border rounded p-2 text-center">
          <div className="text-term-muted">Positions</div>
          <div className="text-term-fg font-bold num">{s.open_positions} open / {s.closed_positions} closed</div>
        </div>
        <div className="border border-term-border rounded p-2 text-center">
          <div className="text-term-muted">Total Trades</div>
          <div className="text-term-fg font-bold num">{s.total_trades}</div>
        </div>
        <div className="border border-term-border rounded p-2 text-center">
          <div className="text-term-muted">Unrealized P&L</div>
          <div className={cn("font-bold num", s.total_unrealized_pl >= 0 ? "up" : "down")}>{fmt$(s.total_unrealized_pl)}</div>
        </div>
        <div className="border border-term-border rounded p-2 text-center">
          <div className="text-term-muted">Realized P&L</div>
          <div className={cn("font-bold num", s.total_realized_pl >= 0 ? "up" : "down")}>{fmt$(s.total_realized_pl)}</div>
        </div>
      </div>

      {/* Per-position breakdown */}
      {data.positions.map((pos) => (
        <PositionDetail key={pos.symbol} pos={pos} />
      ))}
    </div>
  );
}

function PositionDetail({ pos }: { pos: any }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border border-term-border/60 rounded bg-term-bg-secondary">
      <div
        className="flex items-center justify-between p-2 cursor-pointer hover:bg-term-border/20"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-bold text-term-amber">{pos.symbol}</span>
          <span className={cn("text-[8px] px-1 rounded font-bold",
            pos.status === "OPEN" ? "bg-green-900 text-green-300" : "bg-term-border text-term-muted"
          )}>{pos.status}</span>
          {pos.current_qty > 0 && <span className="text-[10px] text-term-muted num">{pos.current_qty} shares</span>}
        </div>
        <div className="flex items-center gap-3 text-[10px]">
          {pos.current_qty > 0 && (
            <>
              <span className="text-term-muted">Avg: <span className="num text-term-fg">{fmt$(pos.avg_cost)}</span></span>
              <span className="text-term-muted">Now: <span className="num text-term-fg">{fmt$(pos.current_price)}</span></span>
              <span className="text-term-muted">Mkt: <span className="num text-term-fg">{fmt$(pos.market_value)}</span></span>
            </>
          )}
          <span className={cn("font-bold num", pos.total_pl >= 0 ? "up" : "down")}>
            {fmt$(pos.total_pl)} ({fmtPct(pos.unrealized_pct)})
          </span>
          <span className="text-term-muted">{expanded ? "▲" : "▼"}</span>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-term-border/40 p-2 space-y-2">
          {/* Position Stats Grid */}
          <div className="grid grid-cols-6 gap-1 text-[9px]">
            <div className="text-center"><div className="text-term-muted">Cost Basis</div><div className="num">{fmt$(pos.cost_basis)}</div></div>
            <div className="text-center"><div className="text-term-muted">Market Value</div><div className="num">{fmt$(pos.market_value)}</div></div>
            <div className="text-center"><div className="text-term-muted">Unrealized</div><div className={cn("num", pos.unrealized_pl >= 0 ? "up" : "down")}>{fmt$(pos.unrealized_pl)}</div></div>
            <div className="text-center"><div className="text-term-muted">Realized</div><div className={cn("num", pos.realized_pl >= 0 ? "up" : "down")}>{fmt$(pos.realized_pl)}</div></div>
            <div className="text-center"><div className="text-term-muted">Bought</div><div className="num">{pos.total_bought_qty} @ {fmt$(pos.total_bought_qty > 0 ? pos.total_bought_cost / pos.total_bought_qty : 0)}</div></div>
            <div className="text-center"><div className="text-term-muted">Sold</div><div className="num">{pos.total_sold_qty > 0 ? `${pos.total_sold_qty} @ ${fmt$(pos.total_sold_proceeds / pos.total_sold_qty)}` : "—"}</div></div>
          </div>

          {/* Trade History Table */}
          {pos.trades.length > 0 && (
            <table className="w-full text-[9px]">
              <thead>
                <tr className="text-term-muted uppercase border-b border-term-border/40">
                  <th className="text-left p-0.5">Date</th>
                  <th className="text-left p-0.5">Side</th>
                  <th className="text-right p-0.5">Qty</th>
                  <th className="text-right p-0.5">Price</th>
                  <th className="text-right p-0.5">Total</th>
                </tr>
              </thead>
              <tbody>
                {pos.trades.map((t: any, i: number) => (
                  <tr key={i} className="border-t border-term-border/20">
                    <td className="p-0.5 text-term-muted">{t.time ? new Date(t.time).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
                    <td className={cn("p-0.5 font-bold", t.side === "BUY" ? "text-green-400" : "text-red-400")}>{t.side}</td>
                    <td className="text-right p-0.5 num">{t.qty}</td>
                    <td className="text-right p-0.5 num">{fmt$(t.price)}</td>
                    <td className="text-right p-0.5 num">{fmt$(t.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {pos.trades.length === 0 && pos.status === "OPEN" && (
            <div className="text-[9px] text-term-muted italic">Position held — no trade history in system (synced from broker)</div>
          )}
        </div>
      )}
    </div>
  );
}

function PortfolioCard({ portfolio, nav }: { portfolio: LeaderboardEntry; nav?: PortfolioNav }) {
  const [showTrade, setShowTrade] = useState(false);
  const [showCash, setShowCash] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const qc = useQueryClient();
  const isUser = portfolio.type === "user";
  const [refreshing, setRefreshing] = useState(false);
  const doRefresh = async () => { setRefreshing(true); try { await refreshPortfolio(portfolio.id); qc.invalidateQueries({ queryKey: ["all-portfolio-navs"] }); qc.invalidateQueries({ queryKey: ["leaderboard"] }); } catch {} setRefreshing(false); };

  const doDelete = async () => {
    await deletePortfolio(portfolio.id);
    qc.invalidateQueries({ queryKey: ["portfolios"] });
    qc.invalidateQueries({ queryKey: ["leaderboard"] });
    qc.invalidateQueries({ queryKey: ["all-portfolio-navs"] });
  };

  const positions = nav?.positions ?? [];

  return (
    <div className="border border-term-border rounded bg-term-bg-secondary">
      <div className="flex items-center justify-between p-2 border-b border-term-border">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: portfolio.color }} />
          <span className="text-sm font-bold text-term-fg">{portfolio.name}</span>
          <span className={cn("text-[9px] uppercase px-1 rounded border", portfolio.type === "system" ? "border-blue-700 text-blue-300" : portfolio.type === "webull" ? "border-purple-700 text-purple-300" : "border-term-border text-term-fg")}>{portfolio.type === "system" ? "AI" : portfolio.type === "webull" ? "WEBULL" : "USER"}</span>
          <span className="text-[10px] text-term-muted">{portfolio.slug}</span>
          {nav && (nav as any).source && (
            <span className={cn("text-[8px] px-1 rounded font-bold", (nav as any).source === "alpaca_live" ? "bg-green-900 text-green-300" : portfolio.type === "webull" ? "bg-purple-900 text-purple-300" : "bg-term-border text-term-muted")}>
              {(nav as any).source === "alpaca_live" ? "LIVE" : portfolio.type === "webull" ? "WEBULL" : "LOCAL"}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-sm font-bold num text-term-fg">{fmt$(nav?.nav ?? portfolio.nav)}</div>
            <div className="flex gap-2 justify-end">
              <span className={cn("text-[10px] num", (nav?.total_return ?? portfolio.total_return) >= 0 ? "up" : "down")}>
                {fmtPct(nav?.total_return ?? portfolio.total_return)}
              </span>
              {(nav as any)?.daily_return != null && (
                <span className={cn("text-[10px] num", (nav as any).daily_return >= 0 ? "up" : "down")}>
                  day: {fmtPct((nav as any).daily_return)}
                </span>
              )}
            </div>
          </div>
          <button className="text-[9px] px-1.5 py-0.5 border border-term-border text-term-cyan hover:bg-term-border rounded disabled:opacity-40" onClick={doRefresh} disabled={refreshing}>{refreshing ? "..." : "REFRESH"}</button>
          <button className={cn("text-[9px] px-1.5 py-0.5 border border-term-border rounded", showHistory ? "bg-term-amber text-black" : "text-term-amber hover:bg-term-border")} onClick={() => { setShowHistory(!showHistory); setShowTrade(false); setShowCash(false); }}>HISTORY</button>
          {isUser && (
            <div className="flex gap-1">
              <button className="text-[9px] px-1.5 py-0.5 border border-term-border text-term-muted hover:text-term-fg rounded" onClick={() => { setShowTrade(!showTrade); setShowCash(false); }}>TRADE</button>
              <button className="text-[9px] px-1.5 py-0.5 border border-term-border text-term-muted hover:text-term-fg rounded" onClick={() => { setShowCash(!showCash); setShowTrade(false); }}>CASH</button>
              {!confirm ? (
                <button className="text-[9px] px-1.5 py-0.5 border border-red-800 text-red-400 hover:bg-red-900 rounded" onClick={() => setConfirm(true)}>DEL</button>
              ) : (
                <button className="text-[9px] px-1.5 py-0.5 bg-red-700 text-white rounded" onClick={doDelete}>CONFIRM</button>
              )}
            </div>
          )}
        </div>
      </div>

      {showHistory && <div className="p-2"><HistoryPanel portfolioId={portfolio.id} onClose={() => setShowHistory(false)} /></div>}
      {showTrade && <div className="p-2"><TradeForm portfolioId={portfolio.id} onDone={() => setShowTrade(false)} /></div>}
      {showCash && <div className="p-2"><CashForm portfolioId={portfolio.id} onDone={() => setShowCash(false)} /></div>}

      {positions.length > 0 && (
        <div className="px-2 py-1">
          <table className="w-full text-[10px]">
            <thead>
              <tr className="text-term-muted uppercase">
                <th className="text-left p-0.5">Symbol</th>
                <th className="text-right p-0.5">Qty</th>
                <th className="text-right p-0.5">Avg Cost</th>
                <th className="text-right p-0.5">Price</th>
                <th className="text-right p-0.5">Mkt Val</th>
                <th className="text-right p-0.5">P&L</th>
                <th className="text-right p-0.5">%</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p: any) => (
                <tr key={p.symbol} className="border-t border-term-border/30">
                  <td className="p-0.5 font-bold text-term-amber">{p.symbol}</td>
                  <td className="text-right p-0.5 num">{p.qty}</td>
                  <td className="text-right p-0.5 num">{fmt$(p.avg_cost)}</td>
                  <td className="text-right p-0.5 num">{fmt$(p.current_price ?? null)}</td>
                  <td className="text-right p-0.5 num">{fmt$(p.market_value ?? null)}</td>
                  <td className={cn("text-right p-0.5 num", (p.unrealized_pl ?? 0) >= 0 ? "up" : "down")}>{fmt$(p.unrealized_pl ?? null)}</td>
                  <td className={cn("text-right p-0.5 num", (p.unrealized_plpc ?? 0) >= 0 ? "up" : "down")}>{fmtPct(p.unrealized_plpc ?? null)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex gap-4 px-2 py-1 text-[10px] text-term-muted border-t border-term-border/30">
        <span>Cash: <span className="num text-term-fg">{fmt$(nav?.cash ?? portfolio.cash)}</span></span>
        <span>Positions: <span className="num text-term-fg">{positions.length || portfolio.positions_count}</span></span>
        <span>Trades: <span className="num text-term-fg">{portfolio.trade_count}</span></span>
      </div>
    </div>
  );
}

export function PORT() {
  const [creating, setCreating] = useState(false);

  const { data: leaderboard, dataUpdatedAt } = useQuery({
    queryKey: ["leaderboard"],
    queryFn: fetchLeaderboard,
    refetchInterval: REFRESH,
  });

  const allIds = (leaderboard || []).map((p) => p.id);
  const { data: navMap } = useQuery({
    queryKey: ["all-portfolio-navs", allIds.join(",")],
    queryFn: async () => {
      const navs: Record<number, PortfolioNav> = {};
      const fetches = allIds.map(async (id) => {
        try {
          const res = await fetch(`/api/v1/portfolio/${id}/nav`);
          const data = await res.json();
          if (data.results) navs[id] = data.results;
        } catch {}
      });
      await Promise.all(fetches);
      return navs;
    },
    refetchInterval: REFRESH,
    enabled: allIds.length > 0,
  });

  const systemPorts = (leaderboard || []).filter((p) => p.type === "system");
  const webullPorts = (leaderboard || []).filter((p) => p.type === "webull");
  const userPorts = (leaderboard || []).filter((p) => p.type === "user");
  const navData = navMap || {};

  const lastUpdate = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : "—";

  return (
    <div className="h-full overflow-auto space-y-3 p-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-term-amber text-xs font-bold">PORTFOLIO MANAGER</span>
          <span className="text-term-muted text-[10px]">{(leaderboard || []).length} portfolios</span>
          <span className="text-[9px] text-term-muted">Updated: {lastUpdate}</span>
          <span className="text-[8px] px-1 bg-green-900 text-green-300 rounded font-bold">AUTO-REFRESH 30s</span>
        </div>
        {!creating && (
          <button className="px-3 py-1 bg-term-amber text-black text-xs font-bold rounded hover:opacity-80" onClick={() => setCreating(true)}>+ NEW PORTFOLIO</button>
        )}
      </div>

      {creating && <CreateForm onDone={() => setCreating(false)} />}

      {/* Combined Leaderboard */}
      {leaderboard && leaderboard.length > 0 && (
        <div className="border border-term-border rounded">
          <div className="px-2 py-1 border-b border-term-border bg-term-bg-secondary flex items-center justify-between">
            <span className="text-[10px] text-term-amber font-bold uppercase">Combined Leaderboard</span>
            <span className="text-[9px] text-term-muted">Ranked by Total Return</span>
          </div>
          <table className="w-full text-[10px]">
            <thead>
              <tr className="text-term-muted uppercase border-b border-term-border">
                <th className="text-left p-1">#</th>
                <th className="text-left p-1">Portfolio</th>
                <th className="text-left p-1">Type</th>
                <th className="text-left p-1">Source</th>
                <th className="text-right p-1">NAV</th>
                <th className="text-right p-1">Cash</th>
                <th className="text-right p-1">Return</th>
                <th className="text-right p-1">Daily</th>
                <th className="text-right p-1">Trades</th>
                <th className="text-right p-1">Pos</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.map((p, i) => {
                const nav = navData[p.id];
                const displayNav = nav?.nav ?? p.nav;
                const displayCash = nav?.cash ?? p.cash;
                const displayReturn = nav?.total_return ?? p.total_return;
                const dailyRet = (nav as any)?.daily_return ?? (p as any)?.daily_return;
                const source = (nav as any)?.source ?? (p as any)?.source ?? "local";
                return (
                  <tr key={p.id} className="border-t border-term-border/30 hover:bg-term-bg-secondary">
                    <td className="p-1 font-bold text-term-amber">{i + 1}</td>
                    <td className="p-1">
                      <span className="inline-block w-2 h-2 rounded-full mr-1 align-middle" style={{ backgroundColor: p.color }} />
                      <span className="font-bold">{p.name}</span>
                      <span className="text-term-muted ml-1">({p.slug})</span>
                    </td>
                    <td className="p-1">
                      <span className={cn("px-1 rounded text-[9px]", p.type === "system" ? "bg-blue-900 text-blue-300" : p.type === "webull" ? "bg-purple-900 text-purple-300" : "bg-term-border text-term-fg")}>
                        {p.type === "system" ? "AI" : p.type === "webull" ? "WEBULL" : "USER"}
                      </span>
                    </td>
                    <td className="p-1">
                      <span className={cn("px-1 rounded text-[8px] font-bold", source === "alpaca_live" ? "bg-green-900 text-green-300" : p.type === "webull" ? "bg-purple-900 text-purple-300" : "bg-term-border text-term-muted")}>
                        {source === "alpaca_live" ? "LIVE" : p.type === "webull" ? "WEBULL" : "LOCAL"}
                      </span>
                    </td>
                    <td className="text-right p-1 num font-bold">{fmt$(displayNav)}</td>
                    <td className="text-right p-1 num">{fmt$(displayCash)}</td>
                    <td className={cn("text-right p-1 num font-bold", displayReturn >= 0 ? "up" : "down")}>{fmtPct(displayReturn)}</td>
                    <td className={cn("text-right p-1 num", dailyRet != null && dailyRet >= 0 ? "up" : dailyRet != null ? "down" : "")}>{dailyRet != null ? fmtPct(dailyRet) : "—"}</td>
                    <td className="text-right p-1 num">{p.trade_count}</td>
                    <td className="text-right p-1 num">{p.positions_count}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* AI Team Portfolios */}
      {systemPorts.length > 0 && (
        <div>
          <div className="text-[10px] text-term-muted uppercase font-bold mb-1 px-1">AI Team Portfolios (Alpaca Live)</div>
          <div className="space-y-2">
            {systemPorts.map((p) => <PortfolioCard key={p.id} portfolio={p} nav={navData[p.id]} />)}
          </div>
        </div>
      )}

      {/* Webull Portfolios */}
      {webullPorts.length > 0 && (
        <div>
          <div className="text-[10px] text-term-muted uppercase font-bold mb-1 px-1">Webull Portfolios (Read-Only)</div>
          <div className="space-y-2">
            {webullPorts.map((p) => <PortfolioCard key={p.id} portfolio={p} nav={navData[p.id]} />)}
          </div>
        </div>
      )}

      {/* User Portfolios */}
      <div>
        <div className="text-[10px] text-term-muted uppercase font-bold mb-1 px-1">Your Portfolios</div>
        {userPorts.length === 0 ? (
          <div className="text-term-muted text-xs p-3 border border-term-border rounded text-center">
            No portfolios yet. Click <span className="text-term-amber font-bold">+ NEW PORTFOLIO</span> to create one.
          </div>
        ) : (
          <div className="space-y-2">
            {userPorts.map((p) => <PortfolioCard key={p.id} portfolio={p} nav={navData[p.id]} />)}
          </div>
        )}
      </div>
    </div>
  );
}
