import pytest

from backend.playlist_policy import policy_from_payload


@pytest.mark.parametrize(
    ("language", "payload"),
    [
        (
            "it",
            {
                "required_tracks": [{"artist": "AC/DC", "title": "Highway to Hell"}],
                "max_tracks_per_artist": 2,
            },
        ),
        (
            "en",
            {
                "required_tracks": [{"artist": "AC/DC", "title": "Highway to Hell"}],
                "max_tracks_per_artist": 2,
            },
        ),
        (
            "fr",
            {
                "required_tracks": [{"artist": "AC/DC", "title": "Highway to Hell"}],
                "max_tracks_per_artist": 2,
            },
        ),
        (
            "es",
            {
                "required_tracks": [{"artist": "AC/DC", "title": "Highway to Hell"}],
                "max_tracks_per_artist": 2,
            },
        ),
        (
            "de",
            {
                "required_tracks": [{"artist": "AC/DC", "title": "Highway to Hell"}],
                "max_tracks_per_artist": 2,
            },
        ),
        (
            "pt",
            {
                "required_tracks": [{"artist": "AC/DC", "title": "Highway to Hell"}],
                "max_tracks_per_artist": 2,
            },
        ),
        (
            "pl",
            {
                "required_tracks": [{"artist": "AC/DC", "title": "Highway to Hell"}],
                "max_tracks_per_artist": 2,
            },
        ),
        (
            "ja",
            {
                "required_tracks": [{"artist": "坂本龍一", "title": "Merry Christmas Mr. Lawrence"}],
                "max_tracks_per_artist": 2,
            },
        ),
        (
            "ko",
            {
                "required_tracks": [{"artist": "BTS", "title": "Dynamite"}],
                "max_tracks_per_artist": 2,
            },
        ),
        (
            "zh",
            {
                "required_tracks": [{"artist": "周杰倫", "title": "晴天"}],
                "max_tracks_per_artist": 2,
            },
        ),
    ],
)
def test_equivalent_multilingual_payloads_share_policy_contract(language, payload):
    payload["field_confidence"] = {
        "required_tracks": 0.95,
        "max_tracks_per_artist": 0.95,
    }

    policy = policy_from_payload(payload)

    assert language
    assert len(policy.required_tracks) == 1
    assert policy.max_tracks_per_artist == 2
