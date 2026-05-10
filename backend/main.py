"""BB-Terminal Backend v2 — Cortex-Medusa v4 API.

Live-computed statistics with 60-second pseudo-realtime refresh.
Pulls portfolio data from Alpaca paper accounts + pipeline data from PG.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
import os
import httpx
import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from env_config import DB_DSN, ALPACA_KEYS, ALPACA_ENDPOINT

TEAMS = {
    "Alpha":   {"cf": "192.168.1.11",  "medusa": "192.168.1.12",  "portfolio": "2A", "color": "#1601D6", "llm": "Codex CLI"},
    "Bravo":   {"cf": "192.168.13.15", "medusa": "192.168.13.14", "portfolio": "2B", "color": "#8F3823", "llm": "Gemini CLI"},
    "Charlie": {"cf": "192.168.13.16", "medusa": "192.168.1.15",  "portfolio": "2C", "color": "#747904", "llm": "Claude Code"},
}


STARTING_CAPITAL = 15000.0


def get_conn():
    return psycopg.connect(DB_DSN)


def alpaca_get(agent: str, path: str):
    keys = ALPACA_KEYS.get(agent)
    if not keys:
        return None
    try:
        r = httpx.get(
            f"{ALPACA_ENDPOINT}{path}",
            headers={"APCA-API-KEY-ID": keys["key"], "APCA-API-SECRET-KEY": keys["secret"]},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def compute_win_rate(agent: str, conn) -> float:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT direction FROM trade_proposals WHERE agent = %s AND direction IS NOT NULL""",
                (agent,),
            )
            rows = cur.fetchall()
            if not rows:
                return 0.0
            buys = sum(1 for r in rows if r[0] and r[0].upper() in ("BUY", "LONG"))
            return buys / len(rows) if rows else 0.0
    except Exception:
        return 0.0


def compute_sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    import statistics
    avg = statistics.mean(returns)
    std = statistics.stdev(returns)
    if std == 0:
        return 0.0
    return (avg / std) * (252 ** 0.5)


def compute_max_drawdown(nav_series: list[float]) -> float:
    if len(nav_series) < 2:
        return 0.0
    peak = nav_series[0]
    max_dd = 0.0
    for nav in nav_series:
        if nav > peak:
            peak = nav
        dd = (peak - nav) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return -max_dd


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="BB-Terminal Cortex-Medusa API v2", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

from market_data import router as market_router
from portfolio import router as portfolio_router
from research_data import router as research_router
from issued_stocks import router as issued_stocks_router
from narrative import narrative_router
from report_generator import report_router
app.include_router(market_router)
app.include_router(portfolio_router)
app.include_router(research_router)
app.include_router(issued_stocks_router)
app.include_router(narrative_router)
app.include_router(report_router)


