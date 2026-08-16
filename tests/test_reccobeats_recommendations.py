from __future__ import annotations

import asyncio

import httpx

from backend.generation_runtime import _reccobeats_replenishment_guidance
from backend.reccobeats_features import (
    _clear_cache,
    recommendation_candidates_from_tracks,
)


def test_recommendations_use_verified_seed_and_return_unique_non_seed_tracks() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/track/search"):
            assert request.url.params["searchText"] == "Anchor Song"
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "id": "seed-1",
                            "trackTitle": "Anchor Song",
                            "artists": [{"name": "Anchor Artist"}],
                        }
                    ]
                },
            )
        if request.url.path.endswith("/track/recommendation"):
            assert request.url.params["seeds"] == "seed-1"
            assert request.url.params["size"] == "5"
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "id": "seed-1",
                            "trackTitle": "Anchor Song",
                            "artists": [{"name": "Anchor Artist"}],
                        },
                        {
                            "id": "rec-1",
                            "trackTitle": "New Song",
                            "artists": [{"name": "New Artist"}],
                        },
                        {
                            "id": "rec-1-duplicate",
                            "trackTitle": "NEW SONG",
                            "artists": [{"name": "NEW ARTIST"}],
                        },
                        {
                            "id": "rec-2",
                            "trackTitle": "Another Song",
                            "artists": [
                                {"name": "Artist A"},
                                {"name": "Artist B"},
                            ],
                        },
                    ]
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    async def run() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await recommendation_candidates_from_tracks(
                [{"artists": "Anchor Artist", "title": "Anchor Song"}],
                limit=5,
                max_anchors=1,
                client=client,
                now=lambda: 100.0,
            )
            second = await recommendation_candidates_from_tracks(
                [{"artists": "Anchor Artist", "title": "Anchor Song"}],
                limit=5,
                max_anchors=1,
                client=client,
                now=lambda: 101.0,
            )
        return first, second

    _clear_cache()
    first, second = asyncio.run(run())

    assert first == [
        {
            "artist": "New Artist",
            "title": "New Song",
            "source": "reccobeats",
            "reccobeats_id": "rec-1",
        },
        {
            "artist": "Artist A, Artist B",
            "title": "Another Song",
            "source": "reccobeats",
            "reccobeats_id": "rec-2",
        },
    ]
    assert second == first
    assert calls == ["/v1/track/search", "/v1/track/recommendation"]


def test_recommendation_discovery_fails_open_when_seed_lookup_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/track/search"):
            return httpx.Response(503)
        raise AssertionError(f"unexpected request: {request.url}")

    async def run() -> list[dict[str, str]]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await recommendation_candidates_from_tracks(
                [{"artist": "Anchor Artist", "title": "Anchor Song"}],
                client=client,
            )

    _clear_cache()
    assert asyncio.run(run()) == []


def test_reccobeats_guidance_keeps_playlist_rules_authoritative() -> None:
    guidance = _reccobeats_replenishment_guidance(
        [{"artist": "Candidate Artist", "title": "Candidate Song"}]
    )

    assert "RECCOBEATS DISCOVERY" in guidance
    assert "Candidate Artist — Candidate Song" in guidance
    assert "not pre-approved selections" in guidance
    assert "every hard constraint" in guidance.casefold()
    assert "forbidden/already-attempted list" in guidance
    assert "Never include a song only because it appears in this pool" in guidance


def test_reccobeats_guidance_is_empty_without_candidates() -> None:
    assert _reccobeats_replenishment_guidance([]) == ""
