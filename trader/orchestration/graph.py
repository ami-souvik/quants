"""
LangGraph StateGraph for the per-ticker agent pipeline.

Graph flow (per ticker):
  START
    → check_restrictions  (ASM/GSM/T2T?)
    → check_entry_cutoff  (current time > 11:00 IST?)
    → check_quiet         (no news + small move?)
    → news_sentiment
    → technical
    → fundamentals
    → bull_bear
    → portfolio_manager   (with circuit-breaker enforcement)
    → cost_guard          (alert if daily LLM budget exceeded)
    → ledger_execute      (simulate fill, update positions)
    → persist_dynamo      (write decisions + trades to DynamoDB)
    → archive_s3          (save prompt/output blobs)
  END

Agents are module-level singletons (instantiated once, reused for all 15 tickers).
The PaperTradingLedger is injected at graph-build time via closure.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from langgraph.graph import END, START, StateGraph

from trader.agents.bull_bear import BullBearAgent
from trader.agents.fundamentals import FundamentalsAgent
from trader.agents.models import TokenUsage, pm_skip_fallback
from trader.agents.news_sentiment import NewsSentimentAgent
from trader.agents.portfolio_manager import PortfolioManagerAgent
from trader.agents.technical import TechnicalAgent
from trader.ingestion.news import get_news_window_tag
from trader.ledger.circuit_breaker import enforce_decision
from trader.orchestration.state import TickerState

if TYPE_CHECKING:
    from trader.ledger.paper_trade import PaperTradingLedger

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# 30-day TTL (seconds) for DynamoDB items
_TTL_SECONDS = 30 * 24 * 3600


# ── Agent singletons ───────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _agents() -> tuple:
    """Lazy-init all 5 agents once; reused across all ticker runs."""
    return (
        NewsSentimentAgent(),
        TechnicalAgent(),
        FundamentalsAgent(),
        BullBearAgent(),
        PortfolioManagerAgent(),
    )


def _ttl() -> int:
    return int(time.time()) + _TTL_SECONDS


# ── Node functions (pure — no ledger dependency) ───────────────────────────────

def check_restrictions_node(state: dict) -> dict:
    if state.get("is_restricted"):
        logger.info("[%s] RESTRICTED — skipping pipeline", state["ticker"])
        return {"skip_reason": "RESTRICTED"}
    return {}


def check_entry_cutoff_node(state: dict) -> dict:
    """Skip new entries if the 11:00 IST entry window has closed."""
    if state.get("entry_cutoff_passed"):
        logger.info("[%s] TIME_CUTOFF — entry window closed (>11:00 IST)", state["ticker"])
        return {"skip_reason": "TIME_CUTOFF"}
    return {}


def check_quiet_node(state: dict) -> dict:
    """Skip the full pipeline when there is no signal to act on."""
    news_count = len(state.get("news_articles", []))
    mdata = state.get("market_data", {})
    pct_1d = abs(mdata.get("pct_change_1d") or 0.0)
    has_corp = bool(state.get("corporate_actions"))
    if news_count == 0 and pct_1d < 1.5 and not has_corp:
        logger.info("[%s] QUIET_SKIP (news=0, |Δ1d|=%.2f%%, no corp)", state["ticker"], pct_1d)
        return {"skip_reason": "QUIET"}
    return {}


def news_sentiment_node(state: dict) -> dict:
    ticker = state["ticker"]
    mdata = state.get("market_data", {})
    now_ist = datetime.now(IST)
    news_window = get_news_window_tag(now_ist)

    news_agent, *_ = _agents()
    t0 = time.time()
    output, usage, valid = news_agent.run(
        ticker=ticker,
        company_name=state["company_name"],
        sector=state["sector"],
        news_articles=state.get("news_articles", []),
        corporate_announcements=state.get("corporate_actions", []),
        close_price=mdata.get("close_price", 0.0),
        pct_1d=mdata.get("pct_change_1d", 0.0),
        news_window_tag=news_window,
    )
    elapsed = int((time.time() - t0) * 1000)

    tokens_used = dict(state.get("tokens_used", {}))
    tokens_used["news_sentiment"] = usage.model_dump()
    errors = list(state.get("errors", []))
    if not valid:
        errors.append(f"{ticker}:news_sentiment schema invalid")

    return {
        "news_output": output.model_dump() if output else None,
        "tokens_used": tokens_used,
        "errors": errors,
        "processing_time_ms": state.get("processing_time_ms", 0) + elapsed,
    }


def technical_node(state: dict) -> dict:
    ticker = state["ticker"]
    mdata = state.get("market_data", {})
    _, tech_agent, *_ = _agents()
    t0 = time.time()

    indicators = {k: mdata.get(k) for k in [
        "rsi_14", "sma_5", "sma_20", "sma_50",
        "ema_12", "ema_26", "macd", "macd_signal",
        "bb_upper", "bb_mid", "bb_lower",
        "atr_14", "adx_14", "vwap_today",
        "pct_change_1d", "pct_change_5d", "pct_change_20d",
        "volume_ratio",
    ]}
    last_5d = mdata.get("last_5d_ohlcv", [])

    output, usage, valid = tech_agent.run(
        ticker=ticker,
        company_name=state["company_name"],
        indicators=indicators,
        last_5d_ohlcv=last_5d,
        current_position=state.get("current_position", {}),
    )
    elapsed = int((time.time() - t0) * 1000)

    tokens_used = dict(state.get("tokens_used", {}))
    tokens_used["technical"] = usage.model_dump()
    errors = list(state.get("errors", []))
    if not valid:
        errors.append(f"{ticker}:technical schema invalid")

    return {
        "technical_output": output.model_dump() if output else None,
        "tokens_used": tokens_used,
        "errors": errors,
        "processing_time_ms": state.get("processing_time_ms", 0) + elapsed,
    }


def fundamentals_node(state: dict) -> dict:
    ticker = state["ticker"]
    mdata = state.get("market_data", {})
    _, _, fund_agent, *_ = _agents()
    t0 = time.time()

    macro_context = mdata.get("macro_context", {})
    known_fundamentals = mdata.get("known_fundamentals", {})

    # Build sector context from news: concatenate titles of news items tagged for fundamentals
    sector_context = "; ".join(
        a.get("title", "") for a in state.get("news_articles", [])[:3]
    ) or "No sector news available."

    output, usage, valid = fund_agent.run(
        ticker=ticker,
        company_name=state["company_name"],
        sector=state["sector"],
        sector_context=sector_context,
        fii_dii_flows=state.get("fii_dii", {}),
        macro_context=macro_context,
        known_fundamentals=known_fundamentals,
    )
    elapsed = int((time.time() - t0) * 1000)

    tokens_used = dict(state.get("tokens_used", {}))
    tokens_used["fundamentals"] = usage.model_dump()
    errors = list(state.get("errors", []))
    if not valid:
        errors.append(f"{ticker}:fundamentals schema invalid")

    return {
        "fundamentals_output": output.model_dump() if output else None,
        "tokens_used": tokens_used,
        "errors": errors,
        "processing_time_ms": state.get("processing_time_ms", 0) + elapsed,
    }


def bull_bear_node(state: dict) -> dict:
    ticker = state["ticker"]
    _, _, _, bb_agent, _ = _agents()
    t0 = time.time()

    output, usage, valid = bb_agent.run(
        ticker=ticker,
        news_agent_output=state.get("news_output") or {},
        technical_agent_output=state.get("technical_output") or {},
        fundamentals_agent_output=state.get("fundamentals_output") or {},
    )
    elapsed = int((time.time() - t0) * 1000)

    tokens_used = dict(state.get("tokens_used", {}))
    tokens_used["bull_bear"] = usage.model_dump()
    errors = list(state.get("errors", []))
    if not valid:
        errors.append(f"{ticker}:bull_bear schema invalid")

    return {
        "bull_bear_output": output.model_dump() if output else None,
        "tokens_used": tokens_used,
        "errors": errors,
        "processing_time_ms": state.get("processing_time_ms", 0) + elapsed,
    }


def _build_pm_node(ledger: "PaperTradingLedger", daily_cost_ref: list[float]):
    """
    Closure that captures the ledger so the PM node can check circuit breakers.
    daily_cost_ref is a one-element list [total_cost_usd]; mutated by the runner.
    """
    def portfolio_manager_node(state: dict) -> dict:
        ticker = state["ticker"]
        _, _, _, _, pm_agent = _agents()
        t0 = time.time()

        snapshot = state.get("portfolio_snapshot", {})
        pos = state.get("current_position", {})

        # Check circuit breakers before calling the LLM
        cb_status = ledger.check_circuit_breakers(
            ticker=ticker,
            is_restricted=state.get("is_restricted", False),
            daily_llm_cost_usd=daily_cost_ref[0],
        )

        max_pos_value = ledger._settings.initial_capital_inr * ledger._settings.max_position_pct

        pm_output, usage, valid = pm_agent.run(
            ticker=ticker,
            news_agent_output=state.get("news_output") or {},
            technical_agent_output=state.get("technical_output") or {},
            fundamentals_agent_output=state.get("fundamentals_output") or {},
            bull_bear_output=state.get("bull_bear_output") or {},
            cash_available=snapshot.get("cash_inr", 0.0),
            open_positions_count=snapshot.get("open_positions", 0),
            position_qty=pos.get("qty", 0),
            avg_price=pos.get("avg_price", 0.0),
            drawdown_pct=snapshot.get("drawdown_pct", 0.0),
            nav=snapshot.get("nav_inr", 0.0),
            max_position_value=max_pos_value,
            is_restricted=state.get("is_restricted", False),
        )

        # Enforce circuit breakers on the LLM's decision
        enforced_decision, rationale = enforce_decision(pm_output.decision, cb_status)
        if enforced_decision != pm_output.decision:
            logger.warning(
                "[%s] Circuit breaker override: %s → %s (%s)",
                ticker, pm_output.decision, enforced_decision, rationale,
            )
            pm_output = pm_output.model_copy(update={
                "decision": enforced_decision,
                "skip_reason": rationale,
                "quantity_shares": 0 if enforced_decision == "SKIP" else pm_output.quantity_shares,
            })

        elapsed = int((time.time() - t0) * 1000)

        # Update running LLM cost
        daily_cost_ref[0] += usage.cost_usd

        tokens_used = dict(state.get("tokens_used", {}))
        tokens_used["portfolio_manager"] = usage.model_dump()
        errors = list(state.get("errors", []))
        if not valid:
            errors.append(f"{ticker}:portfolio_manager schema invalid")

        return {
            "pm_output": pm_output.model_dump(),
            "tokens_used": tokens_used,
            "errors": errors,
            "processing_time_ms": state.get("processing_time_ms", 0) + elapsed,
        }

    return portfolio_manager_node


def cost_guard_node(state: dict) -> dict:
    """Log a warning if daily LLM spend is over budget. No blocking action — just alerting."""
    from trader.config.settings import get_settings
    settings = get_settings()
    total_cost = sum(
        v.get("cost_usd", 0.0) for v in state.get("tokens_used", {}).values()
    )
    if total_cost > settings.daily_llm_budget_usd:
        logger.warning(
            "[cost_guard] Daily LLM budget exceeded: $%.4f > $%.2f",
            total_cost, settings.daily_llm_budget_usd,
        )
    return {}


def _build_ledger_execute_node(ledger: "PaperTradingLedger"):
    def ledger_execute_node(state: dict) -> dict:
        ticker = state["ticker"]
        pm = state.get("pm_output")
        if not pm:
            logger.info("[%s] No PM output — skipping fill", ticker)
            return {"simulated_fill": None}

        decision = pm.get("decision", "SKIP")
        mdata = state.get("market_data", {})
        close_price = mdata.get("close_price", 0.0)

        if decision != "BUY" or close_price <= 0:
            return {"simulated_fill": None}

        fill = ledger.simulate_fill(
            ticker=ticker,
            decision=decision,
            quantity_shares=pm.get("quantity_shares", 0),
            close_price=close_price,
            stop_loss_price=pm.get("stop_loss_price", 0.0),
            target_price=pm.get("target_price", 0.0),
        )

        if fill:
            ledger.open_intraday_position(fill)
            return {"simulated_fill": fill.as_dict()}

        return {"simulated_fill": None}

    return ledger_execute_node


def _build_persist_dynamo_node(date_str: str):
    def persist_dynamo_node(state: dict) -> dict:
        from trader.config.settings import get_settings
        from trader.storage import dynamo

        settings = get_settings()
        ticker = state["ticker"]
        ttl = _ttl()

        skip_reason = state.get("skip_reason")
        pm = state.get("pm_output")

        # Write DECISION items for each agent that ran
        agent_outputs = {
            "NewsSentiment": state.get("news_output"),
            "Technical": state.get("technical_output"),
            "Fundamentals": state.get("fundamentals_output"),
            "BullBear": state.get("bull_bear_output"),
            "PortfolioManager": pm,
        }

        for agent_name, output in agent_outputs.items():
            if output is None and skip_reason:
                # For skips, write a minimal placeholder for PortfolioManager only
                if agent_name != "PortfolioManager":
                    continue
                output = {
                    "decision": "SKIP",
                    "skip_reason": skip_reason,
                    "confidence": 0.0,
                    "primary_thesis": f"Skipped: {skip_reason}",
                }

            if output is None:
                continue

            usage = state.get("tokens_used", {}).get(agent_name.lower().replace(" ", "_"), {})
            item = {
                "PK": f"DATE#{date_str}",
                "SK": f"TICKER#{ticker}#AGENT#{agent_name}",
                "ticker": ticker,
                "decision": output.get("decision", ""),
                "confidence": output.get("confidence", 0.0),
                "reasoning": output.get("reasoning") or output.get("primary_thesis", ""),
                "full_output": output,
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cost_usd": usage.get("cost_usd", 0.0),
                "model": usage.get("model", ""),
                "schema_valid": len(state.get("errors", [])) == 0,
                "retry_count": 0,
                "skip_reason": skip_reason or "",
                "ttl": ttl,
            }
            try:
                dynamo.put_decision(item)
            except Exception as e:
                logger.error("[%s] DynamoDB put_decision failed for %s: %s", ticker, agent_name, e)

        # Write TRADE item if there was a fill
        fill = state.get("simulated_fill")
        if fill:
            import uuid
            trade_item = {
                "PK": f"DATE#{date_str}",
                "SK": f"TRADE#{fill.get('trade_id', str(uuid.uuid4()))}",
                "ticker": ticker,
                "side": fill.get("side", ""),
                "qty": fill.get("qty", 0),
                "fill_price": fill.get("fill_price", 0.0),
                "trade_value_inr": fill.get("trade_value_inr", 0.0),
                "simulated_cost_inr": fill.get("total_cost_inr", 0.0),
                "simulated_cost_bps": fill.get("cost_bps", 0.0),
                "slippage_bps": 3.0,
                "product_type": "MIS",
                "ttl": ttl,
            }
            try:
                dynamo.put_trade(trade_item)
            except Exception as e:
                logger.error("[%s] DynamoDB put_trade failed: %s", ticker, e)

        return {}

    return persist_dynamo_node


def archive_s3_node(state: dict) -> dict:
    """Archive PM prompt/output blobs to S3 (best-effort; pipeline continues on failure)."""
    from trader.config.settings import get_settings
    settings = get_settings()
    if settings.dry_run:
        return {}

    ticker = state["ticker"]
    pm = state.get("pm_output")
    if not pm:
        return {}

    try:
        import json
        from trader.storage.s3 import upload_bytes

        date_str = datetime.now(IST).date().isoformat()
        key = f"decisions/{date_str}/{ticker}/pm_output.json"
        upload_bytes(key, json.dumps(pm, default=str).encode(), content_type="application/json")
    except Exception as e:
        logger.warning("[%s] S3 archive failed (non-fatal): %s", ticker, e)

    return {}


# ── Routing helpers ────────────────────────────────────────────────────────────

def _route_after_restriction(state: dict) -> str:
    return "skip" if state.get("skip_reason") else "continue"


def _route_after_entry_cutoff(state: dict) -> str:
    return "skip" if state.get("skip_reason") else "continue"


def _route_after_quiet(state: dict) -> str:
    return "skip" if state.get("skip_reason") else "continue"


# ── Graph factory ──────────────────────────────────────────────────────────────

def build_ticker_graph(
    ledger: "PaperTradingLedger",
    daily_cost_ref: list[float],
    date_str: str,
):
    """
    Build and compile the per-ticker LangGraph pipeline.

    Args:
        ledger:          The PaperTradingLedger instance (shared across all 15 tickers).
        daily_cost_ref:  Mutable one-element list [float] tracking cumulative LLM cost today.
        date_str:        Trading date "yyyy-mm-dd".

    Returns:
        Compiled LangGraph StateGraph ready for .invoke(ticker_state_dict).
    """
    pm_node = _build_pm_node(ledger, daily_cost_ref)
    ledger_node = _build_ledger_execute_node(ledger)
    persist_node = _build_persist_dynamo_node(date_str)

    graph = StateGraph(TickerState)

    graph.add_node("check_restrictions", check_restrictions_node)
    graph.add_node("check_entry_cutoff", check_entry_cutoff_node)
    graph.add_node("check_quiet", check_quiet_node)
    graph.add_node("news_sentiment", news_sentiment_node)
    graph.add_node("technical", technical_node)
    graph.add_node("fundamentals", fundamentals_node)
    graph.add_node("bull_bear", bull_bear_node)
    graph.add_node("portfolio_manager", pm_node)
    graph.add_node("cost_guard", cost_guard_node)
    graph.add_node("ledger_execute", ledger_node)
    graph.add_node("persist_dynamo", persist_node)
    graph.add_node("archive_s3", archive_s3_node)

    graph.add_edge(START, "check_restrictions")

    graph.add_conditional_edges(
        "check_restrictions",
        _route_after_restriction,
        {"skip": "persist_dynamo", "continue": "check_entry_cutoff"},
    )
    graph.add_conditional_edges(
        "check_entry_cutoff",
        _route_after_entry_cutoff,
        {"skip": "persist_dynamo", "continue": "check_quiet"},
    )
    graph.add_conditional_edges(
        "check_quiet",
        _route_after_quiet,
        {"skip": "persist_dynamo", "continue": "news_sentiment"},
    )

    graph.add_edge("news_sentiment", "technical")
    graph.add_edge("technical", "fundamentals")
    graph.add_edge("fundamentals", "bull_bear")
    graph.add_edge("bull_bear", "portfolio_manager")
    graph.add_edge("portfolio_manager", "cost_guard")
    graph.add_edge("cost_guard", "ledger_execute")
    graph.add_edge("ledger_execute", "persist_dynamo")
    graph.add_edge("persist_dynamo", "archive_s3")
    graph.add_edge("archive_s3", END)

    return graph.compile()
