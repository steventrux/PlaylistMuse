import asyncio
import json

import pytest

from backend import constraint_interpreter
from backend.config import AppConfig
from backend.constraint_interpreter import _extract_json, interpret_constraints


def _config() -> AppConfig:
    return AppConfig(
        provider="custom",
        model="test-model",
        base_url="http://provider.test",
    )


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
