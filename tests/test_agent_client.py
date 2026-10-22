"""OpenRouterClient: request shape, retries with backoff, error mapping, and no leaks in errors."""
from __future__ import annotations

import json

import httpx
import pytest

from ctxeditor.agent.openrouter import (
    AgentAuthError,
    AgentBadOutput,
    AgentCallError,
    AgentProviderError,
    AgentRateLimited,
    AgentTimeout,
    OpenRouterClient,
)
from ctxeditor.agent.settings import AgentSettings, Secret

KEY = "sk-or-v1-TESTKEY123"
OK = {"choices": [{"message": {"content": "<p>hi</p>"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}}


def make(handler, *, retries=3, sleeps=None):
    async def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    settings = AgentSettings(api_key=Secret(KEY), model="vendor/m", max_retries=retries)
    return OpenRouterClient(settings, transport=httpx.MockTransport(handler), base_delay=1.0, sleep=sleep)


async def test_request_shape_and_result():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK)

    result = await make(handler).complete("SYSTEM", "USER")
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions" and seen["auth"] == f"Bearer {KEY}"
    assert seen["body"]["model"] == "vendor/m" and seen["body"]["temperature"] == 0.2
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]
    assert (result.text, result.tokens_in, result.tokens_out) == ("<p>hi</p>", 3, 4)


async def test_retries_with_exponential_backoff_then_succeeds():
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=OK)

    result = await make(handler, sleeps=sleeps).complete("s", "u")
    assert result.text == "<p>hi</p>" and len(calls) == 3 and sleeps == [1.0, 2.0]


@pytest.mark.parametrize("handler,error", [
    (lambda r: httpx.Response(429), AgentRateLimited),
    (lambda r: httpx.Response(500), AgentProviderError),
    (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("t")), AgentTimeout),
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("c")), AgentProviderError),
])
async def test_exhausted_retries_raise_typed_error_after_bounded_attempts(handler, error):
    calls = []

    def counting(request):
        calls.append(1)
        return handler(request)

    with pytest.raises(error):
        await make(counting, retries=2).complete("s", "u")
    assert len(calls) == 3  # one try plus two retries


async def test_auth_and_other_client_errors_are_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401 if len(calls) == 1 else 400)

    with pytest.raises(AgentAuthError):
        await make(handler).complete("s", "u")
    calls.clear()
    with pytest.raises(AgentProviderError):
        await make(lambda r: httpx.Response(400)).complete("s", "u")


async def test_retry_after_header_is_respected_and_capped():
    sleeps, state = [], {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "2"})
        if state["n"] == 2:
            return httpx.Response(429, headers={"retry-after": "999"})
        return httpx.Response(200, json=OK)

    await make(handler, sleeps=sleeps).complete("s", "u")
    assert sleeps == [2.0, 10.0]


@pytest.mark.parametrize("response", [
    httpx.Response(200, json={"choices": []}),
    httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
    httpx.Response(200, text="not json"),
])
async def test_bad_output(response):
    with pytest.raises(AgentBadOutput):
        await make(lambda r: response).complete("s", "u")


async def test_missing_usage_defaults_to_zero():
    body = {"choices": [{"message": {"content": "<p>x</p>"}}]}
    result = await make(lambda r: httpx.Response(200, json=body)).complete("s", "u")
    assert (result.tokens_in, result.tokens_out) == (0, 0)


async def test_errors_never_carry_key_prompt_or_response():
    def handler(request):
        return httpx.Response(500, text=f"echo {KEY} SECRET-RESPONSE")

    with pytest.raises(AgentCallError) as caught:
        await make(handler, retries=1).complete("SECRET-SYSTEM", "SECRET-USER-PROMPT")
    blob = repr(caught.value) + str(caught.value) + str(caught.value.__cause__) + str(caught.value.__context__)
    for leaked in (KEY, "TESTKEY", "SECRET-RESPONSE", "SECRET-SYSTEM", "SECRET-USER-PROMPT"):
        assert leaked not in blob
    assert caught.value.error_class == "provider_error" and "not changed" in caught.value.user_message.lower()
