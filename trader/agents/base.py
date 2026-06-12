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

# ─── Gemini schema helpers ────────────────────────────────────────────────────

# JSON Schema keywords that Gemini's response_schema does NOT support.
# Passing them raises "Unknown field for Schema: <keyword>".
_GEMINI_UNSUPPORTED_KEYS = frozenset({
    "title", "default", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "pattern",
    "minItems", "maxItems",
    "multipleOf",
    "const",          # Pydantic emits {"const": "X"} for single-value Literals (e.g. ProductType="CNC")
    "$schema", "$id",
})


def _resolve_refs(schema: dict, defs: dict) -> dict:
    """
    Recursively resolve $ref pointers using the $defs map.
    Gemini doesn't support $ref / $defs — they must be inlined.
    """
    if "$ref" in schema:
        ref_name = schema["$ref"].split("/")[-1]
        resolved = _resolve_refs(defs.get(ref_name, {}), defs)
        # Merge any sibling keys (e.g. description) into the resolved schema
        merged = {**resolved}
        for k, v in schema.items():
            if k != "$ref":
                merged[k] = v
        return merged

    result = {}
    for key, value in schema.items():
        if key in ("$defs", "$ref"):
            continue  # drop — inlined above
        if isinstance(value, dict):
            result[key] = _resolve_refs(value, defs)
        elif isinstance(value, list):
            result[key] = [
                _resolve_refs(item, defs) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def _strip_unsupported(schema: dict) -> dict:
    """
    Recursively remove JSON Schema keywords that Gemini rejects.
    Also collapses anyOf/oneOf used for Optional[X] → just X (non-nullable).
    """
    # Collapse Optional[X]: anyOf: [{...}, {type: null}] → the non-null branch
    if "anyOf" in schema:
        non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
        if len(non_null) == 1:
            # Replace the anyOf with the unwrapped type, keep sibling keys
            merged = {**non_null[0]}
            for k, v in schema.items():
                if k != "anyOf":
                    merged[k] = v
            schema = merged
        else:
            # Multiple non-null branches — keep as-is but recurse
            schema = {**schema, "anyOf": [_strip_unsupported(s) for s in schema["anyOf"]]}

    result = {}
    for key, value in schema.items():
        if key in _GEMINI_UNSUPPORTED_KEYS:
            continue
        if isinstance(value, dict):
            result[key] = _strip_unsupported(value)
        elif isinstance(value, list):
            result[key] = [
                _strip_unsupported(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def _pydantic_to_gemini_schema(model_class: type[BaseModel]) -> dict:
    """
    Convert a Pydantic model to a Gemini-compatible JSON schema dict.

    Steps:
    1. Generate full JSON schema via Pydantic (includes $defs, $ref, minimum, etc.)
    2. Resolve all $ref / $defs so Gemini gets a fully inlined schema
    3. Strip all keywords Gemini doesn't support
    """
    raw = model_class.model_json_schema()
    defs = raw.get("$defs", {})
    resolved = _resolve_refs(raw, defs)
    return _strip_unsupported(resolved)


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
        response_model: type[T] | None = None,
    ) -> tuple[str, TokenUsage]:
        """
        Call Anthropic API with prompt caching on the system prompt.

        When response_model is provided, uses tool_choice to force structured
        output matching the Pydantic model's JSON schema. This eliminates
        schema validation failures by constraining the model's output format.

        Returns (raw_text_response, TokenUsage).
        """
        import anthropic

        client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        effective_model = model or self.model
        effective_model = effective_model.replace("anthropic/", "")

        start = time.monotonic()

        create_kwargs: dict[str, Any] = dict(
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

        if response_model is not None:
            schema = response_model.model_json_schema()
            # Remove 'title' from the top-level schema; Anthropic doesn't need it
            schema.pop("title", None)
            create_kwargs["tools"] = [
                {
                    "name": "structured_output",
                    "description": "Return the structured analysis result.",
                    "input_schema": schema,
                }
            ]
            create_kwargs["tool_choice"] = {"type": "tool", "name": "structured_output"}

        response = client.messages.create(**create_kwargs)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Extract text: prefer tool_use block when structured output was requested
        if response_model is not None:
            tool_block = next(
                (b for b in response.content if b.type == "tool_use"), None
            )
            if tool_block is not None:
                text = json.dumps(tool_block.input)
            else:
                text = response.content[0].text
        else:
            text = response.content[0].text

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
        return text, token_usage

    # ─── Gemini call ─────────────────────────────────────────────────────────

    def _call_gemini(
        self,
        user_message: str,
        model: str | None = None,
        temperature: float = 0.0,
        response_model: type[T] | None = None,
    ) -> tuple[str, TokenUsage]:
        """
        Call Google Gemini API via the `google.genai` SDK (v1.x).

        Key configuration choices
        ─────────────────────────
        response_mime_type="application/json"
            Forces the model to emit only valid JSON — no markdown fences,
            no prose. Eliminates the need to strip ```json ... ``` wrappers.

        thinking_budget=0  (Gemini 2.x models)
            Gemini 2.5 Flash uses chain-of-thought "thinking" by default.
            Thinking tokens count against max_output_tokens, so at 1024 the
            model burns ~990 tokens on internal reasoning and has only ~34
            tokens left for the actual JSON → truncated output every time.
            Setting thinking_budget=0 disables thinking entirely, which is
            correct here: these are structured extraction tasks, not puzzles.

        max_output_tokens=2048
            Our largest agent output (PM decision) is ~300 tokens. 2048 gives
            ample headroom without wasting quota.
        """
        from google import genai
        from google.genai import types
        from google.genai.errors import APIError as _GeminiAPIError

        raw_model = (model or self.model).replace("google/", "")
        client = genai.Client(api_key=self.settings.gemini_api_key)

        # Build GenerateContentConfig for the new SDK
        config_kwargs: dict = {
            "temperature":        temperature,
            "max_output_tokens":  2048,
            "response_mime_type": "application/json",
            "system_instruction": self._system_prompt,
        }
        if response_model is not None:
            # Gemini only supports a subset of JSON Schema — strip unsupported
            # keywords (minimum, maximum, maxItems, default, title, $ref, etc.)
            # before passing. The cleaned dict is fully inlined (no $ref/$defs).
            config_kwargs["response_schema"] = _pydantic_to_gemini_schema(response_model)
        if any(v in raw_model for v in ("2.5", "2.0")):
            # thinking_budget=0 disables CoT for Gemini 2.x thinking models.
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

        gen_config = types.GenerateContentConfig(**config_kwargs)

        # Retry transient Gemini server errors (500/503/429) with exponential backoff.
        _MAX_GEMINI_RETRIES = 3
        _BACKOFF_BASE = 2.0  # seconds; doubles each attempt: 2s → 4s → 8s

        _TRANSIENT_CODES = {500, 503, 429}

        def _is_transient_gemini(exc: Exception) -> bool:
            if isinstance(exc, _GeminiAPIError):
                return getattr(exc, "code", None) in _TRANSIENT_CODES
            return False

        start = time.monotonic()
        last_gemini_exc: Exception | None = None
        response = None
        for _attempt in range(_MAX_GEMINI_RETRIES):
            try:
                response = client.models.generate_content(
                    model=raw_model,
                    contents=user_message,
                    config=gen_config,
                )
                break  # success
            except Exception as exc:
                if _is_transient_gemini(exc):
                    last_gemini_exc = exc
                    wait = _BACKOFF_BASE ** _attempt
                    logger.warning(
                        "[%s] Gemini transient error (attempt %d/%d): %s — retrying in %.0fs",
                        self.name, _attempt + 1, _MAX_GEMINI_RETRIES, exc, wait,
                    )
                    time.sleep(wait)
                else:
                    raise  # non-transient: propagate immediately
        else:
            # All retries exhausted — re-raise so _call_with_retry can handle it
            raise last_gemini_exc  # type: ignore[misc]

        elapsed_ms = int((time.monotonic() - start) * 1000)

        text = response.text
        metadata = getattr(response, "usage_metadata", None)
        input_tokens   = getattr(metadata, "prompt_token_count",      0) or 0
        output_tokens  = getattr(metadata, "candidates_token_count",  0) or 0
        # thoughts_token_count is non-zero when thinking is active (should be 0 now)
        thought_tokens = getattr(metadata, "thoughts_token_count",    0) or 0
        if thought_tokens:
            logger.debug("[%s] %s — thinking tokens: %d", self.name, raw_model, thought_tokens)

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
        response_model: type[T] | None = None,  # accepted for API compatibility; unused
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

        read_timeout = float(self.settings.ollama_read_timeout)
        payload = {
            "model": raw_model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user",   "content": user_message},
            ],
            "temperature": temperature,
            "stream": False,
            # Cap context window and output to keep inference fast on small hardware.
            # Our prompts are ~800–1500 tokens; 4096 ctx is plenty.
            "options": {
                "num_ctx":     4096,
                "num_predict": 512,   # agent outputs are always short JSON
            },
        }

        start = time.monotonic()
        try:
            # connect=5 s: fail fast if server unreachable.
            # read=OLLAMA_READ_TIMEOUT (default 300 s): tunable for slow hardware.
            resp = httpx.post(
                url,
                json=payload,
                timeout=httpx.Timeout(connect=5.0, read=read_timeout, write=10.0, pool=5.0),
            )
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot connect to Ollama at {base_url}. "
                f"Check that Ollama is running and OLLAMA_BASE_URL is correct. ({exc})"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Ollama at {base_url} timed out after {int(read_timeout)} s. "
                f"Model '{raw_model}' may be too slow on this hardware. "
                f"Try a smaller model (qwen2.5:1.5b, gemma3:1b) or raise OLLAMA_READ_TIMEOUT."
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
        response_model: type[T] | None = None,
    ) -> tuple[str, TokenUsage]:
        """
        Route to the correct backend based on model prefix and key availability.

        Priority / fallback chain
        ─────────────────────────
        1. model starts with "ollama/"    → always Ollama (explicit override)
        2. model starts with "anthropic/" → Anthropic if key set, else Ollama
        3. model starts with "google/"    → Gemini if key set, else Ollama
        4. no recognised prefix           → fall back to Ollama

        When response_model is provided, passes the Pydantic class to the backend
        so it can use native structured-output APIs (Gemini response_schema,
        Anthropic tool_choice) to constrain the model's output format.

        Logging a WARNING when falling back so you know which key is missing.
        """
        effective = model or self.model

        if effective.startswith("ollama/"):
            return self._call_ollama(user_message, model=effective, temperature=temperature,
                                     response_model=response_model)

        if effective.startswith("anthropic/"):
            if self.settings.anthropic_api_key:
                return self._call_anthropic(user_message, model=effective, temperature=temperature,
                                            response_model=response_model)
            logger.warning(
                "[%s] ANTHROPIC_API_KEY not set — falling back to Ollama (%s)",
                self.name, self.settings.ollama_model,
            )
            return self._call_ollama(user_message, temperature=temperature)

        if effective.startswith("google/"):
            if self.settings.gemini_api_key:
                return self._call_gemini(user_message, model=effective, temperature=temperature,
                                         response_model=response_model)
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
        Robustly extract a JSON object from an LLM response.

        Handles (in order):
        1. Clean JSON  → {"key": ...}
        2. Markdown fences → ```json\\n{...}\\n```
        3. Prose prefix  → "Here is the JSON:\\n{...}"  (find first '{')
        """
        import re
        text = text.strip()

        # Strip markdown fences
        if text.startswith("```"):
            lines = text.split("\n")
            inner_lines = lines[1:]                     # drop opening fence line
            if inner_lines and inner_lines[-1].strip().startswith("```"):
                inner_lines = inner_lines[:-1]          # drop closing fence line
            text = "\n".join(inner_lines).strip()

        # If it still doesn't start with '{', find the first JSON object
        if not text.startswith("{"):
            match = re.search(r"\{", text)
            if match:
                text = text[match.start():]

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
        On ValidationError: retry up to max_retries times, unless
        AGENT_SCHEMA_RETRY_ENABLED=false in which case we log and bail immediately.
        Returns (parsed_output, total_token_usage, schema_valid).
        """
        retry_enabled = self.settings.agent_schema_retry_enabled
        effective_max_retries = max_retries if retry_enabled else 0

        total_usage = TokenUsage(agent=self.name, model=self.model)
        last_exc: Exception | None = None

        # Transient API errors (Gemini 500/503/429, Anthropic 529, network issues)
        # are caught here as a safety net — _call_gemini already retries them
        # internally, but if all inner retries fail the exception surfaces here.
        try:
            from google.genai.errors import APIError as _GeminiAPIError
        except ImportError:
            _GeminiAPIError = None  # type: ignore[assignment,misc]

        def _is_transient(exc: Exception) -> bool:
            if _GeminiAPIError and isinstance(exc, _GeminiAPIError):
                return True
            # Anthropic / httpx network errors
            name = type(exc).__name__
            return name in (
                "APIStatusError", "APIConnectionError", "APITimeoutError",
                "InternalServerError", "ServiceUnavailable", "RateLimitError",
                "ConnectError", "TimeoutException",
            )

        for attempt in range(effective_max_retries + 1):
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
                if not retry_enabled:
                    logger.error(
                        "[%s] Schema validation failed (AGENT_SCHEMA_RETRY_ENABLED=false"
                        " — not retrying): %s",
                        self.name,
                        exc,
                    )
                    break
                logger.warning(
                    "[%s] Schema validation failed (attempt %d/%d): %s",
                    self.name,
                    attempt + 1,
                    effective_max_retries + 1,
                    exc,
                )

            except Exception as exc:
                last_exc = exc
                if _is_transient(exc):
                    # Inner retry loop in _call_gemini already attempted backoff;
                    # this is the final fallback log before returning HOLD.
                    logger.error(
                        "[%s] Transient API error after all retries (attempt %d/%d): %s",
                        self.name,
                        attempt + 1,
                        effective_max_retries + 1,
                        exc,
                    )
                else:
                    # Unexpected error — log full traceback and bail immediately.
                    logger.exception(
                        "[%s] Unexpected error calling LLM (attempt %d/%d): %s",
                        self.name,
                        attempt + 1,
                        effective_max_retries + 1,
                        exc,
                    )
                    break  # don't retry unexpected errors

        logger.error("[%s] All retries exhausted. Last error: %s", self.name, last_exc)
        return None, total_usage, False
