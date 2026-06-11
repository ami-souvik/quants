# 🇮🇳 NSE LLM Trading MVP — Claude Code Master Prompt
> This entire file is pasted as the first message to Claude Code.  
> Claude Code should read it, ask any clarifying questions, then begin building.

---

## 0. WHO YOU ARE & WHAT WE'RE BUILDING

You are acting as a **senior full-stack engineer and quant developer** helping me build
a personal-use, paper-trading, multi-agent LLM system for Indian equity markets (NSE).

The system will:
- Watch **15 large-cap Nifty 50 stocks** (list in §3)
- Run **once daily at 17:00 IST** (after market close, news settled)
- Use **5 LLM agents** that debate and produce a structured trade decision
- Record all decisions in a **paper-trading ledger** (no real money yet)
- Display everything in a **Next.js dashboard**
- Run on **AWS** with full **Terraform IaC**
- Cost **under ₹2,000/month** total (LLM + infra combined)

This is **Phase 1: Paper Trading** (Month 1). No real broker order placement.
After 30 days of validated paper performance, we graduate to Phase 2 (live Zerodha).

**Tech stack I own:**
- Languages: Python, TypeScript/JavaScript
- Backend: Python FastAPI
- Databases: DynamoDB (trades/positions/NAV), Redis (hot cache)
- Cloud: AWS (ECS Fargate, EventBridge, SQS, S3, Secrets Manager, CloudWatch)
- IaC: Terraform
- Containers: Docker
- AI: Anthropic Claude API, multi-agent orchestration
- Frontend: Next.js (Vercel free tier)
- Agent framework: LangGraph 1.2.x

---

## 1. PROJECT STRUCTURE TO CREATE

Create this exact folder structure from scratch:

```
agentic-trading/
│
├── CLAUDE.md                        # This file (project context for Claude Code)
├── README.md                        # Auto-generate with setup steps
├── .env.example                     # All env vars (never .env in git)
├── .gitignore
├── pyproject.toml                   # Project metadata + all dependencies (PEP 517/518)
├── docker-compose.yml               # Local dev: FastAPI + Redis
│
├── trader/                          # Core Python backend
│   ├── __init__.py
│   ├── main.py                      # FastAPI app entry point
│   ├── daily_run.py                 # Entry point for ECS Fargate scheduled task
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py              # Pydantic BaseSettings; reads from env/Secrets Manager
│   │   └── tickers.py               # The 15 Nifty stocks + metadata
│   │
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── market_data.py           # jugaad-data + nselib: EOD OHLC, bhavcopy
│   │   ├── news.py                  # NSE/BSE RSS, Moneycontrol RSS, ET Markets RSS
│   │   ├── reddit.py                # r/IndianStockMarket, r/IndianStreetBets
│   │   ├── corporate_actions.py     # NSE announcements, results calendar
│   │   ├── fii_dii.py               # FII/DII daily data via nselib
│   │   └── dedup.py                 # Cosine similarity deduplication of news
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py                  # BaseAgent class: prompt loading, caching, retry
│   │   ├── news_sentiment.py        # Agent 1: News/Sentiment Analyst
│   │   ├── technical.py             # Agent 2: Technical Analyst
│   │   ├── fundamentals.py          # Agent 3: Fundamentals Analyst
│   │   ├── bull_bear.py             # Agent 4: Bull vs Bear Debate
│   │   └── portfolio_manager.py     # Agent 5: Final Portfolio Manager (decision)
│   │
│   ├── orchestration/
│   │   ├── __init__.py
│   │   ├── graph.py                 # LangGraph state machine definition
│   │   ├── state.py                 # TypedDict for LangGraph state
│   │   └── runner.py                # Runs the graph for all 15 tickers daily
│   │
│   ├── ledger/
│   │   ├── __init__.py
│   │   ├── paper_trade.py           # Simulated fills, P&L, position management
│   │   ├── cost_model.py            # Indian transaction cost calculator
│   │   └── circuit_breaker.py       # Kill-switch conditions
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── dynamo.py                # DynamoDB read/write helpers
│   │   └── s3.py                    # Archive raw data + decision logs
│   │
│   ├── metrics/
│   │   ├── __init__.py
│   │   ├── performance.py           # Sharpe, Sortino, drawdown, win rate
│   │   └── benchmarks.py            # Nifty 50 TRI, equal-weight, momentum, MR baselines
│   │
│   ├── prompts/                     # All prompts as versioned Markdown files
│   │   ├── system_shared.md         # Shared system context (cached by Anthropic)
│   │   ├── news_sentiment.md
│   │   ├── technical.md
│   │   ├── fundamentals.md
│   │   ├── bull_bear.md
│   │   └── portfolio_manager.md
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── positions.py
│   │   │   ├── decisions.py
│   │   │   ├── metrics.py
│   │   │   └── health.py
│   │   └── schemas.py               # Pydantic response models
│   │
│   └── tests/
│       ├── test_cost_model.py
│       ├── test_agents.py           # Mock LLM, test schema validation
│       ├── test_ledger.py
│       └── test_ingestion.py
│
├── dashboard/                       # Next.js 14 App Router
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.js
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                 # Main dashboard
│   │   ├── decisions/page.tsx       # Decision log viewer
│   │   ├── metrics/page.tsx         # Performance vs benchmarks
│   │   └── how-it-works/page.tsx    # Visual system architecture explainer
│   ├── components/
│   │   ├── NavChart.tsx             # NAV vs Nifty 50 line chart (Recharts)
│   │   ├── PositionsTable.tsx
│   │   ├── DecisionCard.tsx         # Per-stock agent debate viewer
│   │   ├── AgentCostWidget.tsx      # Daily LLM cost tracker
│   │   └── CircuitBreakerBanner.tsx
│   └── lib/
│       └── api.ts                   # Typed fetch wrapper for FastAPI
│
└── infra/                           # Terraform
    ├── main.tf
    ├── variables.tf
    ├── outputs.tf
    ├── modules/
    │   ├── dynamodb/
    │   ├── ecs/
    │   ├── eventbridge/
    │   └── s3/
    └── environments/
        └── dev/
            └── terraform.tfvars
```

---

## 2. ENVIRONMENT VARIABLES

Create `.env.example` with ALL of these. Load in `settings.py` via Pydantic BaseSettings.
In production, pull from AWS Secrets Manager.

```bash
# LLM APIs
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...           # Gemini 2.5 Flash for News + Technical agents

# Broker (Phase 2 only — leave empty in Phase 1)
KITE_API_KEY=
KITE_API_SECRET=
KITE_ACCESS_TOKEN=               # Refreshed daily via TOTP; empty in paper mode

# Reddit
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=nse-llm-trader/1.0

# AWS
AWS_REGION=ap-south-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
S3_BUCKET_NAME=nse-llm-trader-archive
DYNAMO_TABLE_NAME=nse_trader

# App
PAPER_TRADING_MODE=true          # CRITICAL: true = no real orders ever placed
INITIAL_CAPITAL_INR=1000000      # ₹10 lakh paper capital
MAX_POSITION_PCT=0.15            # 15% NAV max per stock
MAX_OPEN_POSITIONS=5
MAX_HOLD_DAYS=5
CIRCUIT_BREAKER_DRAWDOWN=0.10   # 10% portfolio drawdown → pause entries
DAILY_LLM_BUDGET_USD=1.00       # Alert if exceeded

# Redis
REDIS_URL=redis://localhost:6379

# Logging
LOG_LEVEL=INFO
```

