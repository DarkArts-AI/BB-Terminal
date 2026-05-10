"""Research Data Router — SEC EDGAR filings, yfinance news, EDGAR full-text search."""

from datetime import datetime, timezone, timedelta
from typing import Optional
import json
import time

import httpx
import psycopg
import yfinance as yf
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/v1/market-research")

from env_config import DB_DSN

EDGAR_BASE = "https://efts.sec.gov/LATEST"
EDGAR_SEC = "https://www.sec.gov"
EDGAR_DATA = "https://data.sec.gov"
EDGAR_HEADERS = {"User-Agent": "DarkArtsConsulting lsolt@darkartsconsulting.com", "Accept-Encoding": "gzip, deflate"}

_cik_cache: dict[str, str] = {}
_cik_map_loaded = False
_cik_map: dict[str, str] = {}


def _conn():
    return psycopg.connect(DB_DSN)


def _ensure_tables():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sec_filings LIMIT 0")
        cur.execute("SELECT 1 FROM news_articles LIMIT 0")


_tables_ensured = False


def _ensure_tables_once():
    global _tables_ensured
    if not _tables_ensured:
        _ensure_tables()
        _tables_ensured = True


# ── CIK Lookup ────────────────────────────────────────────────────

def _load_cik_map():
    global _cik_map_loaded, _cik_map
    if _cik_map_loaded:
        return
    try:
        r = httpx.get(f"{EDGAR_SEC}/files/company_tickers.json", headers=EDGAR_HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            for entry in data.values():
                ticker = entry.get("ticker", "").upper()
                cik = str(entry.get("cik_str", ""))
                if ticker and cik:
                    _cik_map[ticker] = cik.zfill(10)
            _cik_map_loaded = True
    except Exception:
        pass


def _get_cik(symbol: str) -> Optional[str]:
    symbol = symbol.upper()
    if symbol in _cik_cache:
        return _cik_cache[symbol]
    _load_cik_map()
    cik = _cik_map.get(symbol)
    if cik:
        _cik_cache[symbol] = cik
    return cik


# ── SEC EDGAR Submissions ─────────────────────────────────────────

def _fetch_sec_filings(symbol: str, form_types: list[str] | None = None, limit: int = 20) -> list[dict]:
    cik = _get_cik(symbol)
    if not cik:
        return []

    try:
        url = f"{EDGAR_DATA}/submissions/CIK{cik}.json"
        r = httpx.get(url, headers=EDGAR_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []

    company_name = data.get("name", "")
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])

    if form_types:
        form_types_upper = [f.upper() for f in form_types]
    else:
        form_types_upper = ["10-K", "10-Q", "8-K", "4", "SC 13G", "SC 13D", "DEF 14A", "S-1", "S-3", "424B"]

    results = []
    for i in range(len(forms)):
        form_upper = forms[i].upper().strip()
        matched = any(form_upper.startswith(ft) for ft in form_types_upper)
        if not matched:
            continue
        acc = accessions[i].replace("-", "") if i < len(accessions) else ""
        acc_dashed = accessions[i] if i < len(accessions) else ""
        doc = primary_docs[i] if i < len(primary_docs) else ""
        doc_url = f"{EDGAR_SEC}/Archives/edgar/data/{int(cik)}/{acc}/{doc}" if acc and doc else None

        results.append({
            "symbol": symbol.upper(),
            "cik": cik,
            "accession_number": acc_dashed,
            "form_type": forms[i],
            "filing_date": dates[i] if i < len(dates) else None,
            "primary_doc_url": doc_url,
            "description": descriptions[i] if i < len(descriptions) else None,
            "company_name": company_name,
        })
        if len(results) >= limit:
            break

    return results


# ── EDGAR Full-Text Search (EFTS) ─────────────────────────────────

