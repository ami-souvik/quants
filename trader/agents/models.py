"""
Pydantic output models for all 5 agents.

Every agent must return one of these validated models. If validation fails,
the caller retries once, then falls back to the SKIP default for the PM.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ── Agent 1: News & Sentiment ─────────────────────────────────────────────────

SentimentLabel = Literal["BULLISH", "SLIGHTLY_BULLISH", "NEUTRAL", "SLIGHTLY_BEARISH", "BEARISH"]
DataQuality = Literal["HIGH", "MEDIUM", "LOW", "STALE"]
NewsWindow = Literal["PRE_OPEN", "PREV_INTRADAY", "PREV_AFTER_CLOSE"]


class NewsSentimentOutput(BaseModel):
    ticker: str
    sentiment_score: float = Field(ge=0.0, le=1.0)
    sentiment_label: SentimentLabel
    key_events: list[str]
    news_window: NewsWindow
    data_quality: DataQuality
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


# ── Agent 2: Technical Analysis ───────────────────────────────────────────────

TechnicalSignal = Literal["BUY", "SHORT", "SKIP"]
IntradayBias = Literal["GAP_UP_CONTINUATION", "GAP_DOWN_FADE", "RANGE_PLAY", "NO_SIGNAL"]
Momentum = Literal["OVERBOUGHT", "NEUTRAL", "OVERSOLD"]
VolumeSignal = Literal["ABOVE_AVG", "AVERAGE", "BELOW_AVG", "DIVERGENT"]


class TechnicalOutput(BaseModel):
    ticker: str
    technical_signal: TechnicalSignal
    intraday_bias: IntradayBias
    momentum: Momentum
    suggested_entry_zone: str
    suggested_stop_loss_pct: float = Field(ge=0.0)
    suggested_target_pct: float = Field(ge=0.0)
    expected_range_pct: float = Field(ge=0.0)
    volume_signal: VolumeSignal
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


# ── Agent 3: Fundamentals ─────────────────────────────────────────────────────

FundamentalBias = Literal["BULLISH", "NEUTRAL", "BEARISH"]
Valuation = Literal["CHEAP", "FAIR", "EXPENSIVE", "UNKNOWN"]
InstitutionalFlow = Literal[
    "FII_BUYING", "FII_SELLING", "DII_BUYING", "DII_SELLING", "MIXED", "NEUTRAL"
]


class FundamentalsOutput(BaseModel):
    ticker: str
    fundamental_bias: FundamentalBias
    valuation: Valuation
    institutional_flow: InstitutionalFlow
    macro_tailwind: bool
    red_flags: list[str]
    data_staleness_days: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


# ── Agent 4: Bull vs Bear Debate ──────────────────────────────────────────────

DebateWinner = Literal["BULL", "BEAR", "DRAW"]


class BullBearOutput(BaseModel):
    ticker: str
    bull_thesis: list[str] = Field(min_length=1, max_length=3)
    bear_thesis: list[str] = Field(min_length=1, max_length=3)
    debate_winner: DebateWinner
    conviction_delta: float = Field(ge=0.0, le=1.0)
    key_risk: str
    confidence: float = Field(ge=0.0, le=1.0)


# ── Agent 5: Portfolio Manager ────────────────────────────────────────────────

PMDecisionType = Literal["BUY", "SKIP"]
SkipReason = Literal["QUIET", "RESTRICTED", "TIME_CUTOFF", "DRAWDOWN", "LOW_CONFIDENCE", ""]
ProductType = Literal["MIS"]
AgentAgreement = Literal["HIGH", "MEDIUM", "LOW"]


class PMDecision(BaseModel):
    ticker: str
    decision: PMDecisionType
    direction: Literal["LONG"] = "LONG"
    skip_reason: SkipReason = ""
    quantity_shares: int = Field(ge=0)
    estimated_trade_value_inr: float = Field(ge=0.0)
    product_type: ProductType = "MIS"
    entry_window: str = "09:15–09:30"
    squareoff_time: str = "15:15"
    target_price: float = Field(ge=0.0)
    stop_loss_price: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    primary_thesis: str
    intraday_exit_triggers: list[str]
    agent_agreement: AgentAgreement
    estimated_cost_bps: float = Field(ge=0.0)
    risk_reward_ratio: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_decision_constraints(self) -> "PMDecision":
        if self.decision == "BUY" and self.quantity_shares == 0:
            raise ValueError("BUY decision must have quantity_shares > 0")
        if self.product_type != "MIS":
            raise ValueError("product_type must be MIS — CNC is forbidden in Phase 1")
        return self


# ── SKIP fallback (used when PM schema validation fails twice) ─────────────────

def pm_skip_fallback(ticker: str) -> PMDecision:
    return PMDecision(
        ticker=ticker,
        decision="SKIP",
        direction="LONG",
        skip_reason="LOW_CONFIDENCE",
        quantity_shares=0,
        estimated_trade_value_inr=0.0,
        product_type="MIS",
        entry_window="09:15–09:30",
        squareoff_time="15:15",
        target_price=0.0,
        stop_loss_price=0.0,
        confidence=0.0,
        primary_thesis="Schema validation failed — defaulting to SKIP.",
        intraday_exit_triggers=[],
        agent_agreement="LOW",
        estimated_cost_bps=13.0,
        risk_reward_ratio=0.0,
    )


# ── Cost tracking ──────────────────────────────────────────────────────────────

class TokenUsage(BaseModel):
    agent: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0       # tokens served from cache (cheap read)
    cache_write_tokens: int = 0  # tokens written to cache (one-time creation cost)
    cost_usd: float = 0.0
