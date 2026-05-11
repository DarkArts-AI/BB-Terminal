from datetime import datetime, timezone
from collections import defaultdict

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

import urllib.request
import json as _json
import threading
import time as _time
import yfinance as yf

from env_config import DB_DSN, CMV4_DSN

narrative_router = APIRouter(prefix="/api/v1/narrative", tags=["narrative"])

AGENTS = ["Alpha", "Bravo", "Charlie"]


def get_conn():
    return psycopg.connect(DB_DSN)


def get_cmv4_conn():
    return psycopg.connect(CMV4_DSN)


@narrative_router.get("/conversation/{cycle_id}")
def conversation(cycle_id: str):
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT pc.cycle_id, pc.agent, pc.symbol, pc.started_at, pc.completed_at, pc.status,
                          pc.final_rating, pc.llm_backend, pc.total_tokens, pc.total_latency_ms,
                          pc.thread_id, pc.origin_source, sn.company_name
                   FROM pipeline_cycles pc
                   LEFT JOIN symbol_names sn ON pc.symbol = sn.symbol
                   WHERE pc.cycle_id = %s""",
                (cycle_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Cycle not found")
            cols = [d[0] for d in cur.description]
            cycle = {c: (str(v) if isinstance(v, datetime) else v) for c, v in zip(cols, row)}

            cur.execute(
                """SELECT id, stage, sub_stage, status, started_at, completed_at,
                          output_summary, output_full, llm_model, tokens_used,
                          latency_ms, refs
                   FROM cycle_stages WHERE cycle_id = %s
                   ORDER BY completed_at NULLS LAST, started_at""",
                (cycle_id,),
            )
            stage_cols = [d[0] for d in cur.description]
            stages = []
            for r in cur.fetchall():
                s = {}
                for c, v in zip(stage_cols, r):
                    if isinstance(v, datetime):
                        s[c] = str(v)
                    else:
                        s[c] = v
                speaker = s.get("sub_stage") or s.get("stage", "system")
                content = s.get("output_full") or s.get("output_summary") or ""
                s["speaker_role"] = speaker
                s["content"] = content
                s["timestamp"] = s.get("completed_at") or s.get("started_at")
                stages.append(s)

            cur.execute(
                """SELECT id, debate_type, round_number, speaker_role, content,
                          refs, ts, token_count
                   FROM debate_rounds WHERE cycle_id = %s
                   ORDER BY debate_type, round_number""",
                (cycle_id,),
            )
            debate_cols = [d[0] for d in cur.description]
            debates = []
            for r in cur.fetchall():
                d = {}
                for c, v in zip(debate_cols, r):
                    if isinstance(v, datetime):
                        d[c] = str(v)
                    else:
                        d[c] = v
                d["timestamp"] = d.get("ts")
                debates.append(d)

            cur.execute(
                """SELECT rating, direction, conviction, executive_summary,
                          investment_thesis, risk_notes
                   FROM cycle_decisions WHERE cycle_id = %s""",
                (cycle_id,),
            )
            dec_row = cur.fetchone()
            decision = None
            if dec_row:
                dec_cols = [d[0] for d in cur.description]
                decision = dict(zip(dec_cols, dec_row))

            cur.execute(
                """SELECT symbol, side, quantity, price, executed_at, status
                   FROM cycle_trades WHERE cycle_id = %s""",
                (cycle_id,),
            )
            trades = [
                {"symbol": r[0], "side": r[1], "qty": float(r[2]) if r[2] else 0,
                 "price": float(r[3]) if r[3] else 0,
                 "time": str(r[4]) if r[4] else None, "status": r[5]}
                for r in cur.fetchall()
            ]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "cycle": cycle,
        "stages": stages,
        "debate_rounds": debates,
        "decision": decision,
        "trades": trades,
    }


@narrative_router.get("/thread/{thread_id}")
def thread(thread_id: str):
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT tl.thread_id, tl.cycle_id, tl.sequence, tl.relationship,
                          pc.agent, pc.symbol, pc.started_at, pc.completed_at,
                          pc.status, pc.final_rating
                   FROM thread_links tl
                   JOIN pipeline_cycles pc ON tl.cycle_id = pc.cycle_id
                   WHERE tl.thread_id = %s
                   ORDER BY tl.sequence""",
                (thread_id,),
            )
            rows = cur.fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail="Thread not found")

            events = []
            for r in rows:
                events.append({
                    "cycle_id": r[1],
                    "sequence": r[2],
                    "relationship": r[3],
                    "agent": r[4],
                    "symbol": r[5],
                    "started_at": str(r[6]) if r[6] else None,
                    "completed_at": str(r[7]) if r[7] else None,
                    "status": r[8],
                    "rating": r[9],
                })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"thread_id": thread_id, "events": events}