---

## 3. THE 15 NIFTY STOCKS

Hardcode this in `config/tickers.py`. Do not make it dynamic — stability matters for Phase 1.

```python
UNIVERSE = [
    # Symbol     | Full name                    | Sector       | Typical daily vol
    ("RELIANCE",  "Reliance Industries",         "Energy",      "High"),
    ("TCS",       "Tata Consultancy Services",   "IT",          "High"),
    ("HDFCBANK",  "HDFC Bank",                   "Banking",     "High"),
    ("INFY",      "Infosys",                     "IT",          "High"),
    ("ICICIBANK", "ICICI Bank",                  "Banking",     "High"),
    ("HINDUNILVR","Hindustan Unilever",           "FMCG",       "High"),
    ("ITC",       "ITC Limited",                 "FMCG",       "High"),
    ("LT",        "Larsen & Toubro",             "Capital Goods","High"),
    ("AXISBANK",  "Axis Bank",                   "Banking",     "High"),
    ("KOTAKBANK", "Kotak Mahindra Bank",         "Banking",     "High"),
    ("BHARTIARTL","Bharti Airtel",               "Telecom",     "High"),
    ("MARUTI",    "Maruti Suzuki",               "Auto",        "High"),
    ("BAJFINANCE","Bajaj Finance",               "NBFC",        "High"),
    ("ASIANPAINT","Asian Paints",                "Paints",      "Medium"),
    ("ADANIENT",  "Adani Enterprises",           "Conglomerate","High"),
]
```

---

## 4. DATA INGESTION LAYER

### 4.1 `ingestion/market_data.py`

Build these functions using `jugaad-data` and `nselib`:

```python
def fetch_eod_ohlcv(ticker: str, days: int = 30) -> pd.DataFrame:
    """
    Returns DataFrame with columns: date, open, high, low, close, volume
    Uses jugaad-data NSEHistory. Handles weekends/holidays automatically.
    Caches in Redis with TTL=23h (refresh only after market close).
    """

def fetch_bhavcopy(date: date) -> pd.DataFrame:
    """
    Downloads full NSE bhavcopy CSV for a given date.
    Archives raw CSV to S3 at s3://{BUCKET}/bhavcopy/{date}.csv
    Returns filtered DataFrame for UNIVERSE tickers only.
    """

def compute_technical_indicators(df: pd.DataFrame) -> dict:
    """
    Input: 30-day OHLCV DataFrame
    Output dict with:
      - rsi_14: float
      - sma_5, sma_20, sma_50: float
      - ema_12, ema_26: float
      - macd, macd_signal: float
      - bb_upper, bb_mid, bb_lower: float  (Bollinger, 20d, 2σ)
      - atr_14: float
      - adx_14: float
      - vwap_today: float
      - pct_change_1d, 5d, 20d: float
      - volume_ratio: float  (today vol / 20d avg vol)
    Use pandas-ta library. No external paid data.
    """

def fetch_nifty50_index(days: int = 30) -> pd.DataFrame:
    """
    Nifty 50 index OHLC via nselib.
    Used as the primary benchmark.
    """
```

### 4.2 `ingestion/news.py`

Feed selection: 18 feeds chosen from 200+ available. Moneycontrol removed RSS in 2024 — skip.
Each feed tagged with consuming agents and priority. Verify live URLs on first deployment.

```python
from dataclasses import dataclass, field

@dataclass
class FeedConfig:
    url: str
    agents: list[str]          # which agents consume this feed
    priority: str              # CRITICAL | HIGH | MEDIUM
    note: str                  # why this feed matters

# ── NSE Official Feeds (6) — always parse first; highest authority ────────────
# Base URL pattern: https://nseindia.com/static/rss-feed/{slug}.xml
# Verify slug at https://www.nseindia.com/static/rss-feed before first deploy.

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
# NSE feeds to SKIP (add to blocklist, don't subscribe):
# Regulation 29/31, Secretarial Compliance, Share Transfers, Statement of Deviation,
# Unitholding Patterns, Voting Results, BRSR, Annual Reports, Investor Complaints,
# Related Party Transactions, Issuer Offer Docs, Reason for Encumbrance,
# Daily Buy Back/Redemption, NSE Circulars.

# ── Economic Times Feeds (6) — primary text news source ──────────────────────
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
# ET feeds to SKIP: ETPrime (paywall teaser only), Astrology/Panchang/Chalisa/Tarot,
# MF/SME/NRI/Careers/Magazines/Podcasts, all ET Now video feeds (titles only),
# Options/Crypto/US Stocks/Digital Real Estate, Wealth/P2P, Auto/Healthcare/Media
# (not in 15-stock universe), Investment Ideas/Market Mood/Stock Recos (secondary signal).

# ── Livemint Feeds (2) — independent second source; dedup against ET ─────────
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
# Livemint feeds to SKIP: Budget, Elections, Education, Sports, AI (generic),
# Insurance, Opinion, Money (personal finance), Science, Technology (generic),
# Videos (titles only), Politics, Industry (covered by ET sector feeds).

# ── Business Standard Feeds (4) — institutional angle; strong SEBI/RBI coverage
# URL pattern: https://www.business-standard.com/rss/{section}-{id}.rss
# Section IDs confirmed active May 2026. Verify at business-standard.com/rss.
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
# BS feeds to SKIP: All 23 election feeds, Cricket/IPL/Sports, Immigration,
# Luxury/Lifestyle, Entertainment, Blueprint Defence, Auto Expo, BS at 50,
# Gold/Silver Rate Today, Opinion (editorial noise), PR/ANI feeds, Shows.

# ── Moneycontrol — SKIP ENTIRELY ─────────────────────────────────────────────
# Removed RSS feeds in late 2024. Scraping violates ToS and breaks on JS rendering.
# ET + Livemint + BS covers identical content. Do not add any Moneycontrol URLs.

# ── Master feed registry (18 feeds total) ────────────────────────────────────
ALL_FEEDS: dict[str, FeedConfig] = {
    **NSE_FEEDS,        # 6 feeds
    **ET_FEEDS,         # 6 feeds
    **LIVEMINT_FEEDS,   # 2 feeds
    **BS_FEEDS,         # 4 feeds
}

# ── Feed-to-agent routing ────────────────────────────────────────────────────
def get_feeds_for_agent(agent_name: str) -> dict[str, FeedConfig]:
    """Returns only the feeds relevant to a specific agent."""
    return {k: v for k, v in ALL_FEEDS.items() if agent_name in v.agents}

# Routing summary (for documentation):
# news_sentiment agent:   et_markets, et_stocks, et_company, livemint_markets,
#                         livemint_companies, bs_stock_market, bs_quarterly_results,
#                         nse_announcements   → 8 feeds
# fundamentals agent:     nse_financial_results, nse_board_meetings, nse_corporate_actions,
#                         nse_insider_trading, nse_shareholding_pattern,
#                         et_company, et_industry_banking, et_industry_energy, et_economy,
#                         bs_quarterly_results, bs_finance, bs_economy,
#                         livemint_companies  → 13 feeds
# technical agent:        nse_corporate_actions (for price adjustment only)  → 1 feed
# portfolio_manager:      et_markets, et_economy, bs_economy, nse_insider_trading  → 4 feeds

def fetch_news_for_ticker(
    ticker: str,
    company_name: str,
    agent_name: str,
    hours_back: int = 24
) -> list[dict]:
    """
    1. Pull only feeds assigned to agent_name (get_feeds_for_agent)
    2. Filter articles mentioning ticker symbol OR company_name (case-insensitive)
    3. Skip articles older than hours_back
    4. Deduplicate via dedup.py (cosine similarity > 0.85 → drop duplicate)
    5. Sort by published_at DESC
    6. Return top 8 articles as list of:
       {title, url, source, published_at, summary, feed_key, agent_tags}
    IMPORTANT: Store headline + URL + max 2-sentence summary only.
    Never store full article body (copyright + token cost).
    Cache per (ticker, agent_name) in Redis with TTL=1h.
    """

def get_news_window_tag(published_at: datetime) -> str:
    """
    Implements Kirtac & Germano (2024) execution timing rules mapped to IST.
    NSE market hours: pre-open 09:00–09:15; session 09:15–15:30.

    - Before 09:00 IST  → "PRE_OPEN"    (news settled; trade at today's open 09:15)
    - 09:00–15:30 IST   → "INTRADAY"    (during session; trade at today's close, exit tomorrow close)
    - After 15:30 IST   → "AFTER_CLOSE" (post-market; trade at tomorrow's open 09:15)

    Returns: "PRE_OPEN" | "INTRADAY" | "AFTER_CLOSE"
    All datetimes must be IST-aware (Asia/Kolkata).
    """
```

