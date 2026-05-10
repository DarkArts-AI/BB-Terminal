"""Market Data Router — yfinance-backed endpoints for BB-Terminal.

Provides equity quotes, historical prices, fundamentals, news,
market movers, options, indices, FX, crypto, and treasury yields.
All responses wrapped in {"results": ...} to match frontend expectations.
"""

import time
import threading
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import pandas as pd
import yfinance as yf
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/v1")

# ── Simple TTL cache ───────────────────────────────────────────────
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()

def cached(key: str, ttl: int = 60):
    with _cache_lock:
        if key in _cache:
            ts, val = _cache[key]
            if time.time() - ts < ttl:
                return val
    return None

def cache_set(key: str, val: Any):
    with _cache_lock:
        _cache[key] = (time.time(), val)


def _safe_float(v, default=None):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v, default=None):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ── Equity Quote ───────────────────────────────────────────────────
@router.get("/equity/price/quote")
def equity_quote(symbol: str = Query(...), provider: str = "yfinance"):
    ck = f"quote:{symbol}"
    hit = cached(ck, ttl=30)
    if hit:
        return {"results": hit}

    t = yf.Ticker(symbol)
    info = t.info or {}
    result = {
        "symbol": symbol.upper(),
        "name": info.get("shortName") or info.get("longName"),
        "exchange": info.get("exchange"),
        "last_price": _safe_float(info.get("currentPrice") or info.get("regularMarketPrice")),
        "open": _safe_float(info.get("open") or info.get("regularMarketOpen")),
        "high": _safe_float(info.get("dayHigh") or info.get("regularMarketDayHigh")),
        "low": _safe_float(info.get("dayLow") or info.get("regularMarketDayLow")),
        "prev_close": _safe_float(info.get("previousClose") or info.get("regularMarketPreviousClose")),
        "bid": _safe_float(info.get("bid")),
        "ask": _safe_float(info.get("ask")),
        "bid_size": _safe_int(info.get("bidSize")),
        "ask_size": _safe_int(info.get("askSize")),
        "volume": _safe_int(info.get("volume") or info.get("regularMarketVolume")),
        "volume_average": _safe_int(info.get("averageVolume")),
        "year_high": _safe_float(info.get("fiftyTwoWeekHigh")),
        "year_low": _safe_float(info.get("fiftyTwoWeekLow")),
        "ma_50d": _safe_float(info.get("fiftyDayAverage")),
        "ma_200d": _safe_float(info.get("twoHundredDayAverage")),
        "currency": info.get("currency"),
    }
    cache_set(ck, [result])
    return {"results": [result]}


# ── Equity Historical ──────────────────────────────────────────────
@router.get("/equity/price/historical")
def equity_historical(
    symbol: str = Query(...),
    interval: str = "1d",
    start_date: str = "",
    provider: str = "yfinance",
):
    ck = f"hist:{symbol}:{interval}:{start_date}"
    hit = cached(ck, ttl=120)
    if hit:
        return {"results": hit}

    t = yf.Ticker(symbol)
    kw = {"interval": interval}
    if start_date:
        kw["start"] = start_date
    else:
        kw["period"] = "1y"
    df = t.history(**kw)
    if df is None or df.empty:
        return {"results": []}

    rows = []
    for idx, r in df.iterrows():
        rows.append({
            "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
            "open": _safe_float(r.get("Open")),
            "high": _safe_float(r.get("High")),
            "low": _safe_float(r.get("Low")),
            "close": _safe_float(r.get("Close")),
            "volume": _safe_int(r.get("Volume")),
        })
    cache_set(ck, rows)
    return {"results": rows}


