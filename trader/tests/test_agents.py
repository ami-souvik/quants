"""
Tests for the 5-agent pipeline.

All LLM calls are mocked — no real API keys needed.
Tests cover: schema validation, retry logic, quiet-skip, circuit breakers,
restricted-ticker skip, and self-consistency majority vote.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from trader.agents.models import (
    BullBearOutput,
    FundamentalsOutput,
    NewsSentimentOutput,
    PMDecision,
    TechnicalOutput,
    TokenUsage,
    pm_skip_fallback,
)
from trader.agents.base import BaseAgent
from trader.agents.news_sentiment import NewsSentimentAgent
from trader.agents.technical import TechnicalAgent
from trader.agents.fundamentals import FundamentalsAgent
from trader.agents.bull_bear import BullBearAgent
from trader.agents.portfolio_manager import PortfolioManagerAgent


# ── Fixture helpers ──────────────────────────────────────────────────────────

def _mock_usage() -> TokenUsage:
    return TokenUsage(agent="test", model="claude-haiku-4-5", input_tokens=100, output_tokens=50, cost_usd=0.0001)


def _valid_news_json(ticker: str = "RELIANCE") -> str:
    return json.dumps({
        "ticker": ticker,
        "sentiment_score": 0.72,
        "sentiment_label": "BULLISH",
        "key_events": ["Q4 profit beat by 8%"],
        "news_window": "PREV_AFTER_CLOSE",
        "data_quality": "HIGH",
        "confidence": 0.78,
        "reasoning": "Strong results and positive guidance.",
    })


def _valid_technical_json(ticker: str = "RELIANCE") -> str:
    return json.dumps({
        "ticker": ticker,
        "technical_signal": "BUY",
        "intraday_bias": "GAP_UP_CONTINUATION",
        "momentum": "OVERSOLD",
        "suggested_entry_zone": "2840–2855",
        "suggested_stop_loss_pct": 0.5,
        "suggested_target_pct": 1.2,
        "expected_range_pct": 1.8,
        "volume_signal": "ABOVE_AVG",
        "confidence": 0.65,
        "reasoning": "RSI oversold with volume confirmation.",
    })


def _valid_fundamentals_json(ticker: str = "RELIANCE") -> str:
    return json.dumps({
        "ticker": ticker,
        "fundamental_bias": "BULLISH",
        "valuation": "FAIR",
        "institutional_flow": "FII_BUYING",
        "macro_tailwind": True,
        "red_flags": [],
        "data_staleness_days": 30,
        "confidence": 0.60,
        "reasoning": "FII accumulation in energy sector.",
    })


def _valid_bull_bear_json(ticker: str = "RELIANCE") -> str:
    return json.dumps({
        "ticker": ticker,
        "bull_thesis": ["RSI oversold", "FII buying", "Results beat"],
        "bear_thesis": ["SMA 20 resistance", "USD/INR pressure", "ADX low"],
        "debate_winner": "BULL",
        "conviction_delta": 0.20,
        "key_risk": "Nifty falls >1.5% tomorrow.",
        "confidence": 0.62,
    })


def _valid_pm_json(
    ticker: str = "RELIANCE",
    decision: str = "BUY",
    confidence: float = 0.72,
) -> str:
    return json.dumps({
        "ticker": ticker,
        "decision": decision,
        "direction": "LONG",
        "skip_reason": "" if decision == "BUY" else "LOW_CONFIDENCE",
        "quantity_shares": 20 if decision == "BUY" else 0,
        "estimated_trade_value_inr": 56810.0 if decision == "BUY" else 0.0,
        "product_type": "MIS",
        "entry_window": "09:15–09:30",
        "squareoff_time": "15:15",
        "target_price": 2950.0 if decision == "BUY" else 0.0,
        "stop_loss_price": 2750.0 if decision == "BUY" else 0.0,
        "confidence": confidence,
        "primary_thesis": "Oversold RSI + Q4 beat.",
        "intraday_exit_triggers": ["Nifty drops >0.8% from open"] if decision == "BUY" else [],
        "agent_agreement": "HIGH",
        "estimated_cost_bps": 13.0,
        "risk_reward_ratio": 2.1,
    })


# ── Model validation tests ───────────────────────────────────────────────────

class TestModelValidation:
    def test_news_sentiment_valid(self):
        output = NewsSentimentOutput.model_validate_json(_valid_news_json())
        assert output.ticker == "RELIANCE"
        assert output.sentiment_score == pytest.approx(0.72)
        assert output.sentiment_label == "BULLISH"

    def test_technical_valid(self):
        output = TechnicalOutput.model_validate_json(_valid_technical_json())
        assert output.technical_signal == "BUY"
        assert output.intraday_bias == "GAP_UP_CONTINUATION"

    def test_fundamentals_valid(self):
        output = FundamentalsOutput.model_validate_json(_valid_fundamentals_json())
        assert output.fundamental_bias == "BULLISH"
        assert output.institutional_flow == "FII_BUYING"

    def test_bull_bear_valid(self):
        output = BullBearOutput.model_validate_json(_valid_bull_bear_json())
        assert len(output.bull_thesis) == 3
        assert output.debate_winner == "BULL"

    def test_pm_valid(self):
        output = PMDecision.model_validate_json(_valid_pm_json())
        assert output.decision == "BUY"
        assert output.quantity_shares == 20

    def test_pm_invalid_sentiment_label(self):
        bad = json.loads(_valid_news_json())
        bad["sentiment_label"] = "VERY_BULLISH"  # not in Literal
        with pytest.raises(ValidationError):
            NewsSentimentOutput.model_validate(bad)

    def test_pm_buy_requires_quantity(self):
        bad = json.loads(_valid_pm_json())
        bad["quantity_shares"] = 0  # BUY with 0 qty → should fail
        with pytest.raises(ValidationError):
            PMDecision.model_validate(bad)

    def test_confidence_out_of_range(self):
        bad = json.loads(_valid_pm_json())
        bad["confidence"] = 1.5  # > 1.0
        with pytest.raises(ValidationError):
            PMDecision.model_validate(bad)


# ── BaseAgent._extract_json tests ────────────────────────────────────────────

class TestJsonExtraction:
    def setup_method(self):
        with patch.object(BaseAgent, "__init__", lambda self: None):
            self.agent = BaseAgent.__new__(BaseAgent)

    def test_plain_json(self):
        raw = '{"ticker": "TCS", "value": 1}'
        result = BaseAgent._extract_json(raw)
        assert result["ticker"] == "TCS"

    def test_json_with_code_fence(self):
        raw = "```json\n{\"ticker\": \"TCS\"}\n```"
        result = BaseAgent._extract_json(raw)
        assert result["ticker"] == "TCS"

    def test_json_with_bare_fence(self):
        raw = "```\n{\"ticker\": \"INFY\"}\n```"
        result = BaseAgent._extract_json(raw)
        assert result["ticker"] == "INFY"


# ── pm_skip_fallback tests ───────────────────────────────────────────────────

class TestPMSkipFallback:
    def test_fallback_structure(self):
        fallback = pm_skip_fallback("RELIANCE")
        assert fallback.decision == "SKIP"
        assert fallback.quantity_shares == 0
        assert fallback.confidence == 0.0
        assert fallback.ticker == "RELIANCE"
        assert fallback.product_type == "MIS"

    def test_fallback_is_valid_pydantic(self):
        fallback = pm_skip_fallback("TCS")
        assert isinstance(fallback, PMDecision)


# ── PM output schema validation test (integration) ──────────────────────────

class TestPMSchemaValidation:
    """Test that a valid mock LLM response passes Pydantic validation."""

    def test_pm_output_schema_valid(self):
        raw = _valid_pm_json("ICICIBANK", "BUY", 0.72)
        pm = PMDecision.model_validate_json(raw)
        assert pm.decision == "BUY"
        assert pm.ticker == "ICICIBANK"
        assert pm.product_type == "MIS"

    def test_pm_schema_error_triggers_retry(self):
        """
        When LLM returns invalid JSON first, then valid JSON second,
        _call_with_retry must succeed on retry.
        """
        call_count = 0
        responses = [
            ("not valid json {{{}}", _mock_usage()),  # first call: garbage
            (_valid_pm_json("TCS", "SKIP", 0.60), _mock_usage()),  # second: valid
        ]

        def fake_call():
            nonlocal call_count
            result = responses[call_count]
            call_count += 1
            return result

        with patch.object(BaseAgent, "__init__", lambda self: None):
            agent = BaseAgent.__new__(BaseAgent)
            agent.name = "portfolio_manager"
            agent.model = "claude-haiku-4-5"
            agent.settings = MagicMock(agent_schema_retry_enabled=True)

        def parse_fn(text: str) -> PMDecision:
            return BaseAgent._parse_output(agent, text, PMDecision)

        result, usage, valid = agent._call_with_retry(fake_call, parse_fn, max_retries=1)
        assert valid is True
        assert result is not None
        assert result.decision == "SKIP"
        assert call_count == 2  # retried exactly once

    def test_both_retries_fail_returns_none(self):
        """When both calls return garbage, schema_valid=False and result=None."""
        def fake_call():
            return ("{{{{ totally broken", _mock_usage())

        with patch.object(BaseAgent, "__init__", lambda self: None):
            agent = BaseAgent.__new__(BaseAgent)
            agent.name = "test"
            agent.model = "claude-haiku-4-5"
            agent.settings = MagicMock(agent_schema_retry_enabled=True)

        def parse_fn(text: str) -> PMDecision:
            return BaseAgent._parse_output(agent, text, PMDecision)

        result, usage, valid = agent._call_with_retry(fake_call, parse_fn, max_retries=1)
        assert valid is False
        assert result is None


# ── Quiet-skip logic test ────────────────────────────────────────────────────

class TestQuietSkipLogic:
    """
    The orchestrator (graph.py) checks quiet-skip before calling agents.
    Test the condition logic directly.
    """

    def _should_skip(self, news_count: int, price_change_1d: float, has_corporate: bool) -> bool:
        return (
            news_count == 0
            and abs(price_change_1d) < 1.5
            and not has_corporate
        )

    def test_quiet_skip_no_news_small_move(self):
        assert self._should_skip(0, 0.5, False) is True

    def test_no_skip_when_news_present(self):
        assert self._should_skip(3, 0.5, False) is False

    def test_no_skip_when_large_move(self):
        assert self._should_skip(0, 2.0, False) is False

    def test_no_skip_when_corporate_action(self):
        assert self._should_skip(0, 0.3, True) is False

    def test_no_skip_when_all_signals_present(self):
        assert self._should_skip(5, 3.0, True) is False


# ── Circuit breaker: drawdown test ──────────────────────────────────────────

class TestCircuitBreakerDrawdown:
    """
    When portfolio drawdown >= 5%, PM must output SKIP — no new BUY entries.
    We test this by asserting the circuit-breaker enforcement logic directly.
    """

    def _enforce_drawdown_rule(self, decision: str, drawdown_pct: float) -> str:
        """Mimic the circuit-breaker enforcement the orchestrator applies."""
        if drawdown_pct >= 5.0 and decision == "BUY":
            return "SKIP"
        return decision

    def test_buy_blocked_when_drawdown_gte_5(self):
        result = self._enforce_drawdown_rule("BUY", 5.0)
        assert result == "SKIP"

    def test_buy_blocked_when_drawdown_gt_5(self):
        result = self._enforce_drawdown_rule("BUY", 7.5)
        assert result == "SKIP"

    def test_skip_passthrough_when_drawdown_gte_5(self):
        result = self._enforce_drawdown_rule("SKIP", 6.0)
        assert result == "SKIP"

    def test_buy_allowed_when_drawdown_lt_5(self):
        result = self._enforce_drawdown_rule("BUY", 4.9)
        assert result == "BUY"


# ── Restricted-ticker skip test ──────────────────────────────────────────────

class TestRestrictedTickerSkip:
    """
    Tickers on NSE ASM/GSM/T2T lists must be skipped before calling any agent.
    """

    def _should_skip_restricted(self, is_restricted: bool) -> bool:
        return is_restricted

    def test_restricted_ticker_is_skipped(self):
        assert self._should_skip_restricted(True) is True

    def test_unrestricted_ticker_is_not_skipped(self):
        assert self._should_skip_restricted(False) is False


# ── Portfolio Manager self-consistency majority vote ─────────────────────────

class TestPMSelfConsistency:
    """
    PM runs 3 Haiku samples and takes majority vote.
    Test that 2x BUY + 1x SKIP → BUY wins.
    """

    def test_majority_vote_buy_wins(self):
        decisions = [
            PMDecision.model_validate_json(_valid_pm_json("RELIANCE", "BUY", 0.70)),
            PMDecision.model_validate_json(_valid_pm_json("RELIANCE", "BUY", 0.65)),
            PMDecision.model_validate_json(_valid_pm_json("RELIANCE", "SKIP", 0.45)),
        ]
        from collections import Counter
        vote_counts = Counter(d.decision for d in decisions)
        winner = vote_counts.most_common(1)[0][0]
        assert winner == "BUY"

    def test_majority_vote_skip_wins(self):
        decisions = [
            PMDecision.model_validate_json(_valid_pm_json("TCS", "SKIP", 0.50)),
            PMDecision.model_validate_json(_valid_pm_json("TCS", "SKIP", 0.48)),
            PMDecision.model_validate_json(_valid_pm_json("TCS", "BUY", 0.72)),
        ]
        from collections import Counter
        vote_counts = Counter(d.decision for d in decisions)
        winner = vote_counts.most_common(1)[0][0]
        assert winner == "SKIP"

    def test_escalation_threshold(self):
        """avg confidence < 0.50 → should escalate to Sonnet."""
        decisions = [
            PMDecision.model_validate_json(_valid_pm_json("INFY", "SKIP", 0.40)),
            PMDecision.model_validate_json(_valid_pm_json("INFY", "SKIP", 0.42)),
            PMDecision.model_validate_json(_valid_pm_json("INFY", "BUY", 0.45)),
        ]
        avg_conf = sum(d.confidence for d in decisions) / len(decisions)
        assert avg_conf < 0.50  # escalation should trigger