@narrative_router.get("/watchlist")
def watchlist_summary():
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            per_agent = {}
            for agent in AGENTS:
                cur.execute(
                    """SELECT
                         COUNT(*) FILTER (WHERE priority = 'HIGH') AS high,
                         COUNT(*) FILTER (WHERE priority = 'MEDIUM') AS medium,
                         COUNT(*) FILTER (WHERE priority = 'LOW') AS low,
                         COUNT(*) AS total
                       FROM agent_watchlist
                       WHERE LOWER(agent) = LOWER(%s) AND removal_date IS NULL""",
                    (agent,),
                )
                r = cur.fetchone()
                per_agent[agent] = {
                    "total": r[3], "high": r[0], "medium": r[1], "low": r[2]
                }

            cur.execute(
                """SELECT agent, symbol FROM agent_watchlist WHERE removal_date IS NULL"""
            )
            agent_symbols = defaultdict(set)
            for r in cur.fetchall():
                agent_symbols[r[0].capitalize()].add(r[1])

            all_symbols = set()
            for s in agent_symbols.values():
                all_symbols |= s

            a_set = agent_symbols.get("Alpha", set())
            b_set = agent_symbols.get("Bravo", set())
            c_set = agent_symbols.get("Charlie", set())

            ab = a_set & b_set
            ac = a_set & c_set
            bc = b_set & c_set
            abc = a_set & b_set & c_set

            convergence = []
            for sym in all_symbols:
                count = sum(1 for s in [a_set, b_set, c_set] if sym in s)
                if count >= 2:
                    agents_on = [a for a, ss in agent_symbols.items() if sym in ss]
                    convergence.append({"symbol": sym, "agent_count": count, "agents": sorted(agents_on)})
            convergence.sort(key=lambda x: (-x["agent_count"], x["symbol"]))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "per_agent": per_agent,
        "total_unique_symbols": len(all_symbols),
        "overlap": {
            "alpha_bravo": sorted(ab),
            "alpha_charlie": sorted(ac),
            "bravo_charlie": sorted(bc),
            "triple": sorted(abc),
        },
        "top_convergence": convergence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@narrative_router.get("/watchlist/{agent}")
