"""
PostgreSQL / Supabase storage helpers for the NSE LLM Trader.

Clean relational table storage with native JSONB support:
  - positions
  - decisions
  - trades
  - nav_history
  - daily_reports
  - daily_logs
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
from trader.config.settings import get_settings

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def _get_connection():
    """Create a database connection to Supabase / PostgreSQL."""
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        raise ImportError(
            "psycopg is required for database operations. "
            "Install it via: pip install 'psycopg[binary]'"
        )

    settings = get_settings()
    db_url = settings.database_url
    if not db_url:
        raise ValueError("DATABASE_URL is not configured in settings or environment.")
    return psycopg.connect(db_url, row_factory=dict_row)


def _serialize_for_json(obj: Any) -> Any:
    """Helper to convert Decimals, datetimes, dates to JSON-serializable types."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _serialize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_for_json(v) for v in obj]
    return obj


# ─── Positions ───────────────────────────────────────────────────────────────

def put_position(item: dict) -> None:
    """Upsert a position record into the positions table."""
    settings = get_settings()
    if settings.dry_run:
        logger.debug("[DRY RUN] put_position → %s", item.get("ticker"))
        return

    ticker = item.get("ticker", "").upper()
    qty = int(item.get("qty", 0))
    avg_price = float(item.get("avg_price", 0.0))
    days_held = int(item.get("days_held", 0))
    current_price = float(item["current_price"]) if item.get("current_price") is not None else None
    unrealized_pnl_inr = float(item.get("unrealized_pnl_inr", 0.0))
    unrealized_pnl_pct = float(item.get("unrealized_pnl_pct", 0.0))
    stop_loss_price = float(item.get("stop_loss_price", 0.0))
    target_price = float(item.get("target_price", 0.0))
    kill_conditions = json.dumps(item.get("kill_conditions", []))
    entry_date = item.get("entry_date")
    horizon_days = int(item.get("horizon_days", 5))
    sector = item.get("sector", "")
    is_closed = bool(item.get("is_closed", False) or qty == 0)

    sql = """
    INSERT INTO positions (
        ticker, qty, avg_price, days_held, current_price,
        unrealized_pnl_inr, unrealized_pnl_pct, stop_loss_price, target_price,
        kill_conditions, entry_date, horizon_days, sector, is_closed, updated_at
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, NOW()
    )
    ON CONFLICT (ticker) DO UPDATE SET
        qty = EXCLUDED.qty,
        avg_price = EXCLUDED.avg_price,
        days_held = EXCLUDED.days_held,
        current_price = EXCLUDED.current_price,
        unrealized_pnl_inr = EXCLUDED.unrealized_pnl_inr,
        unrealized_pnl_pct = EXCLUDED.unrealized_pnl_pct,
        stop_loss_price = EXCLUDED.stop_loss_price,
        target_price = EXCLUDED.target_price,
        kill_conditions = EXCLUDED.kill_conditions,
        entry_date = EXCLUDED.entry_date,
        horizon_days = EXCLUDED.horizon_days,
        sector = EXCLUDED.sector,
        is_closed = EXCLUDED.is_closed,
        updated_at = NOW();
    """
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    ticker, qty, avg_price, days_held, current_price,
                    unrealized_pnl_inr, unrealized_pnl_pct, stop_loss_price, target_price,
                    kill_conditions, entry_date, horizon_days, sector, is_closed
                ),
            )
        conn.commit()


def get_position(ticker: str, date_str: str | None = None) -> dict | None:
    """Fetch position for a ticker. Returns None if not found or closed."""
    sql = "SELECT * FROM positions WHERE ticker = %s AND is_closed = FALSE;"
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            row = cur.fetchone()
            if row:
                # Convert Decimals/Dates for API compatibility
                row = _serialize_for_json(row)
            return row


def get_open_positions() -> list[dict]:
    """Return all currently open positions (qty > 0 and is_closed = false)."""
    sql = "SELECT * FROM positions WHERE is_closed = FALSE AND qty > 0 ORDER BY ticker ASC;"
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            return [_serialize_for_json(r) for r in rows]


def delete_position(ticker: str) -> None:
    """Mark position as closed (or delete)."""
    settings = get_settings()
    if settings.dry_run:
        return
    sql = "UPDATE positions SET is_closed = TRUE, qty = 0, updated_at = NOW() WHERE ticker = %s;"
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
        conn.commit()


# ─── Decisions ───────────────────────────────────────────────────────────────

def put_decision(item: dict) -> None:
    """Insert or update an agent decision."""
    settings = get_settings()
    if settings.dry_run:
        return

    # DynamoDB compatibility extraction
    date_val = item.get("date") or (item.get("PK", "").removeprefix("DATE#") if "PK" in item else None)
    ticker = item.get("ticker", "")
    agent = item.get("agent", "")
    model = item.get("model")

    # If extracted from Dynamo format
    if not ticker and "SK" in item:
        # SK format: TICKER#{symbol}#AGENT#{name}
        parts = item["SK"].split("#")
        if len(parts) >= 4:
            ticker = parts[1]
            agent = parts[3]

    clean_item = _serialize_for_json(item)

    sql = """
    INSERT INTO decisions (date, ticker, agent, model, decision_data, created_at)
    VALUES (%s, %s, %s, %s, %s::jsonb, NOW())
    ON CONFLICT (date, ticker, agent) DO UPDATE SET
        model = EXCLUDED.model,
        decision_data = EXCLUDED.decision_data,
        created_at = NOW();
    """
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (date_val, ticker, agent, model, json.dumps(clean_item)))
        conn.commit()


