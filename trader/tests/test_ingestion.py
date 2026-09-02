"""
Tests for Phase 1B data pipeline.

All tests use synthetic data and mocks — no real network calls, no Redis required.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, time
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 35) -> pd.DataFrame:
    """Synthetic daily OHLCV for `n` sessions — realistic-ish price series."""
    from datetime import date, timedelta
    rng = np.random.default_rng(42)
    close = 2000.0 + np.cumsum(rng.normal(0, 20, n))
    open_  = close * (1 + rng.uniform(-0.005, 0.005, n))
    high   = np.maximum(close, open_) * (1 + rng.uniform(0, 0.01, n))
    low    = np.minimum(close, open_) * (1 - rng.uniform(0, 0.01, n))
    volume = rng.integers(500_000, 5_000_000, n).astype(float)
    # Use timedelta to avoid invalid day numbers (e.g. Jan 32)
    dates = [date(2026, 1, 2) + timedelta(days=i) for i in range(n)]
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low, "close": close, "volume": volume})


# ─── market_data.py ───────────────────────────────────────────────────────────

class TestComputeTechnicalIndicators:
    def test_returns_all_expected_keys(self):
        from trader.ingestion.market_data import compute_technical_indicators
        df = _make_ohlcv(35)
        indicators = compute_technical_indicators(df)

        required = {
            "rsi_14", "sma_5", "sma_20", "sma_50",
            "ema_12", "ema_26", "macd", "macd_signal",
            "bb_upper", "bb_mid", "bb_lower",
            "atr_14", "adx_14", "vwap_today",
            "pct_change_1d", "pct_change_5d", "pct_change_20d", "volume_ratio",
        }
        assert required.issubset(indicators.keys())

    def test_rsi_in_valid_range(self):
        from trader.ingestion.market_data import compute_technical_indicators
        df = _make_ohlcv(35)
        ind = compute_technical_indicators(df)
        rsi = ind["rsi_14"]
        assert rsi is not None
        assert 0.0 <= rsi <= 100.0

    def test_bollinger_band_ordering(self):
        from trader.ingestion.market_data import compute_technical_indicators
        df = _make_ohlcv(35)
        ind = compute_technical_indicators(df)
        if all(ind[k] is not None for k in ("bb_lower", "bb_mid", "bb_upper")):
            assert ind["bb_lower"] <= ind["bb_mid"] <= ind["bb_upper"]

    def test_pct_changes_are_floats(self):
        from trader.ingestion.market_data import compute_technical_indicators
        df = _make_ohlcv(35)
        ind = compute_technical_indicators(df)
        for key in ("pct_change_1d", "pct_change_5d", "pct_change_20d"):
            assert isinstance(ind[key], float), f"{key} should be float"

    def test_volume_ratio_positive(self):
        from trader.ingestion.market_data import compute_technical_indicators
        df = _make_ohlcv(35)
        ind = compute_technical_indicators(df)
        assert ind["volume_ratio"] is not None
        assert ind["volume_ratio"] > 0

    def test_vwap_reasonable(self):
        """VWAP (typical price) should be within high-low range of last session."""
        from trader.ingestion.market_data import compute_technical_indicators
        df = _make_ohlcv(35)
        ind = compute_technical_indicators(df)
        last = df.iloc[-1]
        assert last["low"] <= ind["vwap_today"] <= last["high"]

    def test_raises_on_insufficient_rows(self):
        from trader.ingestion.market_data import compute_technical_indicators
        df = _make_ohlcv(10)
        with pytest.raises(ValueError, match="20"):
            compute_technical_indicators(df)

    def test_sma_50_none_when_insufficient_data(self):
        """SMA-50 should be None when fewer than 50 rows are provided."""
        from trader.ingestion.market_data import compute_technical_indicators
        df = _make_ohlcv(35)  # only 35 rows
        ind = compute_technical_indicators(df)
        assert ind["sma_50"] is None


# ─── news.py — get_news_window_tag ────────────────────────────────────────────

class TestNewsWindowTag:
    def _make_ist_dt(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 5, 26, hour, minute, tzinfo=IST)

    def test_pre_open_before_9am(self):
        from trader.ingestion.news import get_news_window_tag
        dt = self._make_ist_dt(8, 30)
        assert get_news_window_tag(dt) == "PRE_OPEN"

    def test_pre_open_midnight(self):
        from trader.ingestion.news import get_news_window_tag
        dt = self._make_ist_dt(0, 0)
        assert get_news_window_tag(dt) == "PRE_OPEN"

    def test_intraday_at_9am_exactly(self):
        from trader.ingestion.news import get_news_window_tag
        dt = self._make_ist_dt(9, 0)
        assert get_news_window_tag(dt) == "INTRADAY"

    def test_intraday_midday(self):
        from trader.ingestion.news import get_news_window_tag
        dt = self._make_ist_dt(12, 0)
        assert get_news_window_tag(dt) == "INTRADAY"

    def test_intraday_at_1530_exactly(self):
        from trader.ingestion.news import get_news_window_tag
        dt = self._make_ist_dt(15, 30)
        assert get_news_window_tag(dt) == "INTRADAY"

    def test_after_close_just_after_1530(self):
        from trader.ingestion.news import get_news_window_tag
        dt = self._make_ist_dt(15, 31)
        assert get_news_window_tag(dt) == "AFTER_CLOSE"

    def test_after_close_evening(self):
        from trader.ingestion.news import get_news_window_tag
        dt = self._make_ist_dt(17, 0)
        assert get_news_window_tag(dt) == "AFTER_CLOSE"

    def test_after_close_night(self):
        from trader.ingestion.news import get_news_window_tag
        dt = self._make_ist_dt(23, 59)
        assert get_news_window_tag(dt) == "AFTER_CLOSE"

    def test_utc_datetime_converted_correctly(self):
        """A UTC datetime at 03:30 UTC = 09:00 IST should be INTRADAY."""
        from trader.ingestion.news import get_news_window_tag
        utc_dt = datetime(2026, 5, 26, 3, 30, tzinfo=timezone.utc)
        assert get_news_window_tag(utc_dt) == "INTRADAY"

    def test_naive_datetime_treated_as_utc(self):
        """Naive datetimes should be treated as UTC and still produce a valid tag."""
        from trader.ingestion.news import get_news_window_tag
        naive_dt = datetime(2026, 5, 26, 12, 0)  # no tzinfo
        tag = get_news_window_tag(naive_dt)
        assert tag in ("PRE_OPEN", "INTRADAY", "AFTER_CLOSE")


# ─── news.py — feed registry ─────────────────────────────────────────────────

class TestFeedRegistry:
    def test_total_feed_count_is_18(self):
        from trader.ingestion.news import ALL_FEEDS
        assert len(ALL_FEEDS) == 18

    def test_nse_feeds_count(self):
        from trader.ingestion.news import NSE_FEEDS
        assert len(NSE_FEEDS) == 6

    def test_et_feeds_count(self):
        from trader.ingestion.news import ET_FEEDS
        assert len(ET_FEEDS) == 6

    def test_livemint_feeds_count(self):
        from trader.ingestion.news import LIVEMINT_FEEDS
        assert len(LIVEMINT_FEEDS) == 2

    def test_bs_feeds_count(self):
        from trader.ingestion.news import BS_FEEDS
        assert len(BS_FEEDS) == 4

    def test_all_feeds_have_urls(self):
        from trader.ingestion.news import ALL_FEEDS
        for key, cfg in ALL_FEEDS.items():
            assert cfg.url.startswith("http"), f"{key} has invalid URL: {cfg.url}"

    def test_all_feeds_have_agents(self):
        from trader.ingestion.news import ALL_FEEDS
        for key, cfg in ALL_FEEDS.items():
            assert len(cfg.agents) >= 1, f"{key} has no agents assigned"

    def test_all_feeds_have_priority(self):
        from trader.ingestion.news import ALL_FEEDS
        valid = {"CRITICAL", "HIGH", "MEDIUM"}
        for key, cfg in ALL_FEEDS.items():
            assert cfg.priority in valid, f"{key} has invalid priority: {cfg.priority}"

    def test_get_feeds_for_news_sentiment(self):
        from trader.ingestion.news import get_feeds_for_agent
        feeds = get_feeds_for_agent("news_sentiment")
        # Should include ET, Livemint, BS equity feeds + NSE announcements/results/board
        assert len(feeds) >= 8
        assert "et_markets" in feeds
        assert "livemint_markets" in feeds
        assert "bs_stock_market" in feeds
        assert "nse_announcements" in feeds

    def test_get_feeds_for_fundamentals(self):
        from trader.ingestion.news import get_feeds_for_agent
        feeds = get_feeds_for_agent("fundamentals")
        assert len(feeds) >= 13
        assert "nse_financial_results" in feeds
        assert "nse_insider_trading" in feeds
        assert "et_industry_banking" in feeds
        assert "bs_finance" in feeds

    def test_get_feeds_for_technical(self):
        from trader.ingestion.news import get_feeds_for_agent
        feeds = get_feeds_for_agent("technical")
        # Only nse_corporate_actions
        assert "nse_corporate_actions" in feeds

    def test_get_feeds_for_portfolio_manager(self):
        from trader.ingestion.news import get_feeds_for_agent
        feeds = get_feeds_for_agent("portfolio_manager")
        assert "et_markets" in feeds
        assert "et_economy" in feeds
        assert "bs_economy" in feeds
        assert "nse_insider_trading" in feeds

    def test_get_feeds_unknown_agent_returns_empty(self):
        from trader.ingestion.news import get_feeds_for_agent
        feeds = get_feeds_for_agent("nonexistent_agent")
        assert feeds == {}


# ─── news.py — _matches_ticker ────────────────────────────────────────────────

class TestMatchesTicker:
    """Test the internal article-filtering logic."""

    def _article(self, title: str) -> dict:
        return {"title": title, "summary": ""}

    def test_matches_company_name(self):
        from trader.ingestion.news import _matches_ticker
        article = self._article("Reliance Industries reports strong Q4 results")
        assert _matches_ticker(article, "RELIANCE", "Reliance Industries")

    def test_matches_ticker_symbol(self):
        from trader.ingestion.news import _matches_ticker
        article = self._article("INFY misses revenue estimate by 2%")
        assert _matches_ticker(article, "INFY", "Infosys")

    def test_matches_alias(self):
        from trader.ingestion.news import _matches_ticker
        # HUL is an alias for HINDUNILVR
        article = self._article("HUL raises product prices across detergent segment")
        assert _matches_ticker(article, "HINDUNILVR", "Hindustan Unilever")

    def test_no_match_on_unrelated_article(self):
        from trader.ingestion.news import _matches_ticker
        article = self._article("RBI cuts repo rate by 25 bps in surprise move")
        assert not _matches_ticker(article, "TCS", "Tata Consultancy Services")

    def test_case_insensitive(self):
        from trader.ingestion.news import _matches_ticker
        article = self._article("tcs announces new deal with us defence contractor")
        assert _matches_ticker(article, "TCS", "Tata Consultancy Services")


# ─── dedup.py ─────────────────────────────────────────────────────────────────

class TestDeduplicateArticles:
    def _mock_model(self, embeddings_by_title: dict):
        """Return a mock SentenceTransformer that returns pre-computed embeddings."""
        model = MagicMock()
        def encode_side_effect(texts, **kwargs):
            return np.array([embeddings_by_title[t] for t in texts])
        model.encode.side_effect = encode_side_effect
        return model

    def test_empty_list_returns_empty(self):
        from trader.ingestion.dedup import deduplicate_articles
        assert deduplicate_articles([]) == []

    def test_single_article_returned_unchanged(self):
        from trader.ingestion.dedup import deduplicate_articles
        articles = [{"title": "Only article", "url": "http://a.com"}]
        assert deduplicate_articles(articles) == articles

    def test_near_identical_titles_deduplicated(self):
        """Two articles with near-identical titles → only one kept."""
        from trader.ingestion.dedup import deduplicate_articles
        articles = [
            {"title": "Reliance Industries reports Q4 profit up 8%", "url": "http://a.com"},
            {"title": "Reliance Industries reports Q4 profit up 8%", "url": "http://b.com"},
        ]
        result = deduplicate_articles(articles)
        assert len(result) == 1
        assert result[0]["url"] == "http://a.com"

    def test_distinct_articles_both_kept(self):
        """Two distinct articles → both kept."""
        from trader.ingestion.dedup import deduplicate_articles
        articles = [
            {"title": "Reliance reports strong Q4 results", "url": "http://a.com"},
            {"title": "RBI holds interest rates at 6.5%", "url": "http://b.com"},
        ]
        result = deduplicate_articles(articles)
        assert len(result) == 2

    def test_three_similar_one_different(self):
        """3 near-identical + 1 different → 2 kept."""
        from trader.ingestion.dedup import deduplicate_articles
        articles = [
            {"title": "HDFC Bank Q3 net profit jumps 33 percent", "url": "http://a.com"},
            {"title": "HDFC Bank Q3 net profit jumps 33 percent", "url": "http://b.com"},
            {"title": "HDFC Bank Q3 net profit jumps 33 percent year on year", "url": "http://c.com"},
            {"title": "Tata Motors launches new EV lineup", "url": "http://d.com"},
        ]
        result = deduplicate_articles(articles)
        assert len(result) == 2



# ─── fii_dii.py ───────────────────────────────────────────────────────────────

class TestFiiDiiFlows:
    def test_fallback_returns_valid_structure(self):
        """When all sources fail, fetch_fii_dii_flows returns a valid dict with zero values."""
        from trader.ingestion.fii_dii import fetch_fii_dii_flows
        from trader.ingestion.cache import Cache
        from datetime import date

        with patch("trader.ingestion.fii_dii._try_nselib", return_value=None), \
             patch("trader.ingestion.fii_dii._try_nse_direct", return_value=None), \
             patch.object(Cache, "_get", return_value=None), \
             patch.object(Cache, "_set"):
            result = fetch_fii_dii_flows(date(2026, 5, 26))

        assert "fii_net_buy_cr" in result
        assert "dii_net_buy_cr" in result
        assert "date" in result
        assert "source" in result
        assert isinstance(result["fii_net_buy_cr"], float)
        assert isinstance(result["dii_net_buy_cr"], float)

    def test_cache_hit_returns_cached(self):
        """Cached value is returned without hitting any API."""
        from trader.ingestion.fii_dii import fetch_fii_dii_flows
        from trader.ingestion.cache import Cache
        from datetime import date

        cached = {"fii_net_buy_cr": 450.0, "dii_net_buy_cr": -120.0, "date": "2026-05-26", "source": "nse_api"}

        with patch.object(Cache, "_get", return_value=cached), \
             patch("trader.ingestion.fii_dii._try_nselib") as mock_nselib:
            result = fetch_fii_dii_flows(date(2026, 5, 26))

        assert result == cached
        mock_nselib.assert_not_called()

    def test_nselib_result_used_when_available(self):
        from trader.ingestion.fii_dii import fetch_fii_dii_flows
        from trader.ingestion.cache import Cache
        from datetime import date

        nselib_result = {"fii_net_buy_cr": 300.0, "dii_net_buy_cr": 50.0, "date": "2026-05-26", "source": "nselib"}

        with patch.object(Cache, "_get", return_value=None), \
             patch.object(Cache, "_set"), \
             patch("trader.ingestion.fii_dii._try_nselib", return_value=nselib_result) as mock_ns, \
             patch("trader.ingestion.fii_dii._try_nse_direct") as mock_nse:
            result = fetch_fii_dii_flows(date(2026, 5, 26))

        assert result["source"] == "nselib"
        mock_nse.assert_not_called()  # nse_direct not called when nselib succeeds


# ─── Integration smoke test (no network) ─────────────────────────────────────

class TestMarketDataSmoke:
    def test_fetch_eod_ohlcv_with_mock_yfinance(self):
        """fetch_eod_ohlcv correctly normalises yfinance output."""
        from trader.ingestion.market_data import fetch_eod_ohlcv

        mock_df = _make_ohlcv(35)
        # Simulate yfinance output format (uppercase columns, DatetimeIndex)
        yf_df = mock_df.copy()
        yf_df = yf_df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                                       "close": "Close", "volume": "Volume"})
        from datetime import date, timedelta
        yf_df = yf_df.drop(columns=["date"])
        base = date(2026, 1, 2)
        yf_df.index = pd.to_datetime([base + timedelta(days=i) for i in range(len(yf_df))])

        from trader.ingestion.cache import Cache
        with patch.object(Cache, "_get", return_value=None), \
             patch.object(Cache, "_set"), \
             patch("yfinance.download", return_value=yf_df):
            result = fetch_eod_ohlcv("RELIANCE", days=30)

        assert isinstance(result, pd.DataFrame)
        assert set(result.columns) == {"date", "open", "high", "low", "close", "volume"}
        assert len(result) <= 30
        # All close prices should be positive
        assert (result["close"] > 0).all()
