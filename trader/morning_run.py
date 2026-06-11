"""
ECS Fargate entry point — morning decisions run (08:45 IST, Mon–Fri).

Triggered by EventBridge: cron(15 3 ? * MON-FRI *)  [03:15 UTC = 08:45 IST]

Produces BUY/SKIP decisions for all 15 tickers, simulates BUY fills,
and persists open intraday positions to Redis.

The companion squareoff_run.py runs at 15:20 IST to close all positions.

CRITICAL SAFETY GATES (checked before any other imports):
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
    Must be the first check before any import that could reach broker code.
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
        logger.info("DRY_RUN mode: fills and DynamoDB writes are no-ops.")
        os.environ["DRY_RUN"] = "true"

    from trader.orchestration.runner import run_morning

    trade_date = os.environ.get("TRADE_DATE")
    if trade_date:
        logger.info("TRADE_DATE override: %s", trade_date)
    else:
        trade_date = datetime.now(IST).date().isoformat()

    logger.info(
        "Morning run starting for %s (paper_mode=True, dry_run=%s)",
        trade_date, dry_run,
    )

    try:
        run_state = run_morning(trade_date)
    except KeyboardInterrupt:
        logger.info("Morning run interrupted by user.")
        return 0
    except Exception as e:
        logger.exception("Morning run failed: %s", e)
        return 1

    completed = run_state.get("completed_at")
    cost = run_state.get("total_cost_usd", 0.0)
    logger.info("Morning run finished at %s | total LLM cost: $%.4f", completed, cost)

    if cost > 1.00:
        logger.warning(
            "Daily LLM cost $%.4f exceeds $1.00 budget — review model usage.", cost
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
