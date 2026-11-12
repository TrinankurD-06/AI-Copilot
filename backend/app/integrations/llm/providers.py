"""LLM providers behind one small interface: complete(prompt, json_mode) -> str.

Each provider maps its own SDK errors onto three outcomes the gateway acts on:
Transient (retry), RateLimited (skip this provider now), ProviderError (skip).
"""

from __future__ import annotations

from typing import Protocol


class ProviderError(Exception):
    """Provider failed for this call; move on to the next provider."""


class RateLimited(ProviderError):
    """Quota exhausted; do not retry this provider in this call."""


class Transient(ProviderError):
    """Temporary failure (5xx, timeout, empty reply); may be retried."""


class Provider(Protocol):
    name: str
    model: str

    def complete(self, prompt: str, *, json_mode: bool) -> str: ...


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout_s: int):
        from google import genai
        from google.genai import types

        self.model = model
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=timeout_s * 1000)
        )

    def complete(self, prompt: str, *, json_mode: bool) -> str:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            response_mime_type="application/json" if json_mode else "text/plain",
            temperature=0,
        )
        try:
            resp = self._client.models.generate_content(
                model=self.model, contents=prompt, config=config
            )
        except errors.ServerError as e:
            raise Transient(f"gemini {e.code}") from e
        except errors.ClientError as e:
            if e.code == 429:
                raise RateLimited("gemini quota exhausted") from e
            raise ProviderError(f"gemini {e.code}: {e.message}") from e
        if not resp.text:
            raise Transient("gemini returned an empty response")
        return resp.text


class OpenAICompatibleProvider:
    """Groq, OpenRouter, or anything that speaks the OpenAI chat API."""

    def __init__(self, name: str, api_key: str, base_url: str, model: str, timeout_s: int):
        from openai import OpenAI

        self.name = name
        self.model = model
        self._client = OpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout_s, max_retries=0
        )

    def complete(self, prompt: str, *, json_mode: bool) -> str:
        from openai import APIConnectionError, APIStatusError, RateLimitError

        extra = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                **extra,
            )
        except RateLimitError as e:
            raise RateLimited(f"{self.name} rate limited") from e
        except APIConnectionError as e:  # includes timeouts
            raise Transient(f"{self.name} connection error") from e
        except APIStatusError as e:
            if e.status_code >= 500:
                raise Transient(f"{self.name} {e.status_code}") from e
            raise ProviderError(f"{self.name} {e.status_code}: {e.message}") from e
        content = resp.choices[0].message.content
        if not content:
            raise Transient(f"{self.name} returned an empty response")
        return content
