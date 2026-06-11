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


def _log_llm_backends(settings) -> None:
    """
    Log which LLM backend every agent will use, based on available API keys.
    Printed once at the start of each daily run so the operator can spot
    unexpected fallbacks immediately.
    """
    from trader.agents.news_sentiment import NewsSentimentAgent
    from trader.agents.technical import TechnicalAgent
    from trader.agents.fundamentals import FundamentalsAgent
    from trader.agents.bull_bear import BullBearAgent
    from trader.agents.portfolio_manager import PortfolioManagerAgent

    has_anthropic = bool(settings.anthropic_api_key)
    has_gemini    = bool(settings.gemini_api_key)

    def _backend(model: str) -> str:
        if model.startswith("ollama/"):
            return f"Ollama ({settings.ollama_base_url})"
        if model.startswith("anthropic/"):
            return model.replace("anthropic/", "") if has_anthropic else f"⚠ OLLAMA FALLBACK — set ANTHROPIC_API_KEY"
        if model.startswith("google/"):
            return model.replace("google/", "") if has_gemini else f"⚠ OLLAMA FALLBACK — set GEMINI_API_KEY"
        return f"⚠ OLLAMA FALLBACK (unrecognised prefix)"

    logger.info("─── LLM backend summary ─────────────────────────────────────────")
    for cls in [NewsSentimentAgent, TechnicalAgent, FundamentalsAgent, BullBearAgent, PortfolioManagerAgent]:
        # model is now an instance property (reads from settings), not a class attr
        agent = cls()
        model = agent.model
        logger.info("  %-22s %s → %s", cls.name, model, _backend(model))
    logger.info("─────────────────────────────────────────────────────────────────")


def _check_ollama_if_needed(settings) -> None:
    """
    If any agent will fall back to Ollama, verify the server is reachable
    before starting the 15-ticker loop. Raises RuntimeError immediately so
    the operator sees a clear message rather than 15× 5-second timeouts.
    """
    from trader.agents.news_sentiment import NewsSentimentAgent
    from trader.agents.technical import TechnicalAgent
    from trader.agents.fundamentals import FundamentalsAgent
    from trader.agents.bull_bear import BullBearAgent
    from trader.agents.portfolio_manager import PortfolioManagerAgent

    has_anthropic = bool(settings.anthropic_api_key)
    has_gemini    = bool(settings.gemini_api_key)

    def _needs_ollama(model: str) -> bool:
        if model.startswith("ollama/"):
            return True
        if model.startswith("anthropic/") and not has_anthropic:
            return True
        if model.startswith("google/") and not has_gemini:
            return True
        if not any(model.startswith(p) for p in ("anthropic/", "google/", "ollama/")):
            return True
        return False

    agents_needing_ollama = [
        cls.name for cls in
        [NewsSentimentAgent, TechnicalAgent, FundamentalsAgent, BullBearAgent, PortfolioManagerAgent]
        if _needs_ollama(cls().model)
    ]

    if not agents_needing_ollama:
        return  # all agents have cloud keys — no Ollama needed

    logger.info(
        "Agents using Ollama: %s — checking connectivity to %s …",
        ", ".join(agents_needing_ollama),
        settings.ollama_base_url,
    )

    import httpx
    try:
        r = httpx.get(
            f"{settings.ollama_base_url.rstrip('/')}/api/tags",
            timeout=5.0,
        )
        r.raise_for_status()
        models = [m.get("name", "") for m in r.json().get("models", [])]
        logger.info("Ollama reachable. Available models: %s", models or "(none pulled yet)")

        # Warn if the configured model isn't pulled yet
        ollama_model = settings.ollama_model
        if models and not any(m.startswith(ollama_model.split(":")[0]) for m in models):
            logger.warning(
                "Configured OLLAMA_MODEL='%s' not found in Ollama. "
                "Pull it first: ollama pull %s",
                ollama_model, ollama_model,
            )
    except httpx.ConnectError:
        raise RuntimeError(
            f"\n\n"
            f"  ╔══════════════════════════════════════════════════════════════╗\n"
            f"  ║  OLLAMA UNREACHABLE — cannot start daily run                ║\n"
            f"  ╠══════════════════════════════════════════════════════════════╣\n"
            f"  ║  Server:  {settings.ollama_base_url:<50} ║\n"
            f"  ║  Model:   {settings.ollama_model:<50} ║\n"
            f"  ║                                                              ║\n"
            f"  ║  Agents needing Ollama: {', '.join(agents_needing_ollama):<37} ║\n"
            f"  ║                                                              ║\n"
            f"  ║  Fix one of:                                                 ║\n"
            f"  ║  1. Start Ollama on your server and pull the model           ║\n"
            f"  ║       ollama serve  &&  ollama pull {settings.ollama_model:<24} ║\n"
            f"  ║  2. Set the missing API key(s) in .env:                     ║\n"
            f"  ║       {'GEMINI_API_KEY=AIza...' if not has_gemini else 'ANTHROPIC_API_KEY=sk-ant-...':<52} ║\n"
            f"  ╚══════════════════════════════════════════════════════════════╝\n"
        )
    except httpx.TimeoutException:
        raise RuntimeError(
            f"Ollama at {settings.ollama_base_url} did not respond within 5 s. "
            f"Check the server is running and the IP/port is correct."
        )

    # ── Warm up the model ─────────────────────────────────────────────────────
    # The first inference request triggers model loading from disk into VRAM,
    # which can take 20–60 s for 7B+ models. Fire a tiny warm-up request NOW
    # so that cost doesn't land on RELIANCE ticker #1 and cause a timeout.
    _warmup_ollama(settings)


