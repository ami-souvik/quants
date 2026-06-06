"""
Agent 1: News & Sentiment Analyst
Model: gemini-2.5-flash
"""
from __future__ import annotations

import json
import logging

from trader.agents.base import BaseAgent, _safe_format
from trader.agents.models import NewsSentimentOutput, TokenUsage

logger = logging.getLogger(__name__)


class NewsSentimentAgent(BaseAgent):
    name = "news_sentiment"

    @property
    def model(self) -> str:  # type: ignore[override]
        return self.settings.agent_model_news_sentiment

    def run(
        self,
        ticker: str,
        company_name: str,
        sector: str,
        news_articles: list[dict],
        corporate_announcements: list[dict],
        close_price: float,
        pct_1d: float,
        news_window_tag: str,
    ) -> tuple[NewsSentimentOutput | None, TokenUsage, bool]:
        """
        Returns (output, token_usage, schema_valid).
        schema_valid=False means both attempts failed; caller should treat as NEUTRAL.
        """
        user_message = _safe_format(
            self._agent_prompt,
            ticker=ticker,
            company_name=company_name,
            sector=sector,
            news_articles=json.dumps(news_articles, default=str, indent=2),
            corporate_announcements=json.dumps(corporate_announcements, default=str, indent=2),
            close_price=close_price,
            pct_1d=pct_1d,
            news_window_tag=news_window_tag,
        )

        logger.info(
            "[news_sentiment][%s] Input: %d articles, %d corp announcements | "
            "close=%.2f pct_1d=%.2f%% window=%s",
            ticker,
            len(news_articles),
            len(corporate_announcements),
            close_price,
            pct_1d,
            news_window_tag,
        )
        if news_articles:
            for art in news_articles[:5]:
                logger.debug(
                    "[news_sentiment][%s]   article: [%s] %s",
                    ticker, art.get("source", "?"), art.get("title", "")[:120],
                )

        def call_fn():
            return self._call_model(user_message, response_model=NewsSentimentOutput)

        def parse_fn(text: str) -> NewsSentimentOutput:
            return self._parse_output(text, NewsSentimentOutput)

        result, usage, valid = self._call_with_retry(call_fn, parse_fn)

        if valid and result is not None:
            logger.info(
                "[news_sentiment][%s] Output: %s (score=%.2f conf=%.2f) | events: %s",
                ticker,
                result.sentiment_label,
                result.sentiment_score,
                result.confidence,
                "; ".join(result.key_events[:3]) or "none",
            )
        else:
            logger.warning("[news_sentiment][%s] Output: FAILED — schema invalid", ticker)

        return result, usage, valid
