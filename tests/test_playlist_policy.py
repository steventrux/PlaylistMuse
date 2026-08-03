from backend.playlist_policy import (
    apply_playlist_policy,
    hard_allowed_artists,
    policy_from_payload,
)


def _confidence(*fields: str) -> dict[str, float]:
    return {field: 0.95 for field in fields}


def test_policy_parses_ratios_counts_and_unverified_fields():
    policy = policy_from_payload(
        {
            "quota_artists": ["Metallica"],
            "minimum_allowed_artist_ratio": 50,
            "max_tracks_per_artist": 2,
            "lyrics_language": "Italian",
            "soundtrack_title": "Rocky IV",
            "field_confidence": _confidence(
                "quota_artists",
                "minimum_allowed_artist_ratio",
                "max_tracks_per_artist",
                "lyrics_language",
                "soundtrack_title",
            ),
        }
    )

    assert policy.quota_artists == ["Metallica"]
    assert policy.minimum_allowed_artist_ratio == 0.5
    assert policy.max_tracks_per_artist == 2
    assert "lyrics_language" in policy.unsupported_verification
    assert "soundtrack_membership" in policy.unsupported_verification


def test_policy_adds_required_and_removes_excluded_tracks():
    policy = policy_from_payload(
        {
            "required_tracks": [{"artist": "AC/DC", "title": "Highway to Hell"}],
            "excluded_tracks": [{"artist": "Metallica", "title": "Enter Sandman"}],
            "field_confidence": _confidence("required_tracks", "excluded_tracks"),
        }
    )
    draft = {
        "title": "Test",
        "description": "Test playlist",
        "tracks": [
            {"artist": "Metallica", "title": "Enter Sandman", "description": "x", "reason": "x"},
            {"artist": "Metallica", "title": "One", "description": "x", "reason": "x"},
        ],
    }

    result, issues = apply_playlist_policy(draft, policy, requested_count=2)

    assert [(track["artist"], track["title"]) for track in result["tracks"]] == [
        ("AC/DC", "Highway to Hell"),
        ("Metallica", "One"),
    ]
    assert issues == []


def test_policy_limits_tracks_per_artist_and_reports_unmet_ratio():
    policy = policy_from_payload(
        {
            "quota_artists": ["Metallica"],
            "minimum_allowed_artist_ratio": 0.75,
            "max_tracks_per_artist": 1,
            "field_confidence": _confidence(
                "quota_artists",
                "minimum_allowed_artist_ratio",
                "max_tracks_per_artist",
            ),
        }
    )
    draft = {
        "title": "Test",
        "description": "Test playlist",
        "tracks": [
            {"artist": "Metallica", "title": "One", "description": "x", "reason": "x"},
            {"artist": "Metallica", "title": "Fuel", "description": "x", "reason": "x"},
            {"artist": "Megadeth", "title": "Peace Sells", "description": "x", "reason": "x"},
            {"artist": "Anthrax", "title": "Madhouse", "description": "x", "reason": "x"},
        ],
    }

    result, issues = apply_playlist_policy(draft, policy, requested_count=4)

    assert [track["artist"] for track in result["tracks"]] == ["Metallica", "Megadeth", "Anthrax"]
    assert any("quota artist minimum unmet" in issue for issue in issues)
    assert any("artist quota is impossible" in issue for issue in issues)


def test_legacy_allowed_artist_quota_is_not_a_hard_filter():
    payload = {
        "allowed_artists": ["The Rolling Stones"],
        "minimum_allowed_artist_ratio": 0.5,
        "field_confidence": _confidence(
            "allowed_artists",
            "minimum_allowed_artist_ratio",
        ),
    }
    prompt = "musica rock anni '90, più della metà delle canzoni deve essere dei Rolling Stones"
    policy = policy_from_payload(payload, prompt=prompt)

    assert policy.quota_artists == ["The Rolling Stones"]
    assert policy.strict_artist_majority is True
    assert hard_allowed_artists(
        ["The Rolling Stones"],
        policy,
        prompt=prompt,
    ) == []


def test_strict_majority_requires_six_of_ten_tracks():
    policy = policy_from_payload(
        {
            "quota_artists": ["The Rolling Stones"],
            "minimum_allowed_artist_ratio": 0.5,
            "field_confidence": _confidence(
                "quota_artists",
                "minimum_allowed_artist_ratio",
            ),
        },
        prompt="più della metà delle canzoni deve essere dei Rolling Stones",
    )
    tracks = [
        {"artist": "The Rolling Stones", "title": f"Stone {index}"}
        for index in range(6)
    ] + [
        {"artist": "Other Artist", "title": f"Other {index}"}
        for index in range(4)
    ]

    _, issues = apply_playlist_policy(
        {"title": "Test", "description": "", "tracks": tracks},
        policy,
        requested_count=10,
    )

    assert not any("quota artist minimum unmet" in issue for issue in issues)


def test_explicit_only_artist_remains_a_hard_filter():
    policy = policy_from_payload(
        {
            "quota_artists": ["Metallica"],
            "minimum_allowed_artist_ratio": 0.8,
            "field_confidence": _confidence(
                "quota_artists",
                "minimum_allowed_artist_ratio",
            ),
        },
        prompt="solo Metallica, almeno otto brani su dieci",
    )

    assert hard_allowed_artists(
        ["Metallica"],
        policy,
        prompt="solo Metallica, almeno otto brani su dieci",
    ) == ["Metallica"]


def test_low_confidence_policy_fields_are_not_applied():
    policy = policy_from_payload(
        {
            "max_tracks_per_artist": 1,
            "field_confidence": {"max_tracks_per_artist": 0.4},
        }
    )

    assert policy.max_tracks_per_artist is None
    assert policy.active is False