def get_decision(date_str: str, ticker: str, agent: str) -> dict | None:
    """Fetch a single agent decision."""
    sql = "SELECT decision_data FROM decisions WHERE date = %s AND ticker = %s AND agent = %s;"
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (date_str, ticker, agent))
            row = cur.fetchone()
            return row["decision_data"] if row else None


def get_decisions_for_date(date_str: str) -> list[dict]:
    """Return all agent decision dicts for a given trading date."""
    sql = "SELECT decision_data FROM decisions WHERE date = %s ORDER BY ticker ASC, agent ASC;"
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (date_str,))
            rows = cur.fetchall()
            return [r["decision_data"] for r in rows]


# ─── Trades ─────────────────────────────────────────────────────────────────

def put_trade(item: dict) -> None:
    """Insert a simulated trade fill."""
    settings = get_settings()
    if settings.dry_run:
        return

    trade_id = item.get("trade_id") or item.get("SK", "").removeprefix("TRADE#") or str(datetime.now(IST).timestamp())
    date_val = item.get("date") or (item.get("PK", "").removeprefix("DATE#") if "PK" in item else str(date.today()))
    ticker = item.get("ticker", "")
    side = item.get("side", item.get("action", "BUY"))
    qty = int(item.get("qty", 0))
    price = float(item.get("price", item.get("fill_price", 0.0)))
    trade_value_inr = float(item.get("trade_value_inr", 0.0))
    cost_inr = float(item.get("cost_inr", item.get("simulated_cost_inr", 0.0)))
    cost_bps = float(item.get("cost_bps", item.get("simulated_cost_bps", 0.0)))
    slippage_bps = float(item.get("slippage_bps", 0.0))
    charges_breakdown = json.dumps(_serialize_for_json(item.get("charges_breakdown", {})))

    sql = """
    INSERT INTO trades (
        trade_id, date, ticker, side, qty, price, trade_value_inr,
        cost_inr, cost_bps, slippage_bps, charges_breakdown, created_at
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW()
    )
    ON CONFLICT (trade_id) DO UPDATE SET
        price = EXCLUDED.price,
        trade_value_inr = EXCLUDED.trade_value_inr,
        cost_inr = EXCLUDED.cost_inr;
    """
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (trade_id, date_val, ticker, side, qty, price, trade_value_inr, cost_inr, cost_bps, slippage_bps, charges_breakdown)
            )
        conn.commit()


def get_trades_for_date(date_str: str) -> list[dict]:
    """Return all trades for a given date."""
    sql = "SELECT * FROM trades WHERE date = %s ORDER BY created_at ASC;"
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (date_str,))
            rows = cur.fetchall()
            return [_serialize_for_json(r) for r in rows]


def get_all_trades() -> list[dict]:
    """Return all trades in history."""
    sql = "SELECT * FROM trades ORDER BY date ASC, created_at ASC;"
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            return [_serialize_for_json(r) for r in rows]


# ─── NAV History ────────────────────────────────────────────────────────────

def put_nav(item: dict) -> None:
    """Save daily portfolio NAV snapshot."""
    settings = get_settings()
    if settings.dry_run:
        return

    date_val = item.get("date") or (item.get("PK", "").removeprefix("DATE#") if "PK" in item else str(date.today()))
    nav_inr = float(item.get("nav_inr", 0.0))
    cash_inr = float(item.get("cash_inr", 0.0))
    equity_value_inr = float(item.get("equity_value_inr", 0.0))
    daily_return_pct = float(item.get("daily_return_pct", 0.0))
    cumulative_return_pct = float(item.get("cumulative_return_pct", 0.0))
    drawdown_pct = float(item.get("drawdown_pct", 0.0))
    open_positions = int(item.get("open_positions", 0))

    sql = """
    INSERT INTO nav_history (
        date, nav_inr, cash_inr, equity_value_inr, daily_return_pct,
        cumulative_return_pct, drawdown_pct, open_positions, created_at
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, NOW()
    )
    ON CONFLICT (date) DO UPDATE SET
        nav_inr = EXCLUDED.nav_inr,
        cash_inr = EXCLUDED.cash_inr,
        equity_value_inr = EXCLUDED.equity_value_inr,
        daily_return_pct = EXCLUDED.daily_return_pct,
        cumulative_return_pct = EXCLUDED.cumulative_return_pct,
        drawdown_pct = EXCLUDED.drawdown_pct,
        open_positions = EXCLUDED.open_positions,
        created_at = NOW();
    """
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (date_val, nav_inr, cash_inr, equity_value_inr, daily_return_pct, cumulative_return_pct, drawdown_pct, open_positions)
            )
        conn.commit()


