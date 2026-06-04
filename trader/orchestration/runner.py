"""
Daily run orchestrator: runs the agent pipeline for all 15 tickers sequentially.

This module is the glue between:
- Data ingestion (market_data, news, fii_dii)
- The LangGraph per-ticker pipeline (graph.py)
- The PaperTradingLedger (position management)
- DynamoDB persistence (NAV snapshot at end of run)

Runs 15 tickers sequentially (not parallel) to:
- Stay within LLM rate limits
- Keep daily LLM cost observable
- Avoid Redis race conditions
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, date
from zoneinfo import ZoneInfo

from trader.config.settings import get_settings
from trader.config.tickers import UNIVERSE, get_ticker
from trader.ingestion.corporate_actions import fetch_corporate_actions
from trader.ingestion.fii_dii import fetch_fii_dii_flows
from trader.ingestion.market_data import (
    compute_technical_indicators,
    fetch_eod_ohlcv,
    fetch_nifty50_index,
)
from trader.ingestion.news import fetch_news_for_ticker
from trader.ledger.paper_trade import PaperTradingLedger
from trader.orchestration.graph import build_ticker_graph
from trader.orchestration.state import DailyRunState, empty_ticker_state
from trader.storage import dynamo

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# RBI repo rate (hardcoded; update when RBI changes it)
_RBI_RATE = 5.25


def _get_usd_inr() -> float:
    """Fetch current USD/INR rate via yfinance."""
    try:
        import yfinance as yf
        df = yf.download("USDINR=X", period="2d", auto_adjust=True, progress=False)
        if isinstance(df.columns, __import__("pandas").MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        return float(df["close"].dropna().iloc[-1])
    except Exception as e:
        logger.warning("USD/INR fetch failed: %s — using 84.0", e)
        return 84.0


def _build_market_data(ticker: str, trade_date: date) -> dict:
    """
    Fetch OHLCV, compute technical indicators, and assemble the market_data dict
    that flows into the TickerState.
    """
    df = fetch_eod_ohlcv(ticker, days=30)
    if df.empty:
        raise ValueError(f"No OHLCV data for {ticker}")

    indicators = compute_technical_indicators(df)

    last_row = df.iloc[-1]
    close_price = float(last_row["close"])

    # Build last-5d OHLCV list for the technical agent
    last_5d = df.tail(5)[["date", "open", "high", "low", "close", "volume"]].copy()
    last_5d["date"] = last_5d["date"].astype(str)
    last_5d_list = last_5d.to_dict(orient="records")

    return {
        "close_price": close_price,
        "last_5d_ohlcv": last_5d_list,
        "macro_context": {},       # populated by _build_macro_context() in runner
        "known_fundamentals": {},  # Phase 1: empty; agents note staleness
        **indicators,
    }


def _build_macro_context(nifty_df) -> dict:
    """Build the macro_context dict from Nifty 50 index data."""
    if nifty_df is None or nifty_df.empty:
        return {
            "rbi_rate": _RBI_RATE,
            "usd_inr": 84.0,
            "nifty_1d_pct": 0.0,
            "nifty_5d_pct": 0.0,
        }

    closes = nifty_df["close"].dropna()
    nifty_1d_pct = float((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100) if len(closes) >= 2 else 0.0
    nifty_5d_pct = float((closes.iloc[-1] - closes.iloc[-5]) / closes.iloc[-5] * 100) if len(closes) >= 5 else 0.0

    return {
        "rbi_rate": _RBI_RATE,
        "usd_inr": _get_usd_inr(),
        "nifty_1d_pct": round(nifty_1d_pct, 4),
        "nifty_5d_pct": round(nifty_5d_pct, 4),
    }


def _load_ledger(trade_date_str: str) -> PaperTradingLedger:
    """
    Load the ledger from DynamoDB if a previous run exists, else start from scratch.
    Uses yesterday's NAV + today's open positions.
    """
    from datetime import date, timedelta

    settings = get_settings()
    today = date.fromisoformat(trade_date_str)
    yesterday = (today - timedelta(days=1)).isoformat()

    # Try to restore from yesterday's NAV snapshot
    nav_item = dynamo.get_nav(yesterday)
    if nav_item is None:
        logger.info("No prior NAV found — initialising ledger from scratch.")
        return PaperTradingLedger.from_scratch(trade_date_str)

    # Load today's open positions (still under TICKER#X keys)
    position_items: list[dict] = []
    for t in UNIVERSE:
        pos = dynamo.get_position(t.symbol, yesterday)
        if pos and int(pos.get("qty", 0)) > 0:
            pos["PK"] = f"TICKER#{t.symbol}"
            position_items.append(pos)

    return PaperTradingLedger.from_dynamo_snapshot(
        nav_item=nav_item,
        position_items=position_items,
        trade_date=trade_date_str,
    )


def _persist_open_positions(ledger: PaperTradingLedger, date_str: str) -> None:
    """Write open position items to DynamoDB at end of run."""
    import time
    ttl = int(time.time()) + 30 * 24 * 3600

    for pos_dict in ledger.open_positions_as_dicts():
        ticker = pos_dict["ticker"]
        item = {
            "PK": f"TICKER#{ticker}",
            "SK": f"DATE#{date_str}",
            "qty": pos_dict["qty"],
            "avg_price": pos_dict["avg_price"],
            "entry_date": pos_dict["entry_date"],
            "days_held": pos_dict["days_held"],
            "product_type": "CNC",
            "horizon_days": pos_dict["horizon_days"],
            "stop_loss_price": pos_dict["stop_loss_price"],
            "target_price": pos_dict["target_price"],
            "kill_conditions": pos_dict["kill_conditions"],
            "decision_date": pos_dict["entry_date"],
            "ttl": ttl,
        }
        try:
            dynamo.put_position(item)
        except Exception as e:
            logger.error("Failed to persist position for %s: %s", ticker, e)


def run_daily(trade_date_str: str | None = None) -> DailyRunState:
    """
    Execute the full daily pipeline for all 15 tickers.

    Args:
        trade_date_str: "yyyy-mm-dd"; defaults to today in IST.

    Returns:
        DailyRunState summarising the completed run.
    """
    settings = get_settings()

    if trade_date_str is None:
        trade_date_str = datetime.now(IST).date().isoformat()

    logger.info("=== Daily run starting for %s ===", trade_date_str)
    trade_date = date.fromisoformat(trade_date_str)

    # ── Idempotency check ─────────────────────────────────────────────────────
    if dynamo.daily_run_already_completed(trade_date_str):
        logger.info("Daily run for %s already completed — exiting.", trade_date_str)
        return DailyRunState(
            run_date=trade_date_str,
            tickers=[t.symbol for t in UNIVERSE],
            ticker_states={},
            portfolio={},
            total_cost_usd=0.0,
            completed_at=None,
        )

    # ── Load shared data ───────────────────────────────────────────────────────
    logger.info("Fetching Nifty 50 index data…")
    try:
        nifty_df = fetch_nifty50_index(days=30)
    except Exception as e:
        logger.warning("Nifty 50 fetch failed: %s — macro context will be empty.", e)
        nifty_df = None

    macro_ctx = _build_macro_context(nifty_df)

    logger.info("Fetching FII/DII flows…")
    try:
        fii_dii = fetch_fii_dii_flows(trade_date)
    except Exception as e:
        logger.warning("FII/DII fetch failed: %s — using zeros.", e)
        fii_dii = {"fii_net_buy_cr": 0.0, "dii_net_buy_cr": 0.0, "date": "", "source": "unavailable"}

    # ── Load ledger ────────────────────────────────────────────────────────────
    ledger = _load_ledger(trade_date_str)

    # Advance day: increment days_held for all open positions
    # Current prices needed; fetch from yesterday's close as proxy
    current_prices: dict[str, float] = {}
    for t in UNIVERSE:
        try:
            df = fetch_eod_ohlcv(t.symbol, days=2)
            if not df.empty:
                current_prices[t.symbol] = float(df.iloc[-1]["close"])
        except Exception:
            pass
    ledger.advance_day(current_prices)

    # ── Build the compiled graph (once, reused for all 15 tickers) ────────────
    daily_cost_ref: list[float] = [0.0]
    compiled_graph = build_ticker_graph(ledger, daily_cost_ref, trade_date_str)

    # ── Run per-ticker pipeline ────────────────────────────────────────────────
    run_state = DailyRunState(
        run_date=trade_date_str,
        tickers=[t.symbol for t in UNIVERSE],
        ticker_states={},
        portfolio={},
        total_cost_usd=0.0,
        completed_at=None,
    )

    for ticker_cfg in UNIVERSE:
        ticker = ticker_cfg.symbol
        logger.info("--- Processing %s (%s) ---", ticker, ticker_cfg.name)
        t0 = time.time()

        try:
            # ── Ingestion ──────────────────────────────────────────────────────
            market_data = _build_market_data(ticker, trade_date)
            market_data["macro_context"] = macro_ctx

            news_articles = fetch_news_for_ticker(
                ticker=ticker,
                company_name=ticker_cfg.name,
                agent_name="news_sentiment",
                hours_back=24,
            )
            try:
                corp_actions = fetch_corporate_actions(ticker, days_window=7)
            except Exception as e:
                logger.warning("Corp actions fetch failed for %s: %s", ticker, e)
                corp_actions = []

            # ── Assemble TickerState ───────────────────────────────────────────
            portfolio_snap = ledger.portfolio_snapshot({ticker: market_data["close_price"]})
            current_pos = ledger.current_position_for(ticker)

            # Auto-exit positions held beyond max_hold_days
            pos = ledger.positions.get(ticker)
            is_overdue = pos is not None and pos.qty > 0 and pos.days_held >= settings.max_hold_days

            state = empty_ticker_state(
                ticker=ticker,
                company_name=ticker_cfg.name,
                sector=ticker_cfg.sector,
            )
            state.update({
                "market_data": market_data,
                "news_articles": news_articles,
                "corporate_actions": corp_actions,
                "fii_dii": fii_dii,
                "portfolio_snapshot": portfolio_snap,
                "current_position": current_pos,
                "is_restricted": False,  # TODO: plug in real ASM/GSM check
            })

            # If overdue, force EXIT directly (skip LLM pipeline)
            if is_overdue:
                logger.info("[%s] Auto-EXIT: held %d days (max=%d)", ticker, pos.days_held, settings.max_hold_days)
                from trader.agents.models import pm_hold_fallback
                auto_exit = pm_hold_fallback(ticker).model_copy(update={
                    "decision": "EXIT",
                    "primary_thesis": f"Auto-exit: position held {pos.days_held} days (max {settings.max_hold_days}).",
                })
                state["pm_output"] = auto_exit.model_dump()
                # Simulate the fill manually
                fill = ledger.simulate_fill(
                    ticker=ticker,
                    decision="EXIT",
                    quantity_shares=0,  # uses pos.qty
                    close_price=market_data["close_price"],
                )
                if fill:
                    ledger.update_positions(fill)
                    state["simulated_fill"] = fill.as_dict()

            else:
                # ── Run LangGraph pipeline ─────────────────────────────────────
                result = compiled_graph.invoke(state)
                state = result

        except Exception as e:
            logger.exception("Pipeline failed for %s: %s", ticker, e)
            state["errors"] = state.get("errors", []) + [f"Pipeline error: {e}"]

        elapsed_ms = int((time.time() - t0) * 1000)
        state["processing_time_ms"] = elapsed_ms
        run_state["ticker_states"][ticker] = state

        total_ticker_cost = sum(
            v.get("cost_usd", 0.0) for v in state.get("tokens_used", {}).values()
        )
        run_state["total_cost_usd"] += total_ticker_cost

        logger.info(
            "[%s] Done in %dms | LLM cost today: $%.4f",
            ticker, elapsed_ms, run_state["total_cost_usd"],
        )

    # ── End of run: persist positions + NAV ───────────────────────────────────
    _persist_open_positions(ledger, trade_date_str)

    nifty_close = 0.0
    nifty_1d_pct = macro_ctx.get("nifty_1d_pct", 0.0)
    if nifty_df is not None and not nifty_df.empty:
        nifty_close = float(nifty_df["close"].dropna().iloc[-1])

    prev_nav = None
    try:
        from datetime import timedelta
        prev_date = (date.fromisoformat(trade_date_str) - timedelta(days=1)).isoformat()
        prev_nav_item = dynamo.get_nav(prev_date)
        if prev_nav_item:
            prev_nav = float(prev_nav_item.get("nav_inr", 0))
    except Exception:
        pass

    nav_snap = ledger.calculate_nav(
        current_prices={t.symbol: current_prices.get(t.symbol, 0.0) for t in UNIVERSE},
        previous_nav_inr=prev_nav,
    )

    skipped = sum(
        1 for s in run_state["ticker_states"].values() if s.get("skip_reason")
    )
    decisions_made = len(UNIVERSE) - skipped
    schema_errors = sum(len(s.get("errors", [])) for s in run_state["ticker_states"].values())

    import time as _time
    nav_item = {
        "PK": f"DATE#{trade_date_str}",
        "SK": "PORTFOLIO",
        **nav_snap.as_dict(),
        "nifty50_close": nifty_close,
        "nifty50_daily_return_pct": nifty_1d_pct,
        "total_llm_cost_usd_today": run_state["total_cost_usd"],
        "decisions_made": decisions_made,
        "decisions_skipped": skipped,
        "schema_error_count": schema_errors,
        "ttl": int(_time.time()) + 30 * 24 * 3600,
    }
    try:
        dynamo.put_nav(nav_item)
    except Exception as e:
        logger.error("Failed to persist NAV for %s: %s", trade_date_str, e)

    completed_at = datetime.now(IST).isoformat()
    run_state["completed_at"] = completed_at
    run_state["portfolio"] = nav_snap.as_dict()

    logger.info(
        "=== Run complete %s | NAV=₹%.0f | cost=$%.4f | %d tickers (%d skipped) ===",
        trade_date_str, nav_snap.nav_inr, run_state["total_cost_usd"], len(UNIVERSE), skipped,
    )
    return run_state
