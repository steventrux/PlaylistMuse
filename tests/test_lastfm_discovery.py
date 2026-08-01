from __future__ import annotations

import asyncio

import httpx

import backend.lastfm_discovery as discovery


def test_seed_discovery_prefers_similar_tracks() -> None:
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

    tracks = asyncio.run(run())

    assert methods == ["track.getsimilar"]
    assert [track["title"] for track in tracks] == ["Don't Stop Me Now", "Dream On"]
    assert all(track["source"] == "lastfm" for track in tracks)
    assert all(track["lastfm_strategy"] == "similar_track" for track in tracks)


def test_seed_discovery_falls_back_to_similar_artists_and_top_tracks() -> None:
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
        if method == "artist.gettoptracks":
            artist = request.url.params["artist"]
            return httpx.Response(
                200,
                json={
                    "toptracks": {
                        "track": [
                            {
                                "name": f"{artist} Top Track 1",
                                "artist": {"name": artist},
                            },
                            {
                                "name": f"{artist} Top Track 2",
                                "artist": {"name": artist},
                            },
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

    tracks = asyncio.run(run())

    assert methods.count("track.getsimilar") == 1
    assert methods.count("artist.getsimilar") == 1
    assert methods.count("artist.gettoptracks") == 2
    assert len(tracks) == 4
    assert {track["artist"] for track in tracks} == {"The Kolors", "Serena Brancale"}
    assert all(track["source"] == "lastfm" for track in tracks)
    assert all(track["lastfm_strategy"] == "similar_artist" for track in tracks)


def test_prompt_discovery_uses_distinct_ai_anchors(monkeypatch) -> None:
    calls: list[tuple[str, str, int]] = []

    monkeypatch.setattr(discovery, "lastfm_api_key", lambda: "saved-key")

    async def fake_discover_for_seed(
        artist,
        title,
        *,
        limit=40,
        api_key=None,
        client=None,
    ):
        calls.append((artist, title, limit))
        return [
            {
                "artist": f"Related to {artist}",
                "title": f"Signal for {title}",
                "source": "lastfm",
                "lastfm_strategy": "similar_track",
                "lastfm_match": "0.8",
            }
        ]

    monkeypatch.setattr(discovery, "discover_for_seed", fake_discover_for_seed)

    anchors = [
        {"artist": "Artist A", "title": "Track A"},
        {"artist": "Artist A", "title": "Track A"},
        {"artist": "Artist B", "title": "Track B"},
        {"artist": "Artist C", "title": "Track C"},
        {"artist": "Artist D", "title": "Track D"},
    ]

    tracks = asyncio.run(discovery.discover_from_anchors(anchors, limit=12))

    assert [(artist, title) for artist, title, _ in calls] == [
        ("Artist A", "Track A"),
        ("Artist B", "Track B"),
        ("Artist C", "Track C"),
    ]
    assert len(tracks) == 3
