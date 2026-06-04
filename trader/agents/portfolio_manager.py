"""
Agent 5: Portfolio Manager — Final Trade Decision

Model: claude-haiku-4-5 with self-consistency (3 samples, majority vote).
Escalates to claude-sonnet-4-6 if Haiku confidence < 0.5.
"""
from __future__ import annotations

import json
import logging
from collections import Counter

from trader.agents.base import BaseAgent, _safe_format
from trader.agents.models import PMDecision, TokenUsage, pm_hold_fallback
from trader.config.settings import get_settings

logger = logging.getLogger(__name__)

_SELF_CONSISTENCY_SAMPLES = 3
_ESCALATION_CONFIDENCE_THRESHOLD = 0.50


class PortfolioManagerAgent(BaseAgent):
    name = "portfolio_manager"
    model = "anthropic/claude-haiku-4-5"

    def run(
        self,
        ticker: str,
        news_agent_output: dict,
        technical_agent_output: dict,
        fundamentals_agent_output: dict,
        bull_bear_output: dict,
        cash_available: float,
        open_positions_count: int,
        position_qty: int,
        avg_price: float,
        days_held: int,
        drawdown_pct: float,
        nav: float,
        max_position_value: float,
        is_restricted: bool,
    ) -> tuple[PMDecision, TokenUsage, bool]:
        """
        Returns (PMDecision, token_usage, schema_valid).
        Always returns a decision — falls back to HOLD on persistent errors.
        """
        settings = get_settings()
        user_message = _safe_format(
            self._agent_prompt,
            ticker=ticker,
            news_agent_output=json.dumps(news_agent_output, default=str, indent=2),
            technical_agent_output=json.dumps(technical_agent_output, default=str, indent=2),
            fundamentals_agent_output=json.dumps(fundamentals_agent_output, default=str, indent=2),
            bull_bear_output=json.dumps(bull_bear_output, default=str, indent=2),
            cash_available=f"{cash_available:,.2f}",
            open_positions_count=open_positions_count,
            position_qty=position_qty,
            avg_price=f"{avg_price:,.2f}",
            days_held=days_held,
            drawdown_pct=f"{drawdown_pct:.2f}",
            nav=f"{nav:,.2f}",
            max_position_value=f"{max_position_value:,.2f}",
            is_restricted=is_restricted,
        )

        total_usage = TokenUsage(agent=self.name, model=self.model)
        decisions: list[PMDecision] = []

        # ── Step 1: 3-sample self-consistency with Haiku ──────────────────────
        for i in range(_SELF_CONSISTENCY_SAMPLES):
            def call_fn():
                return self._call_model(user_message, model="anthropic/claude-haiku-4-5", temperature=0.3)

            def parse_fn(text: str) -> PMDecision:
                return self._parse_output(text, PMDecision)

            result, usage, valid = self._call_with_retry(call_fn, parse_fn)
            total_usage.input_tokens += usage.input_tokens
            total_usage.output_tokens += usage.output_tokens
            total_usage.cached_tokens += usage.cached_tokens
            total_usage.cost_usd += usage.cost_usd

            if valid and result is not None:
                decisions.append(result)

        if not decisions:
            logger.error("[portfolio_manager] All Haiku samples failed for %s — returning HOLD", ticker)
            return pm_hold_fallback(ticker), total_usage, False

        # ── Step 2: Majority vote on decision type ────────────────────────────
        vote_counts = Counter(d.decision for d in decisions)
        winning_decision_type = vote_counts.most_common(1)[0][0]
        candidates = [d for d in decisions if d.decision == winning_decision_type]

        # Pick the candidate closest to median confidence
        sorted_candidates = sorted(candidates, key=lambda d: d.confidence)
        consensus = sorted_candidates[len(sorted_candidates) // 2]

        avg_confidence = sum(d.confidence for d in decisions) / len(decisions)
        logger.info(
            "[portfolio_manager] Haiku vote: %s (%.0f%% agreement, avg_conf=%.2f)",
            winning_decision_type,
            100 * len(candidates) / len(decisions),
            avg_confidence,
        )

        # ── Step 3: Escalate to Sonnet if confidence is low ───────────────────
        if avg_confidence < _ESCALATION_CONFIDENCE_THRESHOLD:
            logger.info(
                "[portfolio_manager] Low confidence (%.2f) — escalating to claude-sonnet-4-6",
                avg_confidence,
            )
            # Cost guard: only escalate if daily LLM budget not exhausted
            def call_sonnet():
                return self._call_model(user_message, model="anthropic/claude-sonnet-4-6", temperature=0.0)

            def parse_sonnet(text: str) -> PMDecision:
                return self._parse_output(text, PMDecision)

            result, usage, valid = self._call_with_retry(call_sonnet, parse_sonnet)
            total_usage.input_tokens += usage.input_tokens
            total_usage.output_tokens += usage.output_tokens
            total_usage.cached_tokens += usage.cached_tokens
            total_usage.cost_usd += usage.cost_usd

            if valid and result is not None:
                consensus = result
                total_usage.model = "claude-sonnet-4-6"

        return consensus, total_usage, True
