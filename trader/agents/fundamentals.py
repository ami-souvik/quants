"""
Agent 3: Fundamentals Analyst
Model: claude-haiku-4-5
"""
from __future__ import annotations

import json
import logging

from trader.agents.base import BaseAgent, _safe_format
from trader.agents.models import FundamentalsOutput, TokenUsage

logger = logging.getLogger(__name__)


class FundamentalsAgent(BaseAgent):
    name = "fundamentals"
    model = "claude-haiku-4-5"

    def run(
        self,
        ticker: str,
        company_name: str,
        sector: str,
        sector_context: str,
        fii_dii_flows: dict,
        macro_context: dict,
        known_fundamentals: dict,
    ) -> tuple[FundamentalsOutput | None, TokenUsage, bool]:
        """
        Returns (output, token_usage, schema_valid).
        """
        user_message = _safe_format(
            self._agent_prompt,
            ticker=ticker,
            company_name=company_name,
            sector=sector,
            sector_news_summary=sector_context,
            fii_net_buy_cr=fii_dii_flows.get("fii_net_buy_cr", 0.0),
            dii_net_buy_cr=fii_dii_flows.get("dii_net_buy_cr", 0.0),
            rbi_rate=macro_context.get("rbi_rate", "N/A"),
            usd_inr=macro_context.get("usd_inr", "N/A"),
            nifty_1d_pct=macro_context.get("nifty_1d_pct", 0.0),
            nifty_5d_pct=macro_context.get("nifty_5d_pct", 0.0),
            pe_ratio=known_fundamentals.get("pe_ratio", "N/A"),
            pb_ratio=known_fundamentals.get("pb_ratio", "N/A"),
            roe=known_fundamentals.get("roe", "N/A"),
            debt_equity=known_fundamentals.get("debt_equity", "N/A"),
            revenue_growth_yoy=known_fundamentals.get("revenue_growth_yoy", "N/A"),
            promoter_holding_pct=known_fundamentals.get("promoter_holding_pct", "N/A"),
        )

        def call_fn():
            return self._call_anthropic(user_message)

        def parse_fn(text: str) -> FundamentalsOutput:
            return self._parse_output(text, FundamentalsOutput)

        return self._call_with_retry(call_fn, parse_fn)