def _warmup_ollama(settings) -> None:
    """
    Send a tiny request to Ollama so the model is loaded into VRAM
    before the first real ticker call. This converts a per-ticker cold-start
    penalty (20–60 s) into a one-time startup cost.
    """
    import httpx

    raw_model = settings.ollama_model.replace("ollama/", "")
    url = f"{settings.ollama_base_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": raw_model,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "options": {"num_ctx": 128, "num_predict": 4},
    }
    logger.info("Warming up Ollama model '%s' (pre-loading into VRAM)…", raw_model)
    start = time.monotonic()
    try:
        read_timeout = float(settings.ollama_read_timeout)
        r = httpx.post(url, json=payload, timeout=httpx.Timeout(connect=5.0, read=read_timeout, write=5.0, pool=5.0))
        r.raise_for_status()
        elapsed = int((time.monotonic() - start) * 1000)
        logger.info("Ollama warm-up done in %d ms — model ready.", elapsed)
    except Exception as exc:
        # Warm-up failure is non-fatal — log and continue; the first real call will retry.
        logger.warning("Ollama warm-up failed (non-fatal): %s", exc)


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


def _log_ticker_summary(ticker: str, state: dict, elapsed_ms: int, cumulative_cost_usd: float) -> None:
    """
    Print a structured one-block summary for a completed ticker run.
    Covers skip reasons, agent signals, final decision, errors, and cost.
    """
    skip = state.get("skip_reason")
    errors = state.get("errors", [])
    tokens_used = state.get("tokens_used", {})
    ticker_cost = sum(v.get("cost_usd", 0.0) for v in tokens_used.values())

    if skip:
        logger.info("[%s] SKIPPED (%s) | %dms cost=$%.5f", ticker, skip, elapsed_ms, ticker_cost)
        return

    # Pull agent outputs safely
    news_out  = state.get("news_output") or {}
    tech_out  = state.get("technical_output") or {}
    fund_out  = state.get("fundamentals_output") or {}
    bb_out    = state.get("bull_bear_output") or {}
    pm_out    = state.get("pm_output") or {}

    news_label  = news_out.get("sentiment_label", "—")
    news_conf   = news_out.get("confidence", 0)
    tech_signal = tech_out.get("technical_signal", "—")
    tech_conf   = tech_out.get("confidence", 0)
    fund_bias   = fund_out.get("fundamental_bias", "—")
    fund_conf   = fund_out.get("confidence", 0)
    bb_winner   = bb_out.get("debate_winner", "—")
    bb_delta    = bb_out.get("conviction_delta", 0)
    pm_decision = pm_out.get("decision", "—")
    pm_conf     = pm_out.get("confidence", 0)
    pm_qty      = pm_out.get("quantity_shares", 0)
    pm_val      = pm_out.get("estimated_trade_value_inr", 0)
    pm_rr       = pm_out.get("risk_reward_ratio", 0)

    logger.info(
        "[%s] ┌── Ticker Summary ──────────────────────────────────────",
        ticker,
    )
    logger.info(
        "[%s] │  News:   %-18s conf=%.2f",
        ticker, news_label, news_conf,
    )
    logger.info(
        "[%s] │  Tech:   %-18s conf=%.2f",
        ticker, tech_signal, tech_conf,
    )
    logger.info(
        "[%s] │  Fund:   %-18s conf=%.2f",
        ticker, fund_bias, fund_conf,
    )
    logger.info(
        "[%s] │  Debate: winner=%-6s delta=%.2f",
        ticker, bb_winner, bb_delta,
    )
    logger.info(
        "[%s] │  ► PM:   %-10s qty=%d val=₹%.0f conf=%.2f RR=%.1f",
        ticker, pm_decision, pm_qty, pm_val, pm_conf, pm_rr,
    )
    if errors:
        for err in errors:
            logger.warning("[%s] │  ERROR: %s", ticker, err)
    logger.info(
        "[%s] └── %dms | cost=$%.5f | cumulative=$%.4f",
        ticker, elapsed_ms, ticker_cost, cumulative_cost_usd,
    )


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
    Load yesterday's NAV from DynamoDB to restore cash/peak state.
    MIS positions are never loaded here — intraday positions don't persist across days.
    """
    from datetime import date, timedelta

    today = date.fromisoformat(trade_date_str)
    yesterday = (today - timedelta(days=1)).isoformat()

    nav_item = dynamo.get_nav(yesterday)
    if nav_item is None:
        logger.info("No prior NAV found — initialising ledger from scratch.")
        return PaperTradingLedger.from_scratch(trade_date_str)

    # MIS: no positions to restore — all positions were squared off at 15:15 yesterday
    return PaperTradingLedger.from_dynamo_snapshot(
        nav_item=nav_item,
        trade_date=trade_date_str,
    )


def _save_intraday_positions_to_redis(
    ledger: PaperTradingLedger,
    trade_date_str: str,
) -> None:
    """
    Write all open intraday positions to Redis after the morning run.
    The squareoff run reads these at 15:20 IST to close all positions.
    Redis key pattern: INTRADAY_POS:{date}:{ticker}  TTL: 24h
    """
    import json

    open_positions = ledger.open_positions_as_dicts()
    if not open_positions:
        logger.info("[redis] No open intraday positions to save.")
        return

    try:
        import redis as redis_lib
        r = redis_lib.from_url(get_settings().redis_url)
        pipe = r.pipeline()
        tickers_key = f"INTRADAY_TICKERS:{trade_date_str}"
        for pos_dict in open_positions:
            ticker = pos_dict["ticker"]
            pos_key = f"INTRADAY_POS:{trade_date_str}:{ticker}"
            pipe.set(pos_key, json.dumps(pos_dict), ex=86400)
            pipe.sadd(tickers_key, ticker)
        pipe.expire(tickers_key, 86400)
        pipe.execute()
        logger.info(
            "[redis] Saved %d open intraday positions for %s",
            len(open_positions), trade_date_str,
        )
    except Exception as e:
        logger.error("[redis] Failed to save intraday positions: %s", e)


def _load_intraday_positions_from_redis(trade_date_str: str) -> list[dict]:
    """
    Load open intraday positions from Redis for the squareoff run.
    Returns list of position dicts; empty list if Redis unavailable or no positions.
    """
    import json

    try:
        import redis as redis_lib
        r = redis_lib.from_url(get_settings().redis_url)
        tickers_key = f"INTRADAY_TICKERS:{trade_date_str}"
        raw_tickers = r.smembers(tickers_key)
        if not raw_tickers:
            logger.info("[redis] No open positions found for %s.", trade_date_str)
            return []

        positions = []
        for raw in raw_tickers:
            ticker = raw.decode() if isinstance(raw, bytes) else raw
            pos_key = f"INTRADAY_POS:{trade_date_str}:{ticker}"
            raw_pos = r.get(pos_key)
            if raw_pos:
                positions.append(json.loads(raw_pos))

        logger.info(
            "[redis] Loaded %d open intraday positions for %s",
            len(positions), trade_date_str,
        )
        return positions
    except Exception as e:
        logger.warning("[redis] Failed to load intraday positions: %s", e)
        return []


def run_daily(trade_date_str: str | None = None) -> DailyRunState:
    """Deprecated alias for run_morning(). Use run_morning() directly."""
    logger.warning(
        "run_daily() is deprecated — call run_morning() instead. "
        "daily_run.py will be removed once morning_run.py is the ECS entry point."
    )
    return run_morning(trade_date_str)


def run_morning(trade_date_str: str | None = None) -> DailyRunState:
    """
    Execute the morning pipeline for all 15 tickers (08:45 IST).

    Produces BUY/SKIP decisions, simulates BUY fills, and persists
    open intraday positions to Redis. The squareoff run at 15:20 IST
    reads those positions and closes them.

    Args:
        trade_date_str: "yyyy-mm-dd"; defaults to today in IST.

    Returns:
        DailyRunState summarising the completed morning run.
    """
    settings = get_settings()

    if trade_date_str is None:
        trade_date_str = datetime.now(IST).date().isoformat()

    logger.info("=== Daily run starting for %s ===", trade_date_str)
    trade_date = date.fromisoformat(trade_date_str)

    # ── LLM backend pre-flight ─────────────────────────────────────────────────
    _log_llm_backends(settings)
    _check_ollama_if_needed(settings)

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
    # MIS: always starts fresh — no positions carry over from prior day.
    ledger = _load_ledger(trade_date_str)

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

            state = empty_ticker_state(
                ticker=ticker,
                company_name=ticker_cfg.name,
                sector=ticker_cfg.sector,
            )
            now_ist = datetime.now(IST)
            entry_cutoff_passed = (now_ist.hour, now_ist.minute) >= (11, 0)

            state.update({
                "market_data": market_data,
                "news_articles": news_articles,
                "corporate_actions": corp_actions,
                "fii_dii": fii_dii,
                "portfolio_snapshot": portfolio_snap,
                "current_position": current_pos,
                "is_restricted": False,  # TODO: plug in real ASM/GSM check
                "entry_cutoff_passed": entry_cutoff_passed,
            })

            # ── Run LangGraph pipeline ─────────────────────────────────────────
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

        # ── Per-ticker summary block ───────────────────────────────────────────
        _log_ticker_summary(ticker, state, elapsed_ms, run_state["total_cost_usd"])

    # ── End of morning run: save open positions to Redis ──────────────────────
    settings = get_settings()
    if not settings.dry_run:
        _save_intraday_positions_to_redis(ledger, trade_date_str)

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

    # Intraday NAV snapshot: equity = open positions at prior-day close prices.
    # eod=False so equity_value_inr reflects the open MIS positions.
    # The final EOD NAV (equity=0) is overwritten by squareoff_run.py at 15:20 IST.
    nav_snap = ledger.calculate_nav(previous_nav_inr=prev_nav, eod=False)

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
        "=== Morning run complete %s | NAV=₹%.0f (intraday) | cost=$%.4f | %d tickers (%d skipped) ===",
        trade_date_str, nav_snap.nav_inr, run_state["total_cost_usd"], len(UNIVERSE), skipped,
    )
    return run_state


def run_squareoff(trade_date_str: str | None = None) -> dict:
    """
    Execute the mandatory 15:20 IST squareoff run.

    Reads all open intraday positions from Redis, fetches the most recent
    closing prices, calls squareoff_all_positions(), writes each completed
    round-trip to DynamoDB (trades table), and updates nav_daily with the
    final EOD figures (equity_value_inr = 0).

    This function MUST run unconditionally — it is the only safety net
    preventing phantom overnight positions in the simulation.

    Args:
        trade_date_str: "yyyy-mm-dd"; defaults to today in IST.

    Returns:
        dict with summary: {trade_date, trades_closed, net_pnl_inr, nav_inr, completed_at}
    """
    import time as _time
    from datetime import timedelta

    settings = get_settings()

    if trade_date_str is None:
        trade_date_str = datetime.now(IST).date().isoformat()

    logger.info("=== Squareoff run starting for %s ===", trade_date_str)

    # ── Idempotency: skip if already squared off today ─────────────────────
    existing_trades = dynamo.get_trades_for_date(trade_date_str)
    if existing_trades:
        logger.info(
            "Squareoff for %s already completed (%d trades found) — exiting.",
            trade_date_str, len(existing_trades),
        )
        return {
            "trade_date": trade_date_str,
            "trades_closed": len(existing_trades),
            "already_completed": True,
        }

    # ── Load open positions from Redis ─────────────────────────────────────
    position_dicts = _load_intraday_positions_from_redis(trade_date_str)
    if not position_dicts:
        logger.info("No open intraday positions for %s — nothing to squareoff.", trade_date_str)
        # Still write EOD NAV (all cash, no equity)
        nav_item_prev = dynamo.get_nav(trade_date_str)
        cash = float(nav_item_prev.get("cash_inr", settings.initial_capital_inr)) if nav_item_prev else settings.initial_capital_inr
        _write_eod_nav(
            trade_date_str=trade_date_str,
            cash_inr=cash,
            prev_nav_inr=cash,
            trades=[],
            nifty_close=0.0,
            nifty_1d_pct=0.0,
            total_llm_cost_usd=0.0,
        )
        return {"trade_date": trade_date_str, "trades_closed": 0}

    # ── Reconstruct ledger from Redis positions ────────────────────────────
    # Load yesterday's NAV for cash/peak state
    yesterday = (date.fromisoformat(trade_date_str) - timedelta(days=1)).isoformat()
    nav_item = dynamo.get_nav(yesterday)
    ledger = (
        PaperTradingLedger.from_dynamo_snapshot(nav_item=nav_item, trade_date=trade_date_str)
        if nav_item
        else PaperTradingLedger.from_scratch(trade_date_str)
    )

    # Re-populate in-memory positions from Redis
    from trader.ledger.paper_trade import Position
    for pos_dict in position_dicts:
        ticker = pos_dict["ticker"]
        try:
            from trader.config.tickers import get_ticker as _get_ticker
            sector = _get_ticker(ticker).sector
        except ValueError:
            sector = pos_dict.get("sector", "Unknown")
        ledger.positions[ticker] = Position(
            ticker=ticker,
            sector=sector,
            qty=int(pos_dict["qty"]),
            avg_price=float(pos_dict["avg_price"]),
            entry_date=pos_dict.get("entry_date", trade_date_str),
            entry_time_ist=pos_dict.get("entry_time_ist", "09:20"),
            stop_loss_price=float(pos_dict.get("stop_loss_price", 0)),
            target_price=float(pos_dict.get("target_price", 0)),
            current_price=float(pos_dict.get("avg_price", 0)),
        )
        # Adjust cash: subtract the position value that was already deducted in morning run
        # (cash in nav_item already reflects morning buys — don't double-deduct)
    logger.info(
        "[squareoff] Reconstructed %d open intraday positions.", len(position_dicts)
    )

    # ── Fetch closing prices (most recent available EOD data) ──────────────
    closing_prices: dict[str, float] = {}
    for ticker in list(ledger.positions.keys()):
        if ledger.positions[ticker].qty == 0:
            continue
        try:
            df = fetch_eod_ohlcv(ticker, days=2)
            if not df.empty:
                closing_prices[ticker] = float(df.iloc[-1]["close"])
        except Exception as e:
            logger.warning("[squareoff] Could not fetch close for %s: %s", ticker, e)

    # ── Squareoff all positions unconditionally ────────────────────────────
    completed_trades = ledger.squareoff_all_positions(closing_prices)
    logger.info("[squareoff] Closed %d intraday positions.", len(completed_trades))

    # ── Write completed round-trip trades to DynamoDB ──────────────────────
    ttl = int(_time.time()) + 30 * 24 * 3600
    if not settings.dry_run:
        for trade in completed_trades:
            item = {
                "PK": f"DATE#{trade_date_str}",
                "SK": f"TRADE#{trade.trade_id}",
                **trade.as_dict(),
                "ttl": ttl,
            }
            try:
                dynamo.put_trade(item)
            except Exception as e:
                logger.error("[squareoff] Failed to write trade %s: %s", trade.trade_id, e)

    # ── Fetch Nifty context for EOD NAV record ─────────────────────────────
    nifty_close = 0.0
    nifty_1d_pct = 0.0
    try:
        nifty_df = fetch_nifty50_index(days=5)
        if nifty_df is not None and not nifty_df.empty:
            closes = nifty_df["close"].dropna()
            nifty_close = float(closes.iloc[-1])
            if len(closes) >= 2:
                nifty_1d_pct = float((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100)
    except Exception as e:
        logger.warning("[squareoff] Nifty fetch failed: %s", e)

    # LLM cost for today (already in morning run's nav_item)
    morning_nav = dynamo.get_nav(trade_date_str)
    total_llm_cost = float(morning_nav.get("total_llm_cost_usd_today", 0.0)) if morning_nav else 0.0

    # ── Write final EOD NAV ────────────────────────────────────────────────
    if not settings.dry_run:
        _write_eod_nav(
            trade_date_str=trade_date_str,
            cash_inr=ledger.cash_inr,
            prev_nav_inr=float(nav_item.get("nav_inr", settings.initial_capital_inr)) if nav_item else settings.initial_capital_inr,
            trades=completed_trades,
            nifty_close=nifty_close,
            nifty_1d_pct=nifty_1d_pct,
            total_llm_cost_usd=total_llm_cost,
        )

    total_net_pnl = sum(t.net_pnl_inr for t in completed_trades)
    wins = sum(1 for t in completed_trades if t.net_pnl_inr > 0)

    completed_at = datetime.now(IST).isoformat()
    logger.info(
        "=== Squareoff complete %s | %d trades | wins=%d | net P&L=₹%.0f | NAV=₹%.0f ===",
        trade_date_str, len(completed_trades), wins, total_net_pnl, ledger.cash_inr,
    )
    return {
        "trade_date": trade_date_str,
        "trades_closed": len(completed_trades),
        "wins": wins,
        "net_pnl_inr": round(total_net_pnl, 2),
        "nav_inr": round(ledger.cash_inr, 2),
        "completed_at": completed_at,
    }


def _write_eod_nav(
    trade_date_str: str,
    cash_inr: float,
    prev_nav_inr: float,
    trades: list,
    nifty_close: float,
    nifty_1d_pct: float,
    total_llm_cost_usd: float,
) -> None:
    """Write the final end-of-day NAV record to DynamoDB (equity_value_inr = 0)."""
    import time as _time

    wins = sum(1 for t in trades if t.net_pnl_inr > 0)
    losses = len(trades) - wins
    gross_pnl = sum(t.gross_pnl_inr for t in trades)
    total_costs = sum(t.total_cost_inr for t in trades)
    net_pnl = sum(t.net_pnl_inr for t in trades)
    daily_return = (cash_inr - prev_nav_inr) / prev_nav_inr * 100 if prev_nav_inr > 0 else 0.0

    item = {
        "PK": f"DATE#{trade_date_str}",
        "SK": "PORTFOLIO",
        "nav_inr": round(cash_inr, 2),
        "cash_inr": round(cash_inr, 2),
        "equity_value_inr": 0.0,          # always 0 at EOD — all MIS closed
        "intraday_trades_count": len(trades),
        "intraday_wins": wins,
        "intraday_losses": losses,
        "gross_pnl_inr": round(gross_pnl, 2),
        "total_costs_inr": round(total_costs, 2),
        "net_pnl_inr": round(net_pnl, 2),
        "daily_return_pct": round(daily_return, 4),
        "nifty50_close": nifty_close,
        "nifty50_daily_return_pct": round(nifty_1d_pct, 4),
        "total_llm_cost_usd_today": total_llm_cost_usd,
        "squareoff_complete": True,
        "ttl": int(_time.time()) + 30 * 24 * 3600,
    }
    try:
        dynamo.put_nav(item)
        logger.info(
            "[squareoff] EOD NAV written: ₹%.0f | net P&L ₹%.0f | %d trades",
            cash_inr, net_pnl, len(trades),
        )
    except Exception as e:
        logger.error("[squareoff] Failed to write EOD NAV: %s", e)
