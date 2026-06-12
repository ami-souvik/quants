"""
Daily run report builder.

Compiles the full DailyRunState into a structured DailyReport and persists
it to DynamoDB as PK=DATE#{date}, SK=REPORT, type=DAILY_REPORT.

The report is a single DynamoDB item containing:
  - Run-level summary (NAV, cost, durations, decision counts)
  - Macro context (Nifty, FII/DII, macro indicators)
  - Per-ticker detail (all 5 agent outputs, errors, fill, token costs)
  - Run-level errors (infra failures that happened before/outside ticker loop)

Stored as one item (~30–50 KB for 15 tickers) — well within DynamoDB's 400 KB limit.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from trader.storage import dynamo

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def build_report(
    run_state: dict,
    macro_ctx: dict,
    fii_dii: dict,
    nifty_close: float,
    started_at: str,
    run_errors: list[str],
) -> dict:
    """
    Build a comprehensive report dict from a completed run_state.

    Args:
        run_state:   The DailyRunState returned by run_daily().
        macro_ctx:   The macro context dict built during the run.
        fii_dii:     FII/DII flows dict.
        nifty_close: Last Nifty 50 close price.
        started_at:  ISO timestamp when the run started.
        run_errors:  Errors that occurred at the run level (not per-ticker).

    Returns:
        Report dict ready to be written to DynamoDB.
    """
    run_date = run_state.get("run_date", "")
    completed_at = run_state.get("completed_at", datetime.now(IST).isoformat())
    total_cost = run_state.get("total_cost_usd", 0.0)
    portfolio = run_state.get("portfolio", {})
    ticker_states = run_state.get("ticker_states", {})

    # Duration
    try:
        start_dt = datetime.fromisoformat(started_at)
        end_dt = datetime.fromisoformat(completed_at)
        duration_s = (end_dt - start_dt).total_seconds()
    except Exception:
        duration_s = 0.0

    # Aggregate decision counts
    decision_counts: dict[str, int] = {}
    skipped = 0
    errored = 0
    completed = 0

    for state in ticker_states.values():
        if state.get("skip_reason"):
            skipped += 1
            decision_counts["SKIP"] = decision_counts.get("SKIP", 0) + 1
            continue

        errors = state.get("errors", [])
        pm_out = state.get("pm_output") or {}
        decision = pm_out.get("decision", "UNKNOWN")

        if errors and not pm_out:
            errored += 1
            decision_counts["ERROR"] = decision_counts.get("ERROR", 0) + 1
        else:
            completed += 1
            decision_counts[decision] = decision_counts.get(decision, 0) + 1

    schema_errors = sum(len(s.get("errors", [])) for s in ticker_states.values())

    # Per-ticker detail list
    ticker_details = []
    for ticker, state in ticker_states.items():
        skip_reason = state.get("skip_reason")
        errors = state.get("errors", [])
        pm_out = state.get("pm_output") or {}

        if skip_reason:
            status = "skipped"
        elif errors and not pm_out:
            status = "errored"
        else:
            status = "completed"

        tokens_used = state.get("tokens_used") or {}
        ticker_cost = sum(v.get("cost_usd", 0.0) for v in tokens_used.values())

        market_data = state.get("market_data") or {}
        close_price = market_data.get("close_price", 0.0)
        pct_change_1d = market_data.get("pct_change_1d", 0.0)

        ticker_details.append({
            "ticker": ticker,
            "company_name": state.get("company_name", ""),
            "sector": state.get("sector", ""),
            "status": status,
            "skip_reason": skip_reason,
            "errors": errors,
            "processing_time_ms": state.get("processing_time_ms", 0),
            "close_price": close_price,
            "pct_change_1d": pct_change_1d,
            "news_output": state.get("news_output"),
            "technical_output": state.get("technical_output"),
            "fundamentals_output": state.get("fundamentals_output"),
            "bull_bear_output": state.get("bull_bear_output"),
            "pm_output": pm_out or None,
            "simulated_fill": state.get("simulated_fill"),
            "tokens_used": tokens_used,
            "ticker_cost_usd": round(ticker_cost, 6),
        })

    report = {
        "PK": f"DATE#{run_date}",
        "SK": "REPORT",
        "type": "DAILY_REPORT",
        "run_date": run_date,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": round(duration_s, 1),

        "macro": {
            "nifty_close": nifty_close,
            "nifty_1d_pct": macro_ctx.get("nifty_1d_pct", 0.0),
            "nifty_5d_pct": macro_ctx.get("nifty_5d_pct", 0.0),
            "rbi_rate": macro_ctx.get("rbi_rate", 0.0),
            "usd_inr": macro_ctx.get("usd_inr", 0.0),
            "fii_net_buy_cr": fii_dii.get("fii_net_buy_cr", 0.0),
            "dii_net_buy_cr": fii_dii.get("dii_net_buy_cr", 0.0),
            "fii_dii_source": fii_dii.get("source", ""),
        },

        "summary": {
            "tickers_total": len(ticker_states),
            "tickers_completed": completed,
            "tickers_skipped": skipped,
            "tickers_errored": errored,
            "decision_counts": decision_counts,
            "total_llm_cost_usd": round(total_cost, 6),
            "schema_errors": schema_errors,
            "nav_inr": float(portfolio.get("nav_inr", 0.0)),
            "cash_inr": float(portfolio.get("cash_inr", 0.0)),
            "daily_return_pct": float(portfolio.get("daily_return_pct", 0.0)),
            "cumulative_return_pct": float(portfolio.get("cumulative_return_pct", 0.0)),
            "drawdown_pct": float(portfolio.get("drawdown_pct", 0.0)),
            "open_positions": int(portfolio.get("open_positions", 0)),
        },

        "run_errors": run_errors,
        "tickers": ticker_details,
        "ttl": int(time.time()) + 30 * 24 * 3600,
    }

    return report


def persist_report(report: dict) -> None:
    """Write the report to DynamoDB. Logs but does not raise on failure."""
    try:
        dynamo.put_item(dynamo._table(), report)
        logger.info("Daily report persisted for %s", report.get("run_date"))
    except Exception as e:
        logger.error("Failed to persist daily report: %s", e)


def get_report(date_str: str) -> dict | None:
    """Fetch the daily report for a given date string (yyyy-mm-dd)."""
    return dynamo.get_item(dynamo._table(), pk=f"DATE#{date_str}", sk="REPORT")
