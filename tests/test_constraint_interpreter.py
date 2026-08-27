import asyncio
import json
import time

import pytest

from backend import cache_metrics, constraint_interpreter
from backend.config import AppConfig
from backend.constraint_interpreter import (
    _dated_system_prompt,
    _extract_json,
    interpret_constraints,
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
