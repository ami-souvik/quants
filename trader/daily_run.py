"""
ECS Fargate entry point for the daily paper-trading run.

Triggered by EventBridge at 17:00 IST Mon–Fri (11:30 UTC).

CRITICAL SAFETY GATES (checked before anything else):
1. PAPER_TRADING_MODE must be True — exits hard if false.
2. Kite order-placement methods are NEVER imported or called in Phase 1.
3. Daily run is idempotent — running twice on the same day is safe.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

# setup_logging must run before any other trader imports so all loggers inherit
# the handlers (file + console) from the root logger.
from trader.logging_config import setup_logging

IST = ZoneInfo("Asia/Kolkata")

# Write to a date-stamped log file so each day's run is isolated.
# e.g. logs/trader-2026-06-06.log
# Falls back to the LOG_FILE env var (or logs/trader.log) only when LOG_FILE
# is explicitly set, so local/API usage stays unaffected.
_run_date = datetime.now(IST).date().isoformat()
_default_log_file = f"logs/trader-{_run_date}.log"
_log_file = os.environ.get("LOG_FILE") or _default_log_file
setup_logging(log_file=_log_file)
logger = logging.getLogger(__name__)


# ── Phase 1 safety gate ────────────────────────────────────────────────────────

def _enforce_paper_trading_mode() -> None:
    """
    CRITICAL: Abort immediately if PAPER_TRADING_MODE is not True.
    This gate must be the first thing that runs — before any imports that could
    trigger broker connectivity.
    """
    raw = os.environ.get("PAPER_TRADING_MODE", "true").lower()
    if raw not in ("1", "true", "yes"):
        msg = (
            "PAPER_TRADING_MODE is not set to True. "
            "Phase 1 only runs in paper mode. Set PAPER_TRADING_MODE=true and restart."
        )
        logger.critical(msg)
        sys.exit(1)


def _check_dry_run() -> bool:
    raw = os.environ.get("DRY_RUN", "false").lower()
    return raw in ("1", "true", "yes")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    _enforce_paper_trading_mode()
    dry_run = _check_dry_run()

    if dry_run:
        logger.info("DRY_RUN mode: DynamoDB writes and fills are no-ops.")

    # Override settings for dry-run before loading anything else
    if dry_run:
        os.environ["DRY_RUN"] = "true"

    # Import after gate check so no broker module has a chance to initialise
    from trader.orchestration.runner import run_daily

    trade_date = os.environ.get("TRADE_DATE")  # allow override for backfill runs
    if trade_date:
        logger.info("TRADE_DATE override: %s", trade_date)
    else:
        trade_date = datetime.now(IST).date().isoformat()

    run_started_at = datetime.now(IST).isoformat()
    logger.info("Paper trading run starting for %s (dry_run=%s)", trade_date, dry_run)

    try:
        run_state = run_daily(trade_date)
    except KeyboardInterrupt:
        logger.info("Run interrupted by user.")
        _upload_log(_log_file, run_started_at)
        return 0
    except Exception as e:
        logger.exception("Daily run failed with unhandled exception: %s", e)
        _upload_log(_log_file, run_started_at)
        return 1

    completed = run_state.get("completed_at")
    cost = run_state.get("total_cost_usd", 0.0)
    logger.info("Run finished at %s | total LLM cost today: $%.4f", completed, cost)

    if cost > 1.00:
        logger.warning("Daily LLM cost $%.4f exceeds $1.00 budget — review model usage.", cost)

    # Upload the completed log file to S3 so the dashboard can retrieve it.
    # Uses run_started_at (not completed_at) as the timestamp — this makes the
    # S3 key stable even if the run is retried, since started_at is set once.
    _upload_log(_log_file, run_started_at)

    return 0


def _upload_log(log_file: str, run_started_at: str) -> None:
    """Upload the local log file to S3. Non-fatal — logs errors but never raises."""
    try:
        from trader.storage.s3 import upload_log
        upload_log(log_file, run_started_at)
    except Exception as exc:
        logger.error("Log S3 upload failed: %s", exc)


if __name__ == "__main__":
    sys.exit(main())
