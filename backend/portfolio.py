"""Portfolio Router — CRUD, trade simulation, cash management, leaderboard integration."""

from datetime import datetime, timezone
from typing import Optional

import httpx
import psycopg
import yfinance as yf
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/portfolio")

from env_config import DB_DSN, ALPACA_KEYS, ALPACA_ENDPOINT
STARTING_CAPITAL = 15000.0

SLUG_TO_AGENT = {"2A": "Alpha", "2B": "Bravo", "2C": "Charlie", "LIVE-MEDUSA": "LiveMedusa"}

ALPACA_LIVE_ENDPOINT = "https://api.alpaca.markets"
LIVE_MEDUSA_STARTING = 5000.0


def _alpaca_get(agent: str, path: str, endpoint: str | None = None):
    keys = ALPACA_KEYS.get(agent)
    if not keys:
        return None
    base = endpoint or (ALPACA_LIVE_ENDPOINT if agent == "LiveMedusa" else ALPACA_ENDPOINT)
    try:
        r = httpx.get(
            f"{base}{path}",
            headers={"APCA-API-KEY-ID": keys["key"], "APCA-API-SECRET-KEY": keys["secret"]},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _alpaca_portfolio(agent: str, starting: float | None = None) -> dict | None:
    """Fetch live NAV, cash, positions from Alpaca for a system agent."""
    if starting is None:
        starting = LIVE_MEDUSA_STARTING if agent == "LiveMedusa" else STARTING_CAPITAL
    acct = _alpaca_get(agent, "/v2/account")
    if not acct:
        return None
    positions = _alpaca_get(agent, "/v2/positions") or []
    nav = float(acct.get("portfolio_value", 0) or acct.get("equity", 0))
    cash = float(acct.get("cash", 0))
    last_equity = float(acct.get("last_equity", nav))
    return {
        "nav": nav,
        "cash": cash,
        "last_equity": last_equity,
        "daily_return": round((nav - last_equity) / last_equity, 6) if last_equity > 0 else 0,
        "total_return": round((nav - starting) / starting, 6) if starting > 0 else 0,
        "positions": [
            {
                "symbol": p.get("symbol", ""),
                "qty": float(p.get("qty", 0)),
                "avg_cost": float(p.get("avg_entry_price", 0)),
                "current_price": float(p.get("current_price", 0)),
                "market_value": float(p.get("market_value", 0)),
                "unrealized_pl": float(p.get("unrealized_pl", 0)),
                "unrealized_plpc": float(p.get("unrealized_plpc", 0)),
            }
            for p in positions
        ],
        "positions_count": len(positions),
        "source": "alpaca_live",
    }


# ── Webull Integration (WEB-01 ONLY — never on CF/Medusa nodes) ───
WEBULL_APP_KEY = "a5422e29fc6f10ff77ea1b2ea170e4ff"
WEBULL_APP_SECRET = "5f22857c49ea0de8f9160b4b0db9cba2"
_webull_client = None
_webull_trade = None
_webull_cache: dict[str, tuple[float, dict]] = {}
_WEBULL_CACHE_TTL = 120  # seconds — Webull rate limits aggressively

def _get_webull_trade():
    global _webull_client, _webull_trade
    if _webull_trade is None:
        from webull.core.client import ApiClient
        from webull.trade.trade_client import TradeClient
        _webull_client = ApiClient(WEBULL_APP_KEY, WEBULL_APP_SECRET, "us")
        _webull_client.add_endpoint("us", "api.webull.com")
        _webull_trade = TradeClient(_webull_client)
    return _webull_trade


def _webull_portfolio(account_id: str, starting_cash: float) -> dict | None:
    """Fetch live NAV, cash, positions from Webull. Cached to avoid 429s."""
    import time as _time
    cache_key = account_id
    now = _time.time()
    if cache_key in _webull_cache:
        cached_at, cached_data = _webull_cache[cache_key]
        if now - cached_at < _WEBULL_CACHE_TTL:
            return cached_data
    try:
        trade = _get_webull_trade()
        bal_resp = trade.account_v2.get_account_balance(account_id)
        bal = bal_resp.json()
        pos_resp = trade.account_v2.get_account_position(account_id)
        pos_data = pos_resp.json()
        if isinstance(pos_data, dict) and "error_code" in pos_data:
            pos_data = []
    except Exception:
        if cache_key in _webull_cache:
            return _webull_cache[cache_key][1]
        return None

    nav = float(bal.get("total_net_liquidation_value", 0))
    cash = float(bal.get("total_cash_balance", 0))
    day_pl = float(bal.get("total_day_profit_loss", 0))
    total_return = round((nav - starting_cash) / starting_cash, 6) if starting_cash > 0 else 0
    daily_return = round(day_pl / (nav - day_pl), 6) if (nav - day_pl) > 0 else 0

    positions = []
    for p in (pos_data if isinstance(pos_data, list) else []):
        positions.append({
            "symbol": p.get("symbol", ""),
            "qty": float(p.get("quantity", 0)),
            "avg_cost": float(p.get("cost_price", 0)),
            "current_price": float(p.get("last_price", 0)),
            "market_value": float(p.get("market_value", 0)),
            "unrealized_pl": float(p.get("unrealized_profit_loss", 0)),
            "unrealized_plpc": float(p.get("unrealized_profit_loss_rate", 0)),
        })

    return {
        "nav": nav,
        "cash": cash,
        "daily_return": daily_return,
        "total_return": total_return,
        "day_pl": day_pl,
        "positions": positions,
        "positions_count": len(positions),
        "source": "webull_live",
    }






def _conn():
    return psycopg.connect(DB_DSN)


def _now():
    return datetime.now(timezone.utc)


def _get_price(symbol: str) -> Optional[float]:
    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
        return float(info.get("currentPrice") or info.get("regularMarketPrice") or 0) or None
    except Exception:
        return None



def _sync_webull_holdings(portfolio_id: int, account_id: str):
    """Pull positions + cash from Webull API and write into PG portfolio_holdings."""
    try:
        trade = _get_webull_trade()
        bal_resp = trade.account_v2.get_account_balance(account_id)
        bal = bal_resp.json()
        pos_resp = trade.account_v2.get_account_position(account_id)
        pos_data = pos_resp.json()
        if isinstance(pos_data, dict) and "error_code" in pos_data:
            pos_data = []
    except Exception:
        return False

    cash = float(bal.get("total_cash_balance", 0))

    with _conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE portfolios SET cash = %s WHERE id = %s", (cash, portfolio_id))
        cur.execute("DELETE FROM portfolio_holdings WHERE portfolio_id = %s", (portfolio_id,))
        for p in (pos_data if isinstance(pos_data, list) else []):
            sym = p.get("symbol", "")
            qty = float(p.get("quantity", 0))
            avg_cost = float(p.get("cost_price", 0))
            if sym and qty != 0:
                cur.execute(
                    """INSERT INTO portfolio_holdings (portfolio_id, symbol, quantity, avg_cost)
                       VALUES (%s, %s, %s, %s)""",
                    (portfolio_id, sym, qty, avg_cost),
                )
        conn.commit()
    return True


def sync_all_webull():
    """Sync all Webull portfolios — called by daily cron."""
    import json as _json
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, webull_config FROM portfolios WHERE portfolio_type = 'webull'")
        for row in cur.fetchall():
            pid, wb_config = row
            if wb_config:
                cfg = wb_config if isinstance(wb_config, dict) else _json.loads(wb_config)
                acct_id = cfg.get("account_id")
                if acct_id:
                    ok = _sync_webull_holdings(pid, acct_id)
                    print(f"Webull sync {'OK' if ok else 'FAILED'}: portfolio {pid}")



# ── Models ─────────────────────────────────────────────────────────

class PortfolioCreate(BaseModel):
    name: str
    starting_cash: float = 10000.0
    color: str = "#4A90D9"
    description: str = ""


class PortfolioUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None


class TradeRequest(BaseModel):
    symbol: str
    quantity: float
    side: str  # "buy", "sell", or "issue"
    price: Optional[float] = None  # manual price (required for "issue")


class CashRequest(BaseModel):
    amount: float
    action: str  # "deposit", "withdrawal", "transfer"
    target_portfolio_id: Optional[int] = None
    notes: str = ""


# ── Portfolio CRUD ─────────────────────────────────────────────────

@router.get("")
def list_portfolios():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, name, slug, portfolio_type, owner, starting_cash, cash,
                      color, description, created_at
               FROM portfolios ORDER BY portfolio_type, id"""
        )
        rows = []
        for r in cur.fetchall():
            rows.append({
                "id": r[0], "name": r[1], "slug": r[2], "type": r[3],
                "owner": r[4], "starting_cash": float(r[5]), "cash": float(r[6]),
                "color": r[7], "description": r[8],
                "created_at": r[9].isoformat() if r[9] else None,
            })
    return {"results": rows}


@router.get("/{portfolio_id}")
def get_portfolio(portfolio_id: int):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, name, slug, portfolio_type, owner, starting_cash, cash,
                      color, description, created_at
               FROM portfolios WHERE id = %s""",
            (portfolio_id,),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(404, "Portfolio not found")
        port = {
            "id": r[0], "name": r[1], "slug": r[2], "type": r[3],
            "owner": r[4], "starting_cash": float(r[5]), "cash": float(r[6]),
            "color": r[7], "description": r[8],
            "created_at": r[9].isoformat() if r[9] else None,
        }

        cur.execute(
            """SELECT symbol, quantity, avg_cost FROM portfolio_holdings
               WHERE portfolio_id = %s AND quantity != 0 ORDER BY symbol""",
            (portfolio_id,),
        )
        port["holdings"] = [
            {"symbol": h[0], "quantity": float(h[1]), "avg_cost": float(h[2])}
            for h in cur.fetchall()
        ]

        cur.execute(
            """SELECT id, txn_type, symbol, quantity, price, total, notes, created_at
               FROM portfolio_transactions WHERE portfolio_id = %s
               ORDER BY created_at DESC LIMIT 50""",
            (portfolio_id,),
        )
        port["transactions"] = [
            {"id": t[0], "type": t[1], "symbol": t[2],
             "quantity": float(t[3]) if t[3] else None,
             "price": float(t[4]) if t[4] else None,
             "total": float(t[5]), "notes": t[6],
             "time": t[7].isoformat() if t[7] else None}
            for t in cur.fetchall()
        ]
    return {"results": port}


@router.post("")
def create_portfolio(body: PortfolioCreate):
    slug = body.name.lower().replace(" ", "-")[:20]
    with _conn() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                """INSERT INTO portfolios (name, slug, portfolio_type, owner, starting_cash, cash, color, description)
                   VALUES (%s, %s, 'user', 'user', %s, %s, %s, %s) RETURNING id, slug""",
                (body.name, slug, body.starting_cash, body.starting_cash, body.color, body.description),
            )
            row = cur.fetchone()
            conn.commit()

            cur.execute(
                """INSERT INTO portfolio_transactions (portfolio_id, txn_type, total, notes)
                   VALUES (%s, 'deposit', %s, 'Initial funding')""",
                (row[0], body.starting_cash),
            )
            conn.commit()
            return {"results": {"id": row[0], "slug": row[1]}}
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            import uuid
            slug = f"{slug}-{uuid.uuid4().hex[:4]}"
            cur.execute(
                """INSERT INTO portfolios (name, slug, portfolio_type, owner, starting_cash, cash, color, description)
                   VALUES (%s, %s, 'user', 'user', %s, %s, %s, %s) RETURNING id, slug""",
                (body.name, slug, body.starting_cash, body.starting_cash, body.color, body.description),
            )
            row = cur.fetchone()
            conn.commit()
            cur.execute(
                """INSERT INTO portfolio_transactions (portfolio_id, txn_type, total, notes)
                   VALUES (%s, 'deposit', %s, 'Initial funding')""",
                (row[0], body.starting_cash),
            )
            conn.commit()
            return {"results": {"id": row[0], "slug": row[1]}}