# ── Company Profile ────────────────────────────────────────────────
@router.get("/equity/profile")
def equity_profile(symbol: str = Query(...), provider: str = "yfinance"):
    ck = f"profile:{symbol}"
    hit = cached(ck, ttl=3600)
    if hit:
        return {"results": hit}

    t = yf.Ticker(symbol)
    info = t.info or {}
    result = {
        "symbol": symbol.upper(),
        "name": info.get("shortName") or info.get("longName"),
        "stock_exchange": info.get("exchange"),
        "long_description": info.get("longBusinessSummary"),
        "company_url": info.get("website"),
        "business_phone_no": info.get("phone"),
        "hq_address1": info.get("address1"),
        "hq_address_city": info.get("city"),
        "hq_state": info.get("state"),
        "hq_country": info.get("country"),
        "hq_address_postal_code": info.get("zip"),
        "employees": _safe_int(info.get("fullTimeEmployees")),
        "sector": info.get("sector"),
        "industry_category": info.get("industry"),
        "issue_type": info.get("quoteType"),
        "currency": info.get("currency"),
        "market_cap": _safe_float(info.get("marketCap")),
        "shares_outstanding": _safe_float(info.get("sharesOutstanding")),
        "shares_float": _safe_float(info.get("floatShares")),
        "dividend_yield": _safe_float(info.get("dividendYield")),
        "beta": _safe_float(info.get("beta")),
    }
    cache_set(ck, [result])
    return {"results": [result]}


# ── Income Statement ───────────────────────────────────────────────
@router.get("/equity/fundamental/income")
def equity_income(
    symbol: str = Query(...),
    period: str = "annual",
    limit: int = 5,
    provider: str = "yfinance",
):
    ck = f"income:{symbol}:{period}:{limit}"
    hit = cached(ck, ttl=3600)
    if hit:
        return {"results": hit}

    t = yf.Ticker(symbol)
    df = t.financials if period == "annual" else t.quarterly_financials
    if df is None or df.empty:
        return {"results": []}

    rows = []
    for col in list(df.columns)[:limit]:
        d = df[col]
        rows.append({
            "period_ending": col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col),
            "total_revenue": _safe_float(d.get("Total Revenue")),
            "cost_of_revenue": _safe_float(d.get("Cost Of Revenue")),
            "gross_profit": _safe_float(d.get("Gross Profit")),
            "operating_income": _safe_float(d.get("Operating Income")),
            "total_pre_tax_income": _safe_float(d.get("Pretax Income")),
            "net_income": _safe_float(d.get("Net Income")),
            "basic_earnings_per_share": _safe_float(d.get("Basic EPS")),
            "diluted_earnings_per_share": _safe_float(d.get("Diluted EPS")),
            "research_and_development_expense": _safe_float(d.get("Research And Development") or d.get("Research Development")),
            "selling_general_and_admin_expense": _safe_float(d.get("Selling General And Administration") or d.get("Selling General Administrative")),
        })
    cache_set(ck, rows)
    return {"results": rows}


# ── Key Metrics ────────────────────────────────────────────────────
@router.get("/equity/fundamental/metrics")
def equity_metrics(symbol: str = Query(...), provider: str = "yfinance"):
    ck = f"metrics:{symbol}"
    hit = cached(ck, ttl=300)
    if hit:
        return {"results": hit}

    t = yf.Ticker(symbol)
    info = t.info or {}
    result = {
        "symbol": symbol.upper(),
        "market_cap": _safe_float(info.get("marketCap")),
        "pe_ratio": _safe_float(info.get("trailingPE")),
        "forward_pe": _safe_float(info.get("forwardPE")),
        "peg_ratio": _safe_float(info.get("pegRatio")),
        "enterprise_to_ebitda": _safe_float(info.get("enterpriseToEbitda")),
        "revenue_growth": _safe_float(info.get("revenueGrowth")),
        "earnings_growth": _safe_float(info.get("earningsGrowth")),
        "quick_ratio": _safe_float(info.get("quickRatio")),
        "current_ratio": _safe_float(info.get("currentRatio")),
        "debt_to_equity": _safe_float(info.get("debtToEquity")),
        "gross_margin": _safe_float(info.get("grossMargins")),
        "operating_margin": _safe_float(info.get("operatingMargins")),
        "profit_margin": _safe_float(info.get("profitMargins")),
        "return_on_assets": _safe_float(info.get("returnOnAssets")),
        "return_on_equity": _safe_float(info.get("returnOnEquity")),
        "dividend_yield": _safe_float(info.get("dividendYield")),
        "payout_ratio": _safe_float(info.get("payoutRatio")),
        "book_value": _safe_float(info.get("bookValue")),
        "price_to_book": _safe_float(info.get("priceToBook")),
        "enterprise_value": _safe_float(info.get("enterpriseValue")),
    }
    cache_set(ck, [result])
    return {"results": [result]}


