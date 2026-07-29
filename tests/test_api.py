"""Regression tests for PlaylistMuse HTTP contracts."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from backend import main


client = TestClient(main.app)


def _resolved_track(
    video_id: str,
    title: str,
    artists: str,
    *,
    description: str = "A concise musical description.",
    reason: str = "It supports the playlist flow.",
) -> dict[str, Any]:
    return {
        "video_id": video_id,
        "title": title,
        "artists": artists,
        "album": "Album",
        "duration": "3:30",
        "thumbnail_url": "https://example.test/cover.jpg",
        "url": f"https://music.youtube.com/watch?v={video_id}",
        "match_score": 98.0,
        "description": description,
        "reason": reason,
    }


def _playlist(prompt: str, tracks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": "Regression Playlist",
        "description": "A playlist used to protect the existing API contract.",
        "prompt": prompt,
        "requested_count": len(tracks),
        "resolved_count": len(tracks),
        "tracks": tracks,
        "unresolved": [],
    }


def test_health_contract() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "application": "PlaylistMuse"}


def test_seed_search_contract(monkeypatch) -> None:
    songs = [_resolved_track("seed-1", "Gimme Shelter", "The Rolling Stones")]

    async def fake_search(query: str, limit: int):
        assert query == "Rolling Stones"
        assert limit == 8
        return songs

    monkeypatch.setattr(main, "search_songs", fake_search)

    response = client.get("/api/seeds/search", params={"q": "Rolling Stones", "limit": 8})

    assert response.status_code == 200
    assert response.json() == {"query": "Rolling Stones", "results": songs}


def test_generate_normalizes_prompt_and_preserves_options(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    tracks = [
        _resolved_track(f"track-{index}", f"Song {index}", f"Artist {index}")
        for index in range(1, 6)
    ]

    async def fake_generate(prompt: str, count: int, options: main.PlaylistOptions):
        captured.update(
            prompt=prompt,
            count=count,
            options=options.model_dump(),
        )
        return _playlist(prompt, tracks)

    monkeypatch.setattr(main, "_generate", fake_generate)

    response = client.post(
        "/api/playlists/generate",
        json={
            "prompt": "  classic   rock   for a night drive  ",
            "track_count": 5,
            "options": {
                "exclude_live": True,
                "exclude_covers": False,
                "exclude_remixes": True,
            },
        },
    )

    assert response.status_code == 200
    assert captured == {
        "prompt": "classic rock for a night drive",
        "count": 5,
        "options": {
            "exclude_live": True,
            "exclude_covers": False,
            "exclude_remixes": True,
        },
    }
    assert response.json()["tracks"] == tracks


def test_generate_maps_public_value_errors_to_bad_request(monkeypatch) -> None:
    async def fake_generate(
        prompt: str,
        count: int,
        options: main.PlaylistOptions,
    ) -> dict[str, Any]:
        del prompt, count, options
        raise ValueError("Only four distinct tracks could be verified.")

    monkeypatch.setattr(main, "_generate", fake_generate)

    response = client.post(
        "/api/playlists/generate",
        json={"prompt": "A narrow request", "track_count": 5},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Only four distinct tracks could be verified."
    }


def test_seed_generation_keeps_seed_first_and_removes_duplicate(monkeypatch) -> None:
    seed = {
        "video_id": "seed-video",
        "title": "Back in Black",
        "artists": "AC/DC",
        "album": "Back in Black",
        "duration": "4:15",
        "thumbnail_url": "https://example.test/seed.jpg",
        "url": "https://music.youtube.com/watch?v=seed-video",
    }
    generated_tracks = [
        _resolved_track(
            "duplicate-upload",
            "Back in Black",
            "AC/DC",
            description="The reference hard-rock track.",
            reason="It defines the playlist's central energy.",
        ),
        _resolved_track("track-2", "Whole Lotta Love", "Led Zeppelin"),
        _resolved_track("track-3", "Walk This Way", "Aerosmith"),
        _resolved_track("track-4", "Kickstart My Heart", "Mötley Crüe"),
        _resolved_track("track-5", "Paradise City", "Guns N' Roses"),
    ]
    captured: dict[str, Any] = {}

    async def fake_generate(prompt: str, count: int, options: main.PlaylistOptions):
        captured.update(prompt=prompt, count=count, options=options.model_dump())
        return _playlist(prompt, generated_tracks)

    monkeypatch.setattr(main, "_generate", fake_generate)

    response = client.post(
        "/api/playlists/generate-from-seed",
        json={"seed": seed, "track_count": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert captured["count"] == 5
    assert "'Back in Black' by AC/DC" in captured["prompt"]
    assert body["tracks"][0]["video_id"] == "seed-video"
    assert body["tracks"][0]["description"] == "The reference hard-rock track."
    assert body["tracks"][0]["reason"] == "It defines the playlist's central energy."
    assert len(body["tracks"]) == 5
    assert sum(track["title"] == "Back in Black" for track in body["tracks"]) == 1
    assert body["seed"] == body["tracks"][0]


def test_replace_track_skips_existing_songs(monkeypatch) -> None:
    async def fake_draft(config: object, prompt: str, count: int):
        del config
        assert count == 6
        assert "Song being replaced: AC/DC — Back in Black" in prompt
        return {
            "title": "Replacement candidates",
            "description": "Candidates",
            "tracks": [],
        }

    async def fake_resolve(candidates: list[dict], exclusions: dict[str, bool]):
        del candidates, exclusions
        return (
            [
                _resolved_track("duplicate", "Back in Black", "AC/DC"),
                _resolved_track("fresh", "Highway Star", "Deep Purple"),
            ],
            [],
        )

    monkeypatch.setattr(main, "load_config", lambda: object())
    monkeypatch.setattr(main, "generate_playlist_draft", fake_draft)
    monkeypatch.setattr(main, "resolve_candidates", fake_resolve)

    response = client.post(
        "/api/playlists/replace-track",
        json={
            "prompt": "Classic hard rock",
            "playlist_name": "High Voltage",
            "playlist_description": "Energetic guitar-driven rock.",
            "current_track": {
                "video_id": "current",
                "title": "Back in Black",
                "artists": "AC/DC",
                "reason": "It provides the central riff.",
            },
            "existing_tracks": [
                {
                    "video_id": "current",
                    "title": "Back in Black",
                    "artists": "AC/DC",
                },
                {
                    "video_id": "other",
                    "title": "Whole Lotta Love",
                    "artists": "Led Zeppelin",
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["track"]["video_id"] == "fresh"
    assert response.json()["track"]["title"] == "Highway Star"
