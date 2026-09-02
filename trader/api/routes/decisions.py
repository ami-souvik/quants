"""
GET /api/decisions — daily agent decision log.

Returns all agent decisions for a given trading date, including per-agent
outputs (news, technical, fundamentals, bull-bear debate, portfolio manager)
and the simulated fill that resulted from the PM decision.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Query

from trader.api.schemas import (
    AgentDecisionDetail,
    DecisionResponse,
    DecisionsResponse,
    SimulatedFillResponse,
)
from trader.config.tickers import UNIVERSE
from trader.storage import postgres

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["decisions"])

_AGENT_ORDER = [
    "NewsSentiment",
    "Technical",
    "Fundamentals",
    "BullBear",
    "PortfolioManager",
]


def _to_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _to_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _parse_agent_detail(item: dict) -> AgentDecisionDetail:
    """Convert a decision item dict into AgentDecisionDetail."""
    agent_name = item.get("agent")
    if not agent_name and "SK" in item:
        parts = item.get("SK", "").split("#")
        agent_name = parts[3] if len(parts) >= 4 else "Unknown"
    agent_name = agent_name or "Unknown"

    full = item.get("full_output") or {}

    return AgentDecisionDetail(
        agent=agent_name,
        model=item.get("model"),
        # News
        sentiment_score=_to_float(item.get("sentiment_score") or full.get("sentiment_score")),
        sentiment_label=item.get("sentiment_label") or full.get("sentiment_label"),
        key_events=item.get("key_events") or full.get("key_events") or [],
        data_quality=item.get("data_quality") or full.get("data_quality"),
        # Technical
        technical_signal=item.get("technical_signal") or full.get("technical_signal"),
        trend=item.get("trend") or full.get("trend"),
        momentum=item.get("momentum") or full.get("momentum"),
        volume_signal=item.get("volume_signal") or full.get("volume_signal"),
        suggested_stop_loss_pct=_to_float(item.get("suggested_stop_loss_pct") or full.get("suggested_stop_loss_pct")),
        suggested_target_pct=_to_float(item.get("suggested_target_pct") or full.get("suggested_target_pct")),
        # Fundamentals
        fundamental_bias=item.get("fundamental_bias") or full.get("fundamental_bias"),
        valuation=item.get("valuation") or full.get("valuation"),
        institutional_flow=item.get("institutional_flow") or full.get("institutional_flow"),
        macro_tailwind=item.get("macro_tailwind") or full.get("macro_tailwind"),
        red_flags=item.get("red_flags") or full.get("red_flags") or [],
        data_staleness_days=_to_int(item.get("data_staleness_days") or full.get("data_staleness_days")),
        # Bull-bear
        bull_thesis=item.get("bull_thesis") or full.get("bull_thesis") or [],
        bear_thesis=item.get("bear_thesis") or full.get("bear_thesis") or [],
        debate_winner=item.get("debate_winner") or full.get("debate_winner"),
        conviction_delta=_to_float(item.get("conviction_delta") or full.get("conviction_delta")),
        key_risk=item.get("key_risk") or full.get("key_risk"),
        # PM
        decision=item.get("decision") or full.get("decision"),
        quantity_shares=_to_int(item.get("quantity_shares") or full.get("quantity_shares")),
        estimated_trade_value_inr=_to_float(item.get("estimated_trade_value_inr") or full.get("estimated_trade_value_inr")),
        horizon_days=_to_int(item.get("horizon_days") or full.get("horizon_days")),
        target_price=_to_float(item.get("target_price") or full.get("target_price")),
        stop_loss_price=_to_float(item.get("stop_loss_price") or full.get("stop_loss_price")),
        primary_thesis=item.get("primary_thesis") or full.get("primary_thesis") or item.get("reasoning"),
        agent_agreement=item.get("agent_agreement") or full.get("agent_agreement"),
        estimated_cost_bps=_to_float(item.get("estimated_cost_bps") or full.get("estimated_cost_bps")),
        risk_reward_ratio=_to_float(item.get("risk_reward_ratio") or full.get("risk_reward_ratio")),
        # Common
        confidence=_to_float(item.get("confidence") or full.get("confidence")),
        reasoning=item.get("reasoning") or full.get("reasoning") or full.get("primary_thesis"),
        input_tokens=_to_int(item.get("input_tokens")),
        output_tokens=_to_int(item.get("output_tokens")),
        cost_usd=_to_float(item.get("cost_usd")),
        schema_valid=item.get("schema_valid"),
        retry_count=_to_int(item.get("retry_count")),
    )


def _parse_fill(item: dict) -> SimulatedFillResponse | None:
    """Parse a TRADE item into SimulatedFillResponse."""
    if not item:
        return None
    return SimulatedFillResponse(
        side=item.get("side", ""),
        qty=_to_int(item.get("qty")) or 0,
        fill_price=_to_float(item.get("price") or item.get("fill_price")) or 0.0,
        trade_value_inr=_to_float(item.get("trade_value_inr")) or 0.0,
        simulated_cost_inr=_to_float(item.get("cost_inr") or item.get("simulated_cost_inr")) or 0.0,
        simulated_cost_bps=_to_float(item.get("cost_bps") or item.get("simulated_cost_bps")) or 0.0,
        slippage_bps=_to_float(item.get("slippage_bps")) or 0.0,
    )


@router.get("/decisions", response_model=DecisionsResponse)
def get_decisions(
    date: str = Query(
        default=None,
        description="Trading date in yyyy-mm-dd format. Defaults to today.",
    )
) -> DecisionsResponse:
    """
    Return all agent decisions for a trading date from PostgreSQL.
    """
    if date is None:
        from datetime import date as _date
        date = _date.today().isoformat()

    # Fetch all decisions for this date
    try:
        raw_decisions = postgres.get_decisions_for_date(date)
    except Exception as exc:
        logger.error("Failed to fetch decisions for %s: %s", date, exc)
        raw_decisions = []

    # Fetch all trades for this date
    try:
        trade_items = postgres.get_trades_for_date(date)
    except Exception as exc:
        logger.warning("Failed to fetch trades for %s: %s", date, exc)
        trade_items = []

    # Build ticker → trade map
    ticker_trade: dict[str, dict] = {}
    for trade in trade_items:
        sym = trade.get("ticker", "")
        if sym:
            ticker_trade[sym] = trade

    # Group decisions by ticker
    ticker_agents: dict[str, list[dict]] = {}
    for item in raw_decisions:
        sym = item.get("ticker", "")
        if not sym and "SK" in item:
            parts = item["SK"].split("#")
            if len(parts) >= 2:
                sym = parts[1]
        if sym:
            ticker_agents.setdefault(sym, []).append(item)

    decisions: list[DecisionResponse] = []

    for sym in sorted(ticker_agents.keys()):
        agent_items = ticker_agents[sym]

        pm_item: dict | None = None
        for item in agent_items:
            agent_name = item.get("agent") or item.get("SK", "")
            if "PortfolioManager" in agent_name:
                pm_item = item
                break

        agent_detail_map: dict[str, AgentDecisionDetail] = {}
        for item in agent_items:
            detail = _parse_agent_detail(item)
            agent_detail_map[detail.agent] = detail

        ordered_agents = [
            agent_detail_map[a]
            for a in _AGENT_ORDER
            if a in agent_detail_map
        ]
        for a, detail in agent_detail_map.items():
            if a not in _AGENT_ORDER:
                ordered_agents.append(detail)

        fill = _parse_fill(ticker_trade.get(sym, {}))
        if fill and fill.qty == 0:
            fill = None

        decisions.append(
            DecisionResponse(
                ticker=sym,
                date=date,
                pm_decision=pm_item.get("decision") if pm_item else None,
                pm_confidence=_to_float(pm_item.get("confidence")) if pm_item else None,
                pm_reasoning=pm_item.get("primary_thesis") or pm_item.get("reasoning") if pm_item else None,
                agent_agreement=pm_item.get("agent_agreement") if pm_item else None,
                news_sentiment=agent_detail_map.get("NewsSentiment", AgentDecisionDetail(agent="NewsSentiment")).sentiment_label,
                technical_signal=agent_detail_map.get("Technical", AgentDecisionDetail(agent="Technical")).technical_signal,
                fundamental_bias=agent_detail_map.get("Fundamentals", AgentDecisionDetail(agent="Fundamentals")).fundamental_bias,
                debate_winner=agent_detail_map.get("BullBear", AgentDecisionDetail(agent="BullBear")).debate_winner,
                estimated_cost_bps=_to_float(pm_item.get("estimated_cost_bps")) if pm_item else None,
                risk_reward_ratio=_to_float(pm_item.get("risk_reward_ratio")) if pm_item else None,
                skip_reason=pm_item.get("skip_reason") or pm_item.get("decision_rationale") if pm_item else None,
                actual_fill=fill,
                agents=ordered_agents,
            )
        )

    return DecisionsResponse(date=date, decisions=decisions, total=len(decisions))