@router.put("/{portfolio_id}")
def update_portfolio(portfolio_id: int, body: PortfolioUpdate):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT portfolio_type FROM portfolios WHERE id = %s", (portfolio_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Portfolio not found")
        if row[0] == "system":
            raise HTTPException(403, "Cannot edit system portfolios")

        updates, params = [], []
        if body.name is not None:
            updates.append("name = %s")
            params.append(body.name)
        if body.color is not None:
            updates.append("color = %s")
            params.append(body.color)
        if body.description is not None:
            updates.append("description = %s")
            params.append(body.description)
        if not updates:
            return {"results": "no changes"}

        updates.append("updated_at = %s")
        params.append(_now())
        params.append(portfolio_id)
        cur.execute(f"UPDATE portfolios SET {', '.join(updates)} WHERE id = %s", params)
        conn.commit()
    return {"results": "updated"}


@router.delete("/{portfolio_id}")
def delete_portfolio(portfolio_id: int):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT portfolio_type FROM portfolios WHERE id = %s", (portfolio_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Portfolio not found")
        if row[0] == "system":
            raise HTTPException(403, "Cannot delete system portfolios")
        cur.execute("DELETE FROM portfolios WHERE id = %s", (portfolio_id,))
        conn.commit()
    return {"results": "deleted"}


