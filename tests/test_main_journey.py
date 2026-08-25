import asyncio

import pytest
from pydantic import ValidationError

import backend.main as main_module
from backend.main import JourneyGenerateRequest


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
