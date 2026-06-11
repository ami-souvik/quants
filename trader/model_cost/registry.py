"""
ModelPricing dataclass and the lookup registry.

The registry resolves a model name (or alias) to a ModelPricing object
backed by the LiteLLM pricing JSON via fetcher.py.

Alias map handles the naming gap between:
  - What our codebase calls the model  (e.g. "gemini-2.5-flash")
  - The key LiteLLM uses                (e.g. "gemini/gemini-2.5-flash")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from trader.model_cost.fetcher import fetch_pricing_data

logger = logging.getLogger(__name__)

# ── Alias map: our internal name → LiteLLM JSON key ──────────────────────────
# Add entries here as new models are adopted. The registry falls back to the
# key itself if no alias exists, so canonical LiteLLM names need no entry.
MODEL_ALIASES: dict[str, str] = {
    # Gemini: our code uses the bare name; LiteLLM uses the provider-prefixed form
    "gemini-2.5-flash": "gemini/gemini-2.5-flash",
    "gemini-2.5-pro": "gemini/gemini-2.5-pro",
    # Anthropic aliases (in case versioned IDs are used)
    "claude-haiku-4-5-20251014": "claude-haiku-4-5",
    "claude-sonnet-4-6-20251015": "claude-sonnet-4-6",
    
    "gemma-4-31b-it": "gemma-4-31b-it",
}


@dataclass(frozen=True)
class ModelPricing:
    """
    Per-token USD costs for a single model.

    All costs are in USD per token (NOT per million).
    Multiply by 1_000_000 to get the per-million figure.

    Fields match LiteLLM's naming convention so this dataclass can be
    deserialized directly from the pricing JSON with minimal translation.
    """

    model: str                              # canonical LiteLLM key
    litellm_provider: str = "unknown"

    # Base inference costs
    input_cost_per_token: float = 0.0       # prompt tokens (non-cached)
    output_cost_per_token: float = 0.0      # completion tokens

    # Anthropic prompt-caching (Gemini context-caching also uses these fields)
    cache_creation_input_token_cost: float = 0.0   # writing to cache (more expensive)
    cache_read_input_token_cost: float = 0.0       # reading from cache (much cheaper)

    # Context window
    max_input_tokens: int = 0
    max_output_tokens: int = 0

    # ── Convenience properties ───────────────────────────────────────────────

    @property
    def input_cost_per_million(self) -> float:
        return self.input_cost_per_token * 1_000_000

    @property
    def output_cost_per_million(self) -> float:
        return self.output_cost_per_token * 1_000_000

    @property
    def cache_read_cost_per_million(self) -> float:
        return self.cache_read_input_token_cost * 1_000_000

    @property
    def cache_write_cost_per_million(self) -> float:
        return self.cache_creation_input_token_cost * 1_000_000

    @property
    def supports_prompt_caching(self) -> bool:
        return self.cache_read_input_token_cost > 0

    def __str__(self) -> str:
        return (
            f"ModelPricing({self.model!r}: "
            f"in=${self.input_cost_per_million:.3f}/M "
            f"out=${self.output_cost_per_million:.3f}/M "
            f"cache_read=${self.cache_read_cost_per_million:.4f}/M)"
        )


def _parse_entry(model_key: str, entry: dict[str, Any]) -> ModelPricing:
    """Build a ModelPricing from a raw LiteLLM JSON entry."""
    return ModelPricing(
        model=model_key,
        litellm_provider=entry.get("litellm_provider", "unknown"),
        input_cost_per_token=float(entry.get("input_cost_per_token", 0.0)),
        output_cost_per_token=float(entry.get("output_cost_per_token", 0.0)),
        cache_creation_input_token_cost=float(
            entry.get("cache_creation_input_token_cost", 0.0)
        ),
        cache_read_input_token_cost=float(
            entry.get("cache_read_input_token_cost", 0.0)
        ),
        max_input_tokens=int(entry.get("max_input_tokens", 0)),
        max_output_tokens=int(entry.get("max_output_tokens", 0)),
    )


def get_model_pricing(model: str) -> ModelPricing:
    """
    Resolve *model* to a ModelPricing object.

    Lookup order:
      1. Alias map  (e.g. "gemini-2.5-flash" → "gemini/gemini-2.5-flash")
      2. Exact key in the LiteLLM pricing dict
      3. Prefix search — first key that *starts with* the requested name
         (handles minor version suffix differences)
      4. Warn + return a zero-cost sentinel so billing never hard-crashes
    """
    pricing_data = fetch_pricing_data()

    # Resolve alias
    canonical = MODEL_ALIASES.get(model, model)

    # Exact match
    if canonical in pricing_data:
        return _parse_entry(canonical, pricing_data[canonical])

    # Prefix match (e.g. "claude-haiku-4-5" matches "claude-haiku-4-5-20251014")
    prefix_matches = [k for k in pricing_data if k.startswith(canonical)]
    if prefix_matches:
        # Prefer entries without provider prefixes (bedrock_, vertex_, etc.)
        direct = [k for k in prefix_matches
                  if not any(p in k for p in ("bedrock", "vertex", "azure", "sagemaker"))]
        key = direct[0] if direct else prefix_matches[0]
        logger.debug("model_cost: prefix-matched %r → %r", model, key)
        return _parse_entry(key, pricing_data[key])

    # Unknown model — return zero-cost sentinel rather than crashing
    logger.warning(
        "model_cost: unknown model %r — cost tracking will show $0.00 for this model",
        model,
    )
    return ModelPricing(model=model, litellm_provider="unknown")
