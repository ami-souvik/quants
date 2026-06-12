"""
GET /api/report — retrieve the comprehensive daily run report.

Returns the full structured report stored after each daily run, including:
  - Run summary (NAV, cost, decisions made, duration)
  - Macro context (Nifty, FII/DII, RBI rate, USD/INR)
  - Per-ticker detail: all 5 agent outputs, errors, fill, token costs
  - Run-level errors (infra failures)

Query params:
  date  — yyyy-mm-dd (default: today in IST)
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from trader.api.schemas import DailyReportResponse
from trader.storage.report import get_report

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(prefix="/api", tags=["report"])


def _coerce(obj):
    """Recursively convert Decimal → float so Pydantic validation works."""
    from decimal import Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _coerce(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce(v) for v in obj]
    return obj


@router.get("/report", response_model=DailyReportResponse)
def get_daily_report(
    date: str | None = Query(default=None, description="yyyy-mm-dd (default: today IST)"),
) -> DailyReportResponse:
    """
    Returns the comprehensive daily run report for the given date.
    Returns 404 if no report exists yet for that date.
    """
    date_str = date or datetime.now(IST).date().isoformat()

    try:
        item = get_report(date_str)
    except Exception as exc:
        logger.error("DynamoDB error fetching report for %s: %s", date_str, exc)
        raise HTTPException(status_code=503, detail=f"Database error: {exc}")

    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"No report found for {date_str}. The daily run may not have completed yet.",
        )

    item = _coerce(item)

    # Normalise tokens_used per ticker: DynamoDB stores it as-is; coerce to model fields
    for t in item.get("tickers", []):
        raw_tokens = t.get("tokens_used") or {}
        normalised: dict = {}
        for agent, val in raw_tokens.items():
            if isinstance(val, dict):
                normalised[agent] = {
                    "input_tokens":  int(val.get("input", val.get("input_tokens", 0))),
                    "output_tokens": int(val.get("output", val.get("output_tokens", 0))),
                    "cost_usd":      float(val.get("cost_usd", 0.0)),
                }
        t["tokens_used"] = normalised

    try:
        return DailyReportResponse(**item)
    except Exception as exc:
        logger.error("Schema coercion failed for report %s: %s", date_str, exc)
        raise HTTPException(status_code=500, detail=f"Report schema error: {exc}")