def watchlist_agent(agent: str):
    agent = agent.capitalize()
    if agent not in AGENTS:
        raise HTTPException(status_code=400, detail="Unknown agent")
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT symbol, priority, source, thesis_summary, catalyst_date,
                          last_analyzed, added_at
                   FROM agent_watchlist
                   WHERE LOWER(agent) = LOWER(%s) AND removal_date IS NULL
                   ORDER BY
                     CASE priority WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                     added_at""",
                (agent,),
            )
            entries = []
            for r in cur.fetchall():
                entries.append({
                    "symbol": r[0],
                    "priority": r[1],
                    "source": r[2],
                    "thesis_summary": r[3],
                    "catalyst_date": str(r[4]) if r[4] else None,
                    "last_analyzed": str(r[5]) if r[5] else None,
                    "added_at": str(r[6]) if r[6] else None,
                })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"agent": agent, "entries": entries, "count": len(entries)}


@narrative_router.get("/kpis")
def kpis():
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            snapshots = {}
            for agent in AGENTS:
                cur.execute(
                    """SELECT snapshot_date, active_count, high_priority, medium_priority,
                              low_priority, additions_7d, removals_7d, cycles_24h
                       FROM watchlist_snapshots
                       WHERE agent = %s
                       ORDER BY snapshot_date DESC LIMIT 1""",
                    (agent,),
                )
                r = cur.fetchone()
                if r:
                    snapshots[agent] = {
                        "snapshot_date": str(r[0]),
                        "active_count": r[1],
                        "high_priority": r[2],
                        "medium_priority": r[3],
                        "low_priority": r[4],
                        "additions_7d": r[5],
                        "removals_7d": r[6],
                        "cycles_24h": r[7],
                    }

            cycles_24h = {}
            for agent in AGENTS:
                cur.execute(
                    """SELECT COUNT(*) FROM pipeline_cycles
                       WHERE agent = %s AND started_at > NOW() - INTERVAL '24 hours'""",
                    (agent,),
                )
                cycles_24h[agent] = cur.fetchone()[0]

            symbols_all = {}
            symbols_7d = {}
            for agent in AGENTS:
                cur.execute(
                    "SELECT COUNT(DISTINCT symbol) FROM pipeline_cycles WHERE agent = %s",
                    (agent,),
                )
                symbols_all[agent] = cur.fetchone()[0]

                cur.execute(
                    """SELECT COUNT(DISTINCT symbol) FROM pipeline_cycles
                       WHERE agent = %s AND started_at > NOW() - INTERVAL '7 days'""",
                    (agent,),
                )
                symbols_7d[agent] = cur.fetchone()[0]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "watchlist_snapshots": snapshots,
        "pipeline_cycles_24h": cycles_24h,
        "unique_symbols_all_time": symbols_all,
        "unique_symbols_7d": symbols_7d,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@narrative_router.get("/coverage-map")
def coverage_map():
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT agent, symbol FROM agent_watchlist WHERE removal_date IS NULL"
            )
            agent_symbols = defaultdict(set)
            for r in cur.fetchall():
                agent_symbols[r[0].capitalize()].add(r[1])

            per_agent = {a: sorted(agent_symbols.get(a, set())) for a in AGENTS}

            a_set = agent_symbols.get("Alpha", set())
            b_set = agent_symbols.get("Bravo", set())
            c_set = agent_symbols.get("Charlie", set())

            venn = {
                "alpha_only": sorted(a_set - b_set - c_set),
                "bravo_only": sorted(b_set - a_set - c_set),
                "charlie_only": sorted(c_set - a_set - b_set),
                "alpha_bravo": sorted((a_set & b_set) - c_set),
                "alpha_charlie": sorted((a_set & c_set) - b_set),
                "bravo_charlie": sorted((b_set & c_set) - a_set),
                "all_three": sorted(a_set & b_set & c_set),
            }

            convergence_alerts = sorted(a_set & b_set & c_set)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "per_agent": per_agent,
        "venn": venn,
        "convergence_alerts": convergence_alerts,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@narrative_router.get("/cycles")
def list_cycles(
    agent: str | None = None,
    symbol: str | None = None,
    status: str | None = None,
    rating: str | None = None,
    hours: int = 72,
    limit: int = 500,
):
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            clauses = ["pc.started_at > NOW() - INTERVAL '%s hours'" % int(hours)]
            params: list = []
            if agent:
                clauses.append("pc.agent = %s")
                params.append(agent.capitalize())
            if symbol:
                clauses.append("UPPER(pc.symbol) = UPPER(%s)")
                params.append(symbol)
            if status:
                clauses.append("pc.status = %s")
                params.append(status)
            if rating:
                clauses.append("UPPER(pc.final_rating) = UPPER(%s)")
                params.append(rating)

            where = " AND ".join(clauses)
            cur.execute(
                f"""SELECT pc.cycle_id, pc.agent, pc.symbol, pc.status, pc.final_rating,
                          pc.llm_backend, pc.total_tokens, pc.total_latency_ms,
                          pc.started_at, pc.completed_at,
                          sn.company_name, COALESCE(pc.source, 'scheduled') as source
                   FROM pipeline_cycles pc
                   LEFT JOIN symbol_names sn ON pc.symbol = sn.symbol
                   WHERE {where}
                   ORDER BY pc.started_at DESC
                   LIMIT %s""",
                params + [limit],
            )
            cols = [d[0] for d in cur.description]
            rows = []
            for r in cur.fetchall():
                row = {}
                for c, v in zip(cols, r):
                    row[c] = str(v) if isinstance(v, datetime) else v
                rows.append(row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"cycles": rows, "count": len(rows), "timestamp": datetime.now(timezone.utc).isoformat()}


# ── Pipeline Request (User-Submitted Analysis) ─────────────────────────

MAX_CONCURRENT_TICKERS = 3
STALE_TIMEOUT_HOURS = 6


def _expire_stale_requests():
    """Mark requests running longer than STALE_TIMEOUT_HOURS as 'timeout'."""
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE pipeline_requests
                   SET status = 'timeout', completed_at = NOW(),
                       notes = COALESCE(notes, '') || ' [auto-expired after %s hours]'
                   WHERE status = 'running'
                     AND picked_up_at < NOW() - INTERVAL '%s hours'
                   RETURNING id, symbol, picked_up_by""",
                (STALE_TIMEOUT_HOURS, STALE_TIMEOUT_HOURS),
            )
            expired = cur.fetchall()
            conn.commit()
            return expired
    except Exception:
        return []


