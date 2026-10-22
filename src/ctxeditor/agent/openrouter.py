"""OpenRouter client over its OpenAI-compatible chat completions API. All calls happen server-side.

Nothing in an exception, message or log line from this module contains the API key, the prompt, the document or
the response text: failures are reduced to a fixed class and a fixed friendly message.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from .settings import AgentSettings

log = logging.getLogger(__name__)

RETRY_AFTER_CAP_S = 10.0


@dataclass(frozen=True)
class LlmResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class AgentCallError(Exception):
    """A failed model call. error_class is stored on the request row; user_message is safe to show."""

    error_class = "provider_error"
    user_message = "The editing assistant could not complete the request. Your document was not changed."

    def __init__(self) -> None:
        super().__init__(self.user_message)


class AgentTimeout(AgentCallError):
    error_class = "timeout"
    user_message = "The editing assistant took too long to answer. Your document was not changed. Please try again."


class AgentRateLimited(AgentCallError):
    error_class = "rate_limited"
    user_message = "The editing assistant is busy right now. Your document was not changed. Please try again shortly."


class AgentProviderError(AgentCallError):
    error_class = "provider_error"


class AgentBadOutput(AgentCallError):
    error_class = "bad_output"
    user_message = "The editing assistant returned an answer that could not be used. Your document was not changed."


class AgentAuthError(AgentCallError):
    error_class = "auth"
    user_message = "The editing assistant is not set up correctly. Your document was not changed."


class OpenRouterClient:
    def __init__(self, settings: AgentSettings, *, transport: httpx.AsyncBaseTransport | None = None,
                 base_delay: float = 1.0, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self._settings = settings
        self._transport = transport
        self._base_delay = base_delay
        self._sleep = sleep

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            try:
                return min(max(float(response.headers.get("retry-after", "")), 0.0), RETRY_AFTER_CAP_S)
            except ValueError:
                pass
        return self._base_delay * (2 ** attempt)

    async def complete(self, system: str, user: str) -> LlmResult:
        s = self._settings
        payload = {
            "model": s.model,
            "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Authorization": f"Bearer {s.api_key.reveal()}", "Content-Type": "application/json"}
        url = f"{s.base_url.rstrip('/')}/chat/completions"
        failure: AgentCallError = AgentProviderError()
        async with httpx.AsyncClient(timeout=s.timeout_s, transport=self._transport) as http:
            for attempt in range(s.max_retries + 1):
                response: httpx.Response | None = None
                try:
                    response = await http.post(url, json=payload, headers=headers)
                except httpx.TimeoutException:
                    failure = AgentTimeout()
                except httpx.HTTPError:
                    failure = AgentProviderError()
                else:
                    status = response.status_code
                    if status == 200:
                        return self._parse(response)
                    if status in (401, 403):
                        log.warning("agent call rejected status=%s", status)
                        raise AgentAuthError() from None
                    if status == 429:
                        failure = AgentRateLimited()
                    elif status >= 500:
                        failure = AgentProviderError()
                    else:
                        log.warning("agent call failed status=%s", status)
                        raise AgentProviderError() from None
                log.info("agent call retryable failure class=%s attempt=%s", failure.error_class, attempt + 1)
                if attempt < s.max_retries:
                    await self._sleep(self._delay(attempt, response))
        raise failure from None

    @staticmethod
    def _parse(response: httpx.Response) -> LlmResult:
        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
            usage = body.get("usage") or {}
            tokens_in = int(usage.get("prompt_tokens") or 0)
            tokens_out = int(usage.get("completion_tokens") or 0)
        except (ValueError, KeyError, IndexError, TypeError):
            raise AgentBadOutput() from None
        if not isinstance(text, str) or not text.strip():
            raise AgentBadOutput()
        return LlmResult(text=text, tokens_in=tokens_in, tokens_out=tokens_out)
