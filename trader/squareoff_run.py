"""
ECS Fargate entry point — mandatory squareoff run (15:20 IST, Mon–Fri).

Triggered by EventBridge: cron(50 9 ? * MON-FRI *)  [09:50 UTC = 15:20 IST]

Reads all open intraday MIS positions from Redis, simulates SELL fills at
the most recent closing price (15:15 IST proxy), computes round-trip P&L,
writes completed trades to DynamoDB, and updates nav_daily with final EOD
figures (equity_value_inr = 0 — no overnight holdings).

CRITICAL: This run MUST complete unconditionally — it is the only safety
net preventing phantom overnight positions in the simulation. It runs
regardless of P&L, regardless of whether the morning run completed, and
regardless of any circuit-breaker state.

Safety gates:
1. PAPER_TRADING_MODE must be True — exits hard if false.
2. kiteconnect order-placement methods are NEVER imported in Phase 1.
3. This run is idempotent — running twice on the same day is safe.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from trader.logging_config import setup_logging

IST = ZoneInfo("Asia/Kolkata")

_run_date = datetime.now(IST).date().isoformat()
_default_log_file = f"logs/trader-{_run_date}.log"
_log_file = os.environ.get("LOG_FILE") or _default_log_file
setup_logging(log_file=_log_file)
logger = logging.getLogger(__name__)


# ── Phase 1 safety gate ────────────────────────────────────────────────────────

def _enforce_paper_trading_mode() -> None:
    """
    CRITICAL: Abort immediately if PAPER_TRADING_MODE is not True.
    Must be checked before any import that could reach broker code.
    """
    raw = os.environ.get("PAPER_TRADING_MODE", "true").lower()
    if raw not in ("1", "true", "yes"):
        logger.critical(
            "PAPER_TRADING_MODE is not True. "
            "Phase 1 only runs in paper mode. Set PAPER_TRADING_MODE=true and restart."
        )
        sys.exit(1)


def _check_dry_run() -> bool:
    raw = os.environ.get("DRY_RUN", "false").lower()
    return raw in ("1", "true", "yes")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    _enforce_paper_trading_mode()
    dry_run = _check_dry_run()

    if dry_run:
        logger.info("DRY_RUN mode: DynamoDB writes are no-ops.")
        os.environ["DRY_RUN"] = "true"

    from trader.orchestration.runner import run_squareoff

    trade_date = os.environ.get("TRADE_DATE")
    if trade_date:
        logger.info("TRADE_DATE override: %s", trade_date)
    else:
        trade_date = datetime.now(IST).date().isoformat()

    logger.info(
        "Squareoff run starting for %s (paper_mode=True, dry_run=%s)",
        trade_date, dry_run,
    )

    try:
        result = run_squareoff(trade_date)
    except KeyboardInterrupt:
        logger.info("Squareoff run interrupted by user.")
        return 0
    except Exception as e:
        logger.exception("Squareoff run failed: %s", e)
        return 1

    trades = result.get("trades_closed", 0)
    net_pnl = result.get("net_pnl_inr", 0.0)
    nav = result.get("nav_inr", 0.0)
    completed = result.get("completed_at", "—")

    if result.get("already_completed"):
        logger.info("Squareoff already completed for %s — no-op.", trade_date)
        return 0

    logger.info(
        "Squareoff finished: %d trades closed | net P&L ₹%.0f | EOD NAV ₹%.0f | at %s",
        trades, net_pnl, nav, completed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
