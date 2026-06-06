"""
GET /api/logs — daily run log viewer.

Reads trader.log from disk and returns lines filtered to a specific date.
The log file is bind-mounted from the container at settings.log_file.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date

from fastapi import APIRouter, Query

from trader.api.schemas import LogLine, LogsResponse
from trader.config.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["logs"])

# Matches lines like: 2026-06-06T12:06:15 INFO     trader.foo — message
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


@router.get("/logs", response_model=LogsResponse)
def get_logs(
    date_str: str = Query(
        default=None,
        alias="date",
        description="ISO date (YYYY-MM-DD). Defaults to today.",
    ),
) -> LogsResponse:
    """
    Returns all log lines that belong to the requested date.

    Lines are matched by their leading timestamp prefix so only the
    lines for that calendar day are returned — no cross-day bleed.
    """
    settings = get_settings()
    target_date = date_str or date.today().isoformat()

    log_path = settings.log_file
    # Resolve relative path against CWD (works both in Docker and locally)
    if not os.path.isabs(log_path):
        log_path = os.path.join(os.getcwd(), log_path)

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
