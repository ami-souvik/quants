# NSE LLM Trader

A personal, paper-trading multi-agent system for Indian equities (NSE).  
Five LLM agents debate 15 large-cap Nifty 50 stocks every weekday at 17:00 IST and produce structured trade decisions. All fills are **simulated** — no real money is ever touched in Phase 1.

> **Paper Trading Mode only.** `PAPER_TRADING_MODE=true` is enforced at the top of `daily_run.py`.

---

## How it works

```
17:00 IST (Mon–Fri)
         │
         ▼
  ┌─────────────────┐
  │  Data Ingestion  │  OHLCV · 18 RSS feeds · FII/DII flows
  └────────┬────────┘
           │  (per ticker, sequential)
           ▼
  ┌─────────────────┐
  │  News Sentiment  │  Gemini 2.5 Flash — sentiment score 0–1
  ├─────────────────┤
  │   Technical      │  Gemini 2.5 Flash — RSI, MACD, ADX, ATR …
  ├─────────────────┤
  │  Fundamentals    │  Gemini 2.5 Flash — valuation, FII flows, macro
  ├─────────────────┤
  │  Bull vs Bear    │  Gemini 2.5 Flash — adversarial 3-point debate
  ├─────────────────┤
  │ Portfolio Manager│  Gemini 2.5 Flash (→ escalation model if confidence < 0.5)
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Paper Ledger   │  Simulated fill · cost model · circuit breakers
  └────────┬────────┘
           │
           ▼
  DynamoDB · S3 · Redis → Next.js dashboard
```

The full visual breakdown is available at `/how-it-works` in the dashboard.

---

## Stock universe

15 large-cap Nifty 50 stocks across 7 sectors:

| Symbol | Company | Sector |
|--------|---------|--------|
| RELIANCE | Reliance Industries | Energy |
| TCS | Tata Consultancy Services | IT |
| INFY | Infosys | IT |
| HDFCBANK | HDFC Bank | Banking |
| ICICIBANK | ICICI Bank | Banking |
| AXISBANK | Axis Bank | Banking |
| KOTAKBANK | Kotak Mahindra Bank | Banking |
| BAJFINANCE | Bajaj Finance | NBFC |
| HINDUNILVR | Hindustan Unilever | FMCG |
| ITC | ITC Limited | FMCG |
| LT | Larsen & Toubro | Capital Goods |
| BHARTIARTL | Bharti Airtel | Telecom |
| MARUTI | Maruti Suzuki | Auto |
| ASIANPAINT | Asian Paints | Paints |
| ADANIENT | Adani Enterprises | Conglomerate |

---

## Project structure

```
agentic-trading/
├── trader/                   # Python backend
│   ├── daily_run.py          # Entry point — runs all 15 tickers sequentially
│   ├── main.py               # FastAPI app
│   ├── agents/               # 5 LLM agents (base, news_sentiment, technical,
│   │                         #   fundamentals, bull_bear, portfolio_manager)
│   ├── ingestion/            # market_data, news (18 RSS feeds), fii_dii, dedup
│   ├── orchestration/        # LangGraph state machine (graph, state, runner)
│   ├── ledger/               # paper_trade, cost_model, circuit_breaker
│   ├── storage/              # DynamoDB + S3 helpers
│   ├── metrics/              # Sharpe, Sortino, drawdown, benchmarks
│   ├── api/                  # FastAPI routes (positions, decisions, metrics, health)
│   ├── prompts/              # Agent prompts as versioned Markdown files
│   ├── config/               # Pydantic settings + ticker list
│   └── tests/                # pytest suite
├── dashboard/                # Next.js 14 App Router (Tailwind, dark mode)
│   └── app/
│       ├── page.tsx          # Main dashboard (NAV chart, positions)
│       ├── decisions/        # Agent decision log with date filter
│       ├── metrics/          # Performance vs 5 benchmarks
│       ├── logs/             # Daily run log viewer
│       └── how-it-works/     # Visual system architecture explainer
├── infra/                    # Terraform — ECS, DynamoDB, S3, EventBridge, SNS
├── docker-compose.yml        # Local dev: FastAPI + Redis + local DynamoDB
├── Dockerfile
└── pyproject.toml
```

---

## Prerequisites

- Python 3.12+
- Node.js 18+
- Docker + Docker Compose
- AWS CLI configured (`aws sts get-caller-identity` should return your account)

---

## Local setup

### 1. Clone and install

```bash
git clone <repo-url>
cd agentic-trading

# Python dependencies
pip install -e ".[dev]"

# Dashboard dependencies
cd dashboard && npm install && cd ..
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY or GEMINI_API_KEY
# Leave KITE_* empty — Phase 2 only
```

