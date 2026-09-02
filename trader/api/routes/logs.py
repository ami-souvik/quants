"""
Log endpoints — S3-backed, CloudWatch-style.

Each daily run uploads its log file to S3 at:
    logs/{date}/run-{datetime}.log

Two endpoints:

  GET /api/logs/sessions?date=YYYY-MM-DD
      Lists all run sessions (log objects) for a date, newest first.
      Each session includes summary stats: line_count, error_count, warning_count.

  GET /api/logs/session?key=logs/2026-06-13/run-...log
      Downloads the full log content for one session and returns parsed lines.

Legacy endpoint kept for backwards compat:
  GET /api/logs?date=YYYY-MM-DD
      Falls back to reading the local file if no S3 sessions exist.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from trader.api.schemas import (
    LogLine,
    LogSession,
    LogSessionDetailResponse,
    LogSessionsResponse,
    LogsResponse,
)
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


def _parse_text(text: str, date_filter: str | None = None) -> list[LogLine]:
    lines = []
    for raw in text.splitlines():
        parsed = _parse_line(raw)
        if parsed is None:
            continue
        if date_filter and not parsed.timestamp.startswith(date_filter):
            continue
        lines.append(parsed)
    return lines


def _summarise(lines: list[LogLine]) -> dict:
    errors = sum(1 for l in lines if l.level in ("ERROR", "CRITICAL"))
    warnings = sum(1 for l in lines if l.level == "WARNING")
    return {
        "line_count": len(lines),
        "error_count": errors,
        "warning_count": warnings,
        "has_error": errors > 0,
    }


# ── PostgreSQL-backed session endpoints ──────────────────────────────────────

@router.get("/logs/sessions", response_model=LogSessionsResponse)
def list_log_sessions(
    date_str: str = Query(
        default=None,
        alias="date",
        description="ISO date (YYYY-MM-DD). Defaults to today.",
    ),
) -> LogSessionsResponse:
    """
    List all log sessions for a date from PostgreSQL, newest first.
    """
    from trader.storage import postgres

    target_date = date_str or date.today().isoformat()
    try:
        raw_sessions = postgres.list_log_sessions(target_date)
    except Exception as e:
        logger.warning("Failed to list log sessions from PostgreSQL: %s", e)
        raw_sessions = []

    sessions: list[LogSession] = [
        LogSession(
            key=s["key"],
            run_datetime=s["run_datetime"],
            size_bytes=0,
            last_modified=s.get("last_modified", ""),
            line_count=s.get("line_count", 0),
            error_count=s.get("error_count", 0),
            warning_count=s.get("warning_count", 0),
            has_error=s.get("has_error", False),
        )
        for s in raw_sessions
    ]

    return LogSessionsResponse(
        date=target_date,
        sessions=sessions,
        total=len(sessions),
    )


@router.get("/logs/session", response_model=LogSessionDetailResponse)
def get_log_session(
    key: str = Query(..., description="Full key of the log session"),
) -> LogSessionDetailResponse:
    """
    Return the parsed log lines for one session from PostgreSQL or local file.
    """
    from trader.storage import postgres

    # Extract date and datetime from key
    date_part = ""
    run_dt = ""
    try:
        parts = key.split("/")
        if len(parts) >= 2:
            date_part = parts[1]
        name = parts[-1].removeprefix("run-").removesuffix(".log")
        run_dt = name
    except Exception:
        date_part = date.today().isoformat()
        run_dt = date_part

    lines_data: list[dict] = []
    try:
        lines_data = postgres.get_daily_logs(date_part)
    except Exception as e:
        logger.warning("Failed to fetch logs from DB: %s", e)

    lines: list[LogLine] = [
        LogLine(
            timestamp=l.get("timestamp", ""),
            level=l.get("level", "INFO"),
            logger=l.get("logger", "trader"),
            message=l.get("message", ""),
            raw=l.get("raw", ""),
        )
        for l in lines_data
    ]
    stats = _summarise(lines)

    return LogSessionDetailResponse(
        key=key,
        run_datetime=run_dt,
        lines=lines,
        total=len(lines),
        **stats,
    )



# ── Legacy endpoint (local file fallback) ─────────────────────────────────────

def _resolve_log_path(target_date: str) -> Path:
    settings = get_settings()
    base_dir = Path(settings.log_file).parent
    if not base_dir.is_absolute():
        base_dir = Path(os.getcwd()) / base_dir
    dated = base_dir / f"trader-{target_date}.log"
    if dated.exists():
        return dated
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
    Legacy endpoint: reads from the local log file.
    Kept for backwards compat and local dev (no S3 needed).
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
