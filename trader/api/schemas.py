"""
Pydantic response models for all FastAPI endpoints.

All monetary values are expressed as floats here (JSON doesn't support Decimal),
but are stored as Decimal in DynamoDB. The conversion happens in the route layer.
"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# ─── Health ──────────────────────────────────────────────────────────────────

class CircuitBreakerStatus(BaseModel):
    drawdown: bool = False
    concentration: bool = False
    sector_cap: bool = False
    llm_cost: bool = False
    restricted: bool = False

    @property
    def any_active(self) -> bool:
        return any([self.drawdown, self.concentration, self.sector_cap, self.llm_cost])


class HealthResponse(BaseModel):
    status: str = "OK"
    last_run: str | None = None           # ISO 8601 datetime string
    paper_mode: bool = True
    circuit_breakers_active: list[str] = Field(default_factory=list)
    daily_llm_cost_usd: float = 0.0
    environment: str = "development"
    version: str = "0.1.0"


# ─── Positions ───────────────────────────────────────────────────────────────

class PositionResponse(BaseModel):
    ticker: str
    qty: int
    avg_price: float
    days_held: int
    current_price: float | None = None
    unrealized_pnl_inr: float | None = None
    unrealized_pnl_pct: float | None = None
    stop_loss_price: float
    target_price: float
    kill_conditions: list[str] = Field(default_factory=list)
    entry_date: str
    horizon_days: int
    sector: str = ""


class PositionsResponse(BaseModel):
    positions: list[PositionResponse]
    open_count: int
    max_positions: int = 5
    cash_inr: float
    equity_value_inr: float
    nav_inr: float


# ─── Decisions ───────────────────────────────────────────────────────────────

class AgentDecisionDetail(BaseModel):
    agent: str
    model: str | None = None
    # News sentiment fields
    sentiment_score: float | None = None
    sentiment_label: str | None = None
    key_events: list[str] = Field(default_factory=list)
    data_quality: str | None = None
    # Technical fields
    technical_signal: str | None = None
    trend: str | None = None
    momentum: str | None = None
    volume_signal: str | None = None
    suggested_stop_loss_pct: float | None = None
    suggested_target_pct: float | None = None
    # Fundamentals fields
    fundamental_bias: str | None = None
    valuation: str | None = None
    institutional_flow: str | None = None
    macro_tailwind: bool | None = None
    red_flags: list[str] = Field(default_factory=list)
    data_staleness_days: int | None = None
    # Bull-bear fields
    bull_thesis: list[str] = Field(default_factory=list)
    bear_thesis: list[str] = Field(default_factory=list)
    debate_winner: str | None = None
    conviction_delta: float | None = None
    key_risk: str | None = None
    # PM fields
    decision: str | None = None
    quantity_shares: int | None = None
    estimated_trade_value_inr: float | None = None
    horizon_days: int | None = None
    target_price: float | None = None
    stop_loss_price: float | None = None
    primary_thesis: str | None = None
    agent_agreement: str | None = None
    estimated_cost_bps: float | None = None
    risk_reward_ratio: float | None = None
    # Common
    confidence: float | None = None
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    schema_valid: bool | None = None
    retry_count: int | None = None


class SimulatedFillResponse(BaseModel):
    side: str
    qty: int
    fill_price: float
    trade_value_inr: float
    simulated_cost_inr: float
    simulated_cost_bps: float
    slippage_bps: float


class DecisionResponse(BaseModel):
    ticker: str
    date: str
    pm_decision: str | None = None
    pm_confidence: float | None = None
    pm_reasoning: str | None = None
    agent_agreement: str | None = None
    news_sentiment: str | None = None       # e.g. "BULLISH"
    technical_signal: str | None = None     # e.g. "BUY"
    fundamental_bias: str | None = None     # e.g. "BULLISH"
    debate_winner: str | None = None        # "BULL" | "BEAR" | "DRAW"
    estimated_cost_bps: float | None = None
    risk_reward_ratio: float | None = None
    skip_reason: str | None = None
    actual_fill: SimulatedFillResponse | None = None
    agents: list[AgentDecisionDetail] = Field(default_factory=list)


class DecisionsResponse(BaseModel):
    date: str
    decisions: list[DecisionResponse]
    total: int


# ─── Metrics ─────────────────────────────────────────────────────────────────

class BenchmarkPoint(BaseModel):
    date: str
    nav: float


class BenchmarkComparison(BaseModel):
    nifty50_tri: list[BenchmarkPoint] = Field(default_factory=list)
    equal_weight: list[BenchmarkPoint] = Field(default_factory=list)
    momentum_5d: list[BenchmarkPoint] = Field(default_factory=list)
    mean_reversion_5d: list[BenchmarkPoint] = Field(default_factory=list)
    buy_and_hold: list[BenchmarkPoint] = Field(default_factory=list)


class MetricsSummaryResponse(BaseModel):
    nav: float
    initial_capital_inr: float = 1_000_000.0
    cumulative_return_pct: float
    daily_return_pct: float
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    current_drawdown_pct: float
    win_rate: float
    profit_factor: float
    avg_win_loss_ratio: float
    total_trades: int
    total_llm_cost_usd: float
    days_running: int
    data_warning: str | None = None        # "N < 30 observations — statistics not reliable"
    benchmark_comparison: BenchmarkComparison = Field(default_factory=BenchmarkComparison)


class DailyNavPoint(BaseModel):
    date: str
    nav: float
    daily_return_pct: float
    nifty_return_pct: float
    drawdown_pct: float
    llm_cost_usd: float
    open_positions: int


class DailyNavResponse(BaseModel):
    points: list[DailyNavPoint]
    from_date: str | None = None
    to_date: str | None = None


class AgentHitRate(BaseModel):
    agent: str
    hit_rate: float
    n_calls: int
    avg_confidence: float


class AgentCostBreakdown(BaseModel):
    agent: str
    model: str
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    call_count: int


# ─── Logs ────────────────────────────────────────────────────────────────────

class LogLine(BaseModel):
    timestamp: str
    level: str          # INFO | WARNING | ERROR | DEBUG
    logger: str
    message: str
    raw: str            # original log line for display


class LogsResponse(BaseModel):
    date: str
    lines: list[LogLine]
    total: int
    has_error: bool


# ─── Performance analytics ────────────────────────────────────────────────────

class PerformanceAnalyticsResponse(BaseModel):
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    agent_hit_rates: list[AgentHitRate]
    agent_cost_breakdown: list[AgentCostBreakdown]
    benchmark_comparison: BenchmarkComparison
    statistical_warning: str = (
        "Fewer than 30 trading-day observations — reported statistics are not reliable. "
        "Revisit after 6 weeks of live paper-trading data."
    )


# ─── Daily Report ─────────────────────────────────────────────────────────────

class ReportMacro(BaseModel):
    nifty_close: float = 0.0
    nifty_1d_pct: float = 0.0
    nifty_5d_pct: float = 0.0
    rbi_rate: float = 0.0
    usd_inr: float = 0.0
    fii_net_buy_cr: float = 0.0
    dii_net_buy_cr: float = 0.0
    fii_dii_source: str = ""


class ReportSummary(BaseModel):
    tickers_total: int = 0
    tickers_completed: int = 0
    tickers_skipped: int = 0
    tickers_errored: int = 0
    decision_counts: dict[str, int] = Field(default_factory=dict)
    total_llm_cost_usd: float = 0.0
    schema_errors: int = 0
    nav_inr: float = 0.0
    cash_inr: float = 0.0
    daily_return_pct: float = 0.0
    cumulative_return_pct: float = 0.0
    drawdown_pct: float = 0.0
    open_positions: int = 0


class ReportTickerTokens(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class ReportTicker(BaseModel):
    ticker: str
    company_name: str = ""
    sector: str = ""
    status: str = "completed"           # completed | skipped | errored
    skip_reason: str | None = None
    errors: list[str] = Field(default_factory=list)
    processing_time_ms: int = 0
    close_price: float = 0.0
    pct_change_1d: float = 0.0
    news_output: dict[str, Any] | None = None
    technical_output: dict[str, Any] | None = None
    fundamentals_output: dict[str, Any] | None = None
    bull_bear_output: dict[str, Any] | None = None
    pm_output: dict[str, Any] | None = None
    simulated_fill: dict[str, Any] | None = None
    tokens_used: dict[str, ReportTickerTokens] = Field(default_factory=dict)
    ticker_cost_usd: float = 0.0


class DailyReportResponse(BaseModel):
    run_date: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float = 0.0
    macro: ReportMacro = Field(default_factory=ReportMacro)
    summary: ReportSummary = Field(default_factory=ReportSummary)
    run_errors: list[str] = Field(default_factory=list)
    tickers: list[ReportTicker] = Field(default_factory=list)
