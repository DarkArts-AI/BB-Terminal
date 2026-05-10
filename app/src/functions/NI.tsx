import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchNewsCompany } from "@/lib/api";
import { fetchResearchNews, fetchSecFilings } from "@/lib/cm_api";
import { fmtTime } from "@/lib/format";
import { ExternalLink, FileText, RefreshCw } from "lucide-react";
import { cn } from "@/lib/cn";

type Tab = "news" | "filings";

export function NI({ symbol }: { symbol: string }) {
  const [tab, setTab] = useState<Tab>("news");
  const [sweeping, setSweeping] = useState(false);
  const [sweepResult, setSweepResult] = useState<string | null>(null);

  const market = useQuery({
    queryKey: ["news", symbol], queryFn: () => fetchNewsCompany(symbol, 50),
    staleTime: 60_000,
  });

  const research = useQuery({
    queryKey: ["research-news", symbol], queryFn: () => fetchResearchNews(symbol),
    staleTime: 120_000,
  });

  const filings = useQuery({
    queryKey: ["sec-filings", symbol], queryFn: () => fetchSecFilings(symbol),
    staleTime: 300_000,
  });

  const doSweep = async () => {
    setSweeping(true);
    setSweepResult(null);
    try {
      const [newsRes, filingsRes] = await Promise.all([
        fetchResearchNews(symbol, true),
        fetchSecFilings(symbol, true),
      ]);
      research.refetch();
      filings.refetch();
      market.refetch();
      setSweepResult(`Found ${newsRes?.length ?? 0} articles + ${filingsRes?.length ?? 0} filings`);
    } catch (e) {
      setSweepResult("Sweep failed — check backend logs");
    } finally {
      setSweeping(false);
    }
  };

  const allNews = mergeNews(market.data || [], research.data || []);
  const isLoading = market.isLoading && research.isLoading;

  if (isLoading) return <div className="p-4 text-term-muted uppercase text-[11px] tracking-widest">Loading…</div>;

  return (
    <div className="text-[12px]">
      {/* Tab bar + sweep button */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-term-border">
        <button
          className={cn("text-[10px] px-2 py-0.5 rounded border", tab === "news" ? "bg-term-amber text-black border-term-amber" : "border-term-border text-term-muted hover:text-term-fg")}
          onClick={() => setTab("news")}
        >NEWS ({allNews.length})</button>
        <button
          className={cn("text-[10px] px-2 py-0.5 rounded border", tab === "filings" ? "bg-term-cyan text-black border-term-cyan" : "border-term-border text-term-muted hover:text-term-fg")}
          onClick={() => setTab("filings")}
        >SEC FILINGS ({(filings.data || []).length})</button>
        <div className="flex-1" />
        {sweepResult && <span className="text-[9px] text-term-muted">{sweepResult}</span>}
        <button
          className="text-[10px] px-2 py-1 border border-term-amber text-term-amber hover:bg-term-amber hover:text-black rounded flex items-center gap-1 disabled:opacity-40 font-bold"
          onClick={doSweep}
          disabled={sweeping}
        >
          <RefreshCw size={10} className={sweeping ? "animate-spin" : ""} />
          {sweeping ? "SWEEPING..." : "GET LATEST NEWS"}
        </button>
      </div>

      {tab === "news" && (
        <div className="divide-y divide-term-borderSoft">
          {allNews.map((n, i) => (
            <a
              key={`${n.source}-${i}`}
              href={n.url}
              target="_blank"
              rel="noreferrer noopener"
              className="flex items-start gap-3 px-4 py-2 hover:bg-term-amberSubtle group"
            >
              <div className="num text-term-muted w-28 shrink-0">{n.date ? fmtTime(n.date) : "—"}</div>
              <div className="flex-1 min-w-0">
                <div className="text-term-heading group-hover:text-term-amber leading-snug">{n.title}</div>
                {n.summary && <div className="text-term-muted mt-0.5 line-clamp-2">{n.summary}</div>}
                <div className="text-term-muted text-[10px] uppercase tracking-widest mt-0.5">{n.source}</div>
              </div>
              <ExternalLink size={12} className="text-term-muted group-hover:text-term-amber mt-1 shrink-0" />
            </a>
          ))}
          {allNews.length === 0 && <div className="p-4 text-term-muted">No news found. Click GET LATEST NEWS to sweep all sources.</div>}
        </div>
      )}

      {tab === "filings" && (
        <div className="divide-y divide-term-borderSoft">
          {(filings.data || []).map((f, i) => (
            <a
              key={f.accession_number || i}
              href={f.primary_doc_url || "#"}
              target="_blank"
              rel="noreferrer noopener"
              className="flex items-start gap-3 px-4 py-2 hover:bg-term-cyanSubtle group"
            >
              <div className="num text-term-muted w-24 shrink-0">{f.filing_date || "—"}</div>
              <div className={cn("w-14 shrink-0 text-center text-[10px] font-bold px-1 py-0.5 rounded",
                f.form_type.includes("10-K") ? "bg-blue-900 text-blue-300" :
                f.form_type.includes("10-Q") ? "bg-green-900 text-green-300" :
                f.form_type.includes("8-K") ? "bg-yellow-900 text-yellow-300" :
                f.form_type.startsWith("4") ? "bg-purple-900 text-purple-300" :
                f.form_type.includes("S-") ? "bg-red-900 text-red-300" :
                "bg-term-border text-term-muted"
              )}>{f.form_type}</div>
              <div className="flex-1 min-w-0">
                <div className="text-term-heading group-hover:text-term-cyan leading-snug">
                  {f.description || f.form_type}
                </div>
                <div className="text-term-muted text-[10px]">{f.company_name} • {f.accession_number}</div>
              </div>
              <FileText size={12} className="text-term-muted group-hover:text-term-cyan mt-1 shrink-0" />
            </a>
          ))}
          {(filings.data || []).length === 0 && <div className="p-4 text-term-muted">No SEC filings found. Click GET LATEST NEWS to fetch from EDGAR.</div>}
        </div>
      )}
    </div>
  );
}

interface MergedNews {
  title: string;
  url: string;
  date: string | null;
  summary: string | null;
  source: string;
}

function mergeNews(marketNews: any[], researchNews: any[]): MergedNews[] {
  const seen = new Set<string>();
  const all: MergedNews[] = [];

  for (const n of marketNews) {
    const key = n.title?.toLowerCase().trim();
    if (key && !seen.has(key)) {
      seen.add(key);
      all.push({ title: n.title, url: n.url, date: n.date, summary: n.summary, source: n.source || "yfinance" });
    }
  }

  for (const n of researchNews) {
    const key = n.title?.toLowerCase().trim();
    if (key && !seen.has(key)) {
      seen.add(key);
      all.push({ title: n.title, url: n.url, date: n.published_at, summary: n.summary, source: n.source || "research" });
    }
  }

  all.sort((a, b) => {
    const da = a.date ? new Date(a.date).getTime() : 0;
    const db = b.date ? new Date(b.date).getTime() : 0;
    return db - da;
  });

  return all;
}