### 4.3 `ingestion/dedup.py`

```python
def deduplicate_articles(articles: list[dict]) -> list[dict]:
    """
    Uses sentence-transformers (all-MiniLM-L6-v2, free, runs locally)
    to compute embeddings. Drops articles with cosine similarity > 0.85
    to any already-kept article. Returns deduplicated list.
    This avoids blowing up the LLM context with repetitive news.
    """
```

### 4.4 `ingestion/fii_dii.py`

```python
def fetch_fii_dii_flows(date: date) -> dict:
    """
    Gets FII/DII net buy/sell data from nselib.
    Returns: {fii_net_buy_cr: float, dii_net_buy_cr: float, date: str}
    This goes into the Portfolio Manager context as macro signal.
    """
```

---

## 5. TRANSACTION COST MODEL

**This is critical.** Build `ledger/cost_model.py` with exact Indian 2025-2026 charges.
Verify all numbers against Zerodha's published calculator.

```python
@dataclass
class TradeType(Enum):
    DELIVERY = "CNC"    # T+1 settlement; up to 5 days
    INTRADAY = "MIS"    # Same-day square-off

@dataclass
class CostBreakdown:
    brokerage: float
    stt: float
    exchange_txn: float
    gst: float
    sebi_fee: float
    stamp_duty: float
    dp_charges: float   # Only on delivery SELL; ₹15.93 fixed per scrip per day
    total: float
    total_bps: float    # total / trade_value * 10000

def calculate_trade_cost(
    trade_value_inr: float,
    trade_type: TradeType,
    side: str,           # "BUY" or "SELL"
    broker: str = "zerodha"
) -> CostBreakdown:
    """
    Exact charges for 2025-2026:

    DELIVERY (CNC):
      Brokerage: ₹0 (Zerodha delivery is free)
      STT: 0.1% on BUY + 0.1% on SELL
      NSE txn charge: 0.00297% (both sides)
      GST: 18% on (brokerage + txn + SEBI)
      SEBI fee: ₹10 per crore = 0.0001%
      Stamp duty: 0.015% on BUY only
      DP charges: ₹15.93 on SELL only

    INTRADAY (MIS):
      Brokerage: min(₹20, 0.03%) per order
      STT: 0.025% on SELL only
      NSE txn charge: 0.00297% (both sides)
      GST: 18% on (brokerage + txn + SEBI)
      SEBI fee: ₹10 per crore = 0.0001%
      Stamp duty: 0.003% on BUY only
      DP charges: ₹0

    Round-trip delivery benchmark: ~25.5–28 bps
    Round-trip intraday benchmark:  ~10.6–13 bps

    Include 3 bps slippage buffer for large-cap NSE stocks.
    """

def worked_example_test():
    """
    Unit test: ₹50,000 delivery buy → sell.
    Expected: total ~₹127–135. Run on module import in test mode.
    """
```

---

## 6. FIVE-AGENT PIPELINE

### Core design principles
1. **Anthropic prompt caching** — cache the shared system prompt (≥1024 tokens) using `cache_control: {"type": "ephemeral"}`. This gives 90% discount on re-reads across all 15 ticker calls in the same daily run. Put in `prompts/system_shared.md`.
2. **Strict JSON outputs** — every agent returns a validated Pydantic model. Schema errors → retry once → if still invalid → flag and use HOLD default.
3. **Skip-if-quiet rule** — if no news in 24h AND 1d price change < 1.5% AND no corporate announcement → skip full pipeline for that ticker → inherit prior position → log as "QUIET_SKIP".

### 6.1 `prompts/system_shared.md` — The Cacheable System Prompt

```markdown
# SYSTEM CONTEXT (cached — do not modify frequently)

You are part of a 5-agent paper-trading system for Indian equities (NSE).
This is a PERSONAL, NON-COMMERCIAL, PAPER-TRADING experiment. No real money is at risk.

## Market Rules (mandatory — never violate)
- Universe: 15 large-cap Nifty 50 stocks only. No other tickers.
- Paper capital: ₹10,00,000 (₹10 lakh)
- Max position size: 15% of NAV per stock
- Max simultaneous open positions: 5
- Max hold duration: 5 trading days
- Trade type: equity delivery (CNC) — NO intraday squared positions in Phase 1
- Round-trip cost assumption: 28 bps (delivery, realistic Indian charges)
- Circuit limits: reject any trade if the stock is locked at upper/lower circuit
- ASM/GSM: never enter/hold stocks on NSE ASM, GSM, or T2T lists
- Market hours (IST): pre-open 09:00–09:15; session 09:15–15:30; closed otherwise

## Output discipline
- Always output valid JSON matching the schema specified in each agent's prompt
- Never hallucinate ticker symbols or price levels
- Never give financial advice — this is a mechanical simulation experiment
- Confidence = your genuine uncertainty, not a marketing score
- If data is stale (>48h) or missing, lower confidence significantly

## Indian market context
- FII flows influence large-caps strongly; note direction in your reasoning
- Results season: Q1 (Aug), Q2 (Nov), Q3 (Feb), Q4 (May/Jun) — elevated volatility
- RBI policy dates: bi-monthly MPC meetings — macro risk events
- Budget: Union Budget (Feb 1) — sector-level shock potential
- STT increase (Budget 2024, eff. Oct 2024): delivery 0.1%/0.1%, intraday sell 0.025%
- Currency: USD/INR heavily influences IT sector (TCS, INFY)
- Sector correlations: Banking stocks move together on RBI/NPA news
```

### 6.2 Agent 1 — `agents/news_sentiment.py`

**Model:** `gemini-2.5-flash` (cheapest with large context)