def _count_running_tickers() -> int:
    """Count distinct tickers currently in 'running' status."""
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT symbol) FROM pipeline_requests WHERE status = 'running'"
            )
            return cur.fetchone()[0]
    except Exception:
        return 0


class AnalysisRequest(BaseModel):
    symbol: str
    agents: list[str] = ["Alpha", "Bravo", "Charlie"]
    requested_by: str = "operator"
    notes: Optional[str] = None


@narrative_router.post("/request")
def submit_request(req: AnalysisRequest):
    symbol = req.symbol.strip().upper()
    if not symbol or len(symbol) > 10:
        raise HTTPException(status_code=400, detail="Invalid symbol")
    valid_agents = {"Alpha", "Bravo", "Charlie"}
    agents = [a.capitalize() for a in req.agents if a.capitalize() in valid_agents]
    if not agents:
        raise HTTPException(status_code=400, detail="No valid agents specified")
    try:
        created = []
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            for agent in agents:
                cur.execute(
                    """INSERT INTO pipeline_requests (symbol, agents, requested_by, notes)
                       VALUES (%s, %s, %s, %s) RETURNING id, requested_at""",
                    (symbol, [agent], req.requested_by, req.notes),
                )
                row = cur.fetchone()
                created.append({"id": row[0], "agent": agent, "requested_at": str(row[1])})
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "ids": [c["id"] for c in created],
        "symbol": symbol,
        "agents": agents,
        "requested_at": created[0]["requested_at"],
        "status": "pending",
        "count": len(created),
    }


@narrative_router.get("/requests")
def list_requests(status: str | None = None, limit: int = 50):
    _expire_stale_requests()
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            where = ""
            params: list = []
            if status:
                where = "WHERE status = %s"
                params.append(status)
            cur.execute(
                f"""SELECT id, symbol, agents, requested_by, requested_at,
                          status, picked_up_by, picked_up_at, completed_at, cycle_id, notes
                   FROM pipeline_requests {where}
                   ORDER BY requested_at DESC LIMIT %s""",
                params + [limit],
            )
            cols = [d[0] for d in cur.description]
            rows = []
            for r in cur.fetchall():
                row = {}
                for c, v in zip(cols, r):
                    row[c] = str(v) if isinstance(v, datetime) else v
                rows.append(row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"requests": rows, "count": len(rows)}


