import { useWorkspace } from "@/store/workspaceStore";
import { FN_BY_CODE, type FunctionCode } from "@/lib/functions";
import { cn } from "@/lib/cn";

interface Btn { code: FunctionCode; label: string; }

const BUTTONS: Btn[] = [
  { code: "PORT",    label: "Portfolio" },
  { code: "ISP",     label: "Stock Prog" },
  { code: "COMP",    label: "Competition" },
  { code: "ALPHA",   label: "Alpha" },
  { code: "BRAVO",   label: "Bravo" },
  { code: "CHARLIE", label: "Charlie" },
  { code: "COV",     label: "Coverage" },
  { code: "NARV",    label: "Narrative" },
  { code: "CC",      label: "Markets" },
  { code: "INTEL",   label: "Intel" },
  { code: "GP",      label: "Chart" },
  { code: "KEY",     label: "Ratios" },
  { code: "FA",      label: "Financials" },
  { code: "NI",      label: "News" },
  { code: "MOV",     label: "Movers" },
  { code: "WEI",     label: "Global" },
  { code: "CRYPTO",  label: "Crypto" },
  { code: "CURV",    label: "Yields" },
  { code: "HELP",    label: "Help" },
];

export function QuickBar() {
  const { openTab, activeSymbol, tabs, activeTabId } = useWorkspace();
  const activeCode = tabs.find((t) => t.id === activeTabId)?.code;

  return (
    <div className="flex items-stretch h-9 bg-term-bg2 border-b border-term-border overflow-x-auto scroll-thin">
      <span className="hidden sm:flex items-center px-3 sub-header shrink-0 border-r border-term-border">
        CORTEX-MEDUSA
      </span>
      {BUTTONS.map((b) => {
        const fn = FN_BY_CODE[b.code];
        const isActive = b.code === activeCode;
        const needsSymbol = fn?.needsSymbol;
        const title = needsSymbol
          ? `${b.code} — ${fn.name} · uses CTX ${activeSymbol ?? "AAPL"}`
          : `${b.code} — ${fn?.name || b.label}`;
        return (
          <button
            key={b.code}
            title={title}
            onClick={() => openTab(b.code, needsSymbol ? (activeSymbol ?? "AAPL") : undefined)}
            className={cn(
              "group flex flex-col items-center justify-center px-3 py-1 border-r border-term-border shrink-0 min-w-[78px] transition-colors",
              isActive
                ? "bg-term-amberSubtle text-term-amber"
                : "hover:bg-term-panel2 text-term-muted hover:text-term-text"
            )}
          >
            <span className={cn(
              "text-[11px] font-bold tracking-[0.12em]",
              isActive ? "text-term-amber" : "text-term-amber/70 group-hover:text-term-amber"
            )}>
              {b.code}
            </span>
            <span className="text-[9px] uppercase tracking-[0.15em] text-term-muted group-hover:text-term-text">
              {b.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
