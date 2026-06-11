"""
DEPRECATED — use morning_run.py instead.

This module is a backward-compatibility shim. The single daily_run.py has been
split into two separate ECS entry points:

  morning_run.py    — 08:45 IST: decisions + simulated BUY fills
  squareoff_run.py  — 15:20 IST: close all MIS positions + EOD P&L

daily_run.py remains here temporarily so existing tooling (Makefile, local
scripts) keeps working. It will be removed once morning_run.py is the sole
ECS CMD.
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
    logger.warning(
        "daily_run.py is deprecated — use morning_run.py (decisions) and "
        "squareoff_run.py (EOD close). Forwarding to morning_run.main()."
    )
    from trader.morning_run import main as morning_main
    return morning_main()


if __name__ == "__main__":
    sys.exit(main())
