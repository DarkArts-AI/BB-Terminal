#!/usr/bin/env python3
"""BB-Terminal Data Collector v2 — pulls orchestrator activity every 2 minutes.

Handles the actual data formats from each orchestrator:
- Alpha (CF-01): logs/pipeline_runs.jsonl (JSONL, 5-stage reports)
- Bravo (CF-02): pipeline_result_*.json (per-symbol full pipeline), data/portfolio.json, data/history.json
- Charlie (CF-03): logs/{SYMBOL}_{date}_{time}.json (per-symbol pipeline results)
"""

import json
import re
import subprocess
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from env_config import DB_DSN
LOG_FILE = Path("/var/log/openclaw/bbt-collector.log")
STATE_DIR = Path("/home/support/bb-terminal/backend/.collector_state")

AGENTS = {
    "Alpha": {"host": "192.168.1.11", "portfolio": "2A"},
    "Bravo": {"host": "192.168.13.15", "portfolio": "2B"},
    "Charlie": {"host": "192.168.13.16", "portfolio": "2C"},
}

V4_DIR = "~/Cortex-Medusa-v4"


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def ssh_cmd(host: str, cmd: str, timeout: int = 20) -> str:
    try:
        r = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=8",
             "-o", "StrictHostKeyChecking=accept-new",
             "-o", "BatchMode=yes",
             f"support@{host}", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def load_seen(agent: str) -> set:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / f"{agent.lower()}_seen.json"
    if p.exists():
        try:
            return set(json.loads(p.read_text()))
        except Exception:
            pass
    return set()


def save_seen(agent: str, seen: set):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / f"{agent.lower()}_seen.json"
    trimmed = sorted(seen)[-2000:]
    p.write_text(json.dumps(trimmed))


