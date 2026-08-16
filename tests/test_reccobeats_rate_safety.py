from __future__ import annotations

import asyncio

import httpx
import pytest

from backend import reccobeats_http, reccobeats_popularity
from backend.reccobeats_http import (
    ReccoRateLimited,
    clear_reccobeats_http_state,
    request_json,
)
from backend.reccobeats_popularity import (
    enrich_recommendation_popularity,
    popularity_for_tracks,
    reset_request_popularity_cache,
)


def _reset() -> None:
    clear_reccobeats_http_state()
    reset_request_popularity_cache()


def _client_factory(transport: httpx.MockTransport):
    real_client = httpx.AsyncClient

    class ClientFactory:
        def __call__(self, *args, **kwargs):
            kwargs["transport"] = transport
            return real_client(*args, **kwargs)

    return ClientFactory()


def test_identical_recco_get_is_served_from_shared_cache(monkeypatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"content": [{"id": "one"}]})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await request_json(
                client,
                "/track/search",
                params={"searchText": "Example", "size": 20, "page": 0},
            )
            second = await request_json(
                client,
                "/track/search",
                params={"searchText": "Example", "size": 20, "page": 0},
            )
        return first, second

    monkeypatch.setattr(reccobeats_http, "MIN_REQUEST_INTERVAL_SECONDS", 0.0)
    _reset()
    first, second = asyncio.run(run())

    assert first == second
    assert calls == 1


def test_429_opens_global_circuit_breaker_without_second_network_call(monkeypatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(429, headers={"Retry-After": "60"})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ReccoRateLimited):
                await request_json(client, "/track/search", params={"searchText": "A"})
            with pytest.raises(ReccoRateLimited):
                await request_json(client, "/artist/search", params={"searchText": "B"})

    monkeypatch.setattr(reccobeats_http, "MIN_REQUEST_INTERVAL_SECONDS", 0.0)
    _reset()
    asyncio.run(run())

    assert calls == ["/v1/track/search"]


def test_identity_cache_never_downgrades_known_popularity() -> None:
    _reset()
    high = {"artist": "Same Artist", "title": "Same Song", "reccobeats_id": "high"}
    low = {"artist": "Same Artist", "title": "Same Song", "reccobeats_id": "low"}

    reccobeats_popularity._remember_score(high, 78)
    reccobeats_popularity._remember_score(low, 16)

    assert reccobeats_popularity._cached_score(high) == 78
    assert reccobeats_popularity._cached_score(low) == 78
    assert reccobeats_popularity._apply_cached_scores(
        [{**low, "popularity": 16}]
    )[0]["popularity"] == 78


def test_free_form_popularity_uses_strongest_same_isrc_duplicate(monkeypatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.url.path == "/v1/track/search"
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "id": "low",
                        "trackTitle": "Same Song",
                        "artists": [{"name": "Same Artist"}],
                        "isrc": "IT0000000001",
                        "popularity": 16,
                    },
                    {
                        "id": "high",
                        "trackTitle": "Same Song",
                        "artists": [{"name": "Same Artist"}],
                        "isrc": "IT0000000001",
                        "popularity": 78,
                    },
                ]
            },
        )

    monkeypatch.setattr(reccobeats_http, "MIN_REQUEST_INTERVAL_SECONDS", 0.0)
    _reset()
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        reccobeats_popularity.httpx,
        "AsyncClient",
        _client_factory(transport),
    )
    scores = asyncio.run(
        popularity_for_tracks([{"artist": "Same Artist", "title": "Same Song"}])
    )

    assert scores[("same artist", "same song")] == 78
    assert calls == ["/v1/track/search"]


def test_free_form_popularity_does_not_cross_recording_isrc(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/track/search"
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "id": "primary",
                        "trackTitle": "Same Song",
                        "artists": [{"name": "Same Artist"}],
                        "isrc": "IT0000000001",
                        "popularity": 16,
                    },
                    {
                        "id": "other-recording",
                        "trackTitle": "Same Song",
                        "artists": [{"name": "Same Artist"}],
                        "isrc": "IT0000000002",
                        "popularity": 99,
                    },
                ]
            },
        )

    monkeypatch.setattr(reccobeats_http, "MIN_REQUEST_INTERVAL_SECONDS", 0.0)
    _reset()
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        reccobeats_popularity.httpx,
        "AsyncClient",
        _client_factory(transport),
    )
    scores = asyncio.run(
        popularity_for_tracks([{"artist": "Same Artist", "title": "Same Song"}])
    )

    assert scores[("same artist", "same song")] == 16


def test_track_detail_duplicate_isrc_uses_strongest_score(monkeypatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.url.path == "/v1/track"
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "id": "low",
                        "trackTitle": "Same Song",
                        "artists": [{"name": "Same Artist"}],
                        "isrc": "IT0000000001",
                        "popularity": 16,
                    },
                    {
                        "id": "high",
                        "trackTitle": "Same Song",
                        "artists": [{"name": "Same Artist"}],
                        "isrc": "IT0000000001",
                        "popularity": 78,
                    },
                ]
            },
        )

    monkeypatch.setattr(reccobeats_http, "MIN_REQUEST_INTERVAL_SECONDS", 0.0)
    _reset()
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        reccobeats_popularity.httpx,
        "AsyncClient",
        _client_factory(transport),
    )
    enriched = asyncio.run(
        enrich_recommendation_popularity(
            [
                {
                    "artist": "Same Artist",
                    "title": "Same Song",
                    "source": "reccobeats",
                    "reccobeats_id": "low",
                }
            ],
            preference="popular",
        )
    )

    assert enriched[0]["popularity"] == 78
    assert calls == ["/v1/track"]


def test_free_form_scoring_stops_after_one_global_budget(monkeypatch) -> None:
    calls = 0

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def slow_match(client, artist, title):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return None

    async def run():
        reset_request_popularity_cache()
        return await popularity_for_tracks(
            [
                {"artist": "Budget Artist A", "title": "Budget Song A"},
                {"artist": "Budget Artist B", "title": "Budget Song B"},
                {"artist": "Budget Artist C", "title": "Budget Song C"},
            ]
        )

    monkeypatch.setattr(reccobeats_popularity, "TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(reccobeats_popularity, "_max_exact_search_match", slow_match)
    monkeypatch.setattr(
        reccobeats_popularity.httpx,
        "AsyncClient",
        lambda *args, **kwargs: DummyClient(),
    )
    clear_reccobeats_http_state()

    scores = asyncio.run(run())

    assert scores == {}
    assert calls == 1
