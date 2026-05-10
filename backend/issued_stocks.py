"""Issued Stocks Router — Track shares received as compensation (in lieu of payment).

NOT a portfolio. No cash balance, no NAV, no leaderboard.
Tracks issue lots, sales for realized gain / tax planning, and current market value.
"""

from datetime import datetime, date, timezone
from typing import Optional

import psycopg
import yfinance as yf
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/issued-stocks")

from env_config import DB_DSN


def _get_conn():
    return psycopg.connect(DB_DSN)


def _get_price(symbol: str):
    try:
        t = yf.Ticker(symbol)
        p = t.fast_info.get("lastPrice") or t.info.get("currentPrice") or t.info.get("regularMarketPrice")
        return round(float(p), 4) if p else None
    except Exception:
        return None


# ── Pydantic models ───────────────────────────────────────────────

class LotCreate(BaseModel):
    symbol: str
    quantity: float
    issue_price: float
    issue_date: date
    notes: Optional[str] = None


class SaleCreate(BaseModel):
    lot_id: int
    quantity: float
    sale_price: float
    sale_date: date
    notes: Optional[str] = None


# ── GET / — List all lots with current market data ────────────────

@router.get("/")
def list_lots():
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, symbol, quantity, remaining_qty, issue_price, issue_date, notes, created_at
                FROM issued_stock_lots ORDER BY symbol, issue_date
            """)
            lots = cur.fetchall()

            # Get total realized gains from sales table
            cur.execute("SELECT COALESCE(SUM(realized_gain), 0) FROM issued_stock_sales")
            total_realized_gain = float(cur.fetchone()[0])

        # Group by symbol
        symbols_map: dict[str, list[dict]] = {}
        for row in lots:
            lot = {
                "id": row[0], "symbol": row[1], "quantity": row[2],
                "remaining_qty": row[3], "issue_price": row[4],
                "issue_date": str(row[5]), "notes": row[6],
                "created_at": str(row[7]),
            }
            symbols_map.setdefault(row[1], []).append(lot)

        # Fetch prices for all unique symbols
        price_cache: dict[str, Optional[float]] = {}
        for sym in symbols_map:
            price_cache[sym] = _get_price(sym)

        # Build grouped response
        by_symbol = []
        grand_cost_basis = 0.0
        grand_market_value = 0.0

        for sym, sym_lots in symbols_map.items():
            current_price = price_cache.get(sym)
            sym_cost = 0.0
            sym_market = 0.0
            enriched = []

            for lot in sym_lots:
                rem = lot["remaining_qty"]
                ip = lot["issue_price"]
                cost = rem * ip
                sym_cost += cost

                if current_price is not None:
                    cv = round(rem * current_price, 4)
                    ug = round(cv - cost, 4)
                    ug_pct = round(ug / cost, 6) if cost > 0 else 0.0
                    sym_market += cv
                else:
                    cv = None
                    ug = None
                    ug_pct = None

                enriched.append({
                    **lot,
                    "current_price": current_price,
                    "current_value": cv,
                    "unrealized_gain": ug,
                    "unrealized_gain_pct": ug_pct,
                })

            grand_cost_basis += sym_cost
            grand_market_value += sym_market

            by_symbol.append({
                "symbol": sym,
                "current_price": current_price,
                "total_remaining_qty": sum(l["remaining_qty"] for l in sym_lots),
                "total_cost_basis": round(sym_cost, 4),
                "total_market_value": round(sym_market, 4) if current_price is not None else None,
                "total_unrealized_gain": round(sym_market - sym_cost, 4) if current_price is not None else None,
                "lots": enriched,
            })

        summary = {
            "total_cost_basis": round(grand_cost_basis, 4),
            "total_market_value": round(grand_market_value, 4),
            "total_unrealized_gain": round(grand_market_value - grand_cost_basis, 4),
            "total_realized_gain": round(total_realized_gain, 4),
        }

        return {"results": {"by_symbol": by_symbol, "summary": summary,
                "timestamp": datetime.now(timezone.utc).isoformat()}}
    finally:
        conn.close()


# ── POST /lots — Add a new lot ────────────────────────────────────

@router.post("/lots")
def create_lot(body: LotCreate):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO issued_stock_lots (symbol, quantity, remaining_qty, issue_price, issue_date, notes)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, symbol, quantity, remaining_qty, issue_price, issue_date, notes, created_at
            """, (body.symbol.upper(), body.quantity, body.quantity, body.issue_price, body.issue_date, body.notes))
            row = cur.fetchone()
        conn.commit()
        return {"results": {
            "id": row[0], "symbol": row[1], "quantity": row[2],
            "remaining_qty": row[3], "issue_price": float(row[4]),
            "issue_date": str(row[5]), "notes": row[6],
            "created_at": str(row[7]),
        }}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ── DELETE /lots/{lot_id} — Delete a lot (only if no sales) ──────

@router.delete("/lots/{lot_id}")
def delete_lot(lot_id: int):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM issued_stock_sales WHERE lot_id = %s", (lot_id,))
            if cur.fetchone()[0] > 0:
                raise HTTPException(status_code=409, detail="Cannot delete lot with existing sales. Delete sales first.")
            cur.execute("DELETE FROM issued_stock_lots WHERE id = %s RETURNING id", (lot_id,))
            deleted = cur.fetchone()
            if not deleted:
                raise HTTPException(status_code=404, detail="Lot not found")
        conn.commit()
        return {"results": {"deleted": lot_id}}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ── POST /sales — Record a sale ───────────────────────────────────

