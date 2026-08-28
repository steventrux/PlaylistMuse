from __future__ import annotations

import json

from fastapi.testclient import TestClient

import backend.main as main_module
from backend.config import AppConfig


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


def test_emit_progress_is_a_noop_without_a_registered_callback() -> None:
    """Every existing caller of _generate() never sets the ContextVar -- must stay silent."""
    main_module._emit_progress("llm_initial")  # must not raise


def test_generate_stream_emits_stage_events_then_result(monkeypatch) -> None:
    async def fake_generate(config, prompt, count, is_seed_generation=False):
        return {
            "title": "Test Playlist",
            "description": "A test playlist.",
            "tracks": [
                {
                    "artist": f"Artist {index}",
                    "title": f"Track {index}",
                    "description": "Description.",
                    "reason": "Reason.",
                }
                for index in range(count)
            ],
        }

    async def fake_resolve(candidates, exclusions):
        return (
            [
                {
                    "video_id": f"video-{item['title']}",
                    "title": item["title"],
                    "artists": item["artist"],
                    "album": "Album",
                    "duration": "3:00",
                    "thumbnail_url": "",
                    "url": "https://music.youtube.com/watch?v=test",
                    "description": item["description"],
                    "reason": item["reason"],
                }
                for item in candidates
            ],
            [],
        )

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: AppConfig(provider="openai", api_key="sk-test", model="model"),
    )
    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)

    client = TestClient(main_module.app)
    response = client.post(
        "/api/playlists/generate/stream",
        json={"prompt": "A test playlist", "track_count": 5},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)

    stage_events = [event for event in events if event["type"] == "stage"]
    assert [event["stage"] for event in stage_events] == [
        "llm_initial",
        "catalogue_resolution_initial",
    ]
    assert stage_events[0]["message"] == main_module.GENERATION_STAGE_MESSAGES["llm_initial"]

    assert events[-1]["type"] == "result"
    assert len(events[-1]["playlist"]["tracks"]) == 5


def test_generate_stream_reports_error_with_last_stage(monkeypatch) -> None:
    call_count = {"n": 0}

    async def fake_generate(config, prompt, count, is_seed_generation=False):
        call_count["n"] += 1
        n = call_count["n"]
        return {
            "title": "Test Playlist",
            "description": "A test playlist.",
            "tracks": [
                {
                    "artist": f"Artist {n}-{index}",
                    "title": f"Track {n}-{index}",
                    "description": "d",
                    "reason": "r",
                }
                for index in range(count)
            ],
        }

    async def fake_resolve(candidates, exclusions):
        return ([], candidates)

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: AppConfig(provider="openai", api_key="sk-test", model="model"),
    )
    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)

    client = TestClient(main_module.app)
    response = client.post(
        "/api/playlists/generate/stream",
        json={"prompt": "A test playlist", "track_count": 5},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)

    assert events[-1]["type"] == "error"
    assert events[-1]["stage"] == "catalogue_resolution_replenishment"
    assert events[-1]["stage_message"] == (
        main_module.GENERATION_STAGE_MESSAGES["catalogue_resolution_replenishment"]
    )
    assert "PlaylistMuse found only" in events[-1]["message"]


def test_generate_from_seed_stream_keeps_seed_first(monkeypatch) -> None:
    async def fake_generate(prompt, count, options, *, allow_shortfall=False):
        return {
            "name": "Fuzz Riffs",
            "description": "Heavy riffs.",
            "prompt": prompt,
            "requested_count": count,
            "resolved_count": count,
            "tracks": [
                {
                    "video_id": f"track-{index}",
                    "title": f"Track {index}",
                    "artists": "Queens of the Stone Age",
                }
                for index in range(count)
            ],
            "unresolved": [],
        }

    monkeypatch.setattr(main_module, "_generate", fake_generate)
    client = TestClient(main_module.app)
    response = client.post(
        "/api/playlists/generate-from-seed/stream",
        json={
            "seed": {
                "video_id": "selected-seed",
                "title": "Woman",
                "artists": "Wolfmother",
            },
            "track_count": 5,
        },
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[-1]["type"] == "result"
    tracks = events[-1]["playlist"]["tracks"]
    assert tracks[0]["video_id"] == "selected-seed"


def test_generate_stream_emits_energy_ordering_stage_for_explicit_request(monkeypatch) -> None:
    async def fake_generate(config, prompt, count, is_seed_generation=False):
        return {
            "title": "Test Playlist",
            "description": "A test playlist.",
            "tracks": [
                {
                    "artist": f"Artist {index}",
                    "title": f"Track {index}",
                    "description": "Description.",
                    "reason": "Reason.",
                }
                for index in range(count)
            ],
        }

    async def fake_resolve(candidates, exclusions):
        return (
            [
                {
                    "video_id": f"video-{item['title']}",
                    "title": item["title"],
                    "artists": item["artist"],
                    "album": "Album",
                    "duration": "3:00",
                    "thumbnail_url": "",
                    "url": "https://music.youtube.com/watch?v=test",
                    "description": item["description"],
                    "reason": item["reason"],
                }
                for item in candidates
            ],
            [],
        )

    async def fake_order_by_energy(tracks, direction, *, chronological_direction=None):
        assert direction == "increasing"
        assert chronological_direction is None
        return list(reversed(tracks))

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: AppConfig(provider="openai", api_key="sk-test", model="model"),
    )
    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)
    monkeypatch.setattr(main_module, "order_tracks_by_energy", fake_order_by_energy)

    client = TestClient(main_module.app)
    response = client.post(
        "/api/playlists/generate/stream",
        json={"prompt": "A rock playlist with increasing energy", "track_count": 5},
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)

    stage_events = [event for event in events if event["type"] == "stage"]
    assert "energy_ordering" in [event["stage"] for event in stage_events]
    energy_stage = next(event for event in stage_events if event["stage"] == "energy_ordering")
    assert energy_stage["message"] == main_module.GENERATION_STAGE_MESSAGES["energy_ordering"]

    result_titles = [track["title"] for track in events[-1]["playlist"]["tracks"]]
    assert result_titles == ["Track 4", "Track 3", "Track 2", "Track 1", "Track 0"]
