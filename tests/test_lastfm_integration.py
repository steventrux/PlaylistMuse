from __future__ import annotations

from fastapi.testclient import TestClient

import backend.main as main_module


def _resolved_track(index: int) -> dict[str, str]:
    return {
        "video_id": f"video-{index}",
        "title": f"Track {index}",
        "artists": f"Artist {index}",
        "album": f"Album {index}",
        "duration": "3:30",
        "thumbnail_url": "",
        "url": f"https://music.youtube.com/watch?v=video-{index}",
        "description": f"Description {index}.",
        "reason": f"Reason {index}.",
    }


def test_seed_lastfm_context_is_isolated_to_one_generation(monkeypatch) -> None:
    seen: dict[str, object] = {}
    lastfm_candidates = [
        {
            "artist": "The Black Crowes",
            "title": "Hard to Handle",
            "description": "Last.fm recommendation.",
            "reason": "Listening-data match.",
        }
    ]

    async def fake_lastfm(artist, track, limit=40, broaden=False):
        seen["lastfm_request"] = (artist, track, limit, broaden)
        return lastfm_candidates

    async def fake_generate(prompt, count, options, *, allow_shortfall=False):
        seen["generation_context"] = list(main_module._SEED_RECOMMENDATIONS.get())
        seen["anchor_context"] = list(main_module._SEED_ANCHORS.get())
        return {
            "name": "Seed Playlist",
            "description": "A seed-based playlist.",
            "prompt": prompt,
            "requested_count": count,
            "resolved_count": count,
            "tracks": [_resolved_track(index) for index in range(1, count + 1)],
            "unresolved": [],
        }

    monkeypatch.setattr(main_module, "similar_track_candidates", fake_lastfm)
    monkeypatch.setattr(main_module, "_generate", fake_generate)

    client = TestClient(main_module.app)
    response = client.post(
        "/api/playlists/generate-from-seed",
        json={
            "seed": {
                "video_id": "selected-seed",
                "title": "Gimme Shelter",
                "artists": "The Rolling Stones",
                "album": "Let It Bleed",
                "duration": "4:31",
                "thumbnail_url": "",
                "url": "https://music.youtube.com/watch?v=selected-seed",
            },
            "track_count": 5,
            "options": {
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
        },
    )

    assert response.status_code == 200
    assert seen["lastfm_request"] == ("The Rolling Stones", "Gimme Shelter", 20, False)
    assert seen["generation_context"] == lastfm_candidates
    assert seen["anchor_context"] == [
        {
            "artist": "The Rolling Stones",
            "title": "Gimme Shelter",
            "kind": "seed",
        }
    ]
    assert main_module._SEED_RECOMMENDATIONS.get() == ()
    assert main_module._SEED_ANCHORS.get() == ()