# ── Dividends ──────────────────────────────────────────────────────
@router.get("/equity/fundamental/dividends")
def equity_dividends(symbol: str = Query(...), provider: str = "yfinance"):
    ck = f"divs:{symbol}"
    hit = cached(ck, ttl=3600)
    if hit:
        return {"results": hit}

    t = yf.Ticker(symbol)
    divs = t.dividends
    if divs is None or divs.empty:
        return {"results": []}

    rows = [
        {"ex_dividend_date": idx.strftime("%Y-%m-%d"), "amount": round(float(v), 4)}
        for idx, v in divs.items()
    ]
    cache_set(ck, rows)
    return {"results": rows}


# ── Analyst Estimates / Consensus ──────────────────────────────────
@router.get("/equity/estimates/consensus")
def equity_consensus(symbol: str = Query(...), provider: str = "yfinance"):
    ck = f"consensus:{symbol}"
    hit = cached(ck, ttl=300)
    if hit:
        return {"results": hit}

    t = yf.Ticker(symbol)
    info = t.info or {}
    result = {
        "symbol": symbol.upper(),
        "target_high": _safe_float(info.get("targetHighPrice")),
        "target_low": _safe_float(info.get("targetLowPrice")),
        "target_consensus": _safe_float(info.get("targetMeanPrice")),
        "target_median": _safe_float(info.get("targetMedianPrice")),
        "recommendation": info.get("recommendationKey"),
        "recommendation_mean": _safe_float(info.get("recommendationMean")),
        "number_of_analysts": _safe_int(info.get("numberOfAnalystOpinions")),
        "current_price": _safe_float(info.get("currentPrice") or info.get("regularMarketPrice")),
        "currency": info.get("currency"),
    }
    cache_set(ck, [result])
    return {"results": [result]}


# ── Company News ───────────────────────────────────────────────────
@router.get("/news/company")
def news_company(symbol: str = Query(...), limit: int = 30, provider: str = "yfinance"):
    ck = f"news:{symbol}"
    hit = cached(ck, ttl=120)
    if hit:
        return {"results": hit[:limit]}

    t = yf.Ticker(symbol)
    news = t.news or []
    rows = []
    for item in news[:limit]:
        content = item.get("content", {}) if isinstance(item.get("content"), dict) else {}
        pub_date = content.get("pubDate") or item.get("providerPublishTime")
        if isinstance(pub_date, (int, float)):
            pub_date = datetime.fromtimestamp(pub_date, tz=timezone.utc).isoformat()
        rows.append({
            "id": item.get("uuid", ""),
            "date": pub_date or "",
            "title": content.get("title") or item.get("title", ""),
            "url": item.get("link") or content.get("canonicalUrl", {}).get("url", ""),
            "source": content.get("provider", {}).get("displayName") or item.get("publisher", ""),
            "summary": content.get("summary", ""),
            "symbol": symbol.upper(),
        })
    cache_set(ck, rows)
    return {"results": rows[:limit]}


# ── Market Movers ──────────────────────────────────────────────────
def _screen_movers(screen_id: str, cache_key: str):
    hit = cached(cache_key, ttl=120)
    if hit:
        return {"results": hit}

    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=false&scrIds={screen_id}&count=25"
        r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()
        quotes = data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
    except Exception:
        quotes = []

    rows = []
    for q in quotes[:25]:
        rows.append({
            "symbol": q.get("symbol", ""),
            "name": q.get("shortName") or q.get("longName", ""),
            "price": _safe_float(q.get("regularMarketPrice"), 0),
            "change": _safe_float(q.get("regularMarketChange"), 0),
            "percent_change": _safe_float(q.get("regularMarketChangePercent"), 0),
            "volume": _safe_int(q.get("regularMarketVolume"), 0),
            "market_cap": _safe_float(q.get("marketCap")),
            "pe_forward": _safe_float(q.get("forwardPE")),
            "eps_ttm": _safe_float(q.get("epsTrailingTwelveMonths")),
            "dividend_yield": _safe_float(q.get("dividendYield")),
            "exchange": q.get("exchange"),
        })
    cache_set(cache_key, rows)
    return {"results": rows}


@router.get("/equity/discovery/gainers")
def discovery_gainers(provider: str = "yfinance"):
    return _screen_movers("day_gainers", "movers:gainers")


@router.get("/equity/discovery/losers")
def discovery_losers(provider: str = "yfinance"):
    return _screen_movers("day_losers", "movers:losers")


