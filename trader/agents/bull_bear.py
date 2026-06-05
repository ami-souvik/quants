"""
Agent 4: Bull vs Bear Debate
Model: claude-haiku-4-5
Both roles in one call to save tokens.
"""
from __future__ import annotations

import json
import logging

from trader.agents.base import BaseAgent, _safe_format
from trader.agents.models import BullBearOutput, TokenUsage

logger = logging.getLogger(__name__)


class BullBearAgent(BaseAgent):
    name = "bull_bear"
    # model = "anthropic/claude-haiku-4-5"
    model = "google/gemini-2.5-flash"

    def run(
        self,
        ticker: str,
        news_agent_output: dict,
        technical_agent_output: dict,
        fundamentals_agent_output: dict,
    ) -> tuple[BullBearOutput | None, TokenUsage, bool]:
        """
        Returns (output, token_usage, schema_valid).
        """
        user_message = _safe_format(
            self._agent_prompt,
            ticker=ticker,
            news_agent_output=json.dumps(news_agent_output, default=str, indent=2),
            technical_agent_output=json.dumps(technical_agent_output, default=str, indent=2),
            fundamentals_agent_output=json.dumps(fundamentals_agent_output, default=str, indent=2),
        )

        news_label = news_agent_output.get("sentiment_label", "?")
        tech_signal = technical_agent_output.get("technical_signal", "?")
        fund_bias = fundamentals_agent_output.get("fundamental_bias", "?")
        logger.info(
            "[bull_bear][%s] Input signals: news=%s tech=%s fundamentals=%s",
            ticker, news_label, tech_signal, fund_bias,
        )

        def call_fn():
            return self._call_model(user_message)

        def parse_fn(text: str) -> BullBearOutput:
            return self._parse_output(text, BullBearOutput)

        result, usage, valid = self._call_with_retry(call_fn, parse_fn)

        if valid and result is not None:
            logger.info(
                "[bull_bear][%s] Output: winner=%s delta=%.2f conf=%.2f | "
                "key_risk: %s",
                ticker,
                result.debate_winner,
                result.conviction_delta,
                result.confidence,
                result.key_risk[:120],
            )
            logger.debug("[bull_bear][%s] Bull thesis: %s", ticker, " | ".join(result.bull_thesis))
            logger.debug("[bull_bear][%s] Bear thesis: %s", ticker, " | ".join(result.bear_thesis))
        else:
            logger.warning("[bull_bear][%s] Output: FAILED — schema invalid", ticker)

        return result, usage, valid
