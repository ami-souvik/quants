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

    # Broker (Phase 2 only)
    kite_api_key: str = Field(default="")
    kite_api_secret: str = Field(default="")
    kite_access_token: str = Field(default="")

    # Reddit
    reddit_client_id: str = Field(default="")
    reddit_client_secret: str = Field(default="")
    reddit_user_agent: str = Field(default="nse-llm-trader/1.0")

    # AWS
    aws_region: str = Field(default="ap-south-1")
    aws_access_key_id: str = Field(default="")
    aws_secret_access_key: str = Field(default="")
    s3_bucket_name: str = Field(default="nse-llm-trader-archive")
    dynamo_table_name: str = Field(default="nse_trader")
    # Leave empty to use real AWS DynamoDB.
    # Set to http://localhost:8001 when running outside Docker against the local container,
    # or http://dynamodb-local:8000 when running inside the compose network.
    dynamo_endpoint_url: str = Field(default="", description="DynamoDB endpoint override for local dev")

    # App behaviour
    paper_trading_mode: bool = Field(default=True)
    initial_capital_inr: float = Field(default=1_000_000.0)
    max_position_pct: float = Field(default=0.15)
    max_open_positions: int = Field(default=5)
    max_hold_days: int = Field(default=5)
    circuit_breaker_drawdown: float = Field(default=0.10)
    daily_llm_budget_usd: float = Field(default=1.00)

    # FastAPI
    api_key: str = Field(default="changeme-local-dev")
    environment: Literal["development", "staging", "production"] = Field(
        default="development"
    )

    # Redis
    redis_url: str = Field(default="redis://localhost:6379")

    # Logging
    log_level: str = Field(default="INFO")
    # Path to the rotating log file.  Relative to CWD (= /app inside the container).
    # The docker-compose bind-mount makes ./logs/trader.log visible on the host.
    # Set to "" to disable file logging (console only).
    log_file: str = Field(default="logs/trader.log")

    # Dry-run (no DynamoDB writes, no fills)
    dry_run: bool = Field(default=False)

    @field_validator("paper_trading_mode")
    @classmethod
    def paper_mode_must_be_true_in_phase1(cls, v: bool) -> bool:
        # Enforcement is done at runtime in daily_run.py; here we just pass through.
        return v

    @property
    def max_position_value_inr(self) -> float:
        return self.initial_capital_inr * self.max_position_pct


def _load_secret(secret_name: str, region: str) -> dict:
    """Pull a JSON secret from AWS Secrets Manager and return it as a dict."""
    client = boto3.client("secretsmanager", region_name=region)
    try:
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])
    except ClientError as e:
        logger.warning("Could not load secret %s: %s", secret_name, e)
        return {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return cached Settings instance.
    In production, merge LLM keys from Secrets Manager on top of env vars.
    """
    settings = Settings()

    if settings.environment == "production":
        secret = _load_secret("nse-trader/llm-keys", settings.aws_region)
        if secret.get("ANTHROPIC_API_KEY"):
            settings.anthropic_api_key = secret["ANTHROPIC_API_KEY"]
        if secret.get("GEMINI_API_KEY"):
            settings.gemini_api_key = secret["GEMINI_API_KEY"]

    return settings
