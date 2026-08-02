from __future__ import annotations

import asyncio

import httpx

from backend.lastfm import _clear_cache, similar_track_candidates


def test_lastfm_is_disabled_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("PLAYLISTMUSE_LASTFM_API_KEY", raising=False)
    _clear_cache()
    assert asyncio.run(similar_track_candidates("AC/DC", "Back in Black")) == []


def test_lastfm_parses_deduplicates_and_caches_results() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params["method"] == "track.getsimilar"
        assert request.url.params["artist"] == "AC/DC"
        assert request.url.params["track"] == "Back in Black"
        assert request.url.params["autocorrect"] == "1"
        return httpx.Response(
            200,
            json={
                "similartracks": {
                    "track": [
                        {"name": "Highway to Hell", "artist": {"name": "AC/DC"}},
                        {"name": "Highway to Hell", "artist": {"name": "AC/DC"}},
                        {
                            "name": "You Shook Me All Night Long",
                            "artist": {"name": "AC/DC"},
                        },
                        {"name": "Back in Black", "artist": {"name": "AC/DC"}},
                    ]
                }
            },
        )

    async def run() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await similar_track_candidates(
                "AC/DC",
                "Back in Black",
                api_key="test-key",
                client=client,
                now=lambda: 100.0,
            )
            second = await similar_track_candidates(
                "AC/DC",
                "Back in Black",
                api_key="test-key",
                client=client,
                now=lambda: 101.0,
            )
        return first, second

    _clear_cache()
    first, second = asyncio.run(run())
    assert [item["title"] for item in first] == [
        "Highway to Hell",
        "You Shook Me All Night Long",
    ]
    assert second == first
    assert calls == 1


def test_lastfm_failure_falls_back_to_empty_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": 11, "message": "Service Offline"})

    async def run() -> list[dict[str, str]]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await similar_track_candidates(
                "The Rolling Stones",
                "Gimme Shelter",
                api_key="test-key-2",
                client=client,
            )

    _clear_cache()
    assert asyncio.run(run()) == []


def test_lastfm_api_error_is_not_cached() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={"error": 29, "message": "Rate limit exceeded"},
            )
        return httpx.Response(
            200,
            json={
                "similartracks": {
                    "track": [
                        {
                            "name": "Brown Sugar",
                            "artist": {"name": "The Rolling Stones"},
                        }
                    ]
                }
            },
        )

    async def run() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await similar_track_candidates(
                "The Rolling Stones",
                "Gimme Shelter",
                api_key="rate-limit-key",
                client=client,
                now=lambda: 200.0,
            )
            second = await similar_track_candidates(
                "The Rolling Stones",
                "Gimme Shelter",
                api_key="rate-limit-key",
                client=client,
                now=lambda: 201.0,
            )
        return first, second

    _clear_cache()
    first, second = asyncio.run(run())
    assert first == []
    assert [item["title"] for item in second] == ["Brown Sugar"]
    assert calls == 2
