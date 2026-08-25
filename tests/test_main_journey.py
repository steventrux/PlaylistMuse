import pytest
from pydantic import ValidationError

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
