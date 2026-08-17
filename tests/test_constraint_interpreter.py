import asyncio
import json
import time

import pytest

from backend import constraint_interpreter
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