# ── Competition (live-computed) ────────────────────────────────────
@app.get("/api/v1/competition")
def competition():
    rows = []
    try:
        conn = get_conn()
    except Exception as e:
        return {"results": [], "error": str(e)}

    for agent in ["Alpha", "Bravo", "Charlie"]:
        info = TEAMS[agent]

        # Pull live NAV from Alpaca
        acct = alpaca_get(agent, "/v2/account")
        if acct:
            nav = float(acct.get("portfolio_value", 0) or acct.get("equity", 0))
            cash = float(acct.get("cash", 0))
            last_equity = float(acct.get("last_equity", nav))
        else:
            # Fallback to latest reconciliation
            nav, cash, last_equity = STARTING_CAPITAL, STARTING_CAPITAL, STARTING_CAPITAL
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT nav, cash FROM reconciliation WHERE agent = %s ORDER BY reconciled_at DESC LIMIT 1",
                        (agent,),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        nav = float(row[0])
                        cash = float(row[1]) if row[1] else 0
                        last_equity = nav
            except Exception:
                pass

        cumulative_return = (nav - STARTING_CAPITAL) / STARTING_CAPITAL if STARTING_CAPITAL > 0 else 0
        daily_return = (nav - last_equity) / last_equity if last_equity > 0 else 0

        # Trade count from DB
        trade_count = 0
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM executions WHERE agent = %s", (agent,))
                trade_count = cur.fetchone()[0]
                if trade_count == 0:
                    cur.execute("SELECT COUNT(*) FROM trade_proposals WHERE agent = %s", (agent,))
                    trade_count = cur.fetchone()[0]
        except Exception:
            pass

        # NAV history for sharpe / drawdown
        nav_history = []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT nav FROM competition_snapshots WHERE agent = %s ORDER BY snapshot_at",
                    (agent,),
                )
                nav_history = [float(r[0]) for r in cur.fetchall() if r[0]]
        except Exception:
            pass

        if nav_history and len(nav_history) >= 2:
            returns = [(nav_history[i] - nav_history[i-1]) / nav_history[i-1]
                       for i in range(1, len(nav_history)) if nav_history[i-1] > 0]
            sharpe = compute_sharpe(returns)
            max_dd = compute_max_drawdown(nav_history)
        else:
            sharpe = 0.0
            max_dd = 0.0

        win_rate = compute_win_rate(agent, conn)

        rows.append({
            "agent": agent, **info,
            "nav": round(nav, 2),
            "cash": round(cash, 2),
            "cumulative_return": round(cumulative_return, 6),
            "daily_return": round(daily_return, 6),
            "sharpe": round(sharpe, 2),
            "max_drawdown": round(max_dd, 6),
            "trade_count": trade_count,
            "win_rate": round(win_rate, 4),
            "as_of": datetime.now(timezone.utc).isoformat(),
            "source": "alpaca_live" if acct else "db_fallback",
        })

        # Store snapshot for historical tracking
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO competition_snapshots
                       (agent, nav, cumulative_return, daily_return, sharpe, max_drawdown, trade_count, win_rate)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (agent, round(nav, 2), round(cumulative_return, 6), round(daily_return, 6),
                     round(sharpe, 2), round(max_dd, 6), trade_count, round(win_rate, 4)),
                )
            conn.commit()
        except Exception:
            conn.rollback()

    conn.close()
    return {"results": rows, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/v1/competition/history")
def competition_history(days: int = 30):
    data = {}
    try:
        with get_conn() as conn, conn.cursor() as cur:
            for agent in ["Alpha", "Bravo", "Charlie"]:
                cur.execute(
                    """SELECT DISTINCT ON (snapshot_at::date) snapshot_at::date as d, nav
                       FROM competition_snapshots
                       WHERE agent = %s AND snapshot_at > NOW() - interval '%s days'
                       ORDER BY snapshot_at::date, snapshot_at DESC""",
                    (agent, days),
                )
                data[agent] = [{"date": str(r[0]), "nav": float(r[1])} for r in cur.fetchall()]
    except Exception:
        pass
    return {"results": data}


# ── Live Positions (from Alpaca) ───────────────────────────────────
@app.get("/api/v1/positions/{agent}")
def positions(agent: str):
    agent = agent.capitalize()
    if agent not in TEAMS:
        return {"error": "Unknown agent"}

    pos = alpaca_get(agent, "/v2/positions")
    if pos is None:
        return {"results": [], "source": "unavailable"}

    results = []
    for p in pos:
        results.append({
            "symbol": p.get("symbol"),
            "qty": float(p.get("qty", 0)),
            "avg_entry": float(p.get("avg_entry_price", 0)),
            "current_price": float(p.get("current_price", 0)),
            "market_value": float(p.get("market_value", 0)),
            "unrealized_pl": float(p.get("unrealized_pl", 0)),
            "unrealized_plpc": float(p.get("unrealized_plpc", 0)),
            "change_today": float(p.get("change_today", 0)),
            "side": p.get("side", "long"),
        })

    return {
        "results": results,
        "source": "alpaca_live",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Account Summary (from Alpaca) ─────────────────────────────────
@app.get("/api/v1/account/{agent}")
def account(agent: str):
    agent = agent.capitalize()
    if agent not in TEAMS:
        return {"error": "Unknown agent"}

    acct = alpaca_get(agent, "/v2/account")
    if acct is None:
        return {"results": None, "source": "unavailable"}

    return {
        "results": {
            "equity": float(acct.get("equity", 0)),
            "cash": float(acct.get("cash", 0)),
            "buying_power": float(acct.get("buying_power", 0)),
            "portfolio_value": float(acct.get("portfolio_value", 0)),
            "last_equity": float(acct.get("last_equity", 0)),
            "long_market_value": float(acct.get("long_market_value", 0)),
            "short_market_value": float(acct.get("short_market_value", 0)),
            "status": acct.get("status"),
            "pattern_day_trader": acct.get("pattern_day_trader"),
        },
        "source": "alpaca_live",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Team Overview ──────────────────────────────────────────────────
@app.get("/api/v1/team/{agent}")
def team_overview(agent: str):
    agent = agent.capitalize()
    if agent not in TEAMS:
        return {"error": "Unknown agent"}
    info = TEAMS[agent]
    result = {"agent": agent, **info, "pipeline": [], "recent_research": [],
              "recent_trades": [], "latest_recon": None}
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT stage, status, last_run, last_output FROM pipeline_status WHERE agent = %s ORDER BY stage",
                (agent,),
            )
            result["pipeline"] = [
                {"stage": r[0], "status": r[1], "last_run": str(r[2]) if r[2] else None, "output": r[3]}
                for r in cur.fetchall()
            ]
            cur.execute(
                """SELECT stage, symbol, title, content, source, collected_at
                   FROM research_notes WHERE agent = %s
                   ORDER BY collected_at DESC LIMIT 10""",
                (agent,),
            )
            result["recent_research"] = [
                {"stage": r[0], "symbol": r[1], "title": r[2], "content": r[3],
                 "source": r[4], "time": str(r[5])}
                for r in cur.fetchall()
            ]
            cur.execute(
                """SELECT symbol, side, quantity, price, executed_at, status
                   FROM executions WHERE agent = %s
                   ORDER BY executed_at DESC LIMIT 15""",
                (agent,),
            )
            result["recent_trades"] = [
                {"symbol": r[0], "side": r[1], "qty": r[2], "price": r[3],
                 "time": str(r[4]), "status": r[5]}
                for r in cur.fetchall()
            ]
            cur.execute(
                """SELECT portfolio, nav, cash, positions_count, drift_pct, notes, reconciled_at
                   FROM reconciliation WHERE agent = %s
                   ORDER BY reconciled_at DESC LIMIT 1""",
                (agent,),
            )
            row = cur.fetchone()
            if row:
                result["latest_recon"] = {
                    "portfolio": row[0], "nav": row[1], "cash": row[2],
                    "positions": row[3], "drift_pct": row[4], "notes": row[5],
                    "time": str(row[6]),
                }
    except Exception as e:
        result["error"] = str(e)

    # Overlay live Alpaca data if available
    acct = alpaca_get(agent, "/v2/account")
    if acct:
        result["live_nav"] = float(acct.get("portfolio_value", 0) or acct.get("equity", 0))
        result["live_cash"] = float(acct.get("cash", 0))

    return {"results": result}


# ── Research ───────────────────────────────────────────────────────
@app.get("/api/v1/research/{agent}")
def research(agent: str, limit: int = 50):
    agent = agent.capitalize()
    rows = []
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT stage, symbol, title, content, source, collected_at
                   FROM research_notes WHERE agent = %s
                   ORDER BY collected_at DESC LIMIT %s""",
                (agent, limit),
            )
            rows = [
                {"stage": r[0], "symbol": r[1], "title": r[2], "content": r[3],
                 "source": r[4], "time": str(r[5])}
                for r in cur.fetchall()
            ]
    except Exception:
        pass
    return {"results": rows}


# ── Trade Proposals ────────────────────────────────────────────────
@app.get("/api/v1/proposals/{agent}")
def proposals(agent: str, limit: int = 25):
    agent = agent.capitalize()
    rows = []
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT symbol, direction, rationale, confidence, holding_period,
                          proposed_at, status
                   FROM trade_proposals WHERE agent = %s
                   ORDER BY proposed_at DESC LIMIT %s""",
                (agent, limit),
            )
            rows = [
                {"symbol": r[0], "direction": r[1], "rationale": r[2],
                 "confidence": r[3], "holding_period": r[4],
                 "time": str(r[5]), "status": r[6]}
                for r in cur.fetchall()
            ]
    except Exception:
        pass
    return {"results": rows}


# ── Executions ─────────────────────────────────────────────────────
@app.get("/api/v1/executions/{agent}")
def executions(agent: str, limit: int = 50):
    agent = agent.capitalize()
    rows = []
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT symbol, side, quantity, price, order_id, portfolio,
                          executed_at, status
                   FROM executions WHERE agent = %s
                   ORDER BY executed_at DESC LIMIT %s""",
                (agent, limit),
            )
            rows = [
                {"symbol": r[0], "side": r[1], "qty": r[2], "price": r[3],
                 "order_id": r[4], "portfolio": r[5], "time": str(r[6]),
                 "status": r[7]}
                for r in cur.fetchall()
            ]
    except Exception:
        pass
    return {"results": rows}


# ── Reconciliation ─────────────────────────────────────────────────
@app.get("/api/v1/reconciliation/{agent}")
def reconciliation(agent: str, limit: int = 20):
    agent = agent.capitalize()
    rows = []
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT portfolio, nav, cash, positions_count, drift_pct, notes,
                          reconciled_at
                   FROM reconciliation WHERE agent = %s
                   ORDER BY reconciled_at DESC LIMIT %s""",
                (agent, limit),
            )
            rows = [
                {"portfolio": r[0], "nav": r[1], "cash": r[2], "positions": r[3],
                 "drift_pct": r[4], "notes": r[5], "time": str(r[6])}
                for r in cur.fetchall()
            ]
    except Exception:
        pass
    return {"results": rows}


