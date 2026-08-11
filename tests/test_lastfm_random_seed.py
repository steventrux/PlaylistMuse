from __future__ import annotations

import asyncio

import httpx
from fastapi.testclient import TestClient

import backend.lastfm_random_seed as random_seed
import backend.main as main_module
import backend.youtube_routes as youtube_routes


def test_random_seed_candidates_support_track_artist_and_album() -> None:
    track = random_seed._candidate(
        "track",
        {"name": "Dreams", "artist": {"name": "Fleetwood Mac"}},
        "classic rock",
    )
    artist = random_seed._candidate(
        "artist",
        {"name": "Massive Attack"},
        "trip hop",
    )
    album = random_seed._candidate(
        "album",
        {"name": "Blue Train", "artist": {"name": "John Coltrane"}},
        "jazz",
    )

    assert track == {
        "kind": "track",
        "artist": "Fleetwood Mac",
        "title": "Dreams",
        "query": "Fleetwood Mac — Dreams",
        "tag": "classic rock",
        "source": "lastfm",
    }
    assert artist == {
        "kind": "artist",
        "artist": "Massive Attack",
        "query": "Massive Attack",
        "tag": "trip hop",
        "source": "lastfm",
    }
    assert album == {
        "kind": "album",
        "artist": "John Coltrane",
        "album": "Blue Train",
        "query": "John Coltrane — Blue Train",
        "tag": "jazz",
        "source": "lastfm",
    }


def test_random_seed_uses_lastfm_tag_charts(monkeypatch) -> None:
    choices = iter(("track", "rock", 1))

    def choose(values):
        try:
            selected = next(choices)
        except StopIteration:
            return values[0]
        assert selected in values
        return selected

    monkeypatch.setattr(random_seed, "_choice", choose)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["method"] == "tag.gettoptracks"
        assert request.url.params["tag"] == "rock"
        assert request.url.params["page"] == "1"
        return httpx.Response(
            200,
            json={
                "tracks": {
                    "track": [
                        {"name": "Gimme Shelter", "artist": {"name": "The Rolling Stones"}}
                    ]
                }
            },
        )

    async def run() -> dict[str, str] | None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await random_seed.random_seed_suggestion(
                api_key="test-key",
                client=client,
                attempts=1,
            )

    assert asyncio.run(run()) == {
        "kind": "track",
        "artist": "The Rolling Stones",
        "title": "Gimme Shelter",
        "query": "The Rolling Stones — Gimme Shelter",
        "tag": "rock",
        "source": "lastfm",
    }


def test_random_seed_route_requires_lastfm(monkeypatch) -> None:
    monkeypatch.setattr(youtube_routes, "lastfm_api_key", lambda: "")

    response = TestClient(main_module.app).get("/api/lastfm/random-seed")

    assert response.status_code == 409
    assert response.json()["detail"] == "Last.fm is not configured."


def test_random_seed_route_returns_lastfm_suggestion(monkeypatch) -> None:
    suggestion = {
        "kind": "artist",
        "artist": "Nina Simone",
        "query": "Nina Simone",
        "tag": "jazz",
        "source": "lastfm",
    }

    monkeypatch.setattr(youtube_routes, "lastfm_api_key", lambda: "configured-key")

    async def fake_random_seed_suggestion() -> dict[str, str]:
        return suggestion

    monkeypatch.setattr(
        youtube_routes,
        "random_seed_suggestion",
        fake_random_seed_suggestion,
    )

    response = TestClient(main_module.app).get("/api/lastfm/random-seed")

    assert response.status_code == 200
    assert response.json() == suggestion