# ── Trade Simulation ───────────────────────────────────────────────

@router.post("/{portfolio_id}/trade")
def execute_trade(portfolio_id: int, body: TradeRequest):
    symbol = body.symbol.upper()
    qty = abs(body.quantity)
    side = body.side.lower()
    if side not in ("buy", "sell", "issue"):
        raise HTTPException(400, "Side must be 'buy', 'sell', or 'issue'")
    if qty <= 0:
        raise HTTPException(400, "Quantity must be positive")

    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT portfolio_type, cash FROM portfolios WHERE id = %s", (portfolio_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Portfolio not found")
        if row[0] == "system":
            raise HTTPException(403, "Cannot trade in system portfolios")
        cash = float(row[1])

        if side == "issue":
            if not body.price or body.price <= 0:
                raise HTTPException(400, "Issue price is required and must be positive")
            issue_price = round(body.price, 4)
            total = round(issue_price * qty, 2)

            cur.execute(
                "SELECT quantity, avg_cost FROM portfolio_holdings WHERE portfolio_id = %s AND symbol = %s",
                (portfolio_id, symbol),
            )
            existing = cur.fetchone()
            if existing:
                old_qty, old_cost = float(existing[0]), float(existing[1])
                new_qty = old_qty + qty
                new_avg = ((old_qty * old_cost) + (qty * issue_price)) / new_qty
                cur.execute(
                    "UPDATE portfolio_holdings SET quantity = %s, avg_cost = %s, updated_at = %s WHERE portfolio_id = %s AND symbol = %s",
                    (new_qty, round(new_avg, 4), _now(), portfolio_id, symbol),
                )
            else:
                cur.execute(
                    "INSERT INTO portfolio_holdings (portfolio_id, symbol, quantity, avg_cost) VALUES (%s, %s, %s, %s)",
                    (portfolio_id, symbol, qty, issue_price),
                )

            cur.execute(
                "INSERT INTO portfolio_transactions (portfolio_id, txn_type, symbol, quantity, price, total, notes) VALUES (%s, 'issue', %s, %s, %s, %s, 'Stock issued in lieu of payment')",
                (portfolio_id, symbol, qty, issue_price, total),
            )
            conn.commit()
            return {"results": {"action": "issue", "symbol": symbol, "qty": qty, "price": issue_price, "total": total, "cash_remaining": cash}}

        price = _get_price(symbol)
        if not price:
            raise HTTPException(400, f"Cannot get price for {symbol}")

        total = round(price * qty, 2)

        if side == "buy":
            if total > cash:
                raise HTTPException(400, f"Insufficient cash. Need ${total:,.2f}, have ${cash:,.2f}")

            cur.execute(
                "SELECT quantity, avg_cost FROM portfolio_holdings WHERE portfolio_id = %s AND symbol = %s",
                (portfolio_id, symbol),
            )
            existing = cur.fetchone()
            if existing:
                old_qty, old_cost = float(existing[0]), float(existing[1])
                new_qty = old_qty + qty
                new_avg = ((old_qty * old_cost) + (qty * price)) / new_qty
                cur.execute(
                    "UPDATE portfolio_holdings SET quantity = %s, avg_cost = %s, updated_at = %s WHERE portfolio_id = %s AND symbol = %s",
                    (new_qty, round(new_avg, 4), _now(), portfolio_id, symbol),
                )
            else:
                cur.execute(
                    "INSERT INTO portfolio_holdings (portfolio_id, symbol, quantity, avg_cost) VALUES (%s, %s, %s, %s)",
                    (portfolio_id, symbol, qty, round(price, 4)),
                )

            cur.execute("UPDATE portfolios SET cash = cash - %s, updated_at = %s WHERE id = %s", (total, _now(), portfolio_id))
            cur.execute(
                "INSERT INTO portfolio_transactions (portfolio_id, txn_type, symbol, quantity, price, total) VALUES (%s, 'buy', %s, %s, %s, %s)",
                (portfolio_id, symbol, qty, price, total),
            )
            conn.commit()
            return {"results": {"action": "buy", "symbol": symbol, "qty": qty, "price": price, "total": total, "cash_remaining": round(cash - total, 2)}}

        else:  # sell
            cur.execute(
                "SELECT quantity, avg_cost FROM portfolio_holdings WHERE portfolio_id = %s AND symbol = %s",
                (portfolio_id, symbol),
            )
            existing = cur.fetchone()
            if not existing or float(existing[0]) < qty:
                held = float(existing[0]) if existing else 0
                raise HTTPException(400, f"Insufficient shares. Have {held}, trying to sell {qty}")

            old_qty = float(existing[0])
            new_qty = old_qty - qty
            if new_qty == 0:
                cur.execute("DELETE FROM portfolio_holdings WHERE portfolio_id = %s AND symbol = %s", (portfolio_id, symbol))
            else:
                cur.execute(
                    "UPDATE portfolio_holdings SET quantity = %s, updated_at = %s WHERE portfolio_id = %s AND symbol = %s",
                    (new_qty, _now(), portfolio_id, symbol),
                )

            cur.execute("UPDATE portfolios SET cash = cash + %s, updated_at = %s WHERE id = %s", (total, _now(), portfolio_id))
            cur.execute(
                "INSERT INTO portfolio_transactions (portfolio_id, txn_type, symbol, quantity, price, total) VALUES (%s, 'sell', %s, %s, %s, %s)",
                (portfolio_id, symbol, qty, price, total),
            )
            conn.commit()
            realized_pl = round((price - float(existing[1])) * qty, 2)
            return {"results": {"action": "sell", "symbol": symbol, "qty": qty, "price": price, "total": total, "realized_pl": realized_pl, "cash_remaining": round(cash + total, 2)}}