# ── Pipeline Status ────────────────────────────────────────────────
@app.get("/api/v1/pipeline/{agent}")
def pipeline(agent: str):
    agent = agent.capitalize()
    stages = ["Analysts", "Research (Bull/Bear)", "Trader", "Risk Management", "Portfolio Manager", "Execution"]
    rows = []
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT stage, status, last_run, last_output FROM pipeline_status WHERE agent = %s",
                (agent,),
            )
            db_rows = {r[0]: {"stage": r[0], "status": r[1], "last_run": str(r[2]) if r[2] else None, "output": r[3]}
                       for r in cur.fetchall()}
            for s in stages:
                rows.append(db_rows.get(s, {"stage": s, "status": "idle", "last_run": None, "output": None}))
    except Exception:
        rows = [{"stage": s, "status": "idle", "last_run": None, "output": None} for s in stages]
    return {"results": rows}


# ── Cycle Audit ────────────────────────────────────────────────────
@app.get("/api/v1/cycles/{agent}")
def cycles(agent: str, limit: int = 20):
    agent = agent.capitalize()
    rows = []
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT cycle_id, symbol, started_at, completed_at, status, final_rating, llm_backend
                   FROM pipeline_cycles WHERE agent = %s
                   ORDER BY started_at DESC LIMIT %s""",
                (agent, limit),
            )
            rows = [
                {"cycle_id": r[0], "symbol": r[1], "started": str(r[2]) if r[2] else None,
                 "completed": str(r[3]) if r[3] else None, "status": r[4],
                 "rating": r[5], "llm": r[6]}
                for r in cur.fetchall()
            ]
    except Exception:
        pass
    return {"results": rows}


@app.get("/api/v1/cycle/{cycle_id}")
def cycle_detail(cycle_id: str):
    result = {"cycle": None, "stages": [], "decision": None, "trades": [], "reconciliation": None}
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM pipeline_cycles WHERE cycle_id = %s", (cycle_id,))
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            if row:
                result["cycle"] = dict(zip(cols, [str(v) if v else v for v in row]))

            cur.execute("SELECT stage, sub_stage, status, started_at, completed_at, output_summary, llm_model, tokens_used, latency_ms FROM cycle_stages WHERE cycle_id = %s ORDER BY started_at", (cycle_id,))
            result["stages"] = [{"stage": r[0], "sub_stage": r[1], "status": r[2], "started": str(r[3]) if r[3] else None, "completed": str(r[4]) if r[4] else None, "output": r[5], "llm": r[6], "tokens": r[7], "latency_ms": r[8]} for r in cur.fetchall()]

            cur.execute("SELECT rating, direction, conviction, executive_summary, investment_thesis, risk_notes FROM cycle_decisions WHERE cycle_id = %s", (cycle_id,))
            row = cur.fetchone()
            if row:
                result["decision"] = {"rating": row[0], "direction": row[1], "conviction": row[2], "summary": row[3], "thesis": row[4], "risk": row[5]}

            cur.execute("SELECT symbol, side, quantity, price, executed_at, status FROM cycle_trades WHERE cycle_id = %s", (cycle_id,))
            result["trades"] = [{"symbol": r[0], "side": r[1], "qty": float(r[2]) if r[2] else 0, "price": float(r[3]) if r[3] else 0, "time": str(r[4]) if r[4] else None, "status": r[5]} for r in cur.fetchall()]
    except Exception as e:
        result["error"] = str(e)
    return {"results": result}


# ── Health ─────────────────────────────────────────────────────────
@app.get("/api/v1/health")
def health():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        alpaca_ok = alpaca_get("Alpha", "/v2/account") is not None
        return {"status": "healthy", "db": "connected", "alpaca": "connected" if alpaca_ok else "unavailable",
                "time": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"status": "unhealthy", "db": str(e), "time": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=6900)
