"""
Fetches and locally caches the LiteLLM model pricing JSON.

Source: https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json

The downloaded file is cached at CACHE_PATH for CACHE_TTL_SECONDS so we
don't hit GitHub on every process start. If the network is unreachable, the
stale cache (or the in-code fallback snapshot) is used transparently.

This module is intentionally dependency-free beyond the stdlib so it can be
extracted into a standalone package later.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

logger = logging.getLogger(__name__)

LITELLM_PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)

# Cache lives next to this file; a proper package would use platformdirs.
CACHE_PATH = Path(__file__).parent / "_pricing_cache.json"
CACHE_TTL_SECONDS = 60 * 60 * 24  # refresh once per day


def _cache_is_fresh() -> bool:
    if not CACHE_PATH.exists():
        return False
    age = time.time() - CACHE_PATH.stat().st_mtime
    return age < CACHE_TTL_SECONDS


def fetch_pricing_data(force_refresh: bool = False) -> dict[str, Any]:
    """
    Return the full LiteLLM pricing dict.

    Resolution order:
      1. In-memory (module-level singleton after first load)
      2. Fresh local cache file
      3. Remote GitHub fetch → write to cache
      4. Stale cache file (network error fallback)
      5. Hardcoded fallback snapshot (last resort)
    """
    # Fast path: already loaded this process
    if not force_refresh and _LOADED_DATA:
        return _LOADED_DATA

    # Cache is fresh — load from disk
    if not force_refresh and _cache_is_fresh():
        try:
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            _LOADED_DATA.update(data)
            logger.debug("model_cost: loaded pricing from cache (%s)", CACHE_PATH)
            return _LOADED_DATA
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("model_cost: cache read failed (%s); will re-fetch", exc)

    # Fetch from GitHub
    try:
        logger.info("model_cost: fetching fresh pricing from LiteLLM GitHub…")
        with urlopen(LITELLM_PRICING_URL, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        # Persist to cache
        try:
            CACHE_PATH.write_text(raw, encoding="utf-8")
            logger.info("model_cost: pricing cached to %s", CACHE_PATH)
        except OSError as exc:
            logger.warning("model_cost: could not write cache: %s", exc)
        _LOADED_DATA.update(data)
        return _LOADED_DATA

    except (URLError, OSError, json.JSONDecodeError) as exc:
        logger.warning("model_cost: remote fetch failed (%s); falling back", exc)

    # Stale cache fallback
    if CACHE_PATH.exists():
        try:
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            _LOADED_DATA.update(data)
            logger.warning("model_cost: using stale cache (offline fallback)")
            return _LOADED_DATA
        except (json.JSONDecodeError, OSError):
            pass

    # Last resort: hardcoded snapshot (never stale, may lag behind real prices)
    logger.warning("model_cost: using hardcoded fallback snapshot")
    _LOADED_DATA.update(_FALLBACK_SNAPSHOT)
    return _LOADED_DATA


# Module-level singleton — populated on first call to fetch_pricing_data()
_LOADED_DATA: dict[str, Any] = {}

# ── Fallback snapshot — values verified 2026-05-28 from LiteLLM ──────────────
# These are per-token costs (USD), NOT per-million.
# Update this whenever a model reprices and the GitHub URL is temporarily down.
_FALLBACK_SNAPSHOT: dict[str, Any] = {
    "claude-haiku-4-5": {
        "litellm_provider": "anthropic",
        "input_cost_per_token": 1e-06,
        "output_cost_per_token": 5e-06,
        "cache_creation_input_token_cost": 1.25e-06,
        "cache_read_input_token_cost": 1e-07,
        "max_input_tokens": 200_000,
        "max_output_tokens": 64_000,
        "mode": "chat",
    },
    "claude-sonnet-4-6": {
        "litellm_provider": "anthropic",
        "input_cost_per_token": 3e-06,
        "output_cost_per_token": 1.5e-05,
        "cache_creation_input_token_cost": 3.75e-06,
        "cache_read_input_token_cost": 3e-07,
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 64_000,
        "mode": "chat",
    },
    "gemini/gemini-2.5-flash": {
        "litellm_provider": "gemini",
        "input_cost_per_token": 3e-07,
        "output_cost_per_token": 2.5e-06,
        "cache_creation_input_token_cost": 0.0,
        "cache_read_input_token_cost": 3e-08,
        "max_input_tokens": 1_048_576,
        "max_output_tokens": 65_535,
        "mode": "chat",
    },
    "gemma-4-31b-it": {
        "litellm_provider": "gemini",
        "input_cost_per_token": 0,
        "output_cost_per_token": 0,
        "cache_creation_input_token_cost": 0,
        "cache_read_input_token_cost": 0,
        "max_input_tokens": 1_048_576,
        "max_output_tokens": 65_535,
    }
}