# ── Cash Management ────────────────────────────────────────────────

@router.post("/{portfolio_id}/cash")
def manage_cash(portfolio_id: int, body: CashRequest):
    action = body.action.lower()
    amount = abs(body.amount)

    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT portfolio_type, cash FROM portfolios WHERE id = %s", (portfolio_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Portfolio not found")
        if row[0] == "system":
            raise HTTPException(403, "Cannot modify system portfolio cash")
        cash = float(row[1])

        if action == "deposit":
            cur.execute("UPDATE portfolios SET cash = cash + %s, updated_at = %s WHERE id = %s", (amount, _now(), portfolio_id))
            cur.execute(
                "INSERT INTO portfolio_transactions (portfolio_id, txn_type, total, notes) VALUES (%s, 'deposit', %s, %s)",
                (portfolio_id, amount, body.notes or "Cash deposit"),
            )
            conn.commit()
            return {"results": {"action": "deposit", "amount": amount, "new_cash": round(cash + amount, 2)}}

        elif action == "withdrawal":
            if amount > cash:
                raise HTTPException(400, f"Insufficient cash. Have ${cash:,.2f}")
            cur.execute("UPDATE portfolios SET cash = cash - %s, updated_at = %s WHERE id = %s", (amount, _now(), portfolio_id))
            cur.execute(
                "INSERT INTO portfolio_transactions (portfolio_id, txn_type, total, notes) VALUES (%s, 'withdrawal', %s, %s)",
                (portfolio_id, amount, body.notes or "Cash withdrawal"),
            )
            conn.commit()
            return {"results": {"action": "withdrawal", "amount": amount, "new_cash": round(cash - amount, 2)}}

        elif action == "transfer":
            if not body.target_portfolio_id:
                raise HTTPException(400, "target_portfolio_id required for transfers")
            if amount > cash:
                raise HTTPException(400, f"Insufficient cash. Have ${cash:,.2f}")

            cur.execute("SELECT portfolio_type FROM portfolios WHERE id = %s", (body.target_portfolio_id,))
            target = cur.fetchone()
            if not target:
                raise HTTPException(404, "Target portfolio not found")
            if target[0] == "system":
                raise HTTPException(403, "Cannot transfer to system portfolios")

            cur.execute("UPDATE portfolios SET cash = cash - %s, updated_at = %s WHERE id = %s", (amount, _now(), portfolio_id))
            cur.execute("UPDATE portfolios SET cash = cash + %s, updated_at = %s WHERE id = %s", (amount, _now(), body.target_portfolio_id))
            note = body.notes or f"Transfer to portfolio {body.target_portfolio_id}"
            cur.execute(
                "INSERT INTO portfolio_transactions (portfolio_id, txn_type, total, notes) VALUES (%s, 'transfer_out', %s, %s)",
                (portfolio_id, amount, note),
            )
            cur.execute(
                "INSERT INTO portfolio_transactions (portfolio_id, txn_type, total, notes) VALUES (%s, 'transfer_in', %s, %s)",
                (body.target_portfolio_id, amount, f"Transfer from portfolio {portfolio_id}"),
            )
            conn.commit()
            return {"results": {"action": "transfer", "amount": amount, "from": portfolio_id, "to": body.target_portfolio_id}}

        else:
            raise HTTPException(400, "Action must be 'deposit', 'withdrawal', or 'transfer'")