```markdown
# PROMPT: prompts/news_sentiment.md

You are the News & Sentiment Analyst. Your sole job: analyse news about {ticker} and produce a sentiment score with supporting evidence.

## Input you will receive
- ticker: {ticker} ({company_name}, {sector})
- news_articles: [{title, source, published_at, summary}] (up to 8 articles, last 24h)
- corporate_announcements: [{type, headline, date}] (results, board meetings, dividends)
- recent_price: {close_price} (yesterday's close)
- price_change_1d: {pct_1d}%

## What to assess
1. Sentiment polarity: is the NEWS flow bullish, bearish, or neutral for this stock over 1–5 days?
2. Key events: any results, management change, regulatory action, sector news?
3. News timing window: {news_window_tag} — affects when a trade can open
4. News quality: is this rumour, confirmed fact, or forward guidance?
5. Contamination check: flag if news is older than 48h or seems repetitive

## Output schema (strict JSON)
{
  "ticker": "RELIANCE",
  "sentiment_score": 0.72,        // 0.0=very bearish, 0.5=neutral, 1.0=very bullish
  "sentiment_label": "BULLISH",   // BULLISH | SLIGHTLY_BULLISH | NEUTRAL | SLIGHTLY_BEARISH | BEARISH
  "key_events": ["Q4 net profit beat consensus by 8%", "New refinery capex announced"],
  "news_window": "AFTER_CLOSE",   // PRE_OPEN | INTRADAY | AFTER_CLOSE
  "data_quality": "HIGH",         // HIGH | MEDIUM | LOW | STALE
  "confidence": 0.78,
  "reasoning": "Two sentences max explaining the score."
}
```

### 6.3 Agent 2 — `agents/technical.py`

**Model:** `gemini-2.5-flash`

```markdown
# PROMPT: prompts/technical.md

You are the Technical Analyst. Assess price/momentum signals for {ticker} over a 1–5 day horizon.

## Input
- ticker: {ticker} ({company_name})
- indicators: {rsi_14, sma_5, sma_20, sma_50, macd, macd_signal, bb_upper, bb_mid, bb_lower, atr_14, adx_14, volume_ratio, pct_change_1d, pct_change_5d, pct_change_20d, vwap_today}
- last_5d_ohlcv: [{date, open, high, low, close, volume}]
- current_position: {side: null|"LONG", qty: int, avg_price: float, days_held: int}

## What to assess
1. Trend: is price above/below key MAs? Trending or ranging? (ADX > 25 = trending)
2. Momentum: RSI overbought (>70) / oversold (<30)? MACD crossover?
3. Volatility: ATR-based position sizing suggestion (risk ≤ 1% of portfolio per trade)
4. Volume confirmation: above-average volume validates breakouts/breakdowns
5. For held positions: should we exit? (price vs entry, trailing stop logic)

## Output schema
{
  "ticker": "TCS",
  "technical_signal": "BUY",    // BUY | SELL | HOLD | EXIT_LONG
  "trend": "UPTREND",           // UPTREND | DOWNTREND | RANGING
  "momentum": "OVERSOLD",       // OVERBOUGHT | NEUTRAL | OVERSOLD
  "suggested_stop_loss_pct": 2.5, // % below entry for stop loss
  "suggested_target_pct": 5.0,  // % above entry for target
  "volume_signal": "ABOVE_AVG", // ABOVE_AVG | AVERAGE | BELOW_AVG | DIVERGENT
  "confidence": 0.65,
  "reasoning": "Two sentences max."
}
```

### 6.4 Agent 3 — `agents/fundamentals.py`

**Model:** `claude-haiku-4-5` (better quantitative-narrative reasoning)

```markdown
# PROMPT: prompts/fundamentals.md

You are the Fundamentals Analyst. Assess the fundamental health and valuation context for {ticker}.

## Input
- ticker: {ticker} ({company_name}, {sector})
- sector_context: {sector_news_summary}
- fii_dii_flows: {fii_net_buy_cr} crore FII, {dii_net_buy_cr} crore DII (today)
- macro_context: {rbi_rate}, {usd_inr}, {nifty_1d_pct}, {nifty_5d_pct}
- known_fundamentals: {pe_ratio, pb_ratio, roe, debt_equity, revenue_growth_yoy, promoter_holding_pct}
  NOTE: These may be up to 90 days stale (quarterly results). Flag if so.

## What to assess
1. Valuation: is the stock cheap, fair, or expensive vs sector peers?
2. Institutional signal: FII buying = bullish for large-caps; FII selling = bearish
3. Macro fit: does macro environment (RBI, USD/INR, Nifty trend) favour this sector?
4. Quality check: any red flags (high debt, promoter pledge, audit issues)?
5. 1–5 day fundamental catalyst: any expected event (results, analyst day, policy)?

## Output schema
{
  "ticker": "HDFCBANK",
  "fundamental_bias": "BULLISH",  // BULLISH | NEUTRAL | BEARISH
  "valuation": "FAIR",            // CHEAP | FAIR | EXPENSIVE | UNKNOWN
  "institutional_flow": "FII_BUYING",  // FII_BUYING | FII_SELLING | DII_BUYING | DII_SELLING | MIXED | NEUTRAL
  "macro_tailwind": true,
  "red_flags": [],                // List any concerns; empty list if none
  "data_staleness_days": 45,      // How old is the fundamentals data?
  "confidence": 0.55,
  "reasoning": "Two sentences max."
}
```

### 6.5 Agent 4 — `agents/bull_bear.py`

**Model:** `claude-haiku-4-5` (both roles in one call; saves tokens)

```markdown
# PROMPT: prompts/bull_bear.md

You are running a structured debate between a BULL researcher and a BEAR researcher about {ticker}.
Both researchers have read the outputs from the News, Technical, and Fundamentals agents.

## Prior agent outputs (your inputs)
- news_agent: {news_agent_output}
- technical_agent: {technical_agent_output}
- fundamentals_agent: {fundamentals_agent_output}

## Debate rules
- BULL argues why this stock will rise 1–5% over the next 1–5 trading days
- BEAR argues why this stock will fall or underperform over the same window
- Each makes their STRONGEST possible case — no strawmanning
- Both must address the HIGHEST-CONFIDENCE signal from the opposing side
- Each is limited to 3 bullet points

## Output schema
{
  "ticker": "MARUTI",
  "bull_thesis": [
    "RSI at 32 signals oversold; historically bounces 3–5% within 5 days at this level.",
    "FII net bought ₹450 crore in Auto sector today — institutional accumulation signal.",
    "Q4 results beat consensus by 12%; market reaction was muted, suggesting delayed uptake."
  ],
  "bear_thesis": [
    "SMA 20 acting as resistance; three failed breakout attempts in past 10 sessions.",
    "USD/INR at 84.5 pressures auto input costs (steel, semiconductors largely USD-priced).",
    "ADX at 18 signals no clear trend; entry here is guesswork, not signal."
  ],
  "debate_winner": "BULL",      // BULL | BEAR | DRAW — who made the stronger case?
  "conviction_delta": 0.15,     // How much does the winner's case dominate? 0.0–1.0
  "key_risk": "If Nifty falls >1.5% tomorrow, this long is immediately wrong.",
  "confidence": 0.60
}
```

### 6.6 Agent 5 — `agents/portfolio_manager.py`

**Model:** `claude-haiku-4-5` (with self-consistency: 3 samples, majority vote)
Escalate to `claude-sonnet-4-6` ONLY if confidence <0.5 from Haiku (cost guard in code).