@router.post("/sales")
def create_sale(body: SaleCreate):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            # Fetch the lot
            cur.execute("""
                SELECT id, symbol, remaining_qty, issue_price, issue_date
                FROM issued_stock_lots WHERE id = %s
            """, (body.lot_id,))
            lot = cur.fetchone()
            if not lot:
                raise HTTPException(status_code=404, detail="Lot not found")

            lot_id, symbol, remaining_qty, issue_price, issue_date = lot

            if body.quantity > remaining_qty:
                raise HTTPException(status_code=400,
                    detail=f"Sale quantity ({body.quantity}) exceeds remaining ({remaining_qty})")

            cost_basis = round(issue_price * body.quantity, 4)
            proceeds = round(body.sale_price * body.quantity, 4)
            realized_gain = round(proceeds - cost_basis, 4)
            days_held = (body.sale_date - issue_date).days
            holding_period = "long" if days_held >= 365 else "short"

            cur.execute("""
                INSERT INTO issued_stock_sales
                    (lot_id, symbol, quantity, sale_price, sale_date, cost_basis, proceeds, realized_gain, holding_period, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, lot_id, symbol, quantity, sale_price, sale_date, cost_basis, proceeds, realized_gain, holding_period, notes, created_at
            """, (lot_id, symbol, body.quantity, body.sale_price, body.sale_date,
                  cost_basis, proceeds, realized_gain, holding_period, body.notes))
            sale_row = cur.fetchone()

            # Decrement remaining_qty
            cur.execute("""
                UPDATE issued_stock_lots SET remaining_qty = remaining_qty - %s WHERE id = %s
            """, (body.quantity, lot_id))

        conn.commit()
        return {"results": {
            "id": sale_row[0], "lot_id": sale_row[1], "symbol": sale_row[2],
            "quantity": float(sale_row[3]), "sale_price": float(sale_row[4]),
            "sale_date": str(sale_row[5]), "cost_basis": float(sale_row[6]),
            "proceeds": float(sale_row[7]), "realized_gain": float(sale_row[8]),
            "holding_period": sale_row[9], "notes": sale_row[10],
            "created_at": str(sale_row[11]),
            "days_held": days_held,
        }}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ── GET /sales — List all sales ───────────────────────────────────

@router.get("/sales")
def list_sales(symbol: Optional[str] = Query(None)):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            if symbol:
                cur.execute("""
                    SELECT id, lot_id, symbol, quantity, sale_price, sale_date, cost_basis,
                           proceeds, realized_gain, holding_period, notes, created_at
                    FROM issued_stock_sales WHERE symbol = %s ORDER BY sale_date
                """, (symbol.upper(),))
            else:
                cur.execute("""
                    SELECT id, lot_id, symbol, quantity, sale_price, sale_date, cost_basis,
                           proceeds, realized_gain, holding_period, notes, created_at
                    FROM issued_stock_sales ORDER BY sale_date
                """)
            rows = cur.fetchall()

        sales = []
        by_year: dict[int, list[dict]] = {}
        total_short = 0.0
        total_long = 0.0
        total_proceeds = 0.0
        total_cost = 0.0

        for r in rows:
            sale = {
                "id": r[0], "lot_id": r[1], "symbol": r[2], "quantity": r[3],
                "sale_price": r[4], "sale_date": str(r[5]), "cost_basis": r[6],
                "proceeds": r[7], "realized_gain": r[8], "holding_period": r[9],
                "notes": r[10], "created_at": str(r[11]),
            }
            sales.append(sale)
            year = r[5].year
            by_year.setdefault(year, []).append(sale)

            if r[9] == "short":
                total_short += r[8]
            else:
                total_long += r[8]
            total_proceeds += r[7]
            total_cost += r[6]

        tax_summary = {
            "total_short_term_gains": round(total_short, 4),
            "total_long_term_gains": round(total_long, 4),
            "total_proceeds": round(total_proceeds, 4),
            "total_cost_basis": round(total_cost, 4),
        }

        grouped = {str(y): lst for y, lst in sorted(by_year.items())}

        return {"results": {"sales": sales, "by_year": grouped, "tax_summary": tax_summary,
                "timestamp": datetime.now(timezone.utc).isoformat()}}
    finally:
        conn.close()


# ── GET /tax-summary — Tax planning view ─────────────────────────

@router.get("/tax-summary")
def tax_summary(year: Optional[int] = Query(None)):
    if year is None:
        year = datetime.now().year

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT symbol, quantity, sale_price, cost_basis, proceeds, realized_gain, holding_period, sale_date
                FROM issued_stock_sales
                WHERE EXTRACT(YEAR FROM sale_date) = %s
                ORDER BY symbol, sale_date
            """, (year,))
            rows = cur.fetchall()

        total_short = 0.0
        total_long = 0.0
        per_symbol: dict[str, dict] = {}

        for r in rows:
            sym, qty, sp, cb, proc, rg, hp, sd = r
            if hp == "short":
                total_short += rg
            else:
                total_long += rg

            if sym not in per_symbol:
                per_symbol[sym] = {"short_term": 0.0, "long_term": 0.0,
                                   "total_proceeds": 0.0, "total_cost_basis": 0.0, "sale_count": 0}
            entry = per_symbol[sym]
            if hp == "short":
                entry["short_term"] += rg
            else:
                entry["long_term"] += rg
            entry["total_proceeds"] += proc
            entry["total_cost_basis"] += cb
            entry["sale_count"] += 1

        # Round per-symbol values
        for sym in per_symbol:
            for k in ("short_term", "long_term", "total_proceeds", "total_cost_basis"):
                per_symbol[sym][k] = round(per_symbol[sym][k], 4)

        return {"results": {
            "year": year,
            "short_term_total": round(total_short, 4),
            "long_term_total": round(total_long, 4),
            "combined_total": round(total_short + total_long, 4),
            "per_symbol": per_symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }}
    finally:
        conn.close()
