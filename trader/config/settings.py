"""
Application settings loaded from environment variables or AWS Secrets Manager.
In development: reads from .env file.
In production: reads from AWS Secrets Manager (secrets injected via ECS task definition).
"""
import json
import logging
from functools import lru_cache
from typing import Literal

import boto3
from botocore.exceptions import ClientError
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM APIs
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    gemini_api_key: str = Field(default="", description="Google Gemini API key")

    # Local LLM fallback (Ollama)
    # Used automatically when anthropic_api_key / gemini_api_key are not set.
    # ollama_base_url: the HTTP address of your Ollama server.
    #   Local:  http://localhost:11434
    #   Remote: http://<server-ip>:11434
    # ollama_model: any model you have pulled, e.g. "llama3.2:3b", "qwen2.5:7b", "mistral"
    ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama server URL")
    ollama_model: str = Field(default="llama3.2:3b", description="Default Ollama model for local inference")
    # Increase this if your hardware is slow (gemma4 / large models may need 300 s+).
    # connect_timeout is always 5 s (fast fail if server unreachable).
    ollama_read_timeout: int = Field(default=300, description="Ollama inference timeout in seconds")

    # Broker (Phase 2 only)
    kite_api_key: str = Field(default="")
    kite_api_secret: str = Field(default="")
    kite_access_token: str = Field(default="")

    # Reddit
    reddit_client_id: str = Field(default="")
    reddit_client_secret: str = Field(default="")
    reddit_user_agent: str = Field(default="nse-llm-trader/1.0")

    # Database (Supabase / PostgreSQL)
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/postgres",
        description="PostgreSQL / Supabase connection URL",
    )

    # Redis (Upstash / Local Redis)
    redis_url: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL (Upstash or local)",
    )

    # Agent model configuration
    # Use prefixes: "google/", "anthropic/", "ollama/" to select backend.
    # Agents automatically fall back to Ollama if the corresponding API key is missing.
    agent_model_news_sentiment: str = Field(
        default="google/gemini-2.5-flash",
        description="Model for Agent 1: News & Sentiment Analyst",
    )
    agent_model_technical: str = Field(
        default="google/gemini-2.5-flash",
        description="Model for Agent 2: Technical Analyst",
    )
    agent_model_fundamentals: str = Field(
        default="google/gemini-2.5-flash",
        description="Model for Agent 3: Fundamentals Analyst",
    )
    agent_model_bull_bear: str = Field(
        default="google/gemini-2.5-flash",
        description="Model for Agent 4: Bull vs Bear Debate",
    )
    agent_model_portfolio_manager: str = Field(
        default="google/gemini-2.5-flash",
        description="Model for Agent 5: Portfolio Manager (primary / self-consistency samples)",
    )
    agent_model_portfolio_manager_escalation: str = Field(
        default="google/gemini-2.5-flash",
        description="Model for Agent 5 escalation when confidence < threshold",
    )

    # App behaviour
    paper_trading_mode: bool = Field(default=True)
    initial_capital_inr: float = Field(default=1_000_000.0)
    max_position_pct: float = Field(default=0.15)
    max_open_positions: int = Field(default=5)
    max_hold_days: int = Field(default=5)
    circuit_breaker_drawdown: float = Field(default=0.10)
    daily_llm_budget_usd: float = Field(default=1.00)

    # FastAPI / Dashboard Auth
    api_key: str = Field(default="changeme-local-dev")
    environment: Literal["development", "staging", "production"] = Field(
        default="development"
    )

    # Logging
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/trader.log")

    # Dry-run (no DB writes, no fills)
    dry_run: bool = Field(default=False)

    # Schema retry behaviour
    agent_schema_retry_enabled: bool = Field(default=True)

    @field_validator("paper_trading_mode")
    @classmethod
    def paper_mode_must_be_true_in_phase1(cls, v: bool) -> bool:
        # Enforcement is done at runtime in daily_run.py; here we just pass through.
        return v

    @property
    def max_position_value_inr(self) -> float:
        return self.initial_capital_inr * self.max_position_pct


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()