@router.get("/equity/discovery/active")
def discovery_active(provider: str = "yfinance"):
    return _screen_movers("most_actives", "movers:active")


# ── Options Chain ──────────────────────────────────────────────────
@router.get("/derivatives/options/chains")
def options_chains(symbol: str = Query(...), provider: str = "yfinance"):
    ck = f"options:{symbol}"
    hit = cached(ck, ttl=120)
    if hit:
        return {"results": hit}

    t = yf.Ticker(symbol)
    try:
        expirations = t.options
    except Exception:
        return {"results": []}

    if not expirations:
        return {"results": []}

    rows = []
    price_info = t.info or {}
    underlying_price = _safe_float(price_info.get("currentPrice") or price_info.get("regularMarketPrice"))

    for exp in expirations[:4]:
        try:
            chain = t.option_chain(exp)
        except Exception:
            continue

        exp_date = datetime.strptime(exp, "%Y-%m-%d")
        dte = (exp_date - datetime.now()).days

        for otype, df in [("call", chain.calls), ("put", chain.puts)]:
            if df is None or df.empty:
                continue
            for _, r in df.iterrows():
                rows.append({
                    "underlying_symbol": symbol.upper(),
                    "underlying_price": underlying_price,
                    "contract_symbol": r.get("contractSymbol", ""),
                    "expiration": exp,
                    "dte": dte,
                    "strike": _safe_float(r.get("strike")),
                    "option_type": otype,
                    "open_interest": _safe_int(r.get("openInterest")),
                    "volume": _safe_int(r.get("volume")),
                    "last_trade_price": _safe_float(r.get("lastPrice")),
                    "bid": _safe_float(r.get("bid")),
                    "ask": _safe_float(r.get("ask")),
                    "change": _safe_float(r.get("change")),
                    "change_percent": _safe_float(r.get("percentChange")),
                    "implied_volatility": _safe_float(r.get("impliedVolatility")),
                    "in_the_money": bool(r.get("inTheMoney")),
                })

    cache_set(ck, rows)
    return {"results": rows}


# ── Index Historical ───────────────────────────────────────────────
@router.get("/index/price/historical")
def index_historical(
    symbol: str = Query(...),
    interval: str = "1d",
    start_date: str = "",
    provider: str = "yfinance",
):
    ck = f"idx:{symbol}:{interval}:{start_date}"
    hit = cached(ck, ttl=120)
    if hit:
        return {"results": hit}

    t = yf.Ticker(symbol)
    kw = {"interval": interval}
    if start_date:
        kw["start"] = start_date
    else:
        kw["period"] = "1mo"
    df = t.history(**kw)
    if df is None or df.empty:
        return {"results": []}

    rows = [
        {
            "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
            "open": _safe_float(r.get("Open")),
            "high": _safe_float(r.get("High")),
            "low": _safe_float(r.get("Low")),
            "close": _safe_float(r.get("Close")),
            "volume": _safe_int(r.get("Volume")),
        }
        for idx, r in df.iterrows()
    ]
    cache_set(ck, rows)
    return {"results": rows}


# ── Treasury Rates (Federal Reserve H.15) ──────────────────────────
TREASURY_TICKERS = {
    "month_1": "^IRX",    # 13-week (closest to 1mo/3mo)
    "month_3": "^IRX",
    "year_2": "^TWOY",    # 2-year (may not exist, fallback)
    "year_5": "^FVX",     # 5-year
    "year_10": "^TNX",    # 10-year
    "year_30": "^TYX",    # 30-year
}

@router.get("/fixedincome/government/treasury_rates")
def treasury_rates(start_date: str = "", provider: str = "federal_reserve"):
    ck = f"treasury:{start_date}"
    hit = cached(ck, ttl=3600)
    if hit:
        return {"results": hit}

    period = "3mo"
    tickers_to_fetch = {"^IRX": "month_3", "^FVX": "year_5", "^TNX": "year_10", "^TYX": "year_30"}
    all_data = {}
    for sym, field in tickers_to_fetch.items():
        try:
            t = yf.Ticker(sym)
            kw = {"period": period}
            if start_date:
                kw = {"start": start_date}
            df = t.history(**kw)
            if df is not None and not df.empty:
                for idx, r in df.iterrows():
                    d = idx.strftime("%Y-%m-%d")
                    if d not in all_data:
                        all_data[d] = {"date": d}
                    all_data[d][field] = _safe_float(r.get("Close"))
        except Exception:
            pass

    rows = sorted(all_data.values(), key=lambda x: x["date"])
    cache_set(ck, rows)
    return {"results": rows}