def _fetch_edgar_efts(symbol: str, limit: int = 20) -> list[dict]:
    """Use EDGAR full-text search to find filings mentioning this company."""
    try:
        url = f"{EDGAR_BASE}/search-index?q=%22{symbol}%22&dateRange=custom&startdt={(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')}&enddt={datetime.now().strftime('%Y-%m-%d')}&forms=8-K,10-K,10-Q,4,SC%2013G&from=0&size={limit}"
        r = httpx.get(url, headers=EDGAR_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []

    results = []
    for hit in data.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        acc = src.get("file_num", "") or src.get("accession_no", "")
        results.append({
            "symbol": symbol.upper(),
            "cik": src.get("entity_id", ""),
            "accession_number": acc,
            "form_type": src.get("form_type", ""),
            "filing_date": src.get("file_date"),
            "primary_doc_url": None,
            "description": src.get("display_names", [None])[0] if src.get("display_names") else src.get("entity_name"),
            "company_name": src.get("entity_name", ""),
        })
    return results


def _store_filings(filings: list[dict]):
    if not filings:
        return 0
    stored = 0
    with _conn() as conn, conn.cursor() as cur:
        for f in filings:
            if not f.get("accession_number"):
                continue
            cur.execute("""
                INSERT INTO sec_filings (symbol, cik, accession_number, form_type, filing_date, primary_doc_url, description, company_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (accession_number) DO NOTHING
            """, (f["symbol"], f["cik"], f["accession_number"], f["form_type"],
                  f["filing_date"], f["primary_doc_url"], f["description"], f["company_name"]))
            stored += cur.rowcount
        conn.commit()
    return stored


# ── yfinance News ─────────────────────────────────────────────────

def _fetch_yfinance_news(symbol: str) -> list[dict]:
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news or []
    except Exception:
        return []

    results = []
    for item in news[:25]:
        content = item.get("content", {})
        title = content.get("title") or item.get("title", "")
        if not title:
            continue
        pub = content.get("pubDate") or item.get("providerPublishTime")
        url = content.get("canonicalUrl", {}).get("url") or item.get("link", "")
        summary = content.get("summary", "")
        publisher = content.get("provider", {}).get("displayName") or item.get("publisher", "")

        if isinstance(pub, (int, float)):
            pub = datetime.fromtimestamp(pub, tz=timezone.utc).isoformat()

        results.append({
            "symbol": symbol.upper(),
            "source": f"yfinance/{publisher}" if publisher else "yfinance",
            "title": title,
            "url": url,
            "published_at": pub,
            "summary": summary[:2000] if summary else None,
            "event_type": "news",
        })
    return results


# ── Google News via yfinance search ────────────────────────────────

def _fetch_yfinance_company_news(symbol: str) -> list[dict]:
    """Fetch news using yfinance's search to get broader coverage."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        company_name = info.get("shortName") or info.get("longName") or symbol
    except Exception:
        company_name = symbol

    try:
        search = yf.Search(company_name, news_count=15, enable_fuzzy_query=False)
        news = search.news or []
    except Exception:
        return []

    results = []
    for item in news[:15]:
        title = item.get("title", "")
        if not title:
            continue
        pub = item.get("providerPublishTime")
        url = item.get("link", "")
        publisher = item.get("publisher", "")

        if isinstance(pub, (int, float)):
            pub = datetime.fromtimestamp(pub, tz=timezone.utc).isoformat()

        results.append({
            "symbol": symbol.upper(),
            "source": f"search/{publisher}" if publisher else "search",
            "title": title,
            "url": url,
            "published_at": pub,
            "summary": None,
            "event_type": "news",
        })
    return results


def _store_news(articles: list[dict]):
    if not articles:
        return 0
    stored = 0
    with _conn() as conn, conn.cursor() as cur:
        for a in articles:
            if not a.get("title"):
                continue
            cur.execute("""
                INSERT INTO news_articles (symbol, source, title, url, published_at, summary, event_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, source, title) DO NOTHING
            """, (a["symbol"], a["source"], a["title"][:500], a.get("url"), a.get("published_at"),
                  a.get("summary"), a.get("event_type")))
            stored += cur.rowcount
        conn.commit()
    return stored


# ── API Endpoints ─────────────────────────────────────────────────

@router.get("/filings/{symbol}")
def get_filings(symbol: str, form_type: Optional[str] = None, limit: int = 20, refresh: bool = False):
    """Get SEC filings for a symbol. Set refresh=true to fetch latest from EDGAR."""
    _ensure_tables_once()
    symbol = symbol.upper()

    if refresh:
        form_types = [form_type] if form_type else None
        filings = _fetch_sec_filings(symbol, form_types=form_types, limit=limit)
        _store_filings(filings)

    with _conn() as conn, conn.cursor() as cur:
        query = "SELECT symbol, cik, accession_number, form_type, filing_date, primary_doc_url, description, company_name, fetched_at FROM sec_filings WHERE symbol = %s"
        params: list = [symbol]
        if form_type:
            query += " AND form_type = %s"
            params.append(form_type)
        query += " ORDER BY filing_date DESC LIMIT %s"
        params.append(limit)
        cur.execute(query, params)
        rows = cur.fetchall()

    if not rows and not refresh:
        filings = _fetch_sec_filings(symbol, form_types=[form_type] if form_type else None, limit=limit)
        _store_filings(filings)
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    return {"results": [{
        "symbol": r[0], "cik": r[1], "accession_number": r[2], "form_type": r[3],
        "filing_date": str(r[4]) if r[4] else None, "primary_doc_url": r[5],
        "description": r[6], "company_name": r[7], "fetched_at": str(r[8]) if r[8] else None,
    } for r in rows]}


@router.get("/news/{symbol}")
def get_news(symbol: str, source: Optional[str] = None, limit: int = 50, refresh: bool = False):
    """Get news for a symbol from all sources. Set refresh=true to fetch latest."""
    _ensure_tables_once()
    symbol = symbol.upper()

    if refresh:
        articles = _fetch_yfinance_news(symbol)
        articles += _fetch_yfinance_company_news(symbol)
        _store_news(articles)

    with _conn() as conn, conn.cursor() as cur:
        query = "SELECT symbol, source, title, url, published_at, summary, event_type, fetched_at FROM news_articles WHERE symbol = %s"
        params: list = [symbol]
        if source:
            query += " AND source LIKE %s"
            params.append(f"%{source}%")
        query += " ORDER BY published_at DESC NULLS LAST LIMIT %s"
        params.append(limit)
        cur.execute(query, params)
        rows = cur.fetchall()

    if not rows and not refresh:
        articles = _fetch_yfinance_news(symbol)
        articles += _fetch_yfinance_company_news(symbol)
        _store_news(articles)
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    return {"results": [{
        "symbol": r[0], "source": r[1], "title": r[2], "url": r[3],
        "published_at": str(r[4]) if r[4] else None, "summary": r[5],
        "event_type": r[6], "fetched_at": str(r[7]) if r[7] else None,
    } for r in rows]}


@router.get("/filing-text/{symbol}/{accession}")
def get_filing_text(symbol: str, accession: str):
    """Get the primary document URL for a specific filing."""
    _ensure_tables_once()
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT primary_doc_url, form_type, filing_date, description, company_name FROM sec_filings WHERE symbol = %s AND accession_number = %s",
            (symbol.upper(), accession),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Filing not found")
    return {"results": {
        "url": row[0], "form_type": row[1], "filing_date": str(row[2]) if row[2] else None,
        "description": row[3], "company_name": row[4],
    }}


@router.get("/summary/{symbol}")
def research_summary(symbol: str):
    """Combined research summary: latest filings + news for a symbol."""
    _ensure_tables_once()
    symbol = symbol.upper()

    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT form_type, filing_date, description, company_name FROM sec_filings WHERE symbol = %s ORDER BY filing_date DESC LIMIT 5",
            (symbol,),
        )
        filings = [{"form_type": r[0], "filing_date": str(r[1]) if r[1] else None, "description": r[2], "company_name": r[3]} for r in cur.fetchall()]

        cur.execute(
            "SELECT source, title, url, published_at, event_type FROM news_articles WHERE symbol = %s ORDER BY published_at DESC NULLS LAST LIMIT 15",
            (symbol,),
        )
        news = [{"source": r[0], "title": r[1], "url": r[2], "published_at": str(r[3]) if r[3] else None, "event_type": r[4]} for r in cur.fetchall()]

    cik = _get_cik(symbol)

    return {"results": {
        "symbol": symbol,
        "cik": cik,
        "recent_filings": filings,
        "recent_news": news,
        "has_data": bool(filings or news),
    }}


# ── Sync for held positions ───────────────────────────────────────

def sync_research_data():
    """Sync SEC filings and news for all symbols held across all portfolios."""
    _ensure_tables_once()
    symbols = set()
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT symbol FROM portfolio_holdings WHERE quantity != 0 AND symbol IS NOT NULL")
        symbols.update(r[0].upper() for r in cur.fetchall())

    synced = {"filings": 0, "news": 0, "symbols": list(sorted(symbols)), "errors": []}
    for sym in sorted(symbols):
        try:
            filings = _fetch_sec_filings(sym, limit=15)
            synced["filings"] += _store_filings(filings)
            time.sleep(0.12)
        except Exception as e:
            synced["errors"].append(f"{sym}/filings: {e}")

        try:
            articles = _fetch_yfinance_news(sym)
            articles += _fetch_yfinance_company_news(sym)
            synced["news"] += _store_news(articles)
        except Exception as e:
            synced["errors"].append(f"{sym}/news: {e}")

        time.sleep(0.2)

    return synced


@router.post("/sync")
def trigger_sync():
    """Manually trigger research data sync for all held symbols."""
    result = sync_research_data()
    return {"results": result, "message": f"Synced {result['filings']} filings and {result['news']} articles for {len(result['symbols'])} symbols"}
