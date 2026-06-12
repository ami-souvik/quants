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


# ── S3-backed endpoints ───────────────────────────────────────────────────────

@router.get("/logs/sessions", response_model=LogSessionsResponse)
def list_log_sessions(
    date_str: str = Query(
        default=None,
        alias="date",
        description="ISO date (YYYY-MM-DD). Defaults to today.",
    ),
) -> LogSessionsResponse:
    """
    List all log sessions for a date from S3, newest first.
    Each session includes line count, error count, and warning count.
    """
    from trader.storage.s3 import download_log, list_log_sessions

    target_date = date_str or date.today().isoformat()
    raw_sessions = list_log_sessions(target_date)

    sessions: list[LogSession] = []
    for s in raw_sessions:
        # Download each session to compute summary stats.
        # For large deployments a pre-computed stats sidecar would be better,
        # but for 1–3 daily runs this is fast enough.
        try:
            text = download_log(s["key"])
            lines = _parse_text(text)
            stats = _summarise(lines)
        except Exception as exc:
            logger.warning("Could not read log session %s for summary: %s", s["key"], exc)
            stats = {"line_count": 0, "error_count": 0, "warning_count": 0, "has_error": False}

        sessions.append(LogSession(
            key=s["key"],
            run_datetime=s["run_datetime"],
            size_bytes=s["size_bytes"],
            last_modified=s["last_modified"],
            **stats,
        ))

    return LogSessionsResponse(
        date=target_date,
        sessions=sessions,
        total=len(sessions),
    )


@router.get("/logs/session", response_model=LogSessionDetailResponse)
def get_log_session(
    key: str = Query(..., description="Full S3 key of the log session"),
) -> LogSessionDetailResponse:
    """
    Download and return the full parsed log for one session.
    """
    from trader.storage.s3 import download_log

    try:
        text = download_log(key)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Log session not found: {exc}")

    lines = _parse_text(text)
    stats = _summarise(lines)

    # Infer run_datetime from the key name
    name = key.split("/")[-1]
    raw_dt = name.removeprefix("run-").removesuffix(".log")
    date_part, _, time_part = raw_dt.partition("T")
    run_dt = f"{date_part}T{time_part.replace('-', ':')}" if time_part else date_part

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
