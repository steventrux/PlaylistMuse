import asyncio
import json
import time

import httpx
import pytest

from backend import cache_metrics, constraint_interpreter
from backend.config import AppConfig
from backend.constraint_interpreter import (
    _date_context_suffix,
    _dated_system_prompt,
    _extract_json,
    interpret_constraints,
    request_structured_json,
)
from backend.provider_rate_limits import ProviderRateLimitedError


def _config() -> AppConfig:
    return AppConfig(
        provider="custom",
        model="test-model",
        base_url="http://provider.test",
    )


def test_system_prompt_covers_open_ended_decade_to_present_wording():
    """A decade combined with "to now/today/present" must not close release_year_to.

    Regression: "from the 1960s to now" was being interpreted as a closed 1960-1969
    range, silently dropping every later decade the user actually asked for.
    """
    assert "up through the present" in constraint_interpreter.SYSTEM_PROMPT
    assert 'to now"' in constraint_interpreter.SYSTEM_PROMPT
    assert "leave release_year_to null" in constraint_interpreter.SYSTEM_PROMPT


def test_system_prompt_covers_genre_era_present_wording():
    """A decade combined with a genre/era label meaning present-day music (e.g. "modern
    jazz", "contemporary jazz") must be treated the same as literal "to now" wording and
    must not close release_year_to.

    Regression: "the 1970s through modern jazz" was being interpreted as a closed
    1970-1979 range, silently dropping every modern-jazz track the user actually asked
    for.
    """
    assert '"modern jazz"' in constraint_interpreter.SYSTEM_PROMPT
    assert "genre or era label" in constraint_interpreter.SYSTEM_PROMPT


def test_dated_system_prompt_appends_todays_date_without_mutating_base():
    base = "Base system prompt."

    dated = _dated_system_prompt(base)

    assert dated.startswith(base)
    assert time.strftime("%Y-%m-%d", time.gmtime()) in dated
    assert base == "Base system prompt."


def test_dated_system_prompt_is_base_plus_date_context_suffix():
    """Regression for the prompt-caching split: _dated_system_prompt must stay byte-for-
    byte equal to base + _date_context_suffix(), since Anthropic caches the base block
    separately from this suffix -- any drift here would silently change what non-Anthropic
    providers see vs. what gets cached for Anthropic."""
    base = "Base system prompt."

    assert _dated_system_prompt(base) == base + _date_context_suffix()


def test_extracts_constraint_json_from_provider_text():
    payload = _extract_json(
        '```json\n{"allowed_artists":["Metallica"],"confidence":"high"}\n```'
    )

    assert payload["allowed_artists"] == ["Metallica"]
    assert payload["confidence"] == "high"


def test_constraint_payload_can_represent_non_latin_requests():
    payload = _extract_json(
        '{"allowed_artists":["坂本龍一"],"excluded_artists":[],"allowed_albums":[],"excluded_albums":[],"release_year":null,"release_year_from":1980,"release_year_to":1989,"artist_country":null,"confidence":"high"}'
    )

    assert payload["allowed_artists"] == ["坂本龍一"]
    assert payload["release_year_from"] == 1980
    assert payload["release_year_to"] == 1989


