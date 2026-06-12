"""
S3 helpers for archiving raw data and decision logs.

All objects are stored in the bucket configured by S3_BUCKET_NAME env var.
Dry-run mode skips actual writes but logs the intended operation.
"""
from __future__ import annotations

import json
import logging

import boto3
from botocore.exceptions import ClientError

from trader.config.settings import get_settings

logger = logging.getLogger(__name__)


def _s3_client():
    settings = get_settings()
    return boto3.client("s3", region_name=settings.aws_region)


def upload_bytes(s3_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    settings = get_settings()
    if settings.dry_run:
        logger.debug("[DRY RUN] S3 upload → s3://%s/%s (%d bytes)", settings.s3_bucket_name, s3_key, len(data))
        return

    try:
        _s3_client().put_object(
            Bucket=settings.s3_bucket_name,
            Key=s3_key,
            Body=data,
            ContentType=content_type,
        )
        logger.info("Uploaded s3://%s/%s", settings.s3_bucket_name, s3_key)
    except ClientError as e:
        logger.error("S3 upload failed for %s: %s", s3_key, e)
        raise


def upload_json(s3_key: str, obj: dict | list) -> None:
    upload_bytes(s3_key, json.dumps(obj, indent=2, default=str).encode(), content_type="application/json")


def upload_text(s3_key: str, text: str) -> None:
    upload_bytes(s3_key, text.encode(), content_type="text/plain")


def download_bytes(s3_key: str) -> bytes:
    settings = get_settings()
    try:
        response = _s3_client().get_object(Bucket=settings.s3_bucket_name, Key=s3_key)
        return response["Body"].read()
    except ClientError as e:
        logger.error("S3 download failed for %s: %s", s3_key, e)
        raise


def key_exists(s3_key: str) -> bool:
    settings = get_settings()
    try:
        _s3_client().head_object(Bucket=settings.s3_bucket_name, Key=s3_key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise


# ─── Log management ───────────────────────────────────────────────────────────
# S3 key layout:  logs/{date}/run-{datetime}.log
# e.g.            logs/2026-06-13/run-2026-06-13T17-05-32.log
#
# Multiple runs on the same day each get their own object, so no data is lost.

_LOG_PREFIX = "logs"


def log_s3_key(run_datetime: str) -> str:
    """
    Build the S3 key for a log file given an ISO datetime string.

    run_datetime: "2026-06-13T17:05:32+05:30" or any ISO-8601 form.
    Returns:      "logs/2026-06-13/run-2026-06-13T17-05-32.log"

    Colons are replaced with hyphens so the key is safe in all S3 clients
    and browsers without URL-encoding.
    """
    # Strip timezone suffix; keep date + time only
    clean = run_datetime[:19].replace(":", "-")  # "2026-06-13T17-05-32"
    date_part = clean[:10]                        # "2026-06-13"
    return f"{_LOG_PREFIX}/{date_part}/run-{clean}.log"


def upload_log(local_path: str, run_datetime: str) -> str:
    """
    Upload a local log file to S3.

    Args:
        local_path:   Path to the local .log file.
        run_datetime: ISO datetime of when the run started (used to build the key).

    Returns:
        The S3 key the file was uploaded to (or would have been in dry-run).

    Logs but does NOT raise on failure — a missing S3 upload should never
    crash the daily run.
    """
    import os
    key = log_s3_key(run_datetime)
    try:
        with open(local_path, "rb") as f:
            data = f.read()
        upload_bytes(key, data, content_type="text/plain; charset=utf-8")
        logger.info("Log uploaded to s3://%s/%s (%d bytes)", get_settings().s3_bucket_name, key, len(data))
    except FileNotFoundError:
        logger.warning("Log file not found for upload: %s", local_path)
    except Exception as exc:
        logger.error("Log upload failed (%s → %s): %s", local_path, key, exc)
    return key


def list_log_sessions(date_str: str) -> list[dict]:
    """
    List all log sessions (S3 objects) under logs/{date}/.

    Returns a list of dicts with keys:
        key          S3 object key
        size_bytes   object size
        last_modified  ISO datetime string (UTC)
        run_datetime   inferred from the key (e.g. "2026-06-13T17:05:32")
    Sorted newest-first.
    """
    settings = get_settings()
    prefix = f"{_LOG_PREFIX}/{date_str}/"
    try:
        paginator = _s3_client().get_paginator("list_objects_v2")
        sessions: list[dict] = []
        for page in paginator.paginate(Bucket=settings.s3_bucket_name, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                # Extract datetime from "logs/2026-06-13/run-2026-06-13T17-05-32.log"
                name = key.split("/")[-1]  # "run-2026-06-13T17-05-32.log"
                raw_dt = name.removeprefix("run-").removesuffix(".log")  # "2026-06-13T17-05-32"
                run_dt = raw_dt.replace("-", ":", 2)  # restore time colons: "2026-06-13T17:05:32"
                # But we only want to restore the time part colons (positions after T)
                # raw_dt = "2026-06-13T17-05-32" → date colons are already hyphens (correct)
                # We need "2026-06-13T17:05:32"
                date_part, time_part = raw_dt.split("T") if "T" in raw_dt else (raw_dt, "")
                run_dt_clean = f"{date_part}T{time_part.replace('-', ':')}" if time_part else date_part
                sessions.append({
                    "key": key,
                    "size_bytes": obj.get("Size", 0),
                    "last_modified": obj["LastModified"].isoformat(),
                    "run_datetime": run_dt_clean,
                })
        sessions.sort(key=lambda x: x["run_datetime"], reverse=True)
        return sessions
    except ClientError as exc:
        logger.error("S3 list_log_sessions failed for %s: %s", date_str, exc)
        return []


def download_log(s3_key: str) -> str:
    """
    Download a log file from S3 and return its content as a string.
    Raises on S3 errors.
    """
    data = download_bytes(s3_key)
    return data.decode("utf-8", errors="replace")
