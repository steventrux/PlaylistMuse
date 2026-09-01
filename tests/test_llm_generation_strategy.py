from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx

import backend.llm as llm
from backend.config import AppConfig


def _draft(start: int, count: int) -> str:
    return json.dumps(
        {
            "title": "Focused Journey",
            "description": "A coherent playlist with a deliberate musical arc.",
            "tracks": [
                {
                    "artist": f"Artist {index}",
                    "title": f"Track {index}",
                    "description": f"Sound of track {index}.",
                    "reason": f"Track {index} supports the requested flow.",
                }
                for index in range(start, start + count)
            ],
        }
    )


def test_system_prompt_uses_constraint_first_curation_protocol() -> None:
    assert "silently build a constraint checklist" in llm.SYSTEM_PROMPT
    assert "explicit mandatory constraints and placements" in llm.SYSTEM_PROMPT
    assert "ordering, alternation, sections, transitions or an energy progression" in llm.SYSTEM_PROMPT
    assert "Never relax a mandatory requirement" in llm.SYSTEM_PROMPT
    assert "Do not output this planning" in llm.SYSTEM_PROMPT


def test_system_prompt_forbids_track_counts_in_title_and_description() -> None:
    """Regression: two separate real generations stated a count that didn't match the
    final tracks array -- "five tracks by The Rolling Stones" when only 3 were present,
    then "A 23-track chronological descent" on a 20-track playlist. Trying to keep an
    LLM-stated count in sync with the finished array is unreliable; forbidding the count
    outright removes the failure mode instead of chasing it.
    """
    assert (
        'Never state a number of songs, tracks or artist tally in the title or the '
        'description' in llm.SYSTEM_PROMPT
    )
    assert (
        "neither the title nor the description states any number of songs, tracks or "
        "artist tally" in llm.SYSTEM_PROMPT
    )


def test_nearly_complete_response_fills_only_missing_tracks(monkeypatch) -> None:
    calls: list[tuple[int, bool]] = []

    async def fake_request_model(
        client,
        config,
        model,
        user_prompt,
        count,
        *,
        exact_count=False,
    ):
        calls.append((count, exact_count))
        if count == 10:
            return _draft(1, 8)
        assert count == 2
        return _draft(9, 2)

    monkeypatch.setattr(llm, "_request_model", fake_request_model)
    config = SimpleNamespace(
        configured=True,
        provider="openrouter_free",
        model_chain=("model-a",),
    )

    result = asyncio.run(llm.generate_playlist_draft(config, "Road trip rock", 10))

    assert len(result["tracks"]) == 10
    assert calls == [(10, True), (2, False)]


def test_sparse_partial_still_allows_full_retry(monkeypatch) -> None:
    calls = 0

    async def fake_request_model(
        client,
        config,
        model,
        user_prompt,
        count,
        *,
        exact_count=False,
    ):
        nonlocal calls
        calls += 1
        return _draft(1, 3 if calls == 1 else count)

    monkeypatch.setattr(llm, "_request_model", fake_request_model)
    config = SimpleNamespace(
        configured=True,
        provider="openrouter_free",
        model_chain=("model-a",),
    )

    result = asyncio.run(llm.generate_playlist_draft(config, "Road trip rock", 10))

    assert len(result["tracks"]) == 10
    assert calls == 2


class _FakeAsyncClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def post(self, url, *, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self._responses.pop(0)


def _openai_success_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "some/routed-model",
            "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        },
    )


_MANDATORY_REASONING_RESPONSE = httpx.Response(
    400,
    json={
        "error": {
            "message": "Reasoning is mandatory for this endpoint and cannot be disabled.",
            "code": 400,
        }
    },
)


def test_openrouter_falls_back_to_bounded_reasoning_when_disabling_is_rejected() -> None:
    client = _FakeAsyncClient(
        [_MANDATORY_REASONING_RESPONSE, _openai_success_response("hello")]
    )
    config = AppConfig(provider="openrouter_auto", api_key="test-key", model="openrouter/auto")

    text = asyncio.run(
        llm._request_model(client, config, "openrouter/auto", "prompt", 5, exact_count=True)
    )

    assert text == "hello"
    assert len(client.calls) == 2
    assert client.calls[0]["json"]["reasoning"] == {"effort": "none"}
    second_reasoning = client.calls[1]["json"]["reasoning"]
    assert "max_tokens" in second_reasoning
    assert second_reasoning["max_tokens"] < client.calls[1]["json"]["max_tokens"]


