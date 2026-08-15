from __future__ import annotations

import asyncio

import httpx

import backend.lastfm_discovery as discovery


def test_seed_discovery_prefers_similar_tracks() -> None:
    discovery._clear_cache()
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.params["method"]
        methods.append(method)
        assert method == "track.getsimilar"
        return httpx.Response(
            200,
            json={
                "similartracks": {
                    "track": [
                        {
                            "name": "Don't Stop Me Now",
                            "artist": {"name": "Queen"},
                            "match": "0.94",
                        },
                        {
                            "name": "Dream On",
                            "artist": {"name": "Aerosmith"},
                            "match": "0.81",
                        },
                    ]
                }
            },
        )

    async def run() -> list[dict[str, str]]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await discovery.discover_for_seed(
                "Queen",
                "Bohemian Rhapsody",
                limit=10,
                api_key="test-key",
                client=client,
            )

    signals = asyncio.run(run())

    assert methods == ["track.getsimilar"]
    assert [signal["title"] for signal in signals] == [
        "Don't Stop Me Now",
        "Dream On",
    ]
    assert all(signal["source"] == "lastfm" for signal in signals)
    assert all(signal["lastfm_strategy"] == "similar_track" for signal in signals)
    assert all(signal["anchor_artist"] == "Queen" for signal in signals)
    assert all(signal["anchor_title"] == "Bohemian Rhapsody" for signal in signals)


def test_seed_discovery_falls_back_to_similar_artist_signals() -> None:
    discovery._clear_cache()
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.params["method"]
        methods.append(method)
        if method == "track.getsimilar":
            return httpx.Response(200, json={"similartracks": {"track": []}})
        if method == "artist.getsimilar":
            return httpx.Response(
                200,
                json={
                    "similarartists": {
                        "artist": [
                            {"name": "The Kolors", "match": "0.86"},
                            {"name": "Serena Brancale", "match": "0.78"},
                        ]
                    }
                },
            )
        raise AssertionError(f"Unexpected method: {method}")

    async def run() -> list[dict[str, str]]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await discovery.discover_for_seed(
                "Merk & Kremont",
                "PARTENOPE",
                limit=4,
                api_key="test-key",
                client=client,
            )

    signals = asyncio.run(run())

    assert methods == ["track.getsimilar", "artist.getsimilar"]
    assert len(signals) == 2
    assert {signal["artist"] for signal in signals} == {
        "The Kolors",
        "Serena Brancale",
    }
    assert all(signal["title"] == discovery.ARTIST_SIGNAL_TITLE for signal in signals)
    assert all(signal["source"] == "lastfm" for signal in signals)
    assert all(signal["lastfm_strategy"] == "similar_artist" for signal in signals)
    assert all(signal["anchor_artist"] == "Merk & Kremont" for signal in signals)
    assert all(signal["anchor_title"] == "PARTENOPE" for signal in signals)


def test_seed_discovery_caches_results_and_avoids_a_second_call() -> None:
    discovery._clear_cache()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "similartracks": {
                    "track": [{"name": "Dream On", "artist": {"name": "Aerosmith"}, "match": "0.8"}]
                }
            },
        )

    async def run() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await discovery.discover_for_seed(
                "Queen", "Bohemian Rhapsody", api_key="test-key", client=client, now=lambda: 100.0,
            )
            second = await discovery.discover_for_seed(
                "Queen", "Bohemian Rhapsody", api_key="test-key", client=client, now=lambda: 101.0,
            )
        return first, second

    first, second = asyncio.run(run())

    assert calls == 1
    assert second == first


def test_seed_discovery_does_not_cache_a_lastfm_error_response() -> None:
    discovery._clear_cache()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"error": 11, "message": "Service Offline"})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await discovery.discover_for_seed(
                "Queen", "Bohemian Rhapsody", api_key="test-key", client=client, now=lambda: 100.0,
            )
            await discovery.discover_for_seed(
                "Queen", "Bohemian Rhapsody", api_key="test-key", client=client, now=lambda: 101.0,
            )

    asyncio.run(run())

    # track.getsimilar + artist.getsimilar fallback, per attempt, both failing -> 4 calls total
    assert calls == 4


def test_select_prompt_anchors_deduplicates_and_limits() -> None:
    tracks = [
        {"artist": "Artist A", "title": "Track A"},
        {"artist": "Artist A", "title": "Track A"},
        {"artist": "Artist B", "title": "Track B"},
        {"artist": "Artist C", "title": "Track C"},
        {"artist": "Artist D", "title": "Track D"},
    ]

    assert discovery.select_prompt_anchors(tracks) == [
        {"artist": "Artist A", "title": "Track A"},
        {"artist": "Artist B", "title": "Track B"},
        {"artist": "Artist C", "title": "Track C"},
    ]


def test_prompt_anchor_discovery_is_disabled() -> None:
    anchors = [
        {"artist": "Artist A", "title": "Track A"},
        {"artist": "Artist B", "title": "Track B"},
    ]

    signals = asyncio.run(discovery.discover_from_anchors(anchors, limit=12))

    assert signals == []
