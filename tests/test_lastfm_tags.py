from __future__ import annotations

import asyncio

import httpx

from backend.lastfm_tags import (
    LastfmTagEvidence,
    _clear_cache,
    tag_evidence_for_tracks,
    track_tag_evidence,
)


def test_track_tags_are_preferred_and_cached() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["method"])
        return httpx.Response(
            200,
            json={
                "toptags": {
                    "tag": [
                        {"name": "dance"},
                        {"name": "pop"},
                        {"name": "dance"},
                        {"name": "party"},
                    ]
                }
            },
        )

    async def run() -> tuple[LastfmTagEvidence, LastfmTagEvidence]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await track_tag_evidence(
                "Example Artist",
                "Example Track",
                api_key="tag-key",
                client=client,
                now=lambda: 100.0,
            )
            second = await track_tag_evidence(
                "Example Artist",
                "Example Track",
                api_key="tag-key",
                client=client,
                now=lambda: 101.0,
            )
        return first, second

    _clear_cache()
    first, second = asyncio.run(run())

    assert first.track_tags == ("dance", "pop", "party")
    assert first.artist_tags == ()
    assert second == first
    assert calls == ["track.gettoptags"]


def test_artist_tags_are_only_a_fallback_when_track_tags_are_absent() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.params["method"]
        calls.append(method)
        if method == "track.gettoptags":
            return httpx.Response(200, json={"toptags": {"tag": []}})
        assert method == "artist.gettoptags"
        return httpx.Response(
            200,
            json={
                "toptags": {
                    "tag": [
                        {"name": "electropop"},
                        {"name": "italian"},
                    ]
                }
            },
        )

    async def run() -> LastfmTagEvidence:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await track_tag_evidence(
                "Example Artist",
                "Obscure Track",
                api_key="fallback-key",
                client=client,
            )

    _clear_cache()
    evidence = asyncio.run(run())

    assert evidence.track_tags == ()
    assert evidence.artist_tags == ("electropop", "italian")
    assert calls == ["track.gettoptags", "artist.gettoptags"]


def test_lastfm_tag_api_failure_fails_open_without_artist_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"error": 11, "message": "Service Offline"})

    async def run() -> LastfmTagEvidence:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await track_tag_evidence(
                "Example Artist",
                "Example Track",
                api_key="offline-key",
                client=client,
            )

    _clear_cache()
    assert asyncio.run(run()) == LastfmTagEvidence()
    assert calls == 1


def test_batch_enrichment_is_disabled_without_configured_key(monkeypatch) -> None:
    monkeypatch.setattr("backend.lastfm_tags.lastfm_api_key", lambda: "")

    tracks = [
        {"artist": "Artist A", "title": "Track A"},
        {"artist": "Artist B", "title": "Track B"},
    ]

    assert asyncio.run(tag_evidence_for_tracks(tracks)) == [
        LastfmTagEvidence(),
        LastfmTagEvidence(),
    ]
