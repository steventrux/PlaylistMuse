from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import backend.constraint_interpreter as constraint_interpreter
import backend.llm as llm
from backend.config import AppConfig
from backend.provider_rate_limits import (
    ProviderRateLimitedError,
    clear_rate_limits,
    is_rate_limited,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_rate_limits()
    yield
    clear_rate_limits()


def _gemini_429_body(quota_id: str) -> dict:
    return {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [{"quotaId": quota_id}],
                },
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "24s",
                },
            ],
        }
    }


def test_request_model_marks_and_skips_a_rate_limited_gemini_model() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            json=_gemini_429_body("GenerateRequestsPerMinutePerProjectPerModel-FreeTier"),
        )

    config = AppConfig(provider="gemini", api_key="test-key")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(llm.ProviderRequestError):
                await llm._request_model(client, config, "gemini-3.6-flash", "prompt", 5)

            assert is_rate_limited("gemini", "gemini-3.6-flash") is True
            assert calls == 1

            # The second call is skipped entirely -- no network round trip.
            with pytest.raises(ProviderRateLimitedError):
                await llm._request_model(client, config, "gemini-3.6-flash", "prompt", 5)
            assert calls == 1

    asyncio.run(run())


def test_try_complete_request_cascades_past_a_cached_rate_limited_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted_models: list[str] = []

    async def fake_request_model(client, config, model, user_prompt, count, *, exact_count=False):
        attempted_models.append(model)
        if model == "gemini-3.6-flash":
            raise ProviderRateLimitedError("cached as rate-limited")
        return json.dumps(
            {
                "title": "Focused Journey",
                "description": "A coherent playlist with a deliberate musical arc.",
                "tracks": [
                    {
                        "artist": f"Artist {index}",
                        "title": f"Track {index}",
                        "description": "sound",
                        "reason": "reason",
                    }
                    for index in range(count)
                ],
            }
        )

    monkeypatch.setattr(llm, "_request_model", fake_request_model)
    config = AppConfig(
        provider="gemini",
        api_key="test-key",
        model="gemini-3.6-flash",
        fallback_1="gemini-3.7-flash",
    )

    async def run():
        async with httpx.AsyncClient() as client:
            return await llm._try_complete_request(client, config, "prompt", 5)

    complete, _partial, _errors = asyncio.run(run())

    assert attempted_models == ["gemini-3.6-flash", "gemini-3.7-flash"]
    assert complete is not None
    assert len(complete["tracks"]) == 5


def test_request_structured_json_marks_and_skips_a_rate_limited_gemini_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            json=_gemini_429_body("GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
        )

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(constraint_interpreter.httpx, "AsyncClient", fake_async_client)
    config = AppConfig(provider="gemini", api_key="test-key", model="gemini-3.6-flash")

    async def run() -> None:
        with pytest.raises(httpx.HTTPStatusError):
            await constraint_interpreter.request_structured_json(config, "prompt")
        assert is_rate_limited("gemini", "gemini-3.6-flash") is True
        assert calls == 1

        with pytest.raises(ProviderRateLimitedError):
            await constraint_interpreter.request_structured_json(config, "prompt")
        assert calls == 1

    asyncio.run(run())
