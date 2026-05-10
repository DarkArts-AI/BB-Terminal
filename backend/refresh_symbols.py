"""Fetch comprehensive US equity symbol list from NASDAQ trader."""
import urllib.request
import psycopg
import sys

DSN = "dbname=cmv4_dashboard user=cmv4_writer password=CMv4-Dashboard-2026! host=127.0.0.1"

def fetch_nasdaq_listed():
    url = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        lines = resp.read().decode().strip().split("\n")
    symbols = []
    for line in lines[1:]:  # skip header
        if line.startswith("File Creation"):
            continue
        parts = line.split("|")
        if len(parts) >= 2 and parts[0].strip():
            sym = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else sym
            if "$" in sym or len(sym) > 6:
                continue
            symbols.append((sym, name))
    print(f"NASDAQ listed: {len(symbols)}")
    return symbols

def fetch_other_listed():
    url = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        lines = resp.read().decode().strip().split("\n")
    symbols = []
    for line in lines[1:]:
        if line.startswith("File Creation"):
            continue
        parts = line.split("|")
        if len(parts) >= 2 and parts[0].strip():
            sym = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else sym
            if "$" in sym or len(sym) > 6:
                continue
            symbols.append((sym, name))
    print(f"Other listed (NYSE/AMEX/ARCA): {len(symbols)}")
    return symbols

def upsert_symbols(symbols):
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM symbol_names")
            before = cur.fetchone()[0]
            for sym, name in symbols:
                cur.execute(
                    """INSERT INTO symbol_names (symbol, company_name)
                       VALUES (%s, %s)
                       ON CONFLICT (symbol) DO UPDATE SET company_name = EXCLUDED.company_name""",
                    (sym, name),
                )
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM symbol_names")
            after = cur.fetchone()[0]
    print(f"Before: {before}, After: {after}, Added: {after - before}")

if __name__ == "__main__":
    nasdaq = fetch_nasdaq_listed()
    other = fetch_other_listed()
    all_symbols = nasdaq + other
    print(f"Total fetched: {len(all_symbols)}")
    # Sample
    for s in all_symbols[:5]:
        print(f"  {s[0]:8s} {s[1]}")
    print("  ...")
    upsert_symbols(all_symbols)
    print("Done.")
