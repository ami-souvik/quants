"""
GET /api/health — system health check.

Returns the last daily-run timestamp, paper-trading mode flag, circuit-breaker
status, and today's LLM cost. Used by the dashboard status bar and external
uptime monitors.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter

from trader.api.schemas import HealthResponse
from trader.config.settings import get_settings
from trader.storage import postgres

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """
    Returns system health status.

    Checks PostgreSQL for today's NAV item to determine whether the daily run
    has completed. Does NOT raise exceptions on database failures.
    """
    settings = get_settings()
    today = date.today().isoformat()
    last_run: str | None = None
    daily_llm_cost: float = 0.0
    circuit_breakers: list[str] = []

    try:
        nav_item = postgres.get_nav(today)
        if not nav_item:
            history = postgres.get_nav_history()
            if history:
                nav_item = history[-1]
        if nav_item:
            last_run = str(nav_item.get("created_at") or nav_item.get("date") or today)
            daily_llm_cost = float(nav_item.get("total_llm_cost_usd_today", 0.0))

            drawdown = float(nav_item.get("drawdown_pct", 0.0))
            if drawdown <= -settings.circuit_breaker_drawdown * 100:
                circuit_breakers.append("DRAWDOWN")
            if daily_llm_cost > settings.daily_llm_budget_usd:
                circuit_breakers.append("LLM_COST")
    except Exception as exc:
        logger.warning("Health check: PostgreSQL unavailable — %s", exc)

    return HealthResponse(
        status="OK",
        last_run=last_run,
        paper_mode=settings.paper_trading_mode,
        circuit_breakers_active=circuit_breakers,
        daily_llm_cost_usd=daily_llm_cost,
        environment=settings.environment,
    )
