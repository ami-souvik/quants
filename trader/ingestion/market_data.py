"""
Market data ingestion: EOD OHLCV, technical indicators, bhavcopy, Nifty 50 index.

Primary source: yfinance (.NS suffix for NSE) — free, no auth, reliable.
Results are cached in Redis with a 23-hour TTL so the same data is not re-fetched
within a single trading day's pipeline run.

All times are IST (Asia/Kolkata). Dates are Python date objects, not strings.
"""
from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta
from .cache import Cache

import numpy as np
import pandas as pd
import yfinance as yf
from zoneinfo import ZoneInfo

from trader.config.settings import get_settings

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
_REDIS_OHLCV_TTL = 23 * 3600  # 23 hours
_REDIS_INDEX_TTL = 23 * 3600
C_OHLCV = Cache(_REDIS_OHLCV_TTL)
C_INDEX = Cache(_REDIS_INDEX_TTL)


# ─── OHLCV ────────────────────────────────────────────────────────────────────

def fetch_eod_ohlcv(ticker: str, days: int = 30) -> pd.DataFrame:
    """
    Return a DataFrame of daily OHLCV with columns [date, open, high, low, close, volume].

    - Source: yfinance TICKER.NS
    - Cache: Redis 23h TTL
    - Returns exactly up to `days` most recent trading sessions (may be fewer during holidays).
    """
    cache_key = f"eod_ohlcv:{ticker}:{days}"
    cached = C_OHLCV._get(cache_key)
    if cached is not None:
        logger.debug("Cache hit: %s", cache_key)
        return cached

    yf_symbol = f"{ticker}.NS"
    # Request extra buffer to account for weekends/holidays
    end = datetime.now(tz=IST).date()
    start = end - timedelta(days=days + 20)

    try:
        raw = yf.download(
            yf_symbol,
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:
        logger.error("yfinance fetch failed for %s: %s", ticker, e)
        raise

    if raw.empty:
        raise ValueError(f"yfinance returned no data for {ticker} ({yf_symbol})")

    # Flatten MultiIndex columns (yfinance can return these for single-ticker too in newer versions)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw.columns = [c.lower() for c in raw.columns]

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"yfinance missing columns for {ticker}: {missing}")

    df = raw[["open", "high", "low", "close", "volume"]].copy()
    df.index.name = "date"
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.dropna(subset=["close"]).tail(days).reset_index(drop=True)

    C_OHLCV._set(cache_key, df)
    if not df.empty:
        date_from = df["date"].iloc[0]
        date_to   = df["date"].iloc[-1]
        close_last = float(df["close"].iloc[-1])
        pct_chg = float((df["close"].iloc[-1] / df["close"].iloc[-2] - 1) * 100) if len(df) >= 2 else 0.0
        logger.info(
            "[market_data][%s] OHLCV: %d sessions %s→%s | close=%.2f pct1d=%+.2f%%",
            ticker, len(df), date_from, date_to, close_last, pct_chg,
        )
    else:
        logger.info("[market_data][%s] OHLCV: 0 sessions returned", ticker)
    return df


# ─── Bhavcopy ─────────────────────────────────────────────────────────────────

def fetch_bhavcopy(trade_date: date) -> pd.DataFrame:
    """
    Download the full NSE bhavcopy CSV for trade_date, archive to S3,
    and return a DataFrame filtered to UNIVERSE tickers.

    Returns an empty DataFrame on network failure so callers can continue.
    Columns: symbol, open, high, low, close, volume (plus NSE originals).
    """
    from trader.config.tickers import SYMBOLS

    date_str = trade_date.strftime("%d%m%Y")
    url = (
        f"https://nsearchives.nseindia.com/products/content/"
        f"sec_bhavdata_full_{date_str}.csv"
    )

    import httpx
    try:
        with httpx.Client(follow_redirects=True, timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get(url)
            resp.raise_for_status()
            raw_bytes = resp.content
    except Exception as e:
        logger.warning("Bhavcopy download failed for %s (%s); returning empty DataFrame", trade_date, e)
        return pd.DataFrame(columns=["symbol", "open", "high", "low", "close", "volume"])

    df = pd.read_csv(io.BytesIO(raw_bytes))
    df.columns = [c.strip() for c in df.columns]

    # NSE bhavcopy column names can vary across versions; normalise common names
    col_map: dict[str, str] = {}
    for col in df.columns:
        lower = col.lower().strip()
        if lower == "symbol":
            col_map[col] = "symbol"
        elif lower in ("open_price", "open"):
            col_map[col] = "open"
        elif lower in ("high_price", "high"):
            col_map[col] = "high"
        elif lower in ("low_price", "low"):
            col_map[col] = "low"
        elif lower in ("close_price", "close", "last_price"):
            col_map[col] = "close"
        elif lower in ("ttl_trd_qnty", "tottrdqty", "volume", "traded_quantity"):
            col_map[col] = "volume"
    df = df.rename(columns=col_map)

    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].str.strip()
        df = df[df["symbol"].isin(SYMBOLS)]

    return df.reset_index(drop=True)


# ─── Technical indicators ─────────────────────────────────────────────────────