```markdown
# PROMPT: prompts/portfolio_manager.md

You are the Portfolio Manager. You make the FINAL, EXECUTABLE trade decision for {ticker}.
This is a paper-trading simulation on a ₹10 lakh portfolio.

## All prior agent outputs
- news_sentiment: {news_agent_output}
- technical: {technical_agent_output}
- fundamentals: {fundamentals_agent_output}
- bull_bear_debate: {bull_bear_output}

## Current portfolio state
- cash_available_inr: {cash_available}
- open_positions: {open_positions_count} / 5 max
- ticker_current_position: {position_qty} shares @ avg ₹{avg_price}, held {days_held} days
- portfolio_drawdown_pct: {drawdown_pct}%  (circuit breaker if >= 10%)
- nav_today: ₹{nav}

## Decision constraints (hard rules — never violate)
1. PAPER_TRADING_MODE = true. This generates a SIMULATED order only. Never place real orders.
2. Max 15% NAV per position → max buy value = ₹{max_position_value}
3. Max 5 simultaneous positions — if already at 5, only HOLD or EXIT allowed
4. If portfolio drawdown >= 10%: only EXIT decisions allowed, no new BUY
5. Never trade stocks on NSE ASM/GSM/T2T lists (check input flag: {is_restricted})
6. Minimum conviction threshold: confidence >= 0.55 to place a BUY; EXIT if confidence < 0.40
7. Cost hurdle: expected move must exceed 28 bps (delivery round-trip cost) to be worthwhile

## Output schema (MUST be exact — validated by Pydantic)
{
  "ticker": "ICICIBANK",
  "decision": "BUY",              // BUY | SELL | HOLD | EXIT | SKIP
  "decision_rationale": "SKIP",   // Only populated if SKIP: "QUIET", "RESTRICTED", "BUDGET", "DRAWDOWN"
  "quantity_shares": 35,          // 0 if HOLD/SKIP; negative not allowed (no shorting in Phase 1)
  "estimated_trade_value_inr": 87500.0,
  "product_type": "CNC",          // CNC (delivery) always in Phase 1
  "horizon_days": 3,              // 1–5 days
  "target_price": 2620.0,         // 0 if HOLD/SKIP
  "stop_loss_price": 2480.0,      // 0 if HOLD/SKIP
  "confidence": 0.72,             // 0.0–1.0
  "primary_thesis": "Oversold RSI + Q4 beat not yet priced in; FII accumulating Banking sector.",
  "kill_conditions": [
    "Close below 200DMA",
    "Nifty falls >2% intraday",
    "Negative RBI announcement"
  ],
  "agent_agreement": "HIGH",      // HIGH | MEDIUM | LOW (based on News/Tech/Fund alignment)
  "estimated_cost_bps": 28.5,
  "risk_reward_ratio": 2.1        // target_pct / stop_loss_pct
}
```

---

## 7. LANGGRAPH ORCHESTRATION

Build `orchestration/graph.py` as a LangGraph StateGraph:

```python
# orchestration/state.py
class TickerState(TypedDict):
    ticker: str
    company_name: str
    sector: str
    market_data: dict          # OHLCV + indicators
    news_articles: list[dict]
    corporate_actions: list[dict]
    fii_dii: dict
    current_position: dict
    portfolio_snapshot: dict
    is_restricted: bool        # ASM/GSM/T2T check
    # Agent outputs (filled sequentially)
    news_output: dict | None
    technical_output: dict | None
    fundamentals_output: dict | None
    bull_bear_output: dict | None
    pm_output: dict | None
    # Metadata
    skip_reason: str | None
    tokens_used: dict          # {agent: {input: int, output: int, cost_usd: float}}
    errors: list[str]
    processing_time_ms: int

class DailyRunState(TypedDict):
    run_date: str
    tickers: list[str]
    ticker_states: dict[str, TickerState]
    portfolio: dict
    total_cost_usd: float
    completed_at: str | None
```

Graph flow per ticker:
```
START
  → [check_restrictions]      # Is ticker on ASM/GSM/T2T? → skip if yes
  → [check_quiet]             # No news + <1.5% move? → skip if true
  → [news_sentiment_agent]
  → [technical_agent]
  → [fundamentals_agent]
  → [bull_bear_agent]
  → [portfolio_manager_agent]  # Retry logic + self-consistency
  → [cost_guard]               # If daily LLM spend > $1, alert + degrade to cheaper model
  → [ledger_execute]           # Paper-trade fill simulation
  → [persist_to_dynamo]
  → [archive_to_s3]
END
```

Run all 15 tickers **sequentially** (not parallel) in Phase 1 to:
- Stay within LLM rate limits
- Keep total daily LLM cost observable
- Avoid Redis race conditions

---

## 8. PAPER-TRADING LEDGER

### `ledger/paper_trade.py`

```python
class PaperTradingLedger:
    """
    Simulates realistic trade execution for CNC delivery positions.
    All fills are SIMULATED — no broker API called in Phase 1.
    """

    def simulate_fill(self, decision: PMDecision, market_data: dict) -> SimulatedFill:
        """
        Fill logic:
        - BUY: fill at previous day's CLOSE price (next-day open not available at 17:00 IST)
        - EXIT: fill at previous day's CLOSE price
        - Apply 3 bps slippage on top (conservative Nifty 50 estimate)
        - Calculate cost via cost_model.calculate_trade_cost()
        - Return SimulatedFill with fill_price, actual_cost_inr, cost_bps
        """

    def update_positions(self, fill: SimulatedFill) -> dict:
        """
        Updates position in DynamoDB.
        Enforces: max 5 positions, max 15% NAV per stock.
        Auto-exits positions held > MAX_HOLD_DAYS.
        """

    def calculate_nav(self) -> dict:
        """
        NAV = cash + sum(position_qty × current_price for each position)
        Returns {nav, cash, equity_value, daily_return_pct, drawdown_pct}
        """

    def check_circuit_breakers(self) -> CircuitBreakerStatus:
        """
        Returns which circuit breakers are active:
        - DRAWDOWN: portfolio drawdown >= 10% → no new entries
        - CONCENTRATION: any position >= 15% NAV → no adds
        - SECTOR_CAP: any sector >= 40% NAV → no adds in that sector
        - LLM_COST: daily LLM cost > $1 → switch to cheaper models
        - RESTRICTED: ticker on ASM/GSM/T2T list → force EXIT
        """
```

---

## 9. DYNAMODB SCHEMA — SINGLE-TABLE DESIGN

One master table: `nse_trader` (configured via `DYNAMO_TABLE_NAME` env var).
All four entity types live in this table, separated by PK/SK prefix conventions.
On-demand billing. No provisioned capacity. TTL enabled on all items (30-day auto-expiry).

Every item carries a `type` attribute for readability and future filtering.

### Key design

| Entity    | PK                    | SK                                    | type         |
|-----------|-----------------------|---------------------------------------|--------------|
| Position  | `TICKER#{symbol}`     | `DATE#{yyyy-mm-dd}`                   | `POSITION`   |
| Decision  | `DATE#{yyyy-mm-dd}`   | `TICKER#{symbol}#AGENT#{agent_name}`  | `DECISION`   |
| Trade     | `DATE#{yyyy-mm-dd}`   | `TRADE#{uuid}`                        | `TRADE`      |
| NAV       | `DATE#{yyyy-mm-dd}`   | `PORTFOLIO`                           | `NAV`        |

### Access patterns (all satisfied without a GSI in Phase 1)

