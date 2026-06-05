"""
Agent 2: Technical Analyst
Model: gemini-2.5-flash
"""
from __future__ import annotations

import json
import logging

from trader.agents.base import BaseAgent, _safe_format
from trader.agents.models import TechnicalOutput, TokenUsage

logger = logging.getLogger(__name__)


class TechnicalAgent(BaseAgent):
    name = "technical"
    model = "google/gemini-2.5-flash"

    def run(
        self,
        ticker: str,
        company_name: str,
        indicators: dict,
        last_5d_ohlcv: list[dict],
        current_position: dict,
    ) -> tuple[TechnicalOutput | None, TokenUsage, bool]:
        """
        Returns (output, token_usage, schema_valid).
        """
        user_message = _safe_format(
            self._agent_prompt,
            ticker=ticker,
            company_name=company_name,
            indicators=json.dumps(indicators, default=str, indent=2),
            last_5d_ohlcv=json.dumps(last_5d_ohlcv, default=str, indent=2),
            current_position=json.dumps(current_position, default=str, indent=2),
        )

        logger.info(
            "[technical][%s] Input: RSI=%.1f MACD=%.3f/%.3f ADX=%.1f "
            "vol_ratio=%.2f pct1d=%.2f%% pct5d=%.2f%%",
            ticker,
            indicators.get("rsi_14", 0),
            indicators.get("macd", 0),
            indicators.get("macd_signal", 0),
            indicators.get("adx_14", 0),
            indicators.get("volume_ratio", 1),
            indicators.get("pct_change_1d", 0),
            indicators.get("pct_change_5d", 0),
        )
        logger.debug(
            "[technical][%s] Full indicators: %s",
            ticker,
            json.dumps({k: round(v, 4) if isinstance(v, float) else v
                        for k, v in indicators.items()}, default=str),
        )

        def call_fn():
            return self._call_model(user_message)

        def parse_fn(text: str) -> TechnicalOutput:
            return self._parse_output(text, TechnicalOutput)

        result, usage, valid = self._call_with_retry(call_fn, parse_fn)

        if valid and result is not None:
            logger.info(
                "[technical][%s] Output: %s | trend=%s momentum=%s vol=%s "
                "SL=%.1f%% TP=%.1f%% conf=%.2f",
                ticker,
                result.technical_signal,
                result.trend,
                result.momentum,
                result.volume_signal,
                result.suggested_stop_loss_pct,
                result.suggested_target_pct,
                result.confidence,
            )
        else:
            logger.warning("[technical][%s] Output: FAILED — schema invalid", ticker)

        return result, usage, valid
