"""Single entry point for every LLM call made by the planner adapter.

Providers are tried in configured order. Transient errors are retried with
backoff; a rate-limited or failing provider is skipped. A refusal stops the
chain at once, so a declined request is never re-sent to a laxer model. Each call is logged
with provider, model and latency so plans can record which model made them.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

from app.core.config import Settings, settings
from app.integrations.llm.providers import (
    GeminiProvider,
    OpenAICompatibleProvider,
    Provider,
    ProviderError,
    RateLimited,
    Refused,
    Transient,
)

log = logging.getLogger(__name__)

_MISSING = object()
_FENCED = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


@dataclass(frozen=True)
class Completion:
    text: str
    provider: str
    model: str
    latency_ms: int


class LLMGateway:
    def __init__(self, cfg: Settings = settings, providers: list[Provider] | None = None):
        self.max_retries = cfg.LLM_MAX_RETRIES
        self.repair_attempts = cfg.LLM_SCHEMA_REPAIR_ATTEMPTS
        self.providers = providers if providers is not None else self._from_settings(cfg)
        if not self.providers:
            raise ValueError(
                "No LLM provider configured: set GEMINI_API_KEY, GROQ_API_KEY or OPENROUTER_API_KEY"
            )
        log.info("llm providers: %s", ", ".join(f"{p.name}:{p.model}" for p in self.providers))

    @staticmethod
    def _from_settings(cfg: Settings) -> list[Provider]:
        t = cfg.LLM_TIMEOUT_S
        providers: list[Provider] = []
        if cfg.GEMINI_API_KEY:
            providers.append(GeminiProvider(cfg.GEMINI_API_KEY, cfg.GEMINI_MODEL, t))
        if cfg.GROQ_API_KEY:
            providers.append(OpenAICompatibleProvider(
                "groq", cfg.GROQ_API_KEY, "https://api.groq.com/openai/v1", cfg.GROQ_MODEL, t))
        if cfg.OPENROUTER_API_KEY:
            providers.append(OpenAICompatibleProvider(
                "openrouter", cfg.OPENROUTER_API_KEY, "https://openrouter.ai/api/v1", cfg.OPENROUTER_MODEL, t))
        return providers

    def complete(self, prompt: str, *, json_mode: bool = False) -> Completion:
        last: Exception | None = None
        for p in self.providers:
            for attempt in range(1, self.max_retries + 1):
                t0 = time.perf_counter()
                try:
                    text = p.complete(prompt, json_mode=json_mode)
                    ms = int((time.perf_counter() - t0) * 1000)
                    log.info("llm ok provider=%s model=%s latency_ms=%d", p.name, p.model, ms)
                    return Completion(text, p.name, p.model, ms)
                except Refused as e:
                    log.warning("llm refused provider=%s reason=%s", p.name, e)
                    raise  # an answer, not an outage: never shop it to another provider
                except RateLimited as e:
                    log.warning("llm skip provider=%s reason=%s", p.name, e)
                    last = e
                    break
                except Transient as e:
                    log.warning("llm retry provider=%s attempt=%d/%d reason=%s",
                                p.name, attempt, self.max_retries, e)
                    last = e
                    if attempt < self.max_retries:
                        time.sleep(2 ** (attempt - 1))
                except ProviderError as e:
                    log.warning("llm fail provider=%s reason=%s", p.name, e)
                    last = e
                    break
                except Exception as e:  # SDK surprise: do not let one provider sink failover
                    log.error("llm crash provider=%s", p.name, exc_info=True)
                    last = ProviderError(f"{p.name} raised {type(e).__name__}: {e}")
                    break
        raise RuntimeError(f"all LLM providers failed; last error: {last}")

    def complete_json(self, prompt: str) -> tuple[dict, Completion]:
        c = self.complete(prompt, json_mode=True)
        return self.parse_json(c.text), c

    @staticmethod
    def parse_json(text: str) -> dict:
        """Accept a bare object, a fenced block, or prose around either."""
        text = text.strip()
        candidates = [text]
        if m := _FENCED.search(text):
            candidates.insert(0, m.group(1))
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            candidates.append(text[start:end + 1])
        data = _MISSING
        for c in candidates:
            try:
                data = json.loads(c)
                break
            except json.JSONDecodeError:
                continue
        if data is _MISSING:
            raise ValueError(f"invalid JSON from LLM: {text[:200]!r}")
        if not isinstance(data, dict):
            raise ValueError(f"expected a JSON object, got {type(data).__name__}")
        return data