| Query                                  | Operation                                              |
|----------------------------------------|--------------------------------------------------------|
| Position for one ticker on a date      | `GetItem` PK=`TICKER#X` SK=`DATE#Y`                   |
| All positions today (15 tickers)       | 15 × `GetItem` (acceptable for fixed 15-stock universe)|
| All agent decisions for a date         | `Query` PK=`DATE#X` SK begins_with `TICKER#`          |
| One agent's decision for ticker+date   | `GetItem` PK=`DATE#X` SK=`TICKER#X#AGENT#Y`           |
| All trades on a date                   | `Query` PK=`DATE#X` SK begins_with `TRADE#`           |
| NAV for a date                         | `GetItem` PK=`DATE#X` SK=`PORTFOLIO`                  |
| Idempotency check (daily run done?)    | `GetItem` PK=`DATE#X` SK=`PORTFOLIO` → None = not run |

### Item schemas

```python
# ── POSITION ─────────────────────────────────────────────────────────────────
# PK: TICKER#{symbol}  SK: DATE#{yyyy-mm-dd}
{
    "PK": "TICKER#RELIANCE",
    "SK": "DATE#2026-05-26",
    "type": "POSITION",
    "qty": 20,
    "avg_price": Decimal("2840.50"),
    "entry_date": "2026-05-24",
    "days_held": 2,
    "product_type": "CNC",
    "horizon_days": 3,
    "stop_loss_price": Decimal("2750.00"),
    "target_price": Decimal("2950.00"),
    "kill_conditions": ["Close below 200DMA"],
    "decision_date": "2026-05-24",
    "ttl": 1780000000  # Auto-expire after 30 days
}

# ── DECISION  (one row per agent per ticker per day) ──────────────────────────
# PK: DATE#{yyyy-mm-dd}  SK: TICKER#{symbol}#AGENT#{agent_name}
{
    "PK": "DATE#2026-05-26",
    "SK": "TICKER#RELIANCE#AGENT#PortfolioManager",
    "type": "DECISION",
    "decision": "BUY",
    "confidence": Decimal("0.72"),
    "reasoning": "...",
    "full_prompt_s3_key": "decisions/2026-05-26/RELIANCE/pm_prompt.txt",
    "full_output_s3_key": "decisions/2026-05-26/RELIANCE/pm_output.json",
    "input_tokens": 4321,
    "output_tokens": 612,
    "cost_usd": Decimal("0.0043"),
    "model": "claude-haiku-4-5",
    "schema_valid": True,
    "retry_count": 0,
    "ttl": 1780000000
}

# ── TRADE  (one row per simulated fill) ───────────────────────────────────────
# PK: DATE#{yyyy-mm-dd}  SK: TRADE#{uuid}
{
    "PK": "DATE#2026-05-26",
    "SK": "TRADE#abc123",
    "type": "TRADE",
    "ticker": "RELIANCE",
    "side": "BUY",
    "qty": 20,
    "fill_price": Decimal("2840.50"),
    "trade_value_inr": Decimal("56810.00"),
    "simulated_cost_inr": Decimal("162.72"),
    "simulated_cost_bps": Decimal("28.6"),
    "slippage_bps": Decimal("3.0"),
    "product_type": "CNC",
    "ledger_cash_after": Decimal("430000.00"),
    "ttl": 1780000000
}

# ── NAV  (one row per trading day) ────────────────────────────────────────────
# PK: DATE#{yyyy-mm-dd}  SK: PORTFOLIO
{
    "PK": "DATE#2026-05-26",
    "SK": "PORTFOLIO",
    "type": "NAV",
    "nav_inr": Decimal("1015000.00"),
    "cash_inr": Decimal("250000.00"),
    "equity_value_inr": Decimal("765000.00"),
    "open_positions": 3,
    "daily_return_pct": Decimal("0.42"),
    "cumulative_return_pct": Decimal("1.50"),
    "drawdown_pct": Decimal("-1.10"),
    "nifty50_close": Decimal("24210.55"),
    "nifty50_daily_return_pct": Decimal("0.38"),
    "total_llm_cost_usd_today": Decimal("0.087"),
    "decisions_made": 15,
    "decisions_skipped": 3,
    "schema_error_count": 0,
    "ttl": 1780000000
}
```

---

## 10. PERFORMANCE METRICS

### `metrics/performance.py`

```python
def calculate_sharpe(daily_returns: list[float], risk_free_rate_annual: float = 0.068) -> float:
    """Annualized Sharpe ratio. India risk-free = ~6.8% (10Y G-Sec yield 2025)."""

def calculate_sortino(daily_returns: list[float]) -> float:
    """Uses downside deviation only. More relevant than Sharpe for asymmetric strategies."""

def calculate_max_drawdown(nav_series: list[float]) -> float:
    """Max peak-to-trough decline as percentage."""

def calculate_profit_factor(trade_pnls: list[float]) -> float:
    """sum(winners) / abs(sum(losers)). >1.5 is decent; <1.0 is losing."""

def calculate_per_agent_hit_rate(agent: str, date_range: tuple) -> dict:
    """
    For each agent, what % of its directional calls (BULLISH/BEARISH)
    aligned with the actual 5-day realized return?
    Pull from DynamoDB decisions table + nav_daily table.
    Returns {hit_rate: float, n_calls: int, avg_confidence: float}
    """
```

### `metrics/benchmarks.py`

Build these 5 benchmarks. All start at ₹10,00,000 and are recomputed daily:

1. **Nifty 50 TRI** — direct index return (use nselib for NIFTY_50 adjusted for dividends)
2. **Equal-weighted basket** — equal ₹/15 allocation across all 15 tickers, rebalanced weekly
3. **5-day momentum** — each Monday, buy top 5 by prior 5-day return; hold for the week
4. **Mean-reversion** — each Monday, buy bottom 5 by prior 5-day return; hold for the week
5. **Buy-and-hold** — equal allocation on Day 1, never touch

---

## 11. FASTAPI BACKEND

### `api/routes/metrics.py`

```python
GET /api/metrics/summary
→ {nav, cumulative_return_pct, sharpe, sortino, max_drawdown_pct, win_rate, profit_factor,
   total_trades, total_llm_cost_usd, days_running, benchmark_comparison: {...}}

GET /api/metrics/daily?from=2026-05-01&to=2026-05-26
→ [{date, nav, daily_return_pct, nifty_return_pct, drawdown_pct, llm_cost_usd}]

GET /api/decisions?date=2026-05-26
→ [{ticker, pm_decision, pm_confidence, pm_reasoning, agent_agreement,
    news_sentiment, technical_signal, fundamental_bias, debate_winner,
    estimated_cost_bps, risk_reward_ratio, actual_fill: {...}|null}]

GET /api/positions
→ [{ticker, qty, avg_price, days_held, current_price, unrealized_pnl_pct,
    stop_loss_price, target_price, kill_conditions}]

GET /api/health
→ {status: "OK", last_run: "2026-05-26T17:05:32+05:30", paper_mode: true,
   circuit_breakers_active: [], daily_llm_cost_usd: 0.087}
```

All routes:
- Return CORS-enabled JSON
- Auth via simple API key in header `X-API-Key` (loaded from env)
- Pydantic response models for every endpoint
- 60-second Redis cache on GET routes

---

## 12. NEXT.JS DASHBOARD

Build `dashboard/` as Next.js 14 App Router with TypeScript and Tailwind CSS.

### Pages & Components

