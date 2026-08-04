from __future__ import annotations

import pytest

from backend.playlist_policy import apply_playlist_policy, policy_from_payload


def _confidence(*fields: str) -> dict[str, float]:
    return {field: 0.95 for field in fields}


def test_required_track_displaces_optional_track_from_same_artist() -> None:
    policy = policy_from_payload(
        {
            "required_tracks": [
                {"artist": "AC/DC", "title": "Highway to Hell"}
            ],
            "max_tracks_per_artist": 2,
            "field_confidence": _confidence(
                "required_tracks",
                "max_tracks_per_artist",
            ),
        }
    )
    draft = {
        "title": "Test",
        "description": "Test",
        "tracks": [
            {"artist": "AC/DC", "title": "Thunderstruck"},
            {"artist": "AC/DC", "title": "Back in Black"},
            {"artist": "AC/DC", "title": "Highway to Hell"},
            {"artist": "Metallica", "title": "One"},
        ],
    }

    result, issues = apply_playlist_policy(
        draft,
        policy,
        requested_count=4,
    )

    acdc_titles = [
        track["title"]
        for track in result["tracks"]
        if track["artist"] == "AC/DC"
    ]
    assert acdc_titles == ["Highway to Hell", "Thunderstruck"]
    assert "Back in Black" not in acdc_titles
    assert "policy filtering left 3 of 4 candidates" in issues


def test_required_tracks_exceeding_artist_limit_are_rejected() -> None:
    policy = policy_from_payload(
        {
            "required_tracks": [
                {"artist": "AC/DC", "title": "Highway to Hell"},
                {"artist": "AC/DC", "title": "Thunderstruck"},
            ],
            "max_tracks_per_artist": 1,
            "field_confidence": _confidence(
                "required_tracks",
                "max_tracks_per_artist",
            ),
        }
    )

    with pytest.raises(
        ValueError,
        match="Required tracks are incompatible with the maximum tracks per artist",
    ):
        apply_playlist_policy(
            {"title": "Test", "description": "Test", "tracks": []},
            policy,
            requested_count=5,
        )