def content_id(data: dict) -> str:
    raw = json.dumps(data, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()[:16]


# ── Pipeline stage mapping ──────────────────────────────────────────────────

STAGE_MAP = {
    "Market Analyst": "Analysts",
    "Social Analyst": "Analysts",
    "News Analyst": "Analysts",
    "Fundamentals Analyst": "Analysts",
    "market_report": "Analysts",
    "news_report": "Analysts",
    "fundamentals_report": "Analysts",
    "social_report": "Analysts",
    "Bull/Bear Debate": "Research (Bull/Bear)",
    "research_plan": "Research (Bull/Bear)",
    "Trader": "Trader",
    "trader_proposal": "Trader",
    "Risk Manager": "Risk Management",
    "risk_assessment": "Risk Management",
    "Portfolio Manager": "Portfolio Manager",
    "final_decision": "Portfolio Manager",
}


def ingest_alpha_pipeline(data: dict, conn, seen: set) -> int:
    """Alpha: JSONL records with 'reports' array of 5-stage pipeline."""
    rid = data.get("run_id", "")
    if rid in seen:
        return 0
    seen.add(rid)
    symbol = data.get("symbol", "?")
    items = 0

    with conn.cursor() as cur:
        for report in data.get("reports", []):
            stage = STAGE_MAP.get(report.get("name"), report.get("name", "Unknown"))
            summary = report.get("summary", "")[:5000]
            status = report.get("status", "idle")
            completed = report.get("completed_at")

            cur.execute(
                """INSERT INTO research_notes (agent, stage, symbol, title, content, source, collected_at)
                   VALUES ('Alpha', %s, %s, %s, %s, %s, %s)""",
                (stage, symbol, f"{stage}: {symbol}", summary, f"run:{rid}", completed),
            )
            items += 1

            cur.execute(
                """INSERT INTO pipeline_status (agent, stage, status, last_run, last_output)
                   VALUES ('Alpha', %s, %s, %s, %s)
                   ON CONFLICT (agent, stage) DO UPDATE SET status=EXCLUDED.status, last_run=EXCLUDED.last_run, last_output=EXCLUDED.last_output, updated_at=NOW()""",
                (stage, status, completed, summary[:500]),
            )

        decision = data.get("final_decision") or data.get("portfolio_manager", {})
        if decision:
            rating = decision.get("rating") or decision.get("action", "")
            thesis = decision.get("executive_summary") or decision.get("investment_thesis", "")
            if rating:
                direction = "BUY" if rating.lower() in ("buy", "overweight", "strong buy") else \
                            "SELL" if rating.lower() in ("sell", "underweight") else "HOLD"
                cur.execute(
                    """INSERT INTO trade_proposals (agent, symbol, direction, rationale, confidence, status)
                       VALUES ('Alpha', %s, %s, %s, NULL, 'proposed')""",
                    (symbol, direction, thesis[:2000]),
                )
                items += 1

    conn.commit()
    return items


def ingest_bravo_pipeline(data: dict, fname: str, conn, seen: set) -> int:
    """Bravo: pipeline_result_*.json with analyst_reports, research_plan, trader_proposal, risk_assessment, final_decision."""
    cid = content_id(data)
    if cid in seen:
        return 0
    seen.add(cid)
    symbol = data.get("ticker", fname.replace("pipeline_result_", "").replace(".json", ""))
    items = 0

    with conn.cursor() as cur:
        reports = data.get("analyst_reports", {})
        for key, text in reports.items():
            stage = STAGE_MAP.get(key, "Analysts")
            cur.execute(
                """INSERT INTO research_notes (agent, stage, symbol, title, content, source)
                   VALUES ('Bravo', %s, %s, %s, %s, %s)""",
                (stage, symbol, f"{key}: {symbol}", str(text)[:5000], fname),
            )
            items += 1
            cur.execute(
                """INSERT INTO pipeline_status (agent, stage, status, last_run, last_output)
                   VALUES ('Bravo', %s, 'complete', NOW(), %s)
                   ON CONFLICT (agent, stage) DO UPDATE SET status='complete', last_run=NOW(), last_output=EXCLUDED.last_output, updated_at=NOW()""",
                (stage, str(text)[:300]),
            )

        for section_key in ("research_plan", "trader_proposal", "risk_assessment", "final_decision"):
            section = data.get(section_key)
            if not section or isinstance(section, str):
                continue
            stage = STAGE_MAP.get(section_key, section_key)
            summary = section.get("recommendation") or section.get("action") or section.get("rating") or ""
            detail = section.get("rationale") or section.get("reasoning") or section.get("executive_summary") or json.dumps(section)[:2000]
            cur.execute(
                """INSERT INTO research_notes (agent, stage, symbol, title, content, source)
                   VALUES ('Bravo', %s, %s, %s, %s, %s)""",
                (stage, symbol, f"{section_key}: {symbol}", detail[:5000], fname),
            )
            items += 1
            cur.execute(
                """INSERT INTO pipeline_status (agent, stage, status, last_run, last_output)
                   VALUES ('Bravo', %s, 'complete', NOW(), %s)
                   ON CONFLICT (agent, stage) DO UPDATE SET status='complete', last_run=NOW(), last_output=EXCLUDED.last_output, updated_at=NOW()""",
                (stage, f"{summary}: {detail[:200]}"),
            )

        fd = data.get("final_trade_decision") or data.get("final_decision")
        if fd and isinstance(fd, str):
            # Charlie often writes decisions as markdown text
            fd_lower = fd.lower()
            if any(w in fd_lower for w in ("buy", "overweight", "strong buy", "long", "accumulate")):
                direction = "BUY"
            elif any(w in fd_lower for w in ("sell", "underweight", "liquidate", "reduce", "short", "exit")):
                direction = "SELL"
            else:
                direction = "HOLD"
            rating_match = re.search(r"\*\*Rating:\*\*\s*(\w+)", fd)
            if rating_match:
                r_val = rating_match.group(1).lower()
                if r_val in ("buy", "overweight"):
                    direction = "BUY"
                elif r_val in ("sell", "underweight"):
                    direction = "SELL"
            cur.execute(
                """INSERT INTO trade_proposals (agent, symbol, direction, rationale, confidence, status)
                   VALUES ('Charlie', %s, %s, %s, NULL, 'proposed')""",
                (symbol, direction, fd[:2000]),
            )
            items += 1
        if fd and isinstance(fd, dict):
            rating = fd.get("rating") or fd.get("action") or fd.get("decision") or ""
            thesis = fd.get("executive_summary") or fd.get("investment_thesis") or fd.get("summary") or fd.get("explanation") or ""
            if rating:
                direction = "BUY" if rating.lower() in ("buy", "overweight", "strong buy", "long") else \
                            "SELL" if rating.lower() in ("sell", "underweight", "short", "liquidate", "reduce") else "HOLD"
                cur.execute(
                    """INSERT INTO trade_proposals (agent, symbol, direction, rationale, confidence, status)
                       VALUES ('Bravo', %s, %s, %s, NULL, 'proposed')""",
                    (symbol, direction, thesis[:2000]),
                )
                items += 1

    conn.commit()
    return items


def ingest_bravo_history(conn):
    """Bravo: data/history.json — trade execution history."""
    raw = ssh_cmd(AGENTS["Bravo"]["host"], f"cat {V4_DIR}/data/history.json 2>/dev/null", timeout=15)
    if not raw:
        return 0
    try:
        records = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    items = 0
    with conn.cursor() as cur:
        for rec in records:
            if rec.get("event_type") != "Trade Executed":
                continue
            ts = rec.get("timestamp")
            cur.execute(
                """INSERT INTO executions (agent, symbol, side, quantity, price, portfolio, executed_at, status)
                   VALUES ('Bravo', %s, %s, 0, 0, '2B', %s, 'filled')
                   ON CONFLICT DO NOTHING""",
                (rec.get("ticker"), rec.get("decision", "BUY").upper(), ts),
            )
            items += 1
    conn.commit()
    return items


def ingest_bravo_portfolio(conn):
    """Bravo: data/portfolio.json — current portfolio state for competition snapshot."""
    raw = ssh_cmd(AGENTS["Bravo"]["host"], f"cat {V4_DIR}/data/portfolio.json 2>/dev/null", timeout=15)
    if not raw:
        return
    try:
        pf = json.loads(raw)
    except json.JSONDecodeError:
        return
    nav = pf.get("total_value", 0)
    cash = pf.get("cash_balance", 0)
    holdings = pf.get("holdings", [])
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO competition_snapshots (agent, nav, trade_count)
               VALUES ('Bravo', %s, %s)""",
            (nav, len(holdings)),
        )
        cur.execute(
            """INSERT INTO reconciliation (agent, portfolio, nav, cash, positions_count)
               VALUES ('Bravo', '2B', %s, %s, %s)""",
            (nav, cash, len(holdings)),
        )
    conn.commit()


def ingest_charlie_pipeline(data: dict, fname: str, conn, seen: set) -> int:
    """Charlie: logs/{SYMBOL}_{date}_{time}.json — full pipeline results."""
    rid = data.get("run_id", fname)
    if rid in seen:
        return 0
    seen.add(rid)
    symbol = data.get("company_of_interest", fname.split("_")[0] if "_" in fname else "?")
    items = 0

    with conn.cursor() as cur:
        for field in ("market_report", "news_report", "fundamentals_report", "social_report", "sentiment_report"):
            text = data.get(field)
            if not text:
                continue
            stage = STAGE_MAP.get(field, "Analysts")
            cur.execute(
                """INSERT INTO research_notes (agent, stage, symbol, title, content, source)
                   VALUES ('Charlie', %s, %s, %s, %s, %s)""",
                (stage, symbol, f"{field}: {symbol}", str(text)[:5000], fname),
            )
            items += 1
            cur.execute(
                """INSERT INTO pipeline_status (agent, stage, status, last_run, last_output)
                   VALUES ('Charlie', %s, 'complete', NOW(), %s)
                   ON CONFLICT (agent, stage) DO UPDATE SET status='complete', last_run=NOW(), last_output=EXCLUDED.last_output, updated_at=NOW()""",
                (stage, str(text)[:300]),
            )

        charlie_field_map = {
            "investment_debate_state": "Research (Bull/Bear)",
            "risk_debate_state": "Risk Management",
            "investment_plan": "Research (Bull/Bear)",
            "trader_investment_plan": "Trader",
            "risk_debate_summary": "Risk Management",
            "final_trade_decision": "Portfolio Manager",
            "debate": "Research (Bull/Bear)",
            "research_plan": "Research (Bull/Bear)",
            "trader_proposal": "Trader",
            "risk_assessment": "Risk Management",
            "final_decision": "Portfolio Manager",
        }
        for section_key in charlie_field_map:
            section = data.get(section_key)
            if not section:
                continue
            stage = charlie_field_map.get(section_key, STAGE_MAP.get(section_key, section_key))
            if isinstance(section, dict):
                summary = section.get("recommendation") or section.get("action") or section.get("rating") or section.get("decision") or ""
                detail = section.get("rationale") or section.get("reasoning") or section.get("executive_summary") or section.get("summary") or section.get("explanation") or json.dumps(section)[:2000]
            else:
                summary = ""
                detail = str(section)[:2000]
            cur.execute(
                """INSERT INTO research_notes (agent, stage, symbol, title, content, source)
                   VALUES ('Charlie', %s, %s, %s, %s, %s)""",
                (stage, symbol, f"{section_key}: {symbol}", detail[:5000], fname),
            )
            items += 1
            cur.execute(
                """INSERT INTO pipeline_status (agent, stage, status, last_run, last_output)
                   VALUES ('Charlie', %s, 'complete', NOW(), %s)
                   ON CONFLICT (agent, stage) DO UPDATE SET status='complete', last_run=NOW(), last_output=EXCLUDED.last_output, updated_at=NOW()""",
                (stage, f"{summary}: {detail[:200]}"),
            )

        fd = data.get("final_trade_decision") or data.get("final_decision")
        if fd and isinstance(fd, str):
            # Charlie often writes decisions as markdown text
            fd_lower = fd.lower()
            if any(w in fd_lower for w in ("buy", "overweight", "strong buy", "long", "accumulate")):
                direction = "BUY"
            elif any(w in fd_lower for w in ("sell", "underweight", "liquidate", "reduce", "short", "exit")):
                direction = "SELL"
            else:
                direction = "HOLD"
            rating_match = re.search(r"\*\*Rating:\*\*\s*(\w+)", fd)
            if rating_match:
                r_val = rating_match.group(1).lower()
                if r_val in ("buy", "overweight"):
                    direction = "BUY"
                elif r_val in ("sell", "underweight"):
                    direction = "SELL"
            cur.execute(
                """INSERT INTO trade_proposals (agent, symbol, direction, rationale, confidence, status)
                   VALUES ('Charlie', %s, %s, %s, NULL, 'proposed')""",
                (symbol, direction, fd[:2000]),
            )
            items += 1
        if fd and isinstance(fd, dict):
            rating = fd.get("rating") or fd.get("action") or fd.get("decision") or ""
            thesis = fd.get("executive_summary") or fd.get("investment_thesis") or fd.get("summary") or fd.get("explanation") or ""
            if rating:
                direction = "BUY" if rating.lower() in ("buy", "overweight", "strong buy", "long") else \
                            "SELL" if rating.lower() in ("sell", "underweight", "short", "liquidate", "reduce") else "HOLD"
                cur.execute(
                    """INSERT INTO trade_proposals (agent, symbol, direction, rationale, confidence, status)
                       VALUES ('Charlie', %s, %s, %s, NULL, 'proposed')""",
                    (symbol, direction, thesis[:2000]),
                )
                items += 1

    conn.commit()
    return items


def collect_alpha(conn) -> int:
    host = AGENTS["Alpha"]["host"]
    seen = load_seen("Alpha")
    items = 0

    raw = ssh_cmd(host, f"cat {V4_DIR}/logs/pipeline_runs.jsonl 2>/dev/null", timeout=30)
    if raw:
        for line in raw.split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                items += ingest_alpha_pipeline(data, conn, seen)
            except json.JSONDecodeError:
                continue

    save_seen("Alpha", seen)
    return items


def collect_bravo(conn) -> int:
    host = AGENTS["Bravo"]["host"]
    seen = load_seen("Bravo")
    items = 0

    file_list = ssh_cmd(host, f"ls -1 {V4_DIR}/pipeline_result_*.json 2>/dev/null", timeout=15)
    if file_list:
        for fpath in file_list.split("\n"):
            if not fpath.strip():
                continue
            fname = fpath.strip().split("/")[-1]
            if fname in seen:
                continue
            raw = ssh_cmd(host, f'cat "{fpath.strip()}" 2>/dev/null', timeout=15)
            if not raw:
                continue
            try:
                data = json.loads(raw)
                items += ingest_bravo_pipeline(data, fname, conn, seen)
            except json.JSONDecodeError:
                continue

    items += ingest_bravo_history(conn)
    ingest_bravo_portfolio(conn)

    save_seen("Bravo", seen)
    return items


def collect_charlie(conn) -> int:
    host = AGENTS["Charlie"]["host"]
    seen = load_seen("Charlie")
    items = 0

    file_list = ssh_cmd(host, f"ls -1 {V4_DIR}/logs/*.json 2>/dev/null", timeout=15)
    if file_list:
        for fpath in file_list.split("\n"):
            if not fpath.strip():
                continue
            fname = fpath.strip().split("/")[-1]
            if fname in seen:
                continue
            raw = ssh_cmd(host, f'cat "{fpath.strip()}" 2>/dev/null', timeout=15)
            if not raw:
                continue
            try:
                data = json.loads(raw)
                items += ingest_charlie_pipeline(data, fname, conn, seen)
            except json.JSONDecodeError:
                continue

    save_seen("Charlie", seen)
    return items


def ensure_unique_constraint(conn):
    pass



def main():
    log("BB-Terminal collector v2 starting")
    now = datetime.now(timezone.utc)

    try:
        conn = psycopg.connect(DB_DSN)
    except Exception as e:
        log(f"DB connection failed: {e}")
        return

    ensure_unique_constraint(conn)

    collectors = {
        "Alpha": collect_alpha,
        "Bravo": collect_bravo,
        "Charlie": collect_charlie,
    }

    total = 0
    for agent, fn in collectors.items():
        try:
            items = fn(conn)
            total += items
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO collector_log (agent, collected_at, items_found) VALUES (%s, %s, %s)",
                    (agent, now, items),
                )
            conn.commit()
            log(f"{agent}: {items} items collected")
        except Exception as e:
            log(f"{agent}: error: {e}")
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO collector_log (agent, collected_at, items_found, errors) VALUES (%s, %s, 0, %s)",
                    (agent, now, str(e)[:500]),
                )
            conn.commit()

    conn.close()
    log(f"Collection complete: {total} total items")


if __name__ == "__main__":
    main()
