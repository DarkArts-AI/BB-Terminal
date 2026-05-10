import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  fetchIssuedStocks, addIssuedLot, deleteIssuedLot,
  recordStockSale, fetchStockSales, fetchTaxSummary,
} from "@/lib/cm_api";
import { cn } from "@/lib/cn";

const fmt$ = (n: number | null | undefined) => (n ?? 0).toLocaleString("en-US", { style: "currency", currency: "USD" });
const fmtN = (n: number | null | undefined) => (n ?? 0).toLocaleString("en-US");
const fmtPct = (n: number | null | undefined) => ((n ?? 0) >= 0 ? "+" : "") + ((n ?? 0) * 100).toFixed(2) + "%";

type Tab = "positions" | "tax";

export function ISP() {
  const [tab, setTab] = useState<Tab>("positions");
  const [showAdd, setShowAdd] = useState(false);
  const [sellLot, setSellLot] = useState<{ id: number; symbol: string; remaining: number; issue_price: number } | null>(null);

  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["issued-stocks"],
    queryFn: fetchIssuedStocks,
    refetchInterval: 60_000,
  });

  if (isLoading) return <div className="p-4 text-term-muted text-xs">Loading issued stock data...</div>;
  if (error) return <div className="p-4 text-red-400 text-xs">Failed to load issued stocks: {(error as Error).message}</div>;
  if (!data) return <div className="p-4 text-term-muted text-xs">No data available</div>;

  const s = data.summary || { total_cost_basis: 0, total_market_value: 0, total_unrealized_gain: 0, total_realized_gain: 0 };
  const symbols = data.by_symbol || [];

  return (
    <div className="h-full overflow-auto space-y-3 p-2">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-term-amber text-xs font-bold">ISSUED STOCK PROGRAM</span>
          <span className="text-term-muted text-[10px]">{symbols.length} position{symbols.length !== 1 ? "s" : ""}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            className={cn("px-2 py-0.5 text-[9px] font-bold rounded border", tab === "positions" ? "bg-term-amber text-black border-term-amber" : "border-term-border text-term-muted hover:text-term-fg")}
            onClick={() => setTab("positions")}
          >POSITIONS</button>
          <button
            className={cn("px-2 py-0.5 text-[9px] font-bold rounded border", tab === "tax" ? "bg-cyan-700 text-white border-cyan-700" : "border-term-border text-term-muted hover:text-term-fg")}
            onClick={() => setTab("tax")}
          >TAX SUMMARY</button>
        </div>
      </div>

      {/* Summary Bar */}
      <div className="grid grid-cols-4 gap-2 text-[10px]">
        <div className="border border-term-border rounded p-2 text-center">
          <div className="text-term-muted">Total Cost Basis</div>
          <div className="text-term-fg font-bold num">{fmt$(s.total_cost_basis)}</div>
        </div>
        <div className="border border-term-border rounded p-2 text-center">
          <div className="text-term-muted">Total Market Value</div>
          <div className="text-term-fg font-bold num">{fmt$(s.total_market_value)}</div>
        </div>
        <div className="border border-term-border rounded p-2 text-center">
          <div className="text-term-muted">Unrealized G/L</div>
          <div className={cn("font-bold num", s.total_unrealized_gain >= 0 ? "text-green-400" : "text-red-400")}>
            {fmt$(s.total_unrealized_gain)}
          </div>
        </div>
        <div className="border border-term-border rounded p-2 text-center">
          <div className="text-term-muted">Realized G/L</div>
          <div className={cn("font-bold num", s.total_realized_gain >= 0 ? "text-green-400" : "text-red-400")}>
            {fmt$(s.total_realized_gain)}
          </div>
        </div>
      </div>

      {tab === "positions" && (
        <>
          <div className="flex items-center gap-2">
            <button
              className="px-3 py-1 bg-term-amber text-black text-xs font-bold rounded hover:opacity-80"
              onClick={() => { setShowAdd(!showAdd); setSellLot(null); }}
            >{showAdd ? "CANCEL" : "ADD SHARES"}</button>
          </div>

          {showAdd && <AddSharesForm onDone={() => { setShowAdd(false); qc.invalidateQueries({ queryKey: ["issued-stocks"] }); }} />}
          {sellLot && <SaleForm lot={sellLot} onDone={() => { setSellLot(null); qc.invalidateQueries({ queryKey: ["issued-stocks"] }); }} />}

          <PositionsTable symbols={symbols} onSellLot={(lot) => { setSellLot(lot); setShowAdd(false); }} />
        </>
      )}

      {tab === "tax" && <TaxView />}
    </div>
  );
}

