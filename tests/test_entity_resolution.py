import asyncio

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
