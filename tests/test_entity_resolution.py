import asyncio
import time

from backend import entity_resolution
from backend.entity_resolution import canonicalize_interpretation


def test_canonicalization_preserves_payload_when_no_artist_fields():
    payload = {"release_year_from": 1990, "release_year_to": 1999}

    result = asyncio.run(canonicalize_interpretation(payload))

    assert result == payload


def test_canonicalization_uses_cached_artist_entities(monkeypatch):
    async def fake_search(name, client):
        return {
            "input": name,
            "name": "AC/DC",
            "mbid": "66c662b6-6e2f-4930-8610-912e24c63ed1",
            "score": "100",
        }

    monkeypatch.setattr("backend.entity_resolution._search_artist", fake_search)
    payload = {
        "allowed_artists": ["ACDC"],
        "excluded_artists": [],
    }

    result = asyncio.run(canonicalize_interpretation(payload))

    assert result is not None
    assert result["allowed_artists"] == ["AC/DC"]
    assert result["canonical_artist_entities"][0]["mbid"] == "66c662b6-6e2f-4930-8610-912e24c63ed1"


def test_uncertain_artist_resolution_keeps_original_name(monkeypatch):
    async def no_match(name, client):
        return None

    monkeypatch.setattr("backend.entity_resolution._search_artist", no_match)
    payload = {"allowed_artists": ["Phoenix"], "excluded_artists": []}

    result = asyncio.run(canonicalize_interpretation(payload))

    assert result is not None
    assert result["allowed_artists"] == ["Phoenix"]
    assert result["canonical_artist_entities"] == []


def test_write_cache_purges_expired_rows_after_interval(tmp_path, monkeypatch):
    cache_path = tmp_path / "entity_resolution_cache.sqlite3"
    monkeypatch.setattr(entity_resolution, "_cache_path", lambda: cache_path)
    monkeypatch.setattr(entity_resolution, "_last_purge_at", 0.0)

    with entity_resolution._connect() as connection:
        connection.execute(
            "INSERT INTO artist_entity_cache(normalized_name, payload, expires_at) "
            "VALUES (?, ?, ?)",
            ("stale-artist", "{}", time.time() - 10),
        )

    entity_resolution._write_cache(
        "Fresh Artist", {"input": "Fresh Artist", "name": "Fresh Artist", "mbid": "x", "score": "100"}
    )

    with entity_resolution._connect() as connection:
        remaining = {
            row["normalized_name"]
            for row in connection.execute(
                "SELECT normalized_name FROM artist_entity_cache"
            ).fetchall()
        }
    assert "stale-artist" not in remaining