/* ── Positions Table ──────────────────────────────────────────── */

function PositionsTable({ symbols, onSellLot }: {
  symbols: any[];
  onSellLot: (lot: { id: number; symbol: string; remaining: number; issue_price: number }) => void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const qc = useQueryClient();
  const deleteMut = useMutation({
    mutationFn: deleteIssuedLot,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["issued-stocks"] }),
  });

  if (symbols.length === 0) {
    return (
      <div className="text-term-muted text-xs p-3 border border-term-border rounded text-center">
        No issued stock positions. Click <span className="text-term-amber font-bold">ADD SHARES</span> to record stock issuance.
      </div>
    );
  }

  return (
    <div className="border border-term-border rounded">
      <table className="w-full text-[10px]">
        <thead>
          <tr className="text-term-muted uppercase border-b border-term-border bg-term-bg-secondary">
            <th className="text-left p-1 w-6"></th>
            <th className="text-left p-1">Symbol</th>
            <th className="text-right p-1">Shares</th>
            <th className="text-right p-1">Cost Basis</th>
            <th className="text-right p-1">Issue Price</th>
            <th className="text-right p-1">Current</th>
            <th className="text-right p-1">Delta</th>
            <th className="text-right p-1">Chg%</th>
            <th className="text-right p-1">Mkt Value</th>
            <th className="text-right p-1">Unreal G/L</th>
            <th className="text-right p-1">%</th>
          </tr>
        </thead>
        <tbody>
          {symbols.map((sym: any) => {
            const isExp = expanded[sym.symbol] ?? false;
            const lots = sym.lots || [];
            const gl = sym.total_unrealized_gain ?? 0;
            const costBasis = sym.total_cost_basis ?? 0;
            const glPct = costBasis > 0 ? gl / costBasis : 0;

            return (
              <SymbolRows
                key={sym.symbol}
                sym={sym}
                lots={lots}
                gl={gl}
                glPct={glPct}
                isExpanded={isExp}
                onToggle={() => setExpanded((prev) => ({ ...prev, [sym.symbol]: !isExp }))}
                onSellLot={onSellLot}
                onDeleteLot={(id) => { if (confirm(`Delete lot #${id}?`)) deleteMut.mutate(id); }}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SymbolRows({ sym, lots, gl, glPct, isExpanded, onToggle, onSellLot, onDeleteLot }: {
  sym: any; lots: any[]; gl: number; glPct: number; isExpanded: boolean;
  onToggle: () => void;
  onSellLot: (lot: { id: number; symbol: string; remaining: number; issue_price: number }) => void;
  onDeleteLot: (id: number) => void;
}) {
  return (
    <>
      <tr className="border-t border-term-border/30 hover:bg-term-bg-secondary cursor-pointer" onClick={onToggle}>
        <td className="p-1 text-term-muted">{isExpanded ? "▼" : "▶"}</td>
        <td className="p-1 font-bold text-term-amber">{sym.symbol}</td>
        <td className="text-right p-1 num">{fmtN(sym.total_remaining_qty)}</td>
        <td className="text-right p-1 num">{fmt$(sym.total_cost_basis)}</td>
        <td className="text-right p-1 num">{sym.total_remaining_qty > 0 ? fmt$(sym.total_cost_basis / sym.total_remaining_qty) : "---"}</td>
        <td className="text-right p-1 num">{sym.current_price != null ? fmt$(sym.current_price) : "---"}</td>
        <td className={cn("text-right p-1 num", (sym.current_price != null && sym.total_remaining_qty > 0) ? ((sym.current_price - sym.total_cost_basis / sym.total_remaining_qty) >= 0 ? "text-green-400" : "text-red-400") : "")}>{sym.current_price != null && sym.total_remaining_qty > 0 ? fmt$(sym.current_price - sym.total_cost_basis / sym.total_remaining_qty) : "---"}</td>
        <td className={cn("text-right p-1 num", (sym.current_price != null && sym.total_cost_basis > 0) ? ((sym.current_price * sym.total_remaining_qty - sym.total_cost_basis) >= 0 ? "text-green-400" : "text-red-400") : "")}>{sym.current_price != null && sym.total_cost_basis > 0 ? fmtPct((sym.current_price * sym.total_remaining_qty - sym.total_cost_basis) / sym.total_cost_basis) : "---"}</td>
        <td className="text-right p-1 num">{fmt$(sym.total_market_value)}</td>
        <td className={cn("text-right p-1 num font-bold", gl >= 0 ? "text-green-400" : "text-red-400")}>{fmt$(gl)}</td>
        <td className={cn("text-right p-1 num", glPct >= 0 ? "text-green-400" : "text-red-400")}>{fmtPct(glPct)}</td>
      </tr>
      {isExpanded && lots.map((lot: any) => (
        <tr key={lot.id} className="border-t border-term-border/10 bg-term-bg-secondary/50 text-[9px]">
          <td className="p-1"></td>
          <td className="p-1 text-term-muted pl-4">
            Lot #{lot.id} — {new Date(lot.issue_date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" })}
          </td>
          <td className="text-right p-1 num text-term-muted">{fmtN(lot.quantity)} issued / {fmtN(lot.remaining_qty)} rem</td>
          <td className="text-right p-1 num">@ {fmt$(lot.issue_price)}</td>
          <td className="text-right p-1 num">{fmt$(lot.issue_price)}</td>
          <td className="text-right p-1 num">{lot.current_price != null ? fmt$(lot.current_price) : "---"}</td>
          <td className={cn("text-right p-1 num", lot.current_price != null ? ((lot.current_price - lot.issue_price) >= 0 ? "text-green-400" : "text-red-400") : "")}>{lot.current_price != null ? fmt$(lot.current_price - lot.issue_price) : "---"}</td>
          <td className={cn("text-right p-1 num", lot.current_price != null ? ((lot.current_price - lot.issue_price) >= 0 ? "text-green-400" : "text-red-400") : "")}>{lot.current_price != null && lot.issue_price > 0 ? fmtPct((lot.current_price - lot.issue_price) / lot.issue_price) : "---"}</td>
          <td className="text-right p-1 num">{lot.current_value != null ? fmt$(lot.current_value) : "---"}</td>
          <td className={cn("text-right p-1 num", (lot.unrealized_gain ?? 0) >= 0 ? "text-green-400" : "text-red-400")}>
            {lot.unrealized_gain != null ? fmt$(lot.unrealized_gain) : "---"}
          </td>
          <td className="text-right p-1">
            <div className="flex items-center justify-end gap-1">
              {lot.remaining_qty > 0 && (
                <button
                  className="px-1.5 py-0.5 bg-red-800 text-red-200 text-[8px] font-bold rounded hover:bg-red-700"
                  onClick={(e) => { e.stopPropagation(); onSellLot({ id: lot.id, symbol: lot.symbol, remaining: lot.remaining_qty, issue_price: lot.issue_price }); }}
                >SELL</button>
              )}
              <button
                className="px-1 py-0.5 border border-red-800 text-red-400 text-[8px] rounded hover:bg-red-900"
                onClick={(e) => { e.stopPropagation(); onDeleteLot(lot.id); }}
              >DEL</button>
            </div>
          </td>
        </tr>
      ))}
    </>
  );
}

/* ── Add Shares Form ──────────────────────────────────────────── */

function AddSharesForm({ onDone }: { onDone: () => void }) {
  const [symbol, setSymbol] = useState("");
  const [quantity, setQuantity] = useState("");
  const [issuePrice, setIssuePrice] = useState("");
  const [issueDate, setIssueDate] = useState(new Date().toISOString().split("T")[0]);
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState("");
  const qc = useQueryClient();

  const mut = useMutation({
    mutationFn: addIssuedLot,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["issued-stocks"] }); onDone(); },
    onError: (e: Error) => setErr(e.message),
  });

  const submit = () => {
    if (!symbol.trim()) { setErr("Symbol required"); return; }
    if (!quantity || parseFloat(quantity) <= 0) { setErr("Quantity required"); return; }
    if (!issuePrice || parseFloat(issuePrice) <= 0) { setErr("Issue price required"); return; }
    setErr("");
    mut.mutate({
      symbol: symbol.trim().toUpperCase(),
      quantity: parseFloat(quantity),
      issue_price: parseFloat(issuePrice),
      issue_date: issueDate,
      notes: notes.trim() || undefined,
    });
  };

  return (
    <div className="border border-term-border p-3 space-y-2 bg-term-bg-secondary rounded">
      <div className="text-term-amber text-xs font-bold uppercase">Add Issued Shares</div>
      <div className="flex gap-2 items-center flex-wrap">
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 w-24 rounded uppercase" placeholder="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 w-20 rounded" placeholder="Qty" type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 w-28 rounded" placeholder="Issue Price" type="number" step="0.01" value={issuePrice} onChange={(e) => setIssuePrice(e.target.value)} />
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 w-32 rounded" type="date" value={issueDate} onChange={(e) => setIssueDate(e.target.value)} />
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 flex-1 rounded" placeholder="Notes (optional — CUSIP, cert #, etc.)" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <button className="px-3 py-1 bg-term-amber text-black text-xs font-bold rounded hover:opacity-80 disabled:opacity-40" onClick={submit} disabled={mut.isPending}>{mut.isPending ? "..." : "SUBMIT"}</button>
        <button className="px-2 py-1 text-term-muted text-xs hover:text-term-fg" onClick={onDone}>CANCEL</button>
      </div>
      {err && <div className="text-red-400 text-[10px]">{err}</div>}
    </div>
  );
}

/* ── Sale Form ────────────────────────────────────────────────── */

function SaleForm({ lot, onDone }: {
  lot: { id: number; symbol: string; remaining: number; issue_price: number };
  onDone: () => void;
}) {
  const [quantity, setQuantity] = useState(String(lot.remaining));
  const [salePrice, setSalePrice] = useState("");
  const [saleDate, setSaleDate] = useState(new Date().toISOString().split("T")[0]);
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState("");
  const qc = useQueryClient();

  const mut = useMutation({
    mutationFn: recordStockSale,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["issued-stocks"] }); qc.invalidateQueries({ queryKey: ["stock-sales"] }); qc.invalidateQueries({ queryKey: ["tax-summary"] }); onDone(); },
    onError: (e: Error) => setErr(e.message),
  });

  const qty = parseFloat(quantity) || 0;
  const price = parseFloat(salePrice) || 0;
  const costBasis = qty * lot.issue_price;
  const proceeds = qty * price;
  const realizedGain = proceeds - costBasis;

  const submit = () => {
    if (qty <= 0 || qty > lot.remaining) { setErr(`Qty must be 1-${lot.remaining}`); return; }
    if (price <= 0) { setErr("Sale price required"); return; }
    setErr("");
    mut.mutate({
      lot_id: lot.id,
      quantity: qty,
      sale_price: price,
      sale_date: saleDate,
      notes: notes.trim() || undefined,
    });
  };

  return (
    <div className="border border-red-900 p-3 space-y-2 bg-term-bg-secondary rounded">
      <div className="text-red-400 text-xs font-bold uppercase">Sell Shares — {lot.symbol} (Lot #{lot.id})</div>
      <div className="text-[9px] text-term-muted">
        Remaining: <span className="text-term-fg font-bold">{fmtN(lot.remaining)}</span> shares @ {fmt$(lot.issue_price)} issue price
      </div>
      <div className="flex gap-2 items-center flex-wrap">
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 w-20 rounded" placeholder="Qty" type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 w-28 rounded" placeholder="Sale Price" type="number" step="0.01" value={salePrice} onChange={(e) => setSalePrice(e.target.value)} />
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 w-32 rounded" type="date" value={saleDate} onChange={(e) => setSaleDate(e.target.value)} />
        <input className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 flex-1 rounded" placeholder="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <button className="px-3 py-1 bg-red-700 text-white text-xs font-bold rounded hover:opacity-80 disabled:opacity-40" onClick={submit} disabled={mut.isPending}>{mut.isPending ? "..." : "EXECUTE SALE"}</button>
        <button className="px-2 py-1 text-term-muted text-xs hover:text-term-fg" onClick={onDone}>CANCEL</button>
      </div>
      {price > 0 && qty > 0 && (
        <div className="flex gap-4 text-[9px]">
          <span className="text-term-muted">Cost Basis: <span className="num text-term-fg">{fmt$(costBasis)}</span></span>
          <span className="text-term-muted">Proceeds: <span className="num text-term-fg">{fmt$(proceeds)}</span></span>
          <span className="text-term-muted">Realized G/L: <span className={cn("num font-bold", realizedGain >= 0 ? "text-green-400" : "text-red-400")}>{fmt$(realizedGain)}</span></span>
        </div>
      )}
      {err && <div className="text-red-400 text-[10px]">{err}</div>}
    </div>
  );
}

/* ── Tax Summary View ─────────────────────────────────────────── */

function TaxView() {
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);

  const { data: taxData, isLoading: taxLoading } = useQuery({
    queryKey: ["tax-summary", year],
    queryFn: () => fetchTaxSummary(year),
  });

  const { data: salesData, isLoading: salesLoading } = useQuery({
    queryKey: ["stock-sales"],
    queryFn: () => fetchStockSales(),
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-cyan-400 text-xs font-bold">TAX YEAR:</span>
        <select
          className="bg-term-bg border border-term-border text-term-fg text-xs px-2 py-1 rounded"
          value={year}
          onChange={(e) => setYear(parseInt(e.target.value))}
        >
          {Array.from({ length: 5 }, (_, i) => currentYear - i).map((y) => (
            <option key={y} value={y}>{y}</option>
          ))}
        </select>
      </div>

      {taxLoading ? (
        <div className="text-term-muted text-xs p-3">Loading tax data...</div>
      ) : taxData ? (
        <>
          <div className="grid grid-cols-3 gap-2 text-[10px]">
            <div className="border border-cyan-800 rounded p-2 text-center">
              <div className="text-cyan-400 font-bold">Short-Term</div>
              <div className={cn("font-bold num text-lg", (taxData.short_term_total ?? 0) >= 0 ? "text-green-400" : "text-red-400")}>
                {fmt$(taxData.short_term_total)}
              </div>
            </div>
            <div className="border border-cyan-800 rounded p-2 text-center">
              <div className="text-cyan-400 font-bold">Long-Term</div>
              <div className={cn("font-bold num text-lg", (taxData.long_term_total ?? 0) >= 0 ? "text-green-400" : "text-red-400")}>
                {fmt$(taxData.long_term_total)}
              </div>
            </div>
            <div className="border border-cyan-800 rounded p-2 text-center">
              <div className="text-cyan-400 font-bold">Combined</div>
              <div className={cn("text-lg font-bold num", (taxData.combined_total ?? 0) >= 0 ? "text-green-400" : "text-red-400")}>
                {fmt$(taxData.combined_total)}
              </div>
            </div>
          </div>

          {taxData.per_symbol && Object.keys(taxData.per_symbol).length > 0 && (
            <div className="border border-term-border rounded">
              <div className="px-2 py-1 border-b border-term-border bg-term-bg-secondary">
                <span className="text-[10px] text-cyan-400 font-bold uppercase">By Symbol — {year}</span>
              </div>
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="text-term-muted uppercase border-b border-term-border">
                    <th className="text-left p-1">Symbol</th>
                    <th className="text-right p-1">Short-Term</th>
                    <th className="text-right p-1">Long-Term</th>
                    <th className="text-right p-1">Total</th>
                    <th className="text-right p-1">Sales</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(taxData.per_symbol).map(([sym, row]: [string, any]) => {
                    const total = (row.short_term ?? 0) + (row.long_term ?? 0);
                    return (
                      <tr key={sym} className="border-t border-term-border/30">
                        <td className="p-1 font-bold text-term-amber">{sym}</td>
                        <td className={cn("text-right p-1 num", (row.short_term ?? 0) >= 0 ? "text-green-400" : "text-red-400")}>{fmt$(row.short_term)}</td>
                        <td className={cn("text-right p-1 num", (row.long_term ?? 0) >= 0 ? "text-green-400" : "text-red-400")}>{fmt$(row.long_term)}</td>
                        <td className={cn("text-right p-1 num font-bold", total >= 0 ? "text-green-400" : "text-red-400")}>{fmt$(total)}</td>
                        <td className="text-right p-1 num">{row.sale_count ?? 0}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}

      {salesLoading ? (
        <div className="text-term-muted text-xs p-3">Loading sales history...</div>
      ) : salesData && salesData.sales && salesData.sales.length > 0 ? (
        <div className="border border-term-border rounded">
          <div className="px-2 py-1 border-b border-term-border bg-term-bg-secondary">
            <span className="text-[10px] text-cyan-400 font-bold uppercase">Sales History</span>
          </div>
          <table className="w-full text-[10px]">
            <thead>
              <tr className="text-term-muted uppercase border-b border-term-border">
                <th className="text-left p-1">Date</th>
                <th className="text-left p-1">Symbol</th>
                <th className="text-right p-1">Qty</th>
                <th className="text-right p-1">Sale Price</th>
                <th className="text-right p-1">Cost Basis</th>
                <th className="text-right p-1">Proceeds</th>
                <th className="text-right p-1">G/L</th>
                <th className="text-left p-1">Period</th>
              </tr>
            </thead>
            <tbody>
              {salesData.sales.map((sale: any) => (
                <tr key={sale.id} className="border-t border-term-border/30">
                  <td className="p-1 text-term-muted">
                    {new Date(sale.sale_date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" })}
                  </td>
                  <td className="p-1 font-bold text-term-amber">{sale.symbol}</td>
                  <td className="text-right p-1 num">{fmtN(sale.quantity)}</td>
                  <td className="text-right p-1 num">{fmt$(sale.sale_price)}</td>
                  <td className="text-right p-1 num">{fmt$(sale.cost_basis)}</td>
                  <td className="text-right p-1 num">{fmt$(sale.proceeds)}</td>
                  <td className={cn("text-right p-1 num font-bold", sale.realized_gain >= 0 ? "text-green-400" : "text-red-400")}>{fmt$(sale.realized_gain)}</td>
                  <td className="p-1">
                    <span className={cn("text-[8px] px-1 rounded font-bold", sale.holding_period === "long" ? "bg-cyan-900 text-cyan-300" : "bg-yellow-900 text-yellow-300")}>
                      {sale.holding_period === "long" ? "LONG" : "SHORT"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-term-muted text-xs p-3 border border-term-border rounded text-center">
          No sales recorded yet.
        </div>
      )}
    </div>
  );
}