@narrative_router.get("/requests/pending/{agent}")
def pending_requests(agent: str):
    agent = agent.capitalize()
    if agent not in AGENTS:
        raise HTTPException(status_code=400, detail="Unknown agent")
    _expire_stale_requests()
    running_tickers = _count_running_tickers()
    if running_tickers >= MAX_CONCURRENT_TICKERS:
        return {"agent": agent, "pending": [], "count": 0,
                "throttled": True, "running_tickers": running_tickers,
                "max_concurrent": MAX_CONCURRENT_TICKERS}
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id, symbol, requested_by, notes, requested_at
                   FROM pipeline_requests
                   WHERE status = 'pending' AND %s = ANY(agents)
                   ORDER BY requested_at ASC""",
                (agent,),
            )
            cols = [d[0] for d in cur.description]
            rows = []
            for r in cur.fetchall():
                row = {}
                for c, v in zip(cols, r):
                    row[c] = str(v) if isinstance(v, datetime) else v
                rows.append(row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"agent": agent, "pending": rows, "count": len(rows),
            "throttled": False, "running_tickers": running_tickers,
            "max_concurrent": MAX_CONCURRENT_TICKERS}


@narrative_router.post("/requests/{request_id}/claim")
def claim_request(request_id: int, agent: str):
    agent = agent.capitalize()
    _expire_stale_requests()
    running_tickers = _count_running_tickers()
    if running_tickers >= MAX_CONCURRENT_TICKERS:
        raise HTTPException(status_code=429,
                            detail=f"Throttled: {running_tickers}/{MAX_CONCURRENT_TICKERS} tickers running")
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE pipeline_requests
                   SET status = 'running', picked_up_by = %s, picked_up_at = NOW()
                   WHERE id = %s AND status = 'pending'
                   RETURNING id""",
                (agent, request_id),
            )
            row = cur.fetchone()
            conn.commit()
            if not row:
                raise HTTPException(status_code=404, detail="Request not found or already claimed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"id": request_id, "status": "running", "picked_up_by": agent}


@narrative_router.post("/requests/{request_id}/complete")
def complete_request(request_id: int, cycle_id: str | None = None):
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE pipeline_requests
                   SET status = 'complete', completed_at = NOW(), cycle_id = %s
                   WHERE id = %s
                   RETURNING id""",
                (cycle_id, request_id),
            )
            row = cur.fetchone()
            conn.commit()
            if not row:
                raise HTTPException(status_code=404, detail="Request not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"id": request_id, "status": "complete", "cycle_id": cycle_id}


@narrative_router.post("/requests/{request_id}/resubmit")
def resubmit_request(request_id: int):
    """Clone a timed-out or cancelled request as a new pending request."""
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT symbol, agents, requested_by, notes
                   FROM pipeline_requests WHERE id = %s AND status IN ('timeout', 'complete')""",
                (request_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Request not found or not eligible for resubmit")
            symbol, agents, requested_by, notes = row
            resubmit_note = f"resubmit of #{request_id}"
            if notes:
                resubmit_note = f"{notes} | {resubmit_note}"
            created = []
            for agent in (agents or ["Alpha"]):
                cur.execute(
                    """INSERT INTO pipeline_requests (symbol, agents, requested_by, notes)
                       VALUES (%s, %s, %s, %s) RETURNING id, requested_at""",
                    (symbol, [agent], requested_by, resubmit_note),
                )
                r = cur.fetchone()
                created.append({"id": r[0], "agent": agent, "requested_at": str(r[1])})
            conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "ids": [c["id"] for c in created],
        "symbol": symbol,
        "status": "pending",
        "resubmitted_from": request_id,
    }


@narrative_router.get("/symbols")
def list_symbols():
    """Return cached symbol list from symbol_names table."""
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT symbol, company_name FROM symbol_names ORDER BY symbol")
            rows = [{"symbol": r[0], "name": r[1]} for r in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"symbols": rows, "count": len(rows)}


class NoteBody(BaseModel):
    content: str
    updated_by: str = "operator"


@narrative_router.get("/notes/{cycle_id}")
def get_notes(cycle_id: str):
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT content, updated_by, updated_at FROM cycle_notes WHERE cycle_id = %s",
                (cycle_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"cycle_id": cycle_id, "content": "", "updated_by": None, "updated_at": None}
            return {
                "cycle_id": cycle_id,
                "content": row[0],
                "updated_by": row[1],
                "updated_at": str(row[2]) if row[2] else None,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@narrative_router.put("/notes/{cycle_id}")
def save_notes(cycle_id: str, body: NoteBody):
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO cycle_notes (cycle_id, content, updated_by, updated_at)
                   VALUES (%s, %s, %s, NOW())
                   ON CONFLICT (cycle_id) DO UPDATE
                   SET content = EXCLUDED.content,
                       updated_by = EXCLUDED.updated_by,
                       updated_at = NOW()
                   RETURNING updated_at""",
                (cycle_id, body.content, body.updated_by),
            )
            updated_at = cur.fetchone()[0]
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "cycle_id": cycle_id,
        "content": body.content,
        "updated_by": body.updated_by,
        "updated_at": str(updated_at),
    }


@narrative_router.get("/validate-symbol/{symbol}")
def validate_symbol(symbol: str):
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) > 10:
        raise HTTPException(status_code=400, detail="Invalid symbol")
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}&quotesCount=5&newsCount=0"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode())
        quotes = data.get("quotes", [])
        for q in quotes:
            if q.get("symbol", "").upper() == symbol and q.get("quoteType") in ("EQUITY", "ETF"):
                return {
                    "valid": True,
                    "symbol": symbol,
                    "name": q.get("shortname") or q.get("longname") or "",
                    "exchange": q.get("exchange", ""),
                    "type": q.get("quoteType", ""),
                }
        return {"valid": False, "symbol": symbol, "name": None}
    except Exception:
        return {"valid": False, "symbol": symbol, "name": None, "error": "lookup_failed"}


@narrative_router.delete("/requests/{request_id}")
def cancel_request(request_id: int):
    try:
        with get_cmv4_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """DELETE FROM pipeline_requests
                   WHERE id = %s AND status IN ('pending', 'running', 'timeout')
                   RETURNING id, symbol, status""",
                (request_id,),
            )
            row = cur.fetchone()
            conn.commit()
            if not row:
                raise HTTPException(status_code=404, detail="Request not found or already complete")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"id": request_id, "cancelled": True, "was_status": row[2]}


# ---------------------------------------------------------------------------
# Live price data via yfinance (cached, batch-fetched)
# ---------------------------------------------------------------------------

_price_cache: dict[str, dict] = {}
_price_cache_lock = threading.Lock()
_price_cache_ts: float = 0
_PRICE_TTL = 60  # refresh at most every 60s


def _fetch_prices(symbols: list[str]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    if not symbols:
        return results
    tickers = yf.Tickers(" ".join(symbols))
    for sym in symbols:
        try:
            t = tickers.tickers.get(sym)
            if not t:
                continue
            info = t.fast_info
            price = float(info.last_price) if info.last_price else None
            prev = float(info.previous_close) if info.previous_close else None
            if price is not None and prev is not None and prev != 0:
                change = price - prev
                change_pct = (change / prev) * 100
            else:
                change = None
                change_pct = None
            results[sym] = {
                "price": round(price, 2) if price else None,
                "change": round(change, 2) if change is not None else None,
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
                "prev_close": round(prev, 2) if prev else None,
            }
        except Exception:
            results[sym] = {"price": None, "change": None, "change_pct": None, "prev_close": None}
    return results


@narrative_router.post("/prices")
def get_prices(body: dict):
    global _price_cache, _price_cache_ts
    symbols = body.get("symbols", [])
    if not symbols or not isinstance(symbols, list):
        return {"prices": {}}
    symbols = [s.upper().strip() for s in symbols[:200]]

    now = _time.time()
    with _price_cache_lock:
        missing = [s for s in symbols if s not in _price_cache]
        stale = now - _price_cache_ts > _PRICE_TTL

    if missing or stale:
        fetch_list = symbols if stale else missing
        try:
            fresh = _fetch_prices(fetch_list)
            with _price_cache_lock:
                _price_cache.update(fresh)
                _price_cache_ts = now
        except Exception:
            pass

    with _price_cache_lock:
        result = {s: _price_cache.get(s, {}) for s in symbols}
    return {"prices": result}