# ── Portfolio NAV (live-priced) ────────────────────────────────────

@router.get("/{portfolio_id}/nav")
def portfolio_nav(portfolio_id: int):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT cash, starting_cash, name, portfolio_type, slug FROM portfolios WHERE id = %s", (portfolio_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Portfolio not found")
        cash, starting_cash, name, ptype, slug = float(row[0]), float(row[1]), row[2], row[3], row[4]

    if ptype == "system" and slug in SLUG_TO_AGENT:
        live = _alpaca_portfolio(SLUG_TO_AGENT[slug], starting_cash)
        if live:
            return {"results": {
                "portfolio_id": portfolio_id, "name": name, "type": ptype,
                "nav": round(live["nav"], 2), "cash": round(live["cash"], 2),
                "positions_value": round(live["nav"] - live["cash"], 2),
                "starting_cash": starting_cash, "total_return": live["total_return"],
                "daily_return": live["daily_return"],
                "positions": live["positions"],
                "source": "alpaca_live",
                "as_of": _now().isoformat(),
            }}

    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, quantity, avg_cost FROM portfolio_holdings WHERE portfolio_id = %s AND quantity != 0",
            (portfolio_id,),
        )
        holdings = cur.fetchall()

    positions_value = 0.0
    position_details = []
    for h in holdings:
        sym, qty, avg = h[0], float(h[1]), float(h[2])
        price = _get_price(sym)
        if price:
            mv = round(price * qty, 2)
            upl = round((price - avg) * qty, 2)
            positions_value += mv
            position_details.append({
                "symbol": sym, "qty": qty, "avg_cost": avg,
                "current_price": price, "market_value": mv,
                "unrealized_pl": upl,
                "unrealized_plpc": round((price - avg) / avg, 4) if avg > 0 else 0,
            })

    nav = round(cash + positions_value, 2)
    total_return = round((nav - starting_cash) / starting_cash, 6) if starting_cash > 0 else 0

    return {"results": {
        "portfolio_id": portfolio_id, "name": name, "type": ptype,
        "nav": nav, "cash": cash, "positions_value": round(positions_value, 2),
        "starting_cash": starting_cash, "total_return": total_return,
        "positions": position_details,
        "source": "local",
        "as_of": _now().isoformat(),
    }}


