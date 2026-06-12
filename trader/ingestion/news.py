"""
News ingestion: RSS feed fetching, ticker filtering, and news window tagging.

18 feeds across 4 sources (NSE, ET, Livemint, Business Standard), each tagged
with the agents that consume them. fetch_news_for_ticker pulls only the feeds
relevant to the calling agent — no wasted tokens on irrelevant sources.

No full article text is stored — headline + URL + 2-sentence summary only.
Results cached per (ticker, agent_name) in Redis with 1h TTL.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Literal
from zoneinfo import ZoneInfo
from .cache import Cache

import feedparser

from trader.ingestion.dedup import deduplicate_articles

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
_NEWS_CACHE_TTL = 3600  # 1 hour
C = Cache(ttl=_NEWS_CACHE_TTL)

NewsWindowTag = Literal["PRE_OPEN", "INTRADAY", "AFTER_CLOSE"]


# ─── Feed registry ────────────────────────────────────────────────────────────

@dataclass
class FeedConfig:
    url: str
    agents: list[str]   # which agents consume this feed
    priority: str       # CRITICAL | HIGH | MEDIUM
    note: str           # why this feed matters


# ── NSE Official Feeds (6) — always parse first; highest authority ─────────
NSE_FEEDS: dict[str, FeedConfig] = {
    "nse_financial_results": FeedConfig(
        url="https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml",
        agents=["news_sentiment", "fundamentals"],
        priority="CRITICAL",
        note="Quarterly results beat/miss — single highest-signal event per stock.",
    ),
    "nse_board_meetings": FeedConfig(
        url="https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml",
        agents=["news_sentiment", "fundamentals"],
        priority="CRITICAL",
        note="Upcoming results dates, dividend decisions, capex announcements.",
    ),
    "nse_corporate_actions": FeedConfig(
        url="https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml",
        agents=["technical", "fundamentals"],
        priority="CRITICAL",
        note="Dividends/splits/rights — cause price discontinuities; adjust OHLC.",
    ),
    "nse_announcements": FeedConfig(
        url="https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml",
        agents=["news_sentiment"],
        priority="HIGH",
        note="Catch-all regulatory filings, investor presentations, press releases.",
    ),
    "nse_insider_trading": FeedConfig(
        url="https://nsearchives.nseindia.com/content/RSS/InsiderTrading.xml",
        agents=["fundamentals", "portfolio_manager"],
        priority="HIGH",
        note="Promoter/director BUYs = strongly bullish; SELLs are ambiguous.",
    ),
    "nse_shareholding_pattern": FeedConfig(
        url="https://nsearchives.nseindia.com/content/RSS/Shareholding_Pattern.xml",
        agents=["fundamentals"],
        priority="MEDIUM",
        note="Quarterly FII/DII/promoter holding changes — institutional conviction signal.",
    ),
}

# ── Economic Times Feeds (6) — primary text news source ───────────────────
ET_FEEDS: dict[str, FeedConfig] = {
    "et_markets": FeedConfig(
        url="https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        agents=["news_sentiment", "portfolio_manager"],
        priority="CRITICAL",
        note="Primary ET text feed — broadest Indian equity coverage. Filter by ticker in code.",
    ),
    "et_stocks": FeedConfig(
        url="https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
        agents=["news_sentiment"],
        priority="HIGH",
        note="Analyst upgrades/downgrades, block deals, bulk deals.",
    ),
    "et_company": FeedConfig(
        url="https://economictimes.indiatimes.com/news/company/rssfeeds/2143429.cms",
        agents=["news_sentiment", "fundamentals"],
        priority="HIGH",
        note="M&A, management changes, litigation — company-level material events.",
    ),
    "et_industry_banking": FeedConfig(
        url="https://economictimes.indiatimes.com/industry/banking/finance/rssfeeds/13358259.cms",
        agents=["fundamentals"],
        priority="HIGH",
        note="RBI/NPA/credit growth for HDFCBANK, ICICIBANK, AXISBANK, KOTAKBANK, BAJFINANCE.",
    ),
    "et_industry_energy": FeedConfig(
        url="https://economictimes.indiatimes.com/industry/energy/rssfeeds/13358350.cms",
        agents=["fundamentals"],
        priority="HIGH",
        note="Crude prices, refinery margins, new energy policy — for RELIANCE, ADANIENT.",
    ),
    "et_economy": FeedConfig(
        url="https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
        agents=["fundamentals", "portfolio_manager"],
        priority="HIGH",
        note="RBI policy, GDP, inflation, fiscal data — macro context for PM final decision.",
    ),
}

# ── Livemint Feeds (2) — independent second source; dedup against ET ──────
LIVEMINT_FEEDS: dict[str, FeedConfig] = {
    "livemint_markets": FeedConfig(
        url="https://www.livemint.com/rss/markets",
        agents=["news_sentiment"],
        priority="HIGH",
        note="Second independent text source. Cosine-dedup against ET before passing to agents.",
    ),
    "livemint_companies": FeedConfig(
        url="https://www.livemint.com/rss/companies",
        agents=["news_sentiment", "fundamentals"],
        priority="HIGH",
        note="Often breaks Reliance/TCS/HDFC Bank company stories before ET.",
    ),
}

# ── Business Standard Feeds (4) — institutional angle; strong SEBI/RBI coverage
BS_FEEDS: dict[str, FeedConfig] = {
    "bs_stock_market": FeedConfig(
        url="https://www.business-standard.com/rss/markets-106.rss",
        agents=["news_sentiment"],
        priority="HIGH",
        note="Strong institutional angle — block deals, FII activity, analyst calls.",
    ),
    "bs_quarterly_results": FeedConfig(
        url="https://www.business-standard.com/rss/companies-101.rss",
        agents=["news_sentiment", "fundamentals"],
        priority="HIGH",
        note="Results analysis + management commentary — supplements NSE Financial Results.",
    ),
    "bs_finance": FeedConfig(
        url="https://www.business-standard.com/rss/finance-105.rss",
        agents=["fundamentals"],
        priority="MEDIUM",
        note="SEBI orders, RBI circulars — directly affects 6 banking/NBFC stocks.",
    ),
    "bs_economy": FeedConfig(
        url="https://www.business-standard.com/rss/economy-policy-102.rss",
        agents=["fundamentals", "portfolio_manager"],
        priority="MEDIUM",
        note="Policy, budget impact, GST — macro signals that move Nifty basket.",
    ),
}

# ── Master feed registry (18 feeds total) ─────────────────────────────────
ALL_FEEDS: dict[str, FeedConfig] = {
    **NSE_FEEDS,        # 6 feeds
    **ET_FEEDS,         # 6 feeds
    **LIVEMINT_FEEDS,   # 2 feeds
    **BS_FEEDS,         # 4 feeds
}

# Agent routing summary (for reference):
#   news_sentiment:  et_markets, et_stocks, et_company, livemint_markets,
#                    livemint_companies, bs_stock_market, bs_quarterly_results,
#                    nse_announcements, nse_financial_results, nse_board_meetings
#   fundamentals:    nse_financial_results, nse_board_meetings, nse_corporate_actions,
#                    nse_insider_trading, nse_shareholding_pattern,
#                    et_company, et_industry_banking, et_industry_energy, et_economy,
#                    bs_quarterly_results, bs_finance, bs_economy, livemint_companies
#   technical:       nse_corporate_actions
#   portfolio_manager: et_markets, et_economy, bs_economy, nse_insider_trading


def get_feeds_for_agent(agent_name: str) -> dict[str, FeedConfig]:
    """Return only the FeedConfig entries whose agents list includes agent_name."""
    return {k: v for k, v in ALL_FEEDS.items() if agent_name in v.agents}


# ─── Ticker alias table ────────────────────────────────────────────────────────

_TICKER_ALIASES: dict[str, list[str]] = {
    "HDFCBANK":   ["HDFC Bank", "HDFC"],
    "HINDUNILVR": ["HUL", "Hindustan Unilever"],
    "BHARTIARTL": ["Airtel", "Bharti"],
    "ICICIBANK":  ["ICICI Bank", "ICICI"],
    "KOTAKBANK":  ["Kotak Bank", "Kotak"],
    "AXISBANK":   ["Axis Bank"],
    "BAJFINANCE": ["Bajaj Finance", "BAF"],
    "ASIANPAINT": ["Asian Paints"],
    "ADANIENT":   ["Adani Enterprises", "Adani"],
    "RELIANCE":   ["RIL"],
    "INFY":       ["Infosys"],
    "LT":         ["L&T", "Larsen"],
    "MARUTI":     ["Maruti Suzuki", "MSIL"],
    "ITC":        ["ITC"],
    "TCS":        ["TCS", "Tata Consultancy"],
}


# ─── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_published(entry: dict) -> datetime | None:
    """Parse the published date from a feedparser entry into a UTC-aware datetime."""
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_time:
        try:
            return datetime(*parsed_time[:6], tzinfo=timezone.utc)
        except Exception:
            pass
    for field_name in ("published", "updated"):
        raw = entry.get(field_name, "")
        if raw:
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(raw).replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _extract_summary(entry: dict) -> str:
    """Extract a ≤2 sentence summary from a feedparser entry. Strips HTML."""
    raw = entry.get("summary") or entry.get("description") or ""
    raw = re.sub(r"<[^>]+>", "", raw).strip()
    sentences = re.split(r"(?<=[.!?])\s+", raw)
    return " ".join(sentences[:2])[:500]



# NSE blocks feedparser's default "python-feedparser/..." User-Agent with a TCP reset.
# Using a realistic browser UA gets us through their CDN.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_NSE_UA = _BROWSER_UA  # alias for clarity


def _fetch_feed_entries(feed_key: str, cfg: FeedConfig) -> list[dict]:
    """Fetch and parse one RSS feed. Returns raw article dicts with feed metadata.

    NSE feeds require a browser-like User-Agent; all others use feedparser's default.
    On any error (connection reset, SSL, timeout, bad XML) returns [] and logs a warning.
    """
    try:
        ua = _NSE_UA if feed_key.startswith("nse_") else None
        feed = feedparser.parse(cfg.url, agent=ua) if ua else feedparser.parse(cfg.url)
    except Exception as e:
        logger.warning("RSS fetch FAILED [%s] url=%s error=%s", feed_key, cfg.url, e)
        return []

    if feed.bozo and feed.bozo_exception:
        # bozo=True means the feed was malformed XML but feedparser still parsed what it could.
        # Log at DEBUG — don't warn, because many real feeds have minor XML issues.
        logger.debug("Bozo feed [%s]: %s", feed_key, feed.bozo_exception)

    articles = []
    for entry in feed.entries:
        published_at = _parse_published(entry)
        if published_at is None:
            published_at = datetime.now(tz=timezone.utc)

        articles.append({
            "title":        entry.get("title", "").strip(),
            "url":          entry.get("link", ""),
            "source":       feed_key,
            "published_at": published_at,
            "summary":      _extract_summary(entry),
            "feed_key":     feed_key,
            "agent_tags":   cfg.agents,
            "priority":     cfg.priority,
        })
    return articles


def _matches_ticker(article: dict, ticker: str, company_name: str) -> bool:
    """Return True if the article mentions this ticker or company (case-insensitive)."""
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()

    if ticker.lower() in text:
        return True
    if company_name.lower() in text:
        return True
    for alias in _TICKER_ALIASES.get(ticker, []):
        if alias.lower() in text:
            return True
    return False


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_news_for_ticker(
    ticker: str,
    company_name: str,
    agent_name: str,
    hours_back: int = 24,
) -> list[dict]:
    """
    Fetch and filter news articles for a given ticker, scoped to a specific agent.

    Steps:
    1. Pull only feeds assigned to agent_name (via get_feeds_for_agent)
    2. Filter to articles mentioning ticker symbol OR company_name
    3. Drop articles older than hours_back
    4. Deduplicate via cosine similarity (threshold 0.85)
    5. Sort by published_at DESC, return top 8

    Returns list of dicts:
        {title, url, source, published_at, summary, feed_key, agent_tags}

    Cached per (ticker, agent_name) in Redis with 1h TTL.
    """
    cache_key = f"news:{ticker}:{agent_name}:{hours_back}"
    cached = C._get(cache_key)
    if cached is not None:
        logger.debug("News cache hit: %s", cache_key)
        return cached

    agent_feeds = get_feeds_for_agent(agent_name)
    if not agent_feeds:
        logger.warning("No feeds configured for agent '%s'", agent_name)
        return []

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)

    all_articles: list[dict] = []
    feed_stats: dict[str, int] = {}
    for feed_key, cfg in agent_feeds.items():
        entries = _fetch_feed_entries(feed_key, cfg)
        matched = []
        for article in entries:
            pub = article["published_at"]
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub >= cutoff and _matches_ticker(article, ticker, company_name):
                matched.append(article)
                all_articles.append(article)
        feed_stats[feed_key] = len(matched)
        if matched:
            logger.debug(
                "[news][%s] feed=%s fetched=%d matched=%d",
                ticker, feed_key, len(entries), len(matched),
            )
        else:
            logger.debug(
                "[news][%s] feed=%s fetched=%d matched=0 (no relevant articles)",
                ticker, feed_key, len(entries),
            )

    pre_dedup = len(all_articles)
    deduped = deduplicate_articles(all_articles)
    deduped.sort(key=lambda a: a["published_at"], reverse=True)
    result = deduped[:8]

    # Log feeds that had hits (non-zero matches)
    hit_feeds = [f"{k}={v}" for k, v in feed_stats.items() if v > 0]
    logger.info(
        "[news][%s] agent=%s feeds=%d raw=%d post_dedup=%d returned=%d | hits: %s",
        ticker, agent_name, len(agent_feeds), pre_dedup,
        len(deduped), len(result),
        (", ".join(hit_feeds) if hit_feeds else "none"),
    )
    if result:
        for art in result:
            pub_str = art["published_at"] if isinstance(art["published_at"], str) \
                else art["published_at"].isoformat()
            logger.debug(
                "[news][%s]   [%s] %s (%s)",
                ticker, art.get("source", "?"), art.get("title", "")[:120], pub_str[:16],
            )

    serialisable = [
        {**a, "published_at": a["published_at"].isoformat()
         if not isinstance(a["published_at"], str) else a["published_at"]}
        for a in result
    ]
    C._set(cache_key, serialisable)

    # Archive raw articles to S3 once per (ticker, agent, date) — best-effort.
    # Key: news/{date}/{ticker}/{agent_name}.json
    # Only written when there are articles and not in dry-run mode.
    if serialisable:
        try:
            import json
            from datetime import date as _date
            from trader.config.settings import get_settings as _gs
            from trader.storage.s3 import upload_bytes as _upload

            if not _gs().dry_run:
                date_str = _date.today().isoformat()
                s3_key = f"news/{date_str}/{ticker}/{agent_name}.json"
                payload = {
                    "ticker": ticker,
                    "company_name": company_name,
                    "agent_name": agent_name,
                    "date": date_str,
                    "article_count": len(serialisable),
                    "articles": serialisable,
                }
                _upload(s3_key, json.dumps(payload, default=str).encode(), content_type="application/json")
        except Exception as _exc:
            logger.debug("News S3 archive failed (non-fatal): %s", _exc)

    return serialisable


def get_news_window_tag(published_at: datetime) -> NewsWindowTag:
    """
    Map an article's publication time to a trading window tag (IST-based).

    Kirtac & Germano (2024) timing rules:
      Before 09:00 IST  → PRE_OPEN    (trade at today's open)
      09:00–15:30 IST   → INTRADAY    (exit tomorrow's close)
      After  15:30 IST  → AFTER_CLOSE (enter tomorrow's open)
    """
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    ist_time = published_at.astimezone(IST).time()

    from datetime import time as dtime
    if ist_time < dtime(9, 0):
        return "PRE_OPEN"
    elif ist_time <= dtime(15, 30):
        return "INTRADAY"
    else:
        return "AFTER_CLOSE"
