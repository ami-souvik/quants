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

        def call_fn():
            return self._call_model(user_message)

        def parse_fn(text: str) -> BullBearOutput:
            return self._parse_output(text, BullBearOutput)

        return self._call_with_retry(call_fn, parse_fn)
