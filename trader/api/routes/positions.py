"""
GET /api/positions — open paper-trading positions.

Returns all currently open positions with unrealised P&L computed
against today's last-known close price (from DynamoDB or cache).
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException

from trader.api.schemas import PositionResponse, PositionsResponse
from trader.config.settings import get_settings
from trader.config.tickers import UNIVERSE
from trader.storage import postgres

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["positions"])


def _to_float(val) -> float:
    if isinstance(val, Decimal):
        return float(val)
    return float(val) if val is not None else 0.0


@router.get("/positions", response_model=PositionsResponse)
def get_positions() -> PositionsResponse:
    """
    Return all open positions as of today's trading date.
    """
    today = date.today().isoformat()
    settings = get_settings()

    cash_inr = float(settings.initial_capital_inr)
    equity_value = 0.0

    # Pull latest NAV
    try:
        nav_item = postgres.get_nav(today)
        if not nav_item:
            # Check most recent NAV in history
            history = postgres.get_nav_history()
            if history:
                nav_item = history[-1]
        if nav_item:
            cash_inr = _to_float(nav_item.get("cash_inr", settings.initial_capital_inr))
            equity_value = _to_float(nav_item.get("equity_value_inr", 0.0))
    except Exception as exc:
        logger.warning("Could not fetch NAV from PostgreSQL: %s", exc)

    positions: list[PositionResponse] = []
    try:
        open_pos_items = postgres.get_open_positions()
        for item in open_pos_items:
            sym = item.get("ticker", "")
            qty = int(item.get("qty", 0))
            if qty <= 0:
                continue

            avg_price = _to_float(item.get("avg_price", 0.0))
            current_price = _to_float(item["current_price"]) if item.get("current_price") is not None else None
            unrealized_pnl_inr = _to_float(item.get("unrealized_pnl_inr")) if item.get("unrealized_pnl_inr") is not None else None
            unrealized_pnl_pct = _to_float(item.get("unrealized_pnl_pct")) if item.get("unrealized_pnl_pct") is not None else None

            if current_price is not None and avg_price > 0 and unrealized_pnl_inr is None:
                unrealized_pnl_inr = (current_price - avg_price) * qty
                unrealized_pnl_pct = ((current_price - avg_price) / avg_price) * 100

            positions.append(
                PositionResponse(
                    ticker=sym,
                    qty=qty,
                    avg_price=avg_price,
                    days_held=int(item.get("days_held", 0)),
                    current_price=current_price,
                    unrealized_pnl_inr=unrealized_pnl_inr,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                    stop_loss_price=_to_float(item.get("stop_loss_price", 0.0)),
                    target_price=_to_float(item.get("target_price", 0.0)),
                    kill_conditions=item.get("kill_conditions", []) if isinstance(item.get("kill_conditions"), list) else [],
                    entry_date=str(item.get("entry_date", today)),
                    horizon_days=int(item.get("horizon_days", 3)),
                    sector=item.get("sector", ""),
                )
            )
    except Exception as exc:
        logger.warning("Could not fetch positions from PostgreSQL: %s", exc)

    nav_inr = cash_inr + equity_value

    return PositionsResponse(
        positions=positions,
        open_count=len(positions),
        cash_inr=cash_inr,
        equity_value_inr=equity_value,
        nav_inr=nav_inr,
    )

