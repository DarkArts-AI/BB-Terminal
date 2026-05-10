export type FunctionCode =
  | "CC" | "INTEL" | "HELP"
  | "DES" | "GP" | "QR" | "HP"
  | "FA" | "KEY" | "DVD" | "EE" | "NI"
  | "WEI" | "MOV" | "OMON"
  | "CURV" | "FXC" | "CRYPTO"
  | "COMP" | "ALPHA" | "BRAVO" | "CHARLIE" | "PORT" | "ISP" | "COV" | "NARV";

export interface FunctionDef {
  code: FunctionCode;
  name: string;
  needsSymbol: boolean;
  group: "Security" | "Markets" | "Macro" | "System" | "Cortex-Medusa";
  summary: string;
}

export const FUNCTIONS: FunctionDef[] = [
  { code: "COMP",    name: "Competition",           needsSymbol: false, group: "Cortex-Medusa", summary: "Alpha vs Bravo vs Charlie — leaderboard, NAV, pipeline status" },
  { code: "ALPHA",   name: "Alpha Dashboard",       needsSymbol: false, group: "Cortex-Medusa", summary: "CF-01 · Codex CLI · Portfolio 2A · Research, trades, reconciliation" },
  { code: "BRAVO",   name: "Bravo Dashboard",       needsSymbol: false, group: "Cortex-Medusa", summary: "CF-02 · Gemini CLI · Portfolio 2B · Research, trades, reconciliation" },
  { code: "CHARLIE", name: "Charlie Dashboard",     needsSymbol: false, group: "Cortex-Medusa", summary: "CF-03 · Claude Code · Portfolio 2C · Research, trades, reconciliation" },
  { code: "PORT",    name: "Portfolio Manager",      needsSymbol: false, group: "Cortex-Medusa", summary: "Create portfolios, simulate trades, manage cash — unified leaderboard" },
  { code: "ISP",     name: "Issued Stock Program",   needsSymbol: false, group: "Cortex-Medusa", summary: "Track stock issued in lieu of payment — lots, sales, tax summary" },
  { code: "COV",     name: "Coverage Map",          needsSymbol: false, group: "Cortex-Medusa", summary: "Fleet watchlist coverage, convergence alerts, KPI dashboard" },
  { code: "NARV",    name: "Pipeline Narrative",    needsSymbol: false, group: "Cortex-Medusa", summary: "Conversation-style pipeline display with debate rounds" },

  { code: "CC",   name: "Command Center",        needsSymbol: false, group: "System", summary: "Morning briefing · markets, curve, FX, movers, news" },
  { code: "HELP", name: "Function Directory",    needsSymbol: false, group: "System", summary: "List of all terminal functions" },

  { code: "INTEL", name: "Stock Intelligence",   needsSymbol: true,  group: "Security", summary: "Full scorecard — signals across technical, value, fundamentals, analysts" },
  { code: "DES",  name: "Security Description", needsSymbol: true,  group: "Security", summary: "Company profile, sector, HQ, employees" },
  { code: "GP",   name: "Graph / Chart",         needsSymbol: true,  group: "Security", summary: "Historical candlestick chart + volume" },
  { code: "QR",   name: "Quote Recap",           needsSymbol: true,  group: "Security", summary: "Live quote: last, bid/ask, volume, day range" },
  { code: "HP",   name: "Historical Prices",     needsSymbol: true,  group: "Security", summary: "OHLCV table" },
  { code: "FA",   name: "Financial Analysis",    needsSymbol: true,  group: "Security", summary: "Income statement — last 5 fiscal years" },
  { code: "KEY",  name: "Key Ratios & Metrics",  needsSymbol: true,  group: "Security", summary: "PE, EV/EBITDA, margins, ROE, etc." },
  { code: "DVD",  name: "Dividend History",      needsSymbol: true,  group: "Security", summary: "All historical dividends" },
  { code: "EE",   name: "Analyst Estimates",     needsSymbol: true,  group: "Security", summary: "Target prices, recommendation, analyst count" },
  { code: "NI",   name: "News — Company",        needsSymbol: true,  group: "Security", summary: "Latest headlines for the symbol" },
  { code: "OMON", name: "Options Monitor",       needsSymbol: true,  group: "Security", summary: "Options chain with bid/ask, IV, OI, volume" },

  { code: "WEI",  name: "World Equity Indices",  needsSymbol: false, group: "Markets", summary: "Major global indices — level & daily change" },
  { code: "MOV",  name: "Market Movers",         needsSymbol: false, group: "Markets", summary: "US gainers, losers, most active" },
  { code: "CRYPTO", name: "Crypto Monitor",      needsSymbol: false, group: "Markets", summary: "Top crypto prices + sparkline" },
  { code: "FXC",  name: "FX Cross Rates",        needsSymbol: false, group: "Markets", summary: "Major FX pairs matrix" },

  { code: "CURV", name: "US Yield Curve",        needsSymbol: false, group: "Macro", summary: "Treasury par yield curve" },
];

export const FN_BY_CODE: Record<string, FunctionDef> = Object.fromEntries(FUNCTIONS.map((f) => [f.code, f]));

export interface ParsedCommand {
  symbol?: string;
  code: FunctionCode;
}

export function parseCommand(raw: string, activeSymbol: string | null): ParsedCommand | null {
  const parts = raw.trim().toUpperCase().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return null;

  const isFn = (s: string): s is FunctionCode => s in FN_BY_CODE;

  if (parts.length === 1) {
    const p = parts[0];
    if (isFn(p)) {
      const fn = FN_BY_CODE[p];
      if (fn.needsSymbol) {
        if (!activeSymbol) return null;
        return { symbol: activeSymbol, code: p };
      }
      return { code: p };
    }
    return { symbol: p, code: "INTEL" };
  }

  const [sym, fn] = parts;
  if (isFn(fn)) return { symbol: sym, code: fn };
  if (isFn(sym)) {
    const f = FN_BY_CODE[sym];
    return f.needsSymbol ? { symbol: fn, code: sym } : { code: sym };
  }
  return null;
}