**`app/page.tsx` — Main Dashboard**
- NAV vs Nifty 50 line chart (Recharts `LineChart`; two lines, 30-day window)
- Today's stats: NAV, daily return %, drawdown %, LLM cost today
- Open positions table (PositionsTable component)
- Circuit breaker status banner (red if any active)
- Last run timestamp + "Paper Trading Mode" badge

**`app/decisions/page.tsx` — Decision Log**
- Date picker (default: today)
- For each ticker: collapsible DecisionCard showing:
  - Final PM decision + confidence badge
  - All 5 agent outputs in a tab layout
  - Full debate (bull vs bear bullet points)
  - Estimated vs realized return (filled in retrospectively at T+5)

**`app/metrics/page.tsx` — Performance Analytics**
- Benchmark comparison chart: portfolio vs all 5 benchmarks
- Key metrics table: Sharpe, Sortino, max drawdown, win rate, profit factor
- Per-agent hit rate bar chart (which agents are contributing signal?)
- LLM cost breakdown (pie chart by agent × model)
- Statistical significance warning banner: "21 observations is not enough to claim alpha"

**`app/how-it-works/page.tsx` — System Architecture Visual**
A fully static explainer page for the entire system. Sections (keep in sync with actual implementation):
1. **Daily Pipeline overview** — horizontal flow diagram: Data Ingestion → 5 LLM Agents → PM Decision → Paper Ledger → Persist → Dashboard
2. **Data Sources** — 18 RSS feeds grouped by publisher (NSE 6, ET 6, Livemint 2, BS 4) + market data (jugaad-data/nselib) + deduplication note
3. **Five-Agent Pipeline** — per-agent card showing: index, name, model (with escalation logic for PM), inputs, JSON output fields, role description; sequential arrow connectors; prompt caching and retry/fallback notes
4. **Transaction Cost Model** — table of all Indian 2025-26 charges for CNC delivery vs MIS intraday; round-trip bps benchmarks; 28 bps cost hurdle explanation
5. **Circuit Breakers & Safety Gates** — 6 breakers: Portfolio Drawdown ≥10%, LLM Cost >$1, Concentration Cap 15% NAV, Sector Cap 40% NAV, Restricted Ticker (ASM/GSM/T2T), Quiet Skip
6. **Paper Ledger & Position Rules** — 4 key constraints (₹10L capital, 5 max positions, 15% NAV cap, 5-day max hold); fill simulation at prior-day close + 3 bps slippage; CNC-only note
7. **AWS Infrastructure** — table of all services (ECS Fargate, EventBridge, DynamoDB, S3, Secrets Manager, CloudWatch, Redis, SNS) with purpose and detail; cost target <₹2,000/month
8. **Phase Roadmap** — Phase 1 Paper Trading (active) vs Phase 2 Live Trading via Zerodha (future, unlocks after 30-day validation)

> **IMPORTANT:** When any system behaviour listed above changes (new agent, different model, new circuit breaker, cost change, new infrastructure resource), update this section AND the corresponding section in `app/how-it-works/page.tsx` so the dashboard stays accurate.