def test_openrouter_other_400_errors_do_not_trigger_reasoning_fallback() -> None:
    unrelated_400 = httpx.Response(
        400, json={"error": {"message": "Invalid model requested.", "code": 400}}
    )
    client = _FakeAsyncClient([unrelated_400])
    config = AppConfig(provider="openrouter_auto", api_key="test-key", model="openrouter/auto")

    try:
        asyncio.run(
            llm._request_model(client, config, "openrouter/auto", "prompt", 5, exact_count=True)
        )
    except llm.ProviderRequestError:
        pass
    else:
        raise AssertionError("expected a ProviderRequestError for an unrelated 400")

    assert len(client.calls) == 1


def test_gemini_thinking_config_uses_thinking_level_for_3x_flash() -> None:
    assert llm._gemini_thinking_config("gemini-3.6-flash") == {"thinkingLevel": "minimal"}


def test_gemini_thinking_config_uses_low_level_for_3x_pro() -> None:
    assert llm._gemini_thinking_config("gemini-3.1-pro-preview") == {"thinkingLevel": "low"}


def test_gemini_thinking_config_uses_thinking_budget_for_legacy_flash() -> None:
    assert llm._gemini_thinking_config("gemini-2.5-flash") == {"thinkingBudget": 0}


def test_gemini_thinking_config_uses_minimum_budget_for_legacy_pro() -> None:
    assert llm._gemini_thinking_config("gemini-2.5-pro") == {"thinkingBudget": 128}


def test_gemini_thinking_config_treats_bare_alias_as_current_generation() -> None:
    assert llm._gemini_thinking_config("gemini-flash-latest") == {"thinkingLevel": "minimal"}


_REASONING_EFFORT_VALUE_REJECTED = httpx.Response(
    400,
    json={
        "error": {
            "message": "`reasoning_effort` must be one of `low`, `medium`, or `high`",
            "type": "invalid_request_error",
        }
    },
)

_REASONING_EFFORT_UNSUPPORTED = httpx.Response(
    400,
    json={
        "error": {
            "message": "`reasoning_effort` is not supported with this model",
            "type": "invalid_request_error",
        }
    },
)


def test_custom_provider_falls_back_from_none_to_low_reasoning_effort() -> None:
    client = _FakeAsyncClient(
        [_REASONING_EFFORT_VALUE_REJECTED, _openai_success_response("hello")]
    )
    config = AppConfig(provider="custom", api_key="test-key", base_url="https://api.groq.com/openai/v1")

    text = asyncio.run(
        llm._request_model(client, config, "openai/gpt-oss-120b", "prompt", 5, exact_count=True)
    )

    assert text == "hello"
    assert len(client.calls) == 2
    assert client.calls[0]["json"]["reasoning_effort"] == "none"
    assert client.calls[1]["json"]["reasoning_effort"] == "low"


def test_custom_provider_falls_back_to_omitting_reasoning_effort_when_unsupported() -> None:
    client = _FakeAsyncClient(
        [
            _REASONING_EFFORT_UNSUPPORTED,
            _REASONING_EFFORT_UNSUPPORTED,
            _openai_success_response("hello"),
        ]
    )
    config = AppConfig(provider="custom", api_key="test-key", base_url="https://api.groq.com/openai/v1")

    text = asyncio.run(
        llm._request_model(client, config, "allam-2-7b", "prompt", 5, exact_count=True)
    )

    assert text == "hello"
    assert len(client.calls) == 3
    assert client.calls[0]["json"]["reasoning_effort"] == "none"
    assert client.calls[1]["json"]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in client.calls[2]["json"]


def test_custom_provider_other_400_errors_do_not_trigger_reasoning_effort_fallback() -> None:
    unrelated_400 = httpx.Response(
        400, json={"error": {"message": "Invalid API key.", "type": "invalid_request_error"}}
    )
    client = _FakeAsyncClient([unrelated_400])
    config = AppConfig(provider="custom", api_key="bad-key", base_url="https://api.groq.com/openai/v1")

    try:
        asyncio.run(
            llm._request_model(client, config, "allam-2-7b", "prompt", 5, exact_count=True)
        )
    except llm.ProviderRequestError:
        pass
    else:
        raise AssertionError("expected a ProviderRequestError for an unrelated 400")

    assert len(client.calls) == 1


def _anthropic_success_response(text: str) -> httpx.Response:
    return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})


def test_anthropic_system_prompt_caches_only_the_static_block() -> None:
    client = _FakeAsyncClient([_anthropic_success_response("hello")])
    config = AppConfig(provider="anthropic", api_key="test-key", model="claude-sonnet-5")

    text = asyncio.run(
        llm._request_model(client, config, "claude-sonnet-5", "prompt", 5, exact_count=True)
    )

    assert text == "hello"
    assert len(client.calls) == 1
    system = client.calls[0]["json"]["system"]
    assert isinstance(system, list) and len(system) == 2
    assert system[0]["text"] == llm.SYSTEM_PROMPT
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in system[1]
    assert system[0]["text"] + system[1]["text"] == llm._dated_system_prompt(llm.SYSTEM_PROMPT)
