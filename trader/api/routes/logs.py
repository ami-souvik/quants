"""
GET /api/logs — daily run log viewer.

Each daily run writes to its own date-stamped file:
    logs/trader-YYYY-MM-DD.log

This endpoint resolves the correct file for the requested date and returns
all parsed log lines. Falls back to the legacy trader.log if the dated file
doesn't exist (backwards-compat for old runs).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Query

from trader.api.schemas import LogLine, LogsResponse
from trader.config.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["logs"])

# Matches: 2026-06-06T12:06:15 INFO     trader.foo — message
_LOG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"\s+(?P<level>[A-Z]+)"
    r"\s+(?P<logger>\S+)"
    r"\s+[—\-]+\s*"
    r"(?P<message>.+)$"
)


def _parse_line(raw: str) -> LogLine | None:
    raw = raw.rstrip("\n")
    m = _LOG_RE.match(raw)
    if not m:
        return None
    return LogLine(
        timestamp=m.group("ts"),
        level=m.group("level"),
        logger=m.group("logger"),
        message=m.group("message"),
        raw=raw,
    )


def _resolve_log_path(target_date: str) -> Path:
    """
    Returns the best log file path for the given date.

    Priority:
    1. logs/trader-YYYY-MM-DD.log  (date-stamped — produced by daily_run.py)
    2. settings.log_file           (legacy fallback — trader.log)
    """
    settings = get_settings()
    base_dir = Path(settings.log_file).parent
    if not base_dir.is_absolute():
        base_dir = Path(os.getcwd()) / base_dir

    dated = base_dir / f"trader-{target_date}.log"
    if dated.exists():
        return dated

    # Legacy fallback
    legacy = Path(settings.log_file)
    if not legacy.is_absolute():
        legacy = Path(os.getcwd()) / legacy
    return legacy


@router.get("/logs", response_model=LogsResponse)
def get_logs(
    date_str: str = Query(
        default=None,
        alias="date",
        description="ISO date (YYYY-MM-DD). Defaults to today.",
    ),
) -> LogsResponse:
    """
    Returns all log lines for the requested date.

    Reads from logs/trader-YYYY-MM-DD.log when available; falls back to
    the legacy trader.log and filters by timestamp prefix for old runs.
    """
    target_date = date_str or date.today().isoformat()
    log_path = _resolve_log_path(target_date)

    lines: list[LogLine] = []
    has_error = False

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                parsed = _parse_line(raw)
                if parsed is None:
                    continue
                # For dated files every line belongs to the date; for the
                # legacy file we still need to filter by timestamp prefix.
                if not parsed.timestamp.startswith(target_date):
                    continue
                lines.append(parsed)
                if parsed.level in ("ERROR", "CRITICAL"):
                    has_error = True
    except FileNotFoundError:
        logger.warning("Log file not found at %s", log_path)
    except OSError as exc:
        logger.warning("Could not read log file: %s", exc)

    return LogsResponse(
        date=target_date,
        lines=lines,
        total=len(lines),
        has_error=has_error,
    )
