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
                "anchor_artist": artist,
                "anchor_title": title,
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

    signals = asyncio.run(discovery.discover_from_anchors(anchors, limit=12))

    assert [(artist, title) for artist, title, _ in calls] == [
        ("Artist A", "Track A"),
        ("Artist B", "Track B"),
        ("Artist C", "Track C"),
    ]
    assert len(signals) == 3
    assert [signal["anchor_title"] for signal in signals] == [
        "Track A",
        "Track B",
        "Track C",
    ]
