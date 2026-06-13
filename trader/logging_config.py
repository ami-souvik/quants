"""
Centralised logging configuration for the NSE trader.

Call setup_logging() exactly once at the top of each entry point
(daily_run.py, main.py).  Subsequent calls from the same process
are no-ops because the root logger keeps its handlers.

Outputs:
  - StreamHandler → stdout  (always on — visible in docker logs / ECS CloudWatch)
  - FileHandler   → LOG_FILE opened with mode='w' (truncate on open — each run
                    starts with a clean file, never appends to a previous run)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

_ALREADY_CONFIGURED = False

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def setup_logging(
    level: str | None = None,
    log_file: str | None = None,
) -> None:
    """
    Configure the root logger.  Safe to call multiple times — only the
    first call has any effect.

    Args:
        level:    Log level string ("DEBUG", "INFO", …).
                  Defaults to the LOG_LEVEL env var, then "INFO".
        log_file: Path to the log file (opened with mode='w' — always fresh).
                  Defaults to the LOG_FILE env var, then "logs/trader.log".
                  Pass "" to disable file logging entirely.
    """
    global _ALREADY_CONFIGURED
    if _ALREADY_CONFIGURED:
        return
    _ALREADY_CONFIGURED = True

    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    if log_file is None:
        log_file = os.environ.get("LOG_FILE", "logs/trader.log")

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # ── 1. Console (stdout) ────────────────────────────────────────────────────
    # Only add if there isn't already a plain StreamHandler (avoids duplicates
    # when uvicorn / gunicorn add their own).
    has_stream = any(
        type(h) is logging.StreamHandler for h in root.handlers
    )
    if not has_stream:
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        root.addHandler(ch)

    # ── 2. File (mode='w' — truncate at open, never append) ───────────────────
    if log_file:
        log_path = Path(log_file)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
            fh.setFormatter(formatter)
            root.addHandler(fh)
            logging.getLogger(__name__).info(
                "File logging enabled → %s", log_path.resolve()
            )
        except OSError as e:
            # Non-fatal: log to console only if the file can't be opened
            logging.getLogger(__name__).warning(
                "Could not open log file %s: %s — logging to console only.", log_file, e
            )

    # Quiet noisy third-party loggers
    for noisy in ("urllib3", "botocore", "boto3", "httpx", "httpcore", "yfinance"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