Key variables:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key (Haiku/Sonnet agents) |
| `GEMINI_API_KEY` | Gemini API key (Flash agents) |
| `PAPER_TRADING_MODE` | Must be `true` in Phase 1 |
| `DYNAMO_ENDPOINT_URL` | Set to `http://localhost:8001` for local DynamoDB |
| `DRY_RUN` | `true` = run pipeline but skip all DynamoDB writes |
| `OLLAMA_BASE_URL` | Local Ollama fallback when cloud API keys are absent |

If both `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` are empty, agents automatically fall back to Ollama (`OLLAMA_MODEL`, default `llama3.2:3b`).

### 3. Start the stack

```bash
docker compose up
```

Services:
- `trader-api` → [http://localhost:8000](http://localhost:8000)
- `redis` → `localhost:6379`
- `dynamodb-local` → `localhost:8001` (when `DYNAMO_ENDPOINT_URL` is set)

### 4. Start the dashboard

```bash
cd dashboard
npm run dev
# → http://localhost:3000
```

---

## Running the pipeline

### Health check

```bash
curl http://localhost:8000/api/health
```

### Manual daily run

```bash
# Dry-run (no DB writes, full agent execution)
DRY_RUN=true python -m trader.daily_run

# Full paper-trade run
python -m trader.daily_run
```

The pipeline is idempotent — running it twice on the same date is safe (the second run is a no-op).

### Smoke-test market data

```bash
python -c "
from trader.ingestion.market_data import fetch_eod_ohlcv
print(fetch_eod_ohlcv('RELIANCE', days=5))
"
```

---

## Tests

```bash
pytest trader/tests/

# Individual suites
pytest trader/tests/test_cost_model.py   # Must pass — financial arithmetic
pytest trader/tests/test_agents.py       # Schema validation + circuit breakers
pytest trader/tests/test_ledger.py       # Position limits + NAV calculation
pytest trader/tests/test_ingestion.py    # News fetch + dedup
```

---

## API reference

All endpoints require `X-API-Key: <API_KEY>` header (set in `.env`).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Pipeline status, last run time, circuit breakers |
| `GET` | `/api/positions` | Open positions with P&L |
| `GET` | `/api/decisions?date=YYYY-MM-DD` | All agent decisions for a date |
| `GET` | `/api/metrics/summary` | Sharpe, Sortino, drawdown, win rate |
| `GET` | `/api/metrics/daily?from=…&to=…` | NAV time series |

Responses are cached in Redis for 60 seconds.

---

## Transaction costs (India 2025–26, CNC delivery)

| Charge | Rate |
|--------|------|
| Brokerage | ₹0 (Zerodha free delivery) |
| STT | 0.1% buy + 0.1% sell |
| NSE txn charge | 0.00297% both sides |
| GST | 18% on (brokerage + txn + SEBI fee) |
| SEBI fee | ₹10/crore |
| Stamp duty | 0.015% on buy only |
| DP charges | ₹15.93 on sell only |
| **Round-trip total** | **~25.5–28 bps** |

The Portfolio Manager only places a BUY if the expected move exceeds the 28 bps cost hurdle.

---

## Circuit breakers

| Breaker | Trigger | Effect |
|---------|---------|--------|
| Portfolio Drawdown | ≥ 10% NAV | No new BUY — EXIT/HOLD only |
| LLM Cost | Daily spend > $1.00 | Alert + cheaper model substituted |
| Concentration | Any position ≥ 15% NAV | No further adds |
| Sector Cap | Any sector ≥ 40% NAV | No new entries in that sector |
| Restricted Ticker | Stock on NSE ASM/GSM/T2T | Force EXIT |
| Quiet Skip | No news 24 h AND price Δ < 1.5% | Skip pipeline entirely |

---

## AWS deployment

Infrastructure is defined in `infra/` (Terraform, `ap-south-1`).

```bash
cd infra
terraform init
terraform plan -var="alert_email=you@example.com"
terraform apply
```

The EventBridge cron (`cron(30 11 ? * MON-FRI *)`) triggers the ECS Fargate task at 17:00 IST on every trading day. Logs go to CloudWatch (`/ecs/nse-llm-trader`, 30-day retention).

**Cost target:** < ₹2,000/month (LLM + AWS combined). LLM target: < $0.40/run.

---

## Phase roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1** | Active | Paper trading — all decisions simulated, no real orders |
| **Phase 2** | Future | Live trading via Zerodha Kite API — unlocks after 30-day Phase 1 validation |

---

## Key constraints (never relax in Phase 1)

- `PAPER_TRADING_MODE=true` checked at the top of `daily_run.py` — exits if false
- `kiteconnect` order-placement methods (`place_order`, `modify_order`, `cancel_order`) must not exist in the codebase until Phase 2
- All monetary values stored as `Decimal` in DynamoDB, never `float`
- All datetimes must be timezone-aware IST (`Asia/Kolkata`)
- Never store full article body — headline + URL + 2-sentence summary only
- Secrets loaded from environment / AWS Secrets Manager only — `.env` is gitignored

---

*Personal experiment. Not financial advice.*