@pytest.mark.parametrize(
    ("prompt", "country"),
    [
        ("Crea una playlist di musica italiana dal 2000 ad oggi adatta per un party.", "IT"),
        ("Create a playlist of French music for a party.", "FR"),
        ("Crée une playlist de musique allemande pour une fête.", "DE"),
        ("Crea una playlist de música española para una fiesta.", "ES"),
        ("Erstelle eine Playlist mit britischer Musik für eine Party.", "GB"),
    ],
)
def test_national_repertoire_keeps_interpreted_artist_country(monkeypatch, prompt, country):
    payload = {
        "artist_country": country,
        "lyrics_language": None,
        "field_confidence": {
            "artist_country": 0.99,
            "lyrics_language": 0.0,
        },
    }

    async def fake_request(*args, **kwargs):
        return json.dumps(payload)

    monkeypatch.setattr(constraint_interpreter, "request_structured_json", fake_request)
    monkeypatch.setattr(constraint_interpreter, "_read_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(constraint_interpreter, "_write_cache", lambda *args, **kwargs: None)

    interpreted = asyncio.run(interpret_constraints(_config(), prompt))

    assert interpreted is not None
    assert interpreted["artist_country"] == country
    assert interpreted["field_confidence"]["artist_country"] == 0.99


def test_national_origin_and_lyrics_language_remain_independent(monkeypatch):
    payload = {
        "artist_country": "IT",
        "lyrics_language": None,
        "field_confidence": {
            "artist_country": 0.98,
            "lyrics_language": 0.0,
        },
    }

    async def fake_request(*args, **kwargs):
        return json.dumps(payload)

    monkeypatch.setattr(constraint_interpreter, "request_structured_json", fake_request)
    monkeypatch.setattr(constraint_interpreter, "_read_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(constraint_interpreter, "_write_cache", lambda *args, **kwargs: None)

    interpreted = asyncio.run(
        interpret_constraints(
            _config(),
            "Crea una playlist di musica italiana per una festa.",
        )
    )

    assert interpreted is not None
    assert interpreted["artist_country"] == "IT"
    assert interpreted["lyrics_language"] is None


def _config_with_fallback() -> AppConfig:
    return AppConfig(
        provider="custom",
        model="primary-model",
        fallback_1="fallback-model",
        base_url="http://provider.test",
    )


def test_rate_limited_primary_model_falls_back_to_next_model(monkeypatch) -> None:
    """A model cached as rate-limited must not stop constraint interpretation.

    Regression test: ProviderRateLimitedError was introduced without every
    request_structured_json caller catching it, so a rate-limited primary model
    used to propagate uncaught instead of trying the next model in the chain.
    """
    payload = {"allowed_artists": ["Metallica"], "confidence": "high"}

    async def fake_request(config, prompt, *, model=None, **kwargs):
        if model == "primary-model":
            raise ProviderRateLimitedError("custom/primary-model is cached as rate-limited")
        assert model == "fallback-model"
        return json.dumps(payload)

    monkeypatch.setattr(constraint_interpreter, "request_structured_json", fake_request)
    monkeypatch.setattr(constraint_interpreter, "_read_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(constraint_interpreter, "_write_cache", lambda *args, **kwargs: None)

    interpreted = asyncio.run(
        interpret_constraints(_config_with_fallback(), "Playlist di musica heavy metal.")
    )

    assert interpreted == payload


def test_all_models_rate_limited_degrades_to_none_without_raising(monkeypatch) -> None:
    async def always_rate_limited(config, prompt, *, model=None, **kwargs):
        raise ProviderRateLimitedError(f"custom/{model} is cached as rate-limited")

    monkeypatch.setattr(constraint_interpreter, "request_structured_json", always_rate_limited)
    monkeypatch.setattr(constraint_interpreter, "_read_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(constraint_interpreter, "_write_cache", lambda *args, **kwargs: None)

    interpreted = asyncio.run(
        interpret_constraints(_config_with_fallback(), "Playlist di musica heavy metal.")
    )

    assert interpreted is None


def test_write_cache_purges_expired_rows_after_interval(tmp_path, monkeypatch):
    cache_path = tmp_path / "constraint_interpretation_cache.sqlite3"
    monkeypatch.setattr(constraint_interpreter, "_cache_path", lambda: cache_path)
    monkeypatch.setattr(constraint_interpreter, "_last_purge_at", 0.0)

    with constraint_interpreter._connect() as connection:
        connection.execute(
            "INSERT INTO constraint_interpretation_cache(cache_key, payload, expires_at) "
            "VALUES (?, ?, ?)",
            ("stale-key", "{}", time.time() - 10),
        )

    constraint_interpreter._write_cache(_config(), "Fresh prompt", {"confidence": "low"})

    with constraint_interpreter._connect() as connection:
        remaining = {
            row["cache_key"]
            for row in connection.execute(
                "SELECT cache_key FROM constraint_interpretation_cache"
            ).fetchall()
        }
    assert "stale-key" not in remaining


def test_read_cache_records_hit_and_miss_metrics(tmp_path, monkeypatch):
    cache_path = tmp_path / "constraint_interpretation_cache.sqlite3"
    monkeypatch.setattr(constraint_interpreter, "_cache_path", lambda: cache_path)

    before = cache_metrics.snapshot().get(
        "Constraint interpretation", {"hits": 0, "misses": 0}
    )

    assert constraint_interpreter._read_cache(_config(), "Never cached prompt") is None
    after_miss = cache_metrics.snapshot()["Constraint interpretation"]
    assert after_miss["misses"] == before["misses"] + 1

    constraint_interpreter._write_cache(_config(), "Cached prompt", {"confidence": "low"})
    assert constraint_interpreter._read_cache(_config(), "Cached prompt") is not None
    after_hit = cache_metrics.snapshot()["Constraint interpretation"]
    assert after_hit["hits"] == before["hits"] + 1


def test_system_prompt_schema_includes_energy_order():
    assert '"energy_order"' in constraint_interpreter.SYSTEM_PROMPT
    assert '"field_confidence"' in constraint_interpreter.SYSTEM_PROMPT
    assert constraint_interpreter.INTERPRETER_SCHEMA_VERSION == 9


def test_request_structured_json_with_retry_succeeds_on_first_attempt(monkeypatch) -> None:
    """request_structured_json itself must stay untouched -- every other caller
    keeps its exact current behavior; this wrapper is opt-in for callers with
    no fallback chain of their own (see backend/playlist_tags.py,
    backend/local_taste_memory.py).
    """
    calls: list[str | None] = []

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        calls.append(model)
        return '{"ok": true}'

    monkeypatch.setattr(constraint_interpreter, "request_structured_json", fake_request)

    result = asyncio.run(
        constraint_interpreter.request_structured_json_with_retry(
            _config(), "prompt", model="model-a",
        )
    )

    assert result == '{"ok": true}'
    assert calls == ["model-a"], "a successful first attempt must not retry"


def test_request_structured_json_with_retry_retries_once_on_transient_failure(
    monkeypatch,
) -> None:
    attempts = 0

    async def flaky_request(config, prompt, *, system_prompt, max_tokens, model):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("malformed response")
        return '{"ok": true}'

    monkeypatch.setattr(constraint_interpreter, "request_structured_json", flaky_request)

    result = asyncio.run(
        constraint_interpreter.request_structured_json_with_retry(
            _config(), "prompt", model="model-a",
        )
    )

    assert result == '{"ok": true}'
    assert attempts == 2


def test_request_structured_json_with_retry_raises_after_exhausting_attempts(
    monkeypatch,
) -> None:
    attempts = 0

    async def always_fails(config, prompt, *, system_prompt, max_tokens, model):
        nonlocal attempts
        attempts += 1
        raise ValueError(f"attempt {attempts} failed")

    monkeypatch.setattr(constraint_interpreter, "request_structured_json", always_fails)

    with pytest.raises(ValueError, match="attempt 2 failed"):
        asyncio.run(
            constraint_interpreter.request_structured_json_with_retry(
                _config(), "prompt", model="model-a",
            )
        )

    assert attempts == 2


class _FakeAsyncClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def post(self, url, *, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self._responses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


_DUMMY_REQUEST = httpx.Request("POST", "https://openrouter.test/chat/completions")

_MANDATORY_REASONING_RESPONSE = httpx.Response(
    400,
    json={
        "error": {
            "message": "Reasoning is mandatory for this endpoint and cannot be disabled.",
            "code": 400,
        }
    },
    request=_DUMMY_REQUEST,
)


def _openai_success_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "some/routed-model",
            "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        },
        request=_DUMMY_REQUEST,
    )


def test_openrouter_falls_back_to_bounded_reasoning_when_disabling_is_rejected(
    monkeypatch,
) -> None:
    fake_client = _FakeAsyncClient(
        [_MANDATORY_REASONING_RESPONSE, _openai_success_response('{"ok": true}')]
    )
    monkeypatch.setattr(
        constraint_interpreter.httpx, "AsyncClient", lambda **kwargs: fake_client
    )
    config = AppConfig(provider="openrouter_auto", api_key="test-key", model="openrouter/auto")

    result = asyncio.run(request_structured_json(config, "prompt"))

    assert result == '{"ok": true}'
    assert len(fake_client.calls) == 2
    assert fake_client.calls[0]["json"]["reasoning"] == {"effort": "none"}
    second_reasoning = fake_client.calls[1]["json"]["reasoning"]
    assert "max_tokens" in second_reasoning
    assert second_reasoning["max_tokens"] < fake_client.calls[1]["json"]["max_tokens"]


def test_openrouter_other_400_errors_do_not_trigger_reasoning_fallback(monkeypatch) -> None:
    unrelated_400 = httpx.Response(
        400,
        json={"error": {"message": "Invalid model requested.", "code": 400}},
        request=_DUMMY_REQUEST,
    )
    fake_client = _FakeAsyncClient([unrelated_400])
    monkeypatch.setattr(
        constraint_interpreter.httpx, "AsyncClient", lambda **kwargs: fake_client
    )
    config = AppConfig(provider="openrouter_auto", api_key="test-key", model="openrouter/auto")

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(request_structured_json(config, "prompt"))

    assert len(fake_client.calls) == 1


_REASONING_EFFORT_VALUE_REJECTED = httpx.Response(
    400,
    json={
        "error": {
            "message": "`reasoning_effort` must be one of `low`, `medium`, or `high`",
            "type": "invalid_request_error",
        }
    },
    request=_DUMMY_REQUEST,
)

_REASONING_EFFORT_UNSUPPORTED = httpx.Response(
    400,
    json={
        "error": {
            "message": "`reasoning_effort` is not supported with this model",
            "type": "invalid_request_error",
        }
    },
    request=_DUMMY_REQUEST,
)


def test_custom_provider_falls_back_from_none_to_low_reasoning_effort(monkeypatch) -> None:
    fake_client = _FakeAsyncClient(
        [_REASONING_EFFORT_VALUE_REJECTED, _openai_success_response('{"ok": true}')]
    )
    monkeypatch.setattr(
        constraint_interpreter.httpx, "AsyncClient", lambda **kwargs: fake_client
    )
    config = AppConfig(
        provider="custom",
        api_key="test-key",
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-120b",
    )

    result = asyncio.run(request_structured_json(config, "prompt"))

    assert result == '{"ok": true}'
    assert len(fake_client.calls) == 2
    assert fake_client.calls[0]["json"]["reasoning_effort"] == "none"
    assert fake_client.calls[1]["json"]["reasoning_effort"] == "low"


def test_custom_provider_falls_back_to_omitting_reasoning_effort_when_unsupported(
    monkeypatch,
) -> None:
    fake_client = _FakeAsyncClient(
        [
            _REASONING_EFFORT_UNSUPPORTED,
            _REASONING_EFFORT_UNSUPPORTED,
            _openai_success_response('{"ok": true}'),
        ]
    )
    monkeypatch.setattr(
        constraint_interpreter.httpx, "AsyncClient", lambda **kwargs: fake_client
    )
    config = AppConfig(
        provider="custom",
        api_key="test-key",
        base_url="https://api.groq.com/openai/v1",
        model="allam-2-7b",
    )

    result = asyncio.run(request_structured_json(config, "prompt"))

    assert result == '{"ok": true}'
    assert len(fake_client.calls) == 3
    assert fake_client.calls[0]["json"]["reasoning_effort"] == "none"
    assert fake_client.calls[1]["json"]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in fake_client.calls[2]["json"]


def test_custom_provider_other_400_errors_do_not_trigger_reasoning_effort_fallback(
    monkeypatch,
) -> None:
    unrelated_400 = httpx.Response(
        400,
        json={"error": {"message": "Invalid API key.", "type": "invalid_request_error"}},
        request=_DUMMY_REQUEST,
    )
    fake_client = _FakeAsyncClient([unrelated_400])
    monkeypatch.setattr(
        constraint_interpreter.httpx, "AsyncClient", lambda **kwargs: fake_client
    )
    config = AppConfig(
        provider="custom",
        api_key="bad-key",
        base_url="https://api.groq.com/openai/v1",
        model="allam-2-7b",
    )

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(request_structured_json(config, "prompt"))

    assert len(fake_client.calls) == 1


def test_gemini_thinking_config_uses_thinking_level_for_3x_flash() -> None:
    assert constraint_interpreter._gemini_thinking_config("gemini-3.6-flash") == {
        "thinkingLevel": "minimal"
    }


def test_gemini_thinking_config_uses_low_level_for_3x_pro() -> None:
    assert constraint_interpreter._gemini_thinking_config("gemini-3.1-pro-preview") == {
        "thinkingLevel": "low"
    }


def test_gemini_thinking_config_uses_thinking_budget_for_legacy_flash() -> None:
    assert constraint_interpreter._gemini_thinking_config("gemini-2.5-flash") == {
        "thinkingBudget": 0
    }


def test_gemini_thinking_config_uses_minimum_budget_for_legacy_pro() -> None:
    assert constraint_interpreter._gemini_thinking_config("gemini-2.5-pro") == {
        "thinkingBudget": 128
    }


def _anthropic_success_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"content": [{"type": "text", "text": text}]},
        request=_DUMMY_REQUEST,
    )


def test_anthropic_system_prompt_caches_only_the_static_block(monkeypatch) -> None:
    fake_client = _FakeAsyncClient([_anthropic_success_response('{"ok": true}')])
    monkeypatch.setattr(
        constraint_interpreter.httpx, "AsyncClient", lambda **kwargs: fake_client
    )
    config = AppConfig(provider="anthropic", api_key="test-key", model="claude-sonnet-5")

    result = asyncio.run(request_structured_json(config, "prompt"))

    assert result == '{"ok": true}'
    assert len(fake_client.calls) == 1
    system = fake_client.calls[0]["json"]["system"]
    assert isinstance(system, list) and len(system) == 2
    assert system[0]["text"] == constraint_interpreter.SYSTEM_PROMPT
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in system[1]
    assert system[0]["text"] + system[1]["text"] == _dated_system_prompt(
        constraint_interpreter.SYSTEM_PROMPT
    )
