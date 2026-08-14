from __future__ import annotations

import asyncio

from backend import reccobeats_features, reccobeats_http
from backend.reccobeats_features import (
    _clear_cache,
    recommendation_candidates_from_tracks,
)


def test_recco_http_pacing_is_half_a_second() -> None:
    assert reccobeats_http.MIN_REQUEST_INTERVAL_SECONDS == 0.5


def test_recommendation_timeout_excludes_discovery_queue_time(monkeypatch) -> None:
    active_discoveries = 0
    max_active_discoveries = 0

    async def fake_resolve(client, artist: str, title: str):
        nonlocal active_discoveries, max_active_discoveries
        active_discoveries += 1
        max_active_discoveries = max(max_active_discoveries, active_discoveries)
        try:
            await asyncio.sleep(0.08)
            return {
                "id": f"seed-{artist}",
                "trackTitle": title,
                "artists": [{"name": artist}],
            }
        finally:
            active_discoveries -= 1

    async def fake_request_json(client, path: str, *, params=None):
        assert path == "/track/recommendation"
        await asyncio.sleep(0.02)
        seed = str((params or {}).get("seeds", ""))
        suffix = seed.removeprefix("seed-") or "unknown"
        return {
            "content": [
                {
                    "id": f"rec-{suffix}",
                    "trackTitle": f"Recommendation {suffix}",
                    "artists": [{"name": f"Recommended {suffix}"}],
                }
            ]
        }

    monkeypatch.setattr(
        reccobeats_features,
        "RECOMMENDATION_TIMEOUT_SECONDS",
        0.15,
    )
    monkeypatch.setattr(
        reccobeats_features,
        "_resolve_track_candidate",
        fake_resolve,
    )
    monkeypatch.setattr(
        reccobeats_features,
        "_request_json",
        fake_request_json,
    )
    _clear_cache()

    async def run():
        return await asyncio.gather(
            recommendation_candidates_from_tracks(
                [{"artist": "Artist A", "title": "Anchor A"}],
                limit=1,
                max_anchors=1,
            ),
            recommendation_candidates_from_tracks(
                [{"artist": "Artist B", "title": "Anchor B"}],
                limit=1,
                max_anchors=1,
            ),
        )

    first, second = asyncio.run(run())

    assert first and second
    assert first[0]["title"] == "Recommendation Artist A"
    assert second[0]["title"] == "Recommendation Artist B"
    assert max_active_discoveries == 1