# ── Leaderboard (all portfolios with live NAV) ────────────────────

@router.get("/all/leaderboard")
def leaderboard():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, name, slug, portfolio_type, starting_cash, cash, color
               FROM portfolios ORDER BY portfolio_type, id"""
        )
        portfolios = cur.fetchall()

        results = []
        for p in portfolios:
            pid, name, slug, ptype, starting, cash, color = p
            cash = float(cash)
            starting = float(starting)

            if ptype == "system" and slug in SLUG_TO_AGENT:
                live = _alpaca_portfolio(SLUG_TO_AGENT[slug], starting)
                if live:
                    trade_count = 0
                    try:
                        with conn.cursor() as cur2:
                            cur2.execute("SELECT COUNT(*) FROM executions WHERE agent = %s", (SLUG_TO_AGENT[slug],))
                            trade_count = cur2.fetchone()[0]
                    except Exception:
                        pass
                    results.append({
                        "id": pid, "name": name, "slug": slug, "type": ptype,
                        "color": color, "nav": round(live["nav"], 2),
                        "cash": round(live["cash"], 2),
                        "total_return": live["total_return"],
                        "daily_return": live["daily_return"],
                        "trade_count": trade_count,
                        "positions_count": live["positions_count"],
                        "source": "alpaca_live",
                    })
                    continue

            cur.execute(
                "SELECT symbol, quantity, avg_cost FROM portfolio_holdings WHERE portfolio_id = %s AND quantity != 0",
                (pid,),
            )
            holdings = cur.fetchall()

            positions_value = 0.0
            positions_count = 0
            for h in holdings:
                price = _get_price(h[0])
                if price:
                    positions_value += price * float(h[1])
                    positions_count += 1

            nav = round(cash + positions_value, 2)
            total_return = round((nav - starting) / starting, 6) if starting > 0 else 0

            cur.execute("SELECT COUNT(*) FROM portfolio_transactions WHERE portfolio_id = %s AND txn_type IN ('buy', 'sell')", (pid,))
            trade_count = cur.fetchone()[0]

            results.append({
                "id": pid, "name": name, "slug": slug, "type": ptype,
                "color": color, "nav": nav, "cash": round(cash, 2),
                "total_return": total_return, "trade_count": trade_count,
                "positions_count": positions_count,
                "source": "local",
            })

    results.sort(key=lambda x: x.get("total_return", 0), reverse=True)
    return {"results": results}

# ── Position History & Statistics ──────────────────────────────────

@router.get("/{portfolio_id}/history")
def portfolio_history(portfolio_id: int):
    """Full trading history grouped by position with statistics."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, portfolio_type, slug, starting_cash, cash FROM portfolios WHERE id = %s", (portfolio_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Portfolio not found")
        name, ptype, slug, starting_cash, pg_cash = row[0], row[1], row[2], float(row[3]), float(row[4])

    trades = []

    if ptype == "user":
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT txn_type, symbol, quantity, price, total, created_at
                   FROM portfolio_transactions WHERE portfolio_id = %s
                   AND txn_type IN ('buy', 'sell') AND symbol IS NOT NULL
                   ORDER BY created_at""",
                (portfolio_id,),
            )
            for r in cur.fetchall():
                trades.append({
                    "side": r[0].upper(), "symbol": r[1],
                    "qty": float(r[2]) if r[2] else 0,
                    "price": float(r[3]) if r[3] else 0,
                    "total": float(r[4]) if r[4] else 0,
                    "time": r[5].isoformat() if r[5] else None,
                })

    elif ptype == "system" and slug in SLUG_TO_AGENT:
        agent = SLUG_TO_AGENT[slug]
        orders = _alpaca_get(agent, "/v2/orders?status=filled&limit=500&direction=desc")
        if orders and isinstance(orders, list):
            for o in orders:
                if o.get("filled_qty") and float(o["filled_qty"]) > 0:
                    trades.append({
                        "side": o["side"].upper(), "symbol": o["symbol"],
                        "qty": float(o["filled_qty"]),
                        "price": float(o.get("filled_avg_price", 0)),
                        "total": float(o["filled_qty"]) * float(o.get("filled_avg_price", 0)),
                        "time": o.get("filled_at"),
                        "order_type": o.get("order_type"),
                    })
            trades.sort(key=lambda x: x.get("time") or "")

    elif ptype == "webull":
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT txn_type, symbol, quantity, price, total, created_at
                   FROM portfolio_transactions WHERE portfolio_id = %s
                   AND txn_type IN ('buy', 'sell') AND symbol IS NOT NULL
                   ORDER BY created_at""",
                (portfolio_id,),
            )
            for r in cur.fetchall():
                trades.append({
                    "side": r[0].upper(), "symbol": r[1],
                    "qty": float(r[2]) if r[2] else 0,
                    "price": float(r[3]) if r[3] else 0,
                    "total": float(r[4]) if r[4] else 0,
                    "time": r[5].isoformat() if r[5] else None,
                })

    # Build per-symbol position stats
    symbols = {}
    for t in trades:
        sym = t["symbol"]
        if sym not in symbols:
            symbols[sym] = {"trades": [], "total_bought_qty": 0, "total_bought_cost": 0,
                            "total_sold_qty": 0, "total_sold_proceeds": 0}
        symbols[sym]["trades"].append(t)
        if t["side"] == "BUY":
            symbols[sym]["total_bought_qty"] += t["qty"]
            symbols[sym]["total_bought_cost"] += t["total"]
        elif t["side"] == "SELL":
            symbols[sym]["total_sold_qty"] += t["qty"]
            symbols[sym]["total_sold_proceeds"] += t["total"]

    # Get current holdings for open positions
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, quantity, avg_cost FROM portfolio_holdings WHERE portfolio_id = %s AND quantity != 0",
            (portfolio_id,),
        )
        current_holdings = {r[0]: {"qty": float(r[1]), "avg_cost": float(r[2])} for r in cur.fetchall()}

    # For system portfolios, get holdings from Alpaca
    if ptype == "system" and slug in SLUG_TO_AGENT:
        positions_data = _alpaca_get(SLUG_TO_AGENT[slug], "/v2/positions")
        if positions_data and isinstance(positions_data, list):
            current_holdings = {}
            for p in positions_data:
                current_holdings[p["symbol"]] = {
                    "qty": float(p["qty"]),
                    "avg_cost": float(p["avg_entry_price"]),
                }

    positions = []
    all_symbols = set(list(symbols.keys()) + list(current_holdings.keys()))

    for sym in sorted(all_symbols):
        s = symbols.get(sym, {"trades": [], "total_bought_qty": 0, "total_bought_cost": 0,
                               "total_sold_qty": 0, "total_sold_proceeds": 0})
        holding = current_holdings.get(sym)

        current_qty = holding["qty"] if holding else 0
        avg_cost = holding["avg_cost"] if holding else (
            round(s["total_bought_cost"] / s["total_bought_qty"], 4) if s["total_bought_qty"] > 0 else 0
        )
        current_price = _get_price(sym)
        market_value = round(current_price * current_qty, 2) if current_price and current_qty else 0
        cost_basis = round(avg_cost * current_qty, 2) if current_qty else 0
        unrealized_pl = round(market_value - cost_basis, 2) if current_qty else 0
        unrealized_pct = round((current_price - avg_cost) / avg_cost, 4) if avg_cost and current_price and current_qty else 0

        realized_pl = 0.0
        if s["total_sold_qty"] > 0 and s["total_bought_qty"] > 0:
            avg_buy = s["total_bought_cost"] / s["total_bought_qty"]
            realized_pl = round(s["total_sold_proceeds"] - (avg_buy * s["total_sold_qty"]), 2)

        total_pl = round(unrealized_pl + realized_pl, 2)

        status = "OPEN" if current_qty > 0 else "CLOSED"

        positions.append({
            "symbol": sym,
            "status": status,
            "current_qty": current_qty,
            "avg_cost": avg_cost,
            "current_price": current_price,
            "market_value": market_value,
            "cost_basis": cost_basis,
            "unrealized_pl": unrealized_pl,
            "unrealized_pct": unrealized_pct,
            "realized_pl": realized_pl,
            "total_pl": total_pl,
            "total_bought_qty": s["total_bought_qty"],
            "total_bought_cost": round(s["total_bought_cost"], 2),
            "total_sold_qty": s["total_sold_qty"],
            "total_sold_proceeds": round(s["total_sold_proceeds"], 2),
            "trade_count": len(s["trades"]),
            "first_trade": s["trades"][0]["time"] if s["trades"] else None,
            "last_trade": s["trades"][-1]["time"] if s["trades"] else None,
            "trades": s["trades"],
        })

    positions.sort(key=lambda x: (0 if x["status"] == "OPEN" else 1, -abs(x["total_pl"])))

    total_unrealized = sum(p["unrealized_pl"] for p in positions)
    total_realized = sum(p["realized_pl"] for p in positions)
    total_market_value = sum(p["market_value"] for p in positions)

    return {"results": {
        "portfolio_id": portfolio_id, "name": name, "type": ptype,
        "starting_cash": float(starting_cash),
        "positions": positions,
        "summary": {
            "total_positions": len(positions),
            "open_positions": sum(1 for p in positions if p["status"] == "OPEN"),
            "closed_positions": sum(1 for p in positions if p["status"] == "CLOSED"),
            "total_trades": sum(p["trade_count"] for p in positions),
            "total_market_value": round(total_market_value, 2),
            "total_unrealized_pl": round(total_unrealized, 2),
            "total_realized_pl": round(total_realized, 2),
            "total_pl": round(total_unrealized + total_realized, 2),
        },
    }}


