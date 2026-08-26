from __future__ import annotations

import asyncio
import time

import httpx

from backend.reccobeats_features import (
    ReccoBeatsAudioEvidence,
    _clear_cache,
    audio_evidence_for_track,
    audio_evidence_for_tracks,
)


def test_exact_artist_title_match_returns_audio_features_and_is_cached() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/track/search"):
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "id": "track-1",
                            "trackTitle": "Example Song",
                            "artists": [{"name": "Example Artist"}],
                        }
                    ]
                },
            )
        if request.url.path.endswith("/track/track-1/audio-features"):
            return httpx.Response(
                200,
                json={
                    "danceability": 0.81,
                    "energy": 0.72,
                    "valence": 0.66,
                    "tempo": 124.0,
                    "liveness": 0.18,
                    "acousticness": 0.11,
                    "instrumentalness": 0.02,
                    "speechiness": 0.05,
                    "loudness": -5.4,
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    async def run() -> tuple[ReccoBeatsAudioEvidence, ReccoBeatsAudioEvidence]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await audio_evidence_for_track(
                "Example Artist",
                "Example Song",
                client=client,
                now=lambda: 100.0,
            )
            second = await audio_evidence_for_track(
                "Example Artist",
                "Example Song",
                client=client,
                now=lambda: 101.0,
            )
        return first, second

    _clear_cache()
    first, second = asyncio.run(run())

    assert first.match_source == "track_search"
    assert first.features == {
        "danceability": 0.81,
        "energy": 0.72,
        "valence": 0.66,
        "tempo": 124.0,
        "liveness": 0.18,
        "acousticness": 0.11,
        "instrumentalness": 0.02,
        "speechiness": 0.05,
        "loudness": -5.4,
    }
    assert second == first
    assert calls == ["/v1/track/search", "/v1/track/track-1/audio-features"]


def test_wrong_artist_with_same_title_is_never_accepted_and_catalog_fallback_is_strict() -> None:
    requested_searches: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/track/search"):
            requested_searches.append(request.url.params["searchText"])
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "id": "wrong-track",
                            "trackTitle": "Shared Title",
                            "artists": [{"name": "Wrong Artist"}],
                        }
                    ]
                },
            )
        if path.endswith("/artist/search"):
            return httpx.Response(
                200,
                json={"content": [{"id": "artist-1", "name": "Right Artist"}]},
            )
        if path.endswith("/artist/artist-1/track"):
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "id": "right-track",
                            "trackTitle": "Shared Title",
                            "artists": [{"name": "Right Artist"}],
                        }
                    ]
                },
            )
        if path.endswith("/track/right-track/audio-features"):
            return httpx.Response(
                200,
                json={"danceability": 0.73, "energy": 0.84, "tempo": 128.0},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    async def run() -> ReccoBeatsAudioEvidence:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await audio_evidence_for_track(
                "Right Artist",
                "Shared Title",
                client=client,
            )

    _clear_cache()
    evidence = asyncio.run(run())

    assert requested_searches == ["Shared Title", "Right Artist Shared Title"]
    assert evidence.match_source == "artist_catalog"
    assert evidence.features == {
        "danceability": 0.73,
        "energy": 0.84,
        "tempo": 128.0,
    }


def test_title_only_match_without_exact_artist_fails_open() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/track/search"):
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "id": "wrong-track",
                            "trackTitle": "Shared Title",
                            "artists": [{"name": "Wrong Artist"}],
                        }
                    ]
                },
            )
        if path.endswith("/artist/search"):
            return httpx.Response(
                200,
                json={"content": [{"id": "wrong-artist", "name": "Wrong Artist"}]},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    async def run() -> ReccoBeatsAudioEvidence:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await audio_evidence_for_track(
                "Right Artist",
                "Shared Title",
                client=client,
            )

    _clear_cache()
    assert asyncio.run(run()) == ReccoBeatsAudioEvidence()


def test_invalid_feature_values_are_ignored_instead_of_clamped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/track/search"):
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "id": "track-2",
                            "trackTitle": "Odd Data",
                            "artists": [{"name": "Example Artist"}],
                        }
                    ]
                },
            )
        if request.url.path.endswith("/track/track-2/audio-features"):
            return httpx.Response(
                200,
                json={
                    "danceability": 1.2,
                    "energy": -0.1,
                    "valence": 0.4,
                    "tempo": 0,
                    "liveness": "nan",
                    "loudness": -7.0,
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    async def run() -> ReccoBeatsAudioEvidence:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await audio_evidence_for_track(
                "Example Artist",
                "Odd Data",
                client=client,
            )

    _clear_cache()
    evidence = asyncio.run(run())

    assert evidence.features == {"valence": 0.4, "loudness": -7.0}


def test_batch_network_failure_is_neutral(monkeypatch) -> None:
    class BrokenClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(
        "backend.reccobeats_features.httpx.AsyncClient",
        lambda *args, **kwargs: BrokenClient(),
    )
    _clear_cache()

    tracks = [
        {"artist": "Artist A", "title": "Track A"},
        {"artist": "Artist B", "title": "Track B"},
    ]
    assert asyncio.run(audio_evidence_for_tracks(tracks)) == [
        ReccoBeatsAudioEvidence(),
        ReccoBeatsAudioEvidence(),
    ]


def test_batch_budget_preserves_completed_results_and_cancels_slow_work(monkeypatch) -> None:
    fast = ReccoBeatsAudioEvidence(match_source="test", energy=0.8)

    async def fake_evidence(artist, title, *, client=None, now=time.monotonic):
        if title == "Fast":
            return fast
        await asyncio.sleep(0.2)
        return ReccoBeatsAudioEvidence(match_source="too-late", energy=0.9)

    monkeypatch.setattr(
        "backend.reccobeats_features.audio_evidence_for_track",
        fake_evidence,
    )
    monkeypatch.setattr("backend.reccobeats_features.BATCH_TIMEOUT_SECONDS", 0.02)

    started = time.perf_counter()
    results = asyncio.run(
        audio_evidence_for_tracks(
            [
                {"artist": "Artist A", "title": "Fast"},
                {"artist": "Artist B", "title": "Slow"},
            ]
        )
    )
    elapsed = time.perf_counter() - started

    assert results == [fast, ReccoBeatsAudioEvidence()]
    assert elapsed < 0.15


def test_batch_timeout_seconds_override_takes_priority_over_module_default(
    monkeypatch,
) -> None:
    """A caller-supplied timeout_seconds must win even when it's larger than the
    module default -- this is how order_journey_tracks_by_proximity gets a
    realistic budget for a whole playlist without changing the default used by
    smaller callers like creative_intent's refinement fetch."""
    fast = ReccoBeatsAudioEvidence(match_source="test", energy=0.8)

    async def fake_evidence(artist, title, *, client=None, now=time.monotonic):
        if title == "Fast":
            return fast
        await asyncio.sleep(0.05)
        return ReccoBeatsAudioEvidence(match_source="too-late", energy=0.9)

    monkeypatch.setattr(
        "backend.reccobeats_features.audio_evidence_for_track",
        fake_evidence,
    )
    # Module default stays tiny; the explicit override must still let "Slow" finish.
    monkeypatch.setattr("backend.reccobeats_features.BATCH_TIMEOUT_SECONDS", 0.01)

    results = asyncio.run(
        audio_evidence_for_tracks(
            [
                {"artist": "Artist A", "title": "Fast"},
                {"artist": "Artist B", "title": "Slow"},
            ],
            timeout_seconds=1.0,
        )
    )

    assert results == [
        fast,
        ReccoBeatsAudioEvidence(match_source="too-late", energy=0.9),
    ]