def get_nav(date_str: str) -> dict | None:
    """Fetch NAV snapshot for a date."""
    sql = "SELECT * FROM nav_history WHERE date = %s;"
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (date_str,))
            row = cur.fetchone()
            return _serialize_for_json(row) if row else None


def get_nav_history(from_date: str | None = None, to_date: str | None = None) -> list[dict]:
    """Fetch NAV time series."""
    sql = "SELECT * FROM nav_history"
    params = []
    if from_date and to_date:
        sql += " WHERE date >= %s AND date <= %s"
        params.extend([from_date, to_date])
    elif from_date:
        sql += " WHERE date >= %s"
        params.append(from_date)
    elif to_date:
        sql += " WHERE date <= %s"
        params.append(to_date)
    sql += " ORDER BY date ASC;"

    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            return [_serialize_for_json(r) for r in rows]


def daily_run_already_completed(date_str: str) -> bool:
    """Check if the daily run for date_str is already completed."""
    nav = get_nav(date_str)
    return nav is not None


# ─── Daily Reports ──────────────────────────────────────────────────────────

def save_daily_report(report: dict) -> None:
    """Persist daily report to daily_reports table."""
    settings = get_settings()
    if settings.dry_run:
        logger.info("[DRY RUN] save_daily_report for %s", report.get("run_date"))
        return

    run_date = report.get("run_date")
    started_at = report.get("started_at")
    completed_at = report.get("completed_at")
    duration_s = float(report.get("duration_seconds", 0.0))
    macro = json.dumps(_serialize_for_json(report.get("macro", {})))
    summary = json.dumps(_serialize_for_json(report.get("summary", {})))
    run_errors = json.dumps(_serialize_for_json(report.get("run_errors", [])))
    tickers = json.dumps(_serialize_for_json(report.get("tickers", [])))

    sql = """
    INSERT INTO daily_reports (
        run_date, started_at, completed_at, duration_seconds,
        macro, summary, run_errors, tickers, created_at
    ) VALUES (
        %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, NOW()
    )
    ON CONFLICT (run_date) DO UPDATE SET
        started_at = EXCLUDED.started_at,
        completed_at = EXCLUDED.completed_at,
        duration_seconds = EXCLUDED.duration_seconds,
        macro = EXCLUDED.macro,
        summary = EXCLUDED.summary,
        run_errors = EXCLUDED.run_errors,
        tickers = EXCLUDED.tickers,
        created_at = NOW();
    """
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_date, started_at, completed_at, duration_s, macro, summary, run_errors, tickers))
        conn.commit()
    logger.info("Daily report persisted to PostgreSQL for %s", run_date)


def get_daily_report(date_str: str) -> dict | None:
    """Fetch daily report for date string."""
    sql = "SELECT * FROM daily_reports WHERE run_date = %s;"
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (date_str,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "run_date": str(row["run_date"]),
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                "duration_seconds": float(row["duration_seconds"] or 0),
                "macro": row["macro"] or {},
                "summary": row["summary"] or {},
                "run_errors": row["run_errors"] or [],
                "tickers": row["tickers"] or [],
            }


# ─── Daily Logs ─────────────────────────────────────────────────────────────

def save_daily_log(
    run_datetime: str,
    date_str: str,
    lines: list[dict],
    error_count: int = 0,
    warning_count: int = 0,
) -> None:
    """Save parsed log lines for a run session."""
    settings = get_settings()
    if settings.dry_run:
        return

    sql = """
    INSERT INTO daily_logs (
        run_datetime, date, lines, total_lines, error_count, warning_count, created_at
    ) VALUES (
        %s, %s, %s::jsonb, %s, %s, %s, NOW()
    )
    ON CONFLICT (run_datetime) DO UPDATE SET
        lines = EXCLUDED.lines,
        total_lines = EXCLUDED.total_lines,
        error_count = EXCLUDED.error_count,
        warning_count = EXCLUDED.warning_count;
    """
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (run_datetime, date_str, json.dumps(_serialize_for_json(lines)), len(lines), error_count, warning_count)
            )
        conn.commit()


def get_daily_logs(date_str: str) -> list[dict]:
    """Fetch log lines for a date."""
    sql = "SELECT lines FROM daily_logs WHERE date = %s ORDER BY created_at DESC LIMIT 1;"
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (date_str,))
            row = cur.fetchone()
            return row["lines"] if row else []


def list_log_sessions(date_str: str) -> list[dict]:
    """List all log sessions for a date."""
    sql = "SELECT run_datetime, total_lines, error_count, warning_count, created_at FROM daily_logs WHERE date = %s ORDER BY created_at DESC;"
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (date_str,))
            rows = cur.fetchall()
            return [
                {
                    "key": f"logs/{date_str}/run-{r['run_datetime']}.log",
                    "run_datetime": r["run_datetime"],
                    "line_count": r["total_lines"],
                    "error_count": r["error_count"],
                    "warning_count": r["warning_count"],
                    "has_error": r["error_count"] > 0,
                    "last_modified": r["created_at"].isoformat() if r["created_at"] else "",
                }
                for r in rows
            ]