# ── FX Historical ─────────────────────────────────────────────────
@router.get("/currency/price/historical")
def fx_historical(
    symbol: str = Query(...),
    interval: str = "1d",
    start_date: str = "",
    provider: str = "yfinance",
):
    yf_sym = symbol.replace("/", "") + "=X" if "=X" not in symbol else symbol
    ck = f"fx:{yf_sym}:{interval}:{start_date}"
    hit = cached(ck, ttl=300)
    if hit:
        return {"results": hit}

    t = yf.Ticker(yf_sym)
    kw = {"interval": interval}
    if start_date:
        kw["start"] = start_date
    else:
        kw["period"] = "1mo"
    df = t.history(**kw)
    if df is None or df.empty:
        return {"results": []}

    rows = [
        {
            "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
            "open": _safe_float(r.get("Open")),
            "high": _safe_float(r.get("High")),
            "low": _safe_float(r.get("Low")),
            "close": _safe_float(r.get("Close")),
            "volume": _safe_int(r.get("Volume")),
        }
        for idx, r in df.iterrows()
    ]
    cache_set(ck, rows)
    return {"results": rows}


# ── Crypto Historical ──────────────────────────────────────────────
@router.get("/crypto/price/historical")
def crypto_historical(
    symbol: str = Query(...),
    interval: str = "1d",
    start_date: str = "",
    provider: str = "yfinance",
):
    yf_sym = symbol if "-USD" in symbol.upper() else f"{symbol}-USD"
    ck = f"crypto:{yf_sym}:{interval}:{start_date}"
    hit = cached(ck, ttl=120)
    if hit:
        return {"results": hit}

    t = yf.Ticker(yf_sym)
    kw = {"interval": interval}
    if start_date:
        kw["start"] = start_date
    else:
        kw["period"] = "1mo"
    df = t.history(**kw)
    if df is None or df.empty:
        return {"results": []}

    rows = [
        {
            "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
            "open": _safe_float(r.get("Open")),
            "high": _safe_float(r.get("High")),
            "low": _safe_float(r.get("Low")),
            "close": _safe_float(r.get("Close")),
            "volume": _safe_int(r.get("Volume")),
        }
        for idx, r in df.iterrows()
    ]
    cache_set(ck, rows)
    return {"results": rows}


# ── Symbol Search ──────────────────────────────────────────────────
@router.get("/equity/search")
def equity_search(
    query: str = Query(...),
    limit: int = 8,
    provider: str = "sec",
    is_symbol: bool = False,
):
    ck = f"search:{query}:{limit}"
    hit = cached(ck, ttl=300)
    if hit:
        return {"results": hit}

    try:
        url = f"https://efts.sec.gov/LATEST/search-index?q=%22{query}%22&dateRange=custom&startdt=2020-01-01&forms=10-K"
        r = httpx.get(
            f"https://efts.sec.gov/LATEST/search-index?q={query}&limit={limit}",
            headers={"User-Agent": "CortexMedusa/1.0 sentinel@cortex-forge.com"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            hits = data.get("hits", {}).get("hits", [])
            rows = []
            seen = set()
            for h in hits:
                src = h.get("_source", {})
                tickers = src.get("tickers", "").split(",") if src.get("tickers") else []
                name = src.get("entity_name", "")
                for tk in tickers:
                    tk = tk.strip()
                    if tk and tk not in seen:
                        seen.add(tk)
                        rows.append({"symbol": tk, "name": name})
            if rows:
                cache_set(ck, rows[:limit])
                return {"results": rows[:limit]}
    except Exception:
        pass

    # Fallback: use yfinance search
    try:
        results = yf.Search(query)
        quotes = results.quotes if hasattr(results, 'quotes') else []
        rows = [
            {"symbol": q.get("symbol", ""), "name": q.get("shortname") or q.get("longname", "")}
            for q in quotes[:limit]
        ]
        cache_set(ck, rows)
        return {"results": rows}
    except Exception:
        return {"results": []}