# ── Manual Refresh Endpoint ────────────────────────────────────────

@router.post("/{portfolio_id}/refresh")
def refresh_portfolio(portfolio_id: int):
    """Force-refresh a portfolio's live data (Alpaca or Webull)."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, portfolio_type, slug, webull_config, starting_cash FROM portfolios WHERE id = %s", (portfolio_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Portfolio not found")
        name, ptype, slug, wb_config, starting = row

    if ptype == "system" and slug in SLUG_TO_AGENT:
        live = _alpaca_portfolio(SLUG_TO_AGENT[slug])
        if live:
            return {"results": {"name": name, "source": "alpaca_live", "nav": round(live["nav"], 2), "as_of": _now().isoformat()}}
        raise HTTPException(503, "Alpaca unreachable")

    if ptype == "webull" and wb_config:
        cfg = wb_config if isinstance(wb_config, dict) else __import__('json').loads(wb_config)
        acct_id = cfg.get("account_id", "")
        if acct_id:
            ok = _sync_webull_holdings(portfolio_id, acct_id)
            if ok:
                return {"results": {"name": name, "source": "webull_synced", "nav": None, "as_of": _now().isoformat()}}
        raise HTTPException(503, "Webull unreachable")

    return {"results": {"name": name, "source": "local", "nav": None, "as_of": _now().isoformat()}}
