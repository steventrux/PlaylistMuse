from backend.playlist_policy import policy_from_payload
from backend.policy_enforcement import apply_track_positions


def _payload(position: str, index=None):
    return {
        "required_tracks": [{"artist": "Closing Artist", "title": "Closing Song"}],
        "track_positions": [
            {
                "artist": "Closing Artist",
                "title": "Closing Song",
                "position": position,
                "index": index,
            }
        ],
        "field_confidence": {
            "required_tracks": 0.99,
            "track_positions": 0.99,
        },
    }


def _tracks():
    return [
        {"artists": "Closing Artist", "title": "Closing Song"},
        {"artists": "Artist B", "title": "Song B"},
        {"artists": "Artist C", "title": "Song C"},
    ]


def test_explicit_last_track_is_applied_without_reordering_the_others():
    policy = policy_from_payload(_payload("last"))
    result = apply_track_positions(_tracks(), policy)
    assert [track["title"] for track in result] == [
        "Song B",
        "Song C",
        "Closing Song",
    ]


def test_explicit_first_and_numbered_positions_are_general():
    first = apply_track_positions(_tracks()[::-1], policy_from_payload(_payload("first")))
    indexed = apply_track_positions(_tracks(), policy_from_payload(_payload("index", 2)))
    assert first[0]["title"] == "Closing Song"
    assert indexed[1]["title"] == "Closing Song"


def test_low_confidence_position_is_not_enforced():
    payload = _payload("last")
    payload["field_confidence"]["track_positions"] = 0.4
    policy = policy_from_payload(payload)
    assert apply_track_positions(_tracks(), policy) == _tracks()
