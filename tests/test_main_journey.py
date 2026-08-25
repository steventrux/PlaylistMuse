import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import backend.main as main_module
from backend.main import JourneyGenerateRequest
from backend.youtube import track_identity_key


def _journey_request(**overrides) -> dict:
    payload = {
        "start": {
            "video_id": "start-vid",
            "title": "Start Song",
            "artists": "Start Artist",
            "album": "",
            "duration": "3:00",
            "thumbnail_url": "",
            "url": "https://music.youtube.com/watch?v=start-vid",
        },
        "end": {
            "video_id": "end-vid",
            "title": "End Song",
            "artists": "End Artist",
            "album": "",
            "duration": "3:00",
            "thumbnail_url": "",
            "url": "https://music.youtube.com/watch?v=end-vid",
        },
        "track_count": 5,
        "options": {
            "exclude_live": True,
            "exclude_covers": True,
            "exclude_remixes": True,
        },
    }
    payload.update(overrides)
    return payload


def test_journey_request_rejects_identical_start_and_end() -> None:
    payload = _journey_request(
        end={
            "video_id": "start-vid-alt",
            "title": "start song",
            "artists": "START ARTIST",
        }
    )
    with pytest.raises(ValidationError):
        JourneyGenerateRequest(**payload)


def test_journey_request_accepts_different_start_and_end() -> None:
    request = JourneyGenerateRequest(**_journey_request())
    assert request.track_count == 5
    assert request.start.title == "Start Song"
    assert request.end.title == "End Song"


def test_generate_from_journey_playlist_pins_anchors_and_merges_evidence(monkeypatch) -> None:
    async def fake_similar(artist, title, *, limit, broaden=False, api_key=None, client=None):
        if artist == "Start Artist":
            return [
                {
                    "artist": "Shared Artist",
                    "title": "Shared Song",
                    "lastfm_strategy": "similar_track",
                }
            ]
        return [
            {
                "artist": "Shared Artist",
                "title": "Shared Song",
                "lastfm_strategy": "similar_track",
            },
            {
                "artist": "End Neighbor",
                "title": "End Neighbor Song",
                "lastfm_strategy": "similar_track",
            },
        ]

    captured_anchors = []

    async def fake_generate(prompt, count, options):
        captured_anchors.append(main_module._SEED_ANCHORS.get())
        assert count == 3
        assert "Start Song" in prompt
        assert "End Song" in prompt
        return {
            "title": "Journey",
            "description": "A path.",
            "tracks": [
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge One",
                    "description": "d",
                    "reason": "r",
                },
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge Two",
                    "description": "d",
                    "reason": "r",
                },
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge Three",
                    "description": "d",
                    "reason": "r",
                },
            ],
        }

    monkeypatch.setattr(main_module, "similar_track_candidates", fake_similar)
    monkeypatch.setattr(main_module, "_generate", fake_generate)

    request = main_module.JourneyGenerateRequest(**_journey_request())
    result = asyncio.run(main_module._generate_from_journey_playlist(request))

    assert result["tracks"][0]["video_id"] == "start-vid"
    assert result["tracks"][-1]["video_id"] == "end-vid"
    assert len(result["tracks"]) == 5
    assert len(captured_anchors[0]) == 2


def test_generate_from_journey_playlist_degrades_gracefully_without_lastfm(monkeypatch) -> None:
    async def fake_similar(artist, title, *, limit, broaden=False, api_key=None, client=None):
        return []

    async def fake_generate(prompt, count, options):
        return {
            "title": "Journey",
            "description": "A path.",
            "tracks": [
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge One",
                    "description": "d",
                    "reason": "r",
                },
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge Two",
                    "description": "d",
                    "reason": "r",
                },
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge Three",
                    "description": "d",
                    "reason": "r",
                },
            ],
        }

    monkeypatch.setattr(main_module, "similar_track_candidates", fake_similar)
    monkeypatch.setattr(main_module, "_generate", fake_generate)

    request = main_module.JourneyGenerateRequest(**_journey_request())
    result = asyncio.run(main_module._generate_from_journey_playlist(request))

    assert len(result["tracks"]) == 5


def _journey_track_payload(video_id: str, title: str, artists: str) -> dict:
    return {
        "video_id": video_id,
        "title": title,
        "artists": artists,
        "album": "",
        "duration": "3:00",
        "thumbnail_url": "",
        "url": f"https://music.youtube.com/watch?v={video_id}",
        "description": "d",
        "reason": "r",
    }


def test_journey_generation_retries_when_either_anchor_is_reproduced(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_generate(prompt, count, options):
        calls.append(prompt)
        assert count == 3
        if len(calls) == 1:
            tracks = [
                _journey_track_payload("alt-end", "End Song", "End Artist"),
                _journey_track_payload("t2", "Bridge Two", "Bridge Artist"),
                _journey_track_payload("t3", "Bridge Three", "Bridge Artist"),
            ]
        else:
            assert "Do not include" in prompt
            tracks = [
                _journey_track_payload("t2", "Bridge Two", "Bridge Artist"),
                _journey_track_payload("t3", "Bridge Three", "Bridge Artist"),
                _journey_track_payload("t4", "Bridge Four", "Bridge Artist"),
            ]
        return {"title": "Journey", "description": "A path.", "tracks": tracks}

    monkeypatch.setattr(main_module, "_generate", fake_generate)
    client = TestClient(main_module.app)
    response = client.post("/api/playlists/generate-from-journey", json=_journey_request())

    assert response.status_code == 200
    tracks = response.json()["tracks"]
    identities = [track_identity_key(t["title"], t["artists"]) for t in tracks]

    assert len(calls) == 2
    assert tracks[0]["video_id"] == "start-vid"
    assert tracks[-1]["video_id"] == "end-vid"
    assert identities.count(track_identity_key("End Song", "End Artist")) == 1
    assert len(identities) == len(set(identities))
    assert len(tracks) == 5


def test_journey_generation_fails_loudly_when_an_anchor_keeps_being_reproduced(monkeypatch) -> None:
    async def fake_generate(prompt, count, options):
        tracks = [
            _journey_track_payload("alt-start", "Start Song", "Start Artist"),
            _journey_track_payload("t2", "Bridge Two", "Bridge Artist"),
            _journey_track_payload("t3", "Bridge Three", "Bridge Artist"),
        ]
        return {"title": "Journey", "description": "A path.", "tracks": tracks}

    monkeypatch.setattr(main_module, "_generate", fake_generate)
    client = TestClient(main_module.app)
    response = client.post("/api/playlists/generate-from-journey", json=_journey_request())

    assert response.status_code == 400
