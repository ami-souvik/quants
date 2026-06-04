"""
BaseAgent: shared prompt loading, LLM calling, retry logic, and cost tracking.

All 5 agents subclass this. Key behaviours:
- Loads prompt from trader/prompts/{name}.md
- Caches the shared system prompt via Anthropic's prompt caching (90% token discount)
- Retries once on Pydantic validation errors; returns HOLD fallback on second failure
- Logs token usage + cost after every call
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from trader.agents.models import TokenUsage
from trader.config.settings import get_settings
from trader.model_cost import compute_cost as _model_cost_compute

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Paths
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def _safe_format(template: str, **kwargs) -> str:
    """
    Safe string substitution that replaces only known {varname} placeholders.

    Unlike str.format(), this never raises KeyError on unknown {tokens} such as
    the JSON schema examples embedded in agent prompts (e.g. {ticker: "X", ...}).
    Only exact single-identifier placeholders present in kwargs are replaced;
    everything else is left verbatim.
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


class BaseAgent:
    """
    Abstract base for all 5 trading agents.

    Subclasses must implement `run()`, which calls either
    `_call_anthropic()` or `_call_gemini()` and returns a validated model.
    """

    name: str = "base"
    model: str = "claude-haiku-4-5"

    def __init__(self) -> None:
        self.settings = get_settings()
        self._system_prompt: str = _load_prompt("system_shared")
        self._agent_prompt: str = _load_prompt(self.name)

    # ─── Anthropic (Claude) call ─────────────────────────────────────────────

    def _call_anthropic(
        self,
        user_message: str,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> tuple[str, TokenUsage]:
        """
        Call Anthropic API with prompt caching on the system prompt.
        Returns (raw_text_response, TokenUsage).
        """
        import anthropic

        client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        effective_model = model or self.model
        effective_model = effective_model.replace("anthropic/", "")

        start = time.monotonic()
        response = client.messages.create(
            model=effective_model,
            max_tokens=1024,
            temperature=temperature,
            system=[
                {
                    "type": "text",
                    "text": self._system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        usage = response.usage
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        cached_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
        # cache_write_tokens are the tokens being stored for the first time
        cache_write_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0

        cost = _model_cost_compute(
            effective_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
        )

        token_usage = TokenUsage(
            agent=self.name,
            model=effective_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
            cost_usd=cost,
        )
        logger.info(
            "[%s] %s — in=%d out=%d cache_read=%d cache_write=%d cost=$%.5f elapsed=%dms",
            self.name,
            effective_model,
            input_tokens,
            output_tokens,
            cached_tokens,
            cache_write_tokens,
            cost,
            elapsed_ms,
        )
        return response.content[0].text, token_usage

    # ─── Gemini call ─────────────────────────────────────────────────────────

    def _call_gemini(
        self,
        user_message: str,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> tuple[str, TokenUsage]:
        """
        Call Google Gemini API.
        System prompt injected as a system_instruction.
        Accepts model name with or without the "google/" prefix.
        Returns (raw_text_response, TokenUsage).
        """
        import google.generativeai as genai

        # Strip provider prefix so the Gemini SDK gets the bare model name
        raw_model = (model or self.model).replace("google/", "")

        genai.configure(api_key=self.settings.gemini_api_key)
        client = genai.GenerativeModel(
            model_name=raw_model,
            system_instruction=self._system_prompt,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=1024,
            ),
        )

        start = time.monotonic()
        response = client.generate_content(user_message)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        text = response.text
        metadata = getattr(response, "usage_metadata", None)
        input_tokens = getattr(metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(metadata, "candidates_token_count", 0) or 0

        cost = _model_cost_compute(raw_model, input_tokens=input_tokens, output_tokens=output_tokens)

        token_usage = TokenUsage(
            agent=self.name,
            model=raw_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=0,
            cost_usd=cost,
        )
        logger.info(
            "[%s] %s — in=%d out=%d cost=$%.5f elapsed=%dms",
            self.name, raw_model, input_tokens, output_tokens, cost, elapsed_ms,
        )
        return text, token_usage

    # ─── Ollama call (local LLM, zero cost) ──────────────────────────────────

    def _call_ollama(
        self,
        user_message: str,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> tuple[str, TokenUsage]:
        """
        Call a local Ollama server via its OpenAI-compatible /v1/chat/completions endpoint.

        Base URL is read from settings.ollama_base_url (default http://localhost:11434).
        Model is read from settings.ollama_model (default llama3.2:3b) unless overridden.

        Cost is always $0.00 — local inference.
        Timeout is generous (120 s) because local inference can be slow.
        """
        import httpx

        raw_model = (model or self.settings.ollama_model).replace("ollama/", "")
        base_url = self.settings.ollama_base_url.rstrip("/")
        url = f"{base_url}/v1/chat/completions"

        payload = {
            "model": raw_model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user",   "content": user_message},
            ],
            "temperature": temperature,
            "stream": False,
        }

        start = time.monotonic()
        try:
            # connect_timeout=5s (fail fast if server unreachable),
            # read_timeout=90s (model might be slow to generate the first token).
            resp = httpx.post(url, json=payload, timeout=httpx.Timeout(connect=5.0, read=90.0, write=10.0, pool=5.0))
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot connect to Ollama at {base_url}. "
                f"Check that Ollama is running and OLLAMA_BASE_URL is correct. ({exc})"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Ollama at {base_url} timed out after 90 s. "
                f"The model '{raw_model}' may be too large for your hardware, "
                f"or the server is overloaded. ({exc})"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Ollama returned HTTP {exc.response.status_code} for model '{raw_model}'. "
                f"Is the model pulled? Run: ollama pull {raw_model}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Ollama request failed ({url}): {exc}") from exc
        elapsed_ms = int((time.monotonic() - start) * 1000)

        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        input_tokens  = usage.get("prompt_tokens",     0)
        output_tokens = usage.get("completion_tokens", 0)

        token_usage = TokenUsage(
            agent=self.name,
            model=raw_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=0,
            cost_usd=0.0,   # local inference — free
        )
        logger.info(
            "[%s] ollama/%s — in=%d out=%d cost=$0.00 elapsed=%dms",
            self.name, raw_model, input_tokens, output_tokens, elapsed_ms,
        )
        return text, token_usage

    # ─── Unified dispatcher ───────────────────────────────────────────────────

    def _call_model(
        self,
        user_message: str,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> tuple[str, TokenUsage]:
        """
        Route to the correct backend based on model prefix and key availability.

        Priority / fallback chain
        ─────────────────────────
        1. model starts with "ollama/"    → always Ollama (explicit override)
        2. model starts with "anthropic/" → Anthropic if key set, else Ollama
        3. model starts with "google/"    → Gemini if key set, else Ollama
        4. no recognised prefix           → fall back to Ollama

        Logging a WARNING when falling back so you know which key is missing.
        """
        effective = model or self.model

        if effective.startswith("ollama/"):
            return self._call_ollama(user_message, model=effective, temperature=temperature)

        if effective.startswith("anthropic/"):
            if self.settings.anthropic_api_key:
                return self._call_anthropic(user_message, model=effective, temperature=temperature)
            logger.warning(
                "[%s] ANTHROPIC_API_KEY not set — falling back to Ollama (%s)",
                self.name, self.settings.ollama_model,
            )
            return self._call_ollama(user_message, temperature=temperature)

        if effective.startswith("google/"):
            if self.settings.gemini_api_key:
                return self._call_gemini(user_message, model=effective, temperature=temperature)
            logger.warning(
                "[%s] GEMINI_API_KEY not set — falling back to Ollama (%s)",
                self.name, self.settings.ollama_model,
            )
            return self._call_ollama(user_message, temperature=temperature)

        # Bare model name (legacy) — fall through to Ollama
        logger.warning(
            "[%s] Unrecognised model prefix for '%s' — falling back to Ollama (%s). "
            "Use 'anthropic/', 'google/', or 'ollama/' prefixes to be explicit.",
            self.name, effective, self.settings.ollama_model,
        )
        return self._call_ollama(user_message, temperature=temperature)

    # ─── JSON extraction + Pydantic parsing ──────────────────────────────────

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """
        Strip markdown code fences and parse JSON.
        LLMs sometimes wrap JSON in ```json ... ```.
        """
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Drop first and last fence lines
            inner = "\n".join(lines[1:] if lines[-1].strip() == "```" else lines[1:])
            inner = inner.rstrip("`").strip()
            text = inner
        return json.loads(text)

    def _parse_output(self, text: str, model_class: type[T]) -> T:
        """Parse and validate LLM text output into a Pydantic model."""
        data = self._extract_json(text)
        return model_class.model_validate(data)

    # ─── Retry wrapper ────────────────────────────────────────────────────────

    def _call_with_retry(
        self,
        call_fn,
        parse_fn,
        max_retries: int = 1,
    ) -> tuple[Any, TokenUsage, bool]:
        """
        Execute call_fn(), parse with parse_fn().
        On ValidationError: retry up to max_retries times.
        Returns (parsed_output, total_token_usage, schema_valid).
        """
        total_usage = TokenUsage(agent=self.name, model=self.model)
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                text, usage = call_fn()
                total_usage.input_tokens += usage.input_tokens
                total_usage.output_tokens += usage.output_tokens
                total_usage.cached_tokens += usage.cached_tokens
                total_usage.cache_write_tokens += usage.cache_write_tokens
                total_usage.cost_usd += usage.cost_usd

                result = parse_fn(text)
                return result, total_usage, True

            except (ValidationError, json.JSONDecodeError, KeyError, ValueError) as exc:
                last_exc = exc
                logger.warning(
                    "[%s] Schema validation failed (attempt %d/%d): %s",
                    self.name,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )

        logger.error("[%s] All retries exhausted. Last error: %s", self.name, last_exc)
        return None, total_usage, False