### Design requirements
- Dark mode by default (trading terminals are dark)
- Mobile responsive (you'll check this from phone)
- Refresh button triggers `router.refresh()` (no auto-polling — avoid unnecessary AWS costs)
- Show all monetary values in ₹ (INR) with Indian number formatting (lakhs, crores)

---

## 13. TERRAFORM INFRASTRUCTURE

### `infra/main.tf` — Full AWS setup for `ap-south-1`

Create these resources:

```hcl
# DynamoDB (4 tables, on-demand)
resource "aws_dynamodb_table" "positions" { ... }
resource "aws_dynamodb_table" "decisions" { ... }
resource "aws_dynamodb_table" "trades" { ... }
resource "aws_dynamodb_table" "nav_daily" { ... }

# S3 (raw data archive + decision logs)
resource "aws_s3_bucket" "archive" {
  # Enable versioning: false (cost control)
  # Lifecycle: delete objects >90 days old
}

# Secrets Manager
resource "aws_secretsmanager_secret" "llm_keys" { }
resource "aws_secretsmanager_secret" "broker_keys" { }   # Empty in Phase 1

# ECR (Docker image registry)
resource "aws_ecr_repository" "trader" { }

# ECS Cluster + Task Definition (Fargate, 1 vCPU, 2 GB)
resource "aws_ecs_cluster" "trader" { }
resource "aws_ecs_task_definition" "daily_run" {
  # Image from ECR
  # Command: ["python", "-m", "trader.daily_run"]
  # Env vars from Secrets Manager
  # CPU: 1024, Memory: 2048
}

# EventBridge rule: 17:00 IST Mon–Fri = 11:30 UTC Mon–Fri
resource "aws_cloudwatch_event_rule" "daily_close" {
  schedule_expression = "cron(30 11 ? * MON-FRI *)"
}
resource "aws_cloudwatch_event_target" "run_task" { ... }

# IAM roles
resource "aws_iam_role" "ecs_task_role" {
  # DynamoDB: read/write to trader tables only
  # S3: read/write to archive bucket only
  # Secrets Manager: read llm_keys and broker_keys
  # CloudWatch Logs: create log groups, put log events
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "trader" {
  retention_in_days = 30
}

# SNS Topic for alerts (circuit breakers, LLM cost overruns)
resource "aws_sns_topic" "alerts" { }
resource "aws_sns_topic_subscription" "email" {
  # Subscribe your email
}
```

### `infra/variables.tf`

```hcl
variable "aws_region" { default = "ap-south-1" }
variable "project_name" { default = "nse-llm-trader" }
variable "alert_email" { type = string }
variable "environment" { default = "dev" }
```

---

## 14. DOCKER & LOCAL DEV

### `docker-compose.yml`

```yaml
version: "3.9"
services:
  trader-api:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    volumes: ["./trader:/app/trader"]
    command: uvicorn trader.main:app --reload --host 0.0.0.0 --port 8000

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

### `Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN mkdir trader && touch trader/__init__.py && pip install --no-cache-dir .
COPY trader/ ./trader/
RUN pip install --no-cache-dir --no-deps .
CMD ["python", "-m", "trader.daily_run"]
```

### `pyproject.toml` — Project metadata + dependencies

```toml
[build-system]
requires = ["setuptools>=61.0.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "nse-llm-trader"
version = "0.1.0"
description = "Multi-agent LLM paper-trading system for Indian equities (NSE)"
requires-python = ">=3.12"
dependencies = [
    # Data
    "jugaad-data>=0.24.0",
    "nselib>=0.0.5",
    "yfinance>=0.2.40",
    "pandas>=2.2.0",
    "pandas-ta>=0.3.14b0",
    "feedparser>=6.0.11",
    "praw>=7.7.1",
    "sentence-transformers>=3.0.0",
    # LLM & orchestration
    "anthropic>=0.34.0",
    "google-generativeai>=0.8.0",
    "langgraph>=1.2.0",
    "langchain-anthropic>=0.3.0",
    "langchain-google-genai>=2.0.0",
    # Backend
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.8.0",
    "pydantic-settings>=2.4.0",
    "boto3>=1.35.0",
    "redis>=5.0.8",
    "httpx>=0.27.0",
    "pytz>=2024.1",
    # Numerics
    "numpy>=1.26.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "black>=24.0.0",
    "ruff>=0.6.0",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["trader*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["trader/tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.black]
line-length = 100
target-version = ["py312"]
```

---

## 15. TESTS

Build these test files. All tests must pass before any deployment.

### `tests/test_cost_model.py`

```python
def test_delivery_buy_50k():
    """₹50,000 delivery BUY. Expected total cost ≈ ₹70 (no sell-side charges on buy)."""

def test_delivery_round_trip_50k():
    """₹50,000 delivery BUY + SELL. Expected total ≈ ₹127–135 (25–27 bps)."""

def test_intraday_round_trip_50k():
    """₹50,000 intraday BUY + SELL. Expected total ≈ ₹53–60 (10–12 bps)."""

def test_dp_charges_only_on_sell():
    """DP charge of ₹15.93 must only appear on SELL side of delivery trades."""

def test_brokerage_cap():
    """₹5,00,000 intraday trade: brokerage capped at ₹20, not 0.03% (=₹150)."""
```

### `tests/test_agents.py`

```python
def test_pm_output_schema_valid():
    """Mock LLM response → Pydantic validation must pass."""

def test_pm_schema_error_triggers_retry():
    """Invalid JSON from LLM → system retries once → HOLD fallback if still invalid."""

def test_quiet_skip_logic():
    """No news + price_change_1d < 1.5% → SKIP without calling LLM."""

def test_circuit_breaker_drawdown():
    """Portfolio drawdown >= 10% → PM can only output EXIT or HOLD, never BUY."""

def test_restricted_ticker_skip():
    """Ticker marked as ASM/GSM → SKIP without calling agents."""
```

### `tests/test_ledger.py`

```python
def test_max_positions_enforced():
    """With 5 open positions, BUY decision must be rejected."""

def test_max_position_size():
    """BUY decision that would exceed 15% of NAV must be auto-reduced or rejected."""

def test_auto_exit_held_too_long():
    """Position held 5 days → auto EXIT signal generated."""

def test_nav_calculation():
    """NAV = cash + sum(qty × price) for all positions. Verify arithmetic."""
```

---

## 16. IMPLEMENTATION ORDER

Build in this exact order. Do not skip ahead.

**Phase 1A — Foundation (Days 1–2)**
1. `infra/` — Terraform resources (DynamoDB, S3, Secrets Manager, ECR)
2. `config/settings.py` + `config/tickers.py`
3. `ledger/cost_model.py` + `tests/test_cost_model.py` (must pass)
4. `storage/dynamo.py` helpers
5. `.env.example`, `Dockerfile`, `docker-compose.yml`, `pyproject.toml`

**Phase 1B — Data Pipeline (Days 3–4)**
6. `ingestion/market_data.py` — OHLCV + technical indicators
7. `ingestion/news.py` — RSS feeds + news window tagging
8. `ingestion/dedup.py` — cosine similarity dedup
9. `ingestion/fii_dii.py`
10. `tests/test_ingestion.py`

**Phase 1C — Agents (Days 5–6)**
11. `agents/base.py` — BaseAgent with caching + retry
12. `prompts/system_shared.md` (the cacheable part)
13. All 5 agent files + their prompt markdown files
14. `tests/test_agents.py`

**Phase 1D — Orchestration & Ledger (Day 7)**
15. `orchestration/state.py` + `orchestration/graph.py` + `orchestration/runner.py`
16. `ledger/paper_trade.py` + `ledger/circuit_breaker.py`
17. `daily_run.py` — wires everything together
18. `tests/test_ledger.py`

**Phase 1E — API + Dashboard (Days 8–10)**
19. `api/routes/` — all 4 route files + `api/schemas.py`
20. `trader/main.py` — FastAPI app
21. `dashboard/` — Next.js app (all pages and components)
22. End-to-end dry run: `docker-compose up` → hit all API endpoints

**Phase 1F — AWS Deployment (Days 11–14)**
23. `infra/ecs/` module — ECS task + EventBridge cron
24. `infra/eventbridge/` module
25. GitHub Actions CI/CD: `push to main → terraform plan → docker build → ECR push → ECS task update`
26. First scheduled run on AWS; verify CloudWatch logs

---

## 17. CRITICAL RULES FOR CLAUDE CODE

> Read these before generating any code. Never violate them.

1. **`PAPER_TRADING_MODE=true` must be checked at the top of `daily_run.py` before any broker call.** If false, throw an exception and exit. This gate must exist even in Phase 1 where no broker is wired.

2. **Never import or call `kiteconnect` order-placement methods in Phase 1.** Data-only Kite methods (quotes, history) are OK. Order placement (`place_order`, `modify_order`, `cancel_order`) must not exist in the codebase until Phase 2.

3. **Never commit secrets.** `.env` in `.gitignore`. All keys from env vars or Secrets Manager only.

4. **Every LLM call must have a cost tracker.** Log `{agent, model, input_tokens, output_tokens, cost_usd}` to CloudWatch after every call. Aggregate daily in `nav_daily` table.

5. **Schema validation before DynamoDB writes.** If an agent's output fails Pydantic validation twice, write a `HOLD` fallback decision with `schema_valid=False` flag. Never crash the daily pipeline over one bad LLM output.

6. **Prompt files are versioned in Git.** When you change a prompt, the old version stays in Git history. This is your ablation study dataset.

7. **All monetary values stored as `Decimal` in DynamoDB, not `float`.** Financial calculations must be exact.

8. **The `daily_run.py` must be idempotent.** Running it twice on the same day must not create duplicate trades. Check DynamoDB for existing run before processing.

9. **Never store full article text.** Headlines + URLs + 2-sentence summaries only. This is both a copyright consideration and a cost control.

10. **All times must be timezone-aware IST.** Use `pytz.timezone("Asia/Kolkata")` or `zoneinfo.ZoneInfo("Asia/Kolkata")`. Never store naive datetimes.

---

## 18. FIRST TASK FOR CLAUDE CODE

When you start, run through this checklist:

```
□ Confirm Python 3.12 is available
□ Confirm AWS credentials are configured (aws sts get-caller-identity)
□ Confirm all env vars in .env.example are present in local .env
□ Run: pip install -e ".[dev]"
□ Run: pytest tests/test_cost_model.py — must pass before anything else
□ Run: docker-compose up — confirm FastAPI health endpoint responds
□ Run: python -c "from trader.ingestion.market_data import fetch_eod_ohlcv; print(fetch_eod_ohlcv('RELIANCE', days=5))"
□ Confirm DynamoDB tables exist (terraform apply if not)
□ Run daily_run.py in dry-run mode: PAPER_TRADING_MODE=true DRY_RUN=true python -m trader.daily_run
```

Ask me for any missing credentials or config values before starting the build.
Do not generate placeholder/stub code — build the real implementation.

---

## 19. SUCCESS CRITERIA FOR PHASE 1

The build is complete when ALL of the following are true:

- [ ] `pytest tests/` passes with ≥ 95% pass rate
- [ ] `docker-compose up` runs cleanly; `/api/health` returns 200
- [ ] Daily run completes for all 15 tickers in < 8 minutes
- [ ] All 5 agent outputs are schema-valid ≥ 98% of the time across a 3-day dry run
- [ ] Daily LLM cost is < $0.40 per run (monitor via CloudWatch)
- [ ] DynamoDB tables populated correctly after each run
- [ ] Next.js dashboard displays NAV chart, positions, and decision log
- [ ] EventBridge triggers ECS task at 17:00 IST on a weekday
- [ ] Total monthly AWS + LLM cost estimate is < ₹2,000

---

*End of CLAUDE.md — Begin building.*