def compute_technical_indicators(df: pd.DataFrame) -> dict:
    """
    Compute a full set of technical indicators from a daily OHLCV DataFrame.

    Input columns (lowercase required): open, high, low, close, volume.
    At least 20 rows required; 30+ recommended for stable 20-period indicators.

    Returns a dict of float values (None where data is insufficient).
    Pure pandas implementation with zero heavy C/LLVM dependencies.
    """
    if len(df) < 20:
        raise ValueError(f"Need ≥20 rows for technical indicators; got {len(df)}")

    ta_df = df[["open", "high", "low", "close", "volume"]].copy().reset_index(drop=True)
    close  = ta_df["close"].astype(float)
    high   = ta_df["high"].astype(float)
    low    = ta_df["low"].astype(float)
    volume = ta_df["volume"].astype(float)

    def _val(val) -> float | None:
        return float(val) if pd.notna(val) else None

    # RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100.0 - (100.0 / (1.0 + rs))
    rsi_14 = _val(rsi_series.iloc[-1])

    # Moving Averages
    sma_5  = _val(close.rolling(5).mean().iloc[-1])
    sma_20 = _val(close.rolling(20).mean().iloc[-1])
    sma_50 = _val(close.rolling(50).mean().iloc[-1]) if len(ta_df) >= 50 else None

    ema_12_series = close.ewm(span=12, adjust=False).mean()
    ema_26_series = close.ewm(span=26, adjust=False).mean()
    ema_12 = _val(ema_12_series.iloc[-1])
    ema_26 = _val(ema_26_series.iloc[-1])

    # MACD
    macd_series = ema_12_series - ema_26_series
    signal_series = macd_series.ewm(span=9, adjust=False).mean()
    macd = _val(macd_series.iloc[-1])
    macd_signal = _val(signal_series.iloc[-1])

    # Bollinger Bands
    std_20 = close.rolling(20).std()
    bb_upper = _val((close.rolling(20).mean() + 2 * std_20).iloc[-1])
    bb_mid   = sma_20
    bb_lower = _val((close.rolling(20).mean() - 2 * std_20).iloc[-1])

    # ATR 14
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr_series = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    atr_14 = _val(atr_series.iloc[-1])

    # ADX 14
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_smooth = pd.Series(tr).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    plus_di = 100.0 * pd.Series(plus_dm).ewm(alpha=1/14, min_periods=14, adjust=False).mean() / tr_smooth.replace(0, np.nan)
    minus_di = 100.0 * pd.Series(minus_dm).ewm(alpha=1/14, min_periods=14, adjust=False).mean() / tr_smooth.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_series = dx.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    adx_14 = _val(adx_series.iloc[-1])

    # VWAP today (typical price)
    last_row = ta_df.iloc[-1]
    vwap_today = float((last_row["high"] + last_row["low"] + last_row["close"]) / 3)

    pct_1d  = float((close.iloc[-1] / close.iloc[-2]  - 1) * 100) if len(close) >= 2  else None
    pct_5d  = float((close.iloc[-1] / close.iloc[-6]  - 1) * 100) if len(close) >= 6  else None
    pct_20d = float((close.iloc[-1] / close.iloc[-21] - 1) * 100) if len(close) >= 21 else None

    vol = ta_df["volume"]
    avg_20 = float(vol.iloc[-20:].mean())
    volume_ratio = float(vol.iloc[-1] / avg_20) if avg_20 > 0 else None

    result = {
        "rsi_14":         rsi_14,
        "sma_5":          sma_5,
        "sma_20":         sma_20,
        "sma_50":         sma_50,
        "ema_12":         ema_12,
        "ema_26":         ema_26,
        "macd":           macd,
        "macd_signal":    macd_signal,
        "bb_upper":       bb_upper,
        "bb_mid":         bb_mid,
        "bb_lower":       bb_lower,
        "atr_14":         atr_14,
        "adx_14":         adx_14,
        "vwap_today":     vwap_today,
        "pct_change_1d":  pct_1d,
        "pct_change_5d":  pct_5d,
        "pct_change_20d": pct_20d,
        "volume_ratio":   volume_ratio,
    }
    logger.debug(
        "Indicators: RSI=%.1f MACD=%.3f/%.3f ADX=%.1f vol_ratio=%.2f "
        "pct1d=%.2f%% pct5d=%.2f%% pct20d=%.2f%%",
        rsi_14 or 0, macd or 0, macd_signal or 0, adx_14 or 0,
        volume_ratio or 1, pct_1d or 0, pct_5d or 0, pct_20d or 0,
    )
    return result


# ─── Nifty 50 index ───────────────────────────────────────────────────────────

def fetch_nifty50_index(days: int = 30) -> pd.DataFrame:
    """
    Return Nifty 50 index daily OHLC via yfinance (^NSEI symbol).
    Used as the primary benchmark. Cached 23h in Redis.
    """
    cache_key = f"nifty50_index:{days}"
    cached = C_INDEX._get(cache_key)
    if cached is not None:
        return cached

    end = datetime.now(tz=IST).date()
    start = end - timedelta(days=days + 20)

    try:
        raw = yf.download(
            "^NSEI",
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:
        logger.error("yfinance fetch failed for ^NSEI: %s", e)
        raise

    if raw.empty:
        raise ValueError("yfinance returned no data for Nifty 50 (^NSEI)")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw.columns = [c.lower() for c in raw.columns]

    df = raw[["open", "high", "low", "close"]].copy()
    df.index.name = "date"
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.dropna(subset=["close"]).tail(days).reset_index(drop=True)

    C_INDEX._set(cache_key, df)
    return df
