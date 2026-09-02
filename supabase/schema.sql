-- ==============================================================================
-- Supabase / PostgreSQL Schema for NSE Agentic Paper Trader & Better Auth
-- ==============================================================================

-- 1. POSITIONS (Current open and closed paper trading positions)
CREATE TABLE IF NOT EXISTS positions (
    ticker TEXT PRIMARY KEY,
    qty INTEGER NOT NULL DEFAULT 0,
    avg_price NUMERIC(12, 4) NOT NULL DEFAULT 0,
    days_held INTEGER NOT NULL DEFAULT 0,
    current_price NUMERIC(12, 4),
    unrealized_pnl_inr NUMERIC(12, 4) DEFAULT 0,
    unrealized_pnl_pct NUMERIC(8, 4) DEFAULT 0,
    stop_loss_price NUMERIC(12, 4) NOT NULL DEFAULT 0,
    target_price NUMERIC(12, 4) NOT NULL DEFAULT 0,
    kill_conditions JSONB DEFAULT '[]'::jsonb,
    entry_date DATE NOT NULL,
    horizon_days INTEGER NOT NULL DEFAULT 5,
    sector TEXT NOT NULL DEFAULT '',
    is_closed BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. DECISIONS (Per-agent debate and trade signals for each ticker & date)
CREATE TABLE IF NOT EXISTS decisions (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    ticker TEXT NOT NULL,
    agent TEXT NOT NULL,
    model TEXT,
    decision_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_date_ticker_agent UNIQUE (date, ticker, agent)
);
CREATE INDEX IF NOT EXISTS idx_decisions_date ON decisions(date);
CREATE INDEX IF NOT EXISTS idx_decisions_ticker ON decisions(ticker);

-- 3. TRADES (Simulated fills, slippage, and brokerage cost breakdown)
CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    trade_id TEXT UNIQUE NOT NULL,
    date DATE NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL, -- 'BUY' | 'SELL'
    qty INTEGER NOT NULL,
    price NUMERIC(12, 4) NOT NULL,
    trade_value_inr NUMERIC(14, 4) NOT NULL,
    cost_inr NUMERIC(10, 4) NOT NULL DEFAULT 0,
    cost_bps NUMERIC(8, 4) NOT NULL DEFAULT 0,
    slippage_bps NUMERIC(8, 4) NOT NULL DEFAULT 0,
    charges_breakdown JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date);

-- 4. NAV HISTORY (Daily portfolio NAV, cash, drawdown snapshots)
CREATE TABLE IF NOT EXISTS nav_history (
    date DATE PRIMARY KEY,
    nav_inr NUMERIC(14, 4) NOT NULL,
    cash_inr NUMERIC(14, 4) NOT NULL,
    equity_value_inr NUMERIC(14, 4) NOT NULL,
    daily_return_pct NUMERIC(8, 4) DEFAULT 0,
    cumulative_return_pct NUMERIC(8, 4) DEFAULT 0,
    drawdown_pct NUMERIC(8, 4) DEFAULT 0,
    open_positions INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_nav_history_date ON nav_history(date ASC);

-- 5. DAILY REPORTS (Comprehensive end-of-day run reports & agent outputs)
CREATE TABLE IF NOT EXISTS daily_reports (
    run_date DATE PRIMARY KEY,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_seconds NUMERIC(8, 2) DEFAULT 0,
    macro JSONB DEFAULT '{}'::jsonb,
    summary JSONB DEFAULT '{}'::jsonb,
    run_errors JSONB DEFAULT '[]'::jsonb,
    tickers JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. DAILY LOGS (Structured log session lines for web dashboard log viewer)
CREATE TABLE IF NOT EXISTS daily_logs (
    id BIGSERIAL PRIMARY KEY,
    run_datetime TEXT NOT NULL,
    date DATE NOT NULL,
    lines JSONB DEFAULT '[]'::jsonb,
    total_lines INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    warning_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_run_datetime UNIQUE (run_datetime)
);
CREATE INDEX IF NOT EXISTS idx_daily_logs_date ON daily_logs(date);

-- ==============================================================================
-- Better Auth Schema for Next.js Authentication (User & Session Management)
-- ==============================================================================

CREATE TABLE IF NOT EXISTS "user" (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    "emailVerified" BOOLEAN NOT NULL DEFAULT FALSE,
    image TEXT,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS session (
    id TEXT PRIMARY KEY,
    "expiresAt" TIMESTAMPTZ NOT NULL,
    token TEXT NOT NULL UNIQUE,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "ipAddress" TEXT,
    "userAgent" TEXT,
    "userId" TEXT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS account (
    id TEXT PRIMARY KEY,
    "accountId" TEXT NOT NULL,
    "providerId" TEXT NOT NULL,
    "userId" TEXT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    "accessToken" TEXT,
    "refreshToken" TEXT,
    "idToken" TEXT,
    "accessTokenExpiresAt" TIMESTAMPTZ,
    "refreshTokenExpiresAt" TIMESTAMPTZ,
    scope TEXT,
    password TEXT,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS verification (
    id TEXT PRIMARY KEY,
    identifier TEXT NOT NULL,
    value TEXT NOT NULL,
    "expiresAt" TIMESTAMPTZ NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
