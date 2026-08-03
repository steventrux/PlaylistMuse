from backend.playlist_policy import apply_playlist_policy, policy_from_payload


def _confidence(*fields: str) -> dict[str, float]:
    return {field: 0.95 for field in fields}


def test_policy_parses_ratios_counts_and_unverified_fields():
    policy = policy_from_payload(
        {
            "minimum_allowed_artist_ratio": 50,
            "max_tracks_per_artist": 2,
            "lyrics_language": "Italian",
            "soundtrack_title": "Rocky IV",
            "field_confidence": _confidence(
                "minimum_allowed_artist_ratio",
                "max_tracks_per_artist",
                "lyrics_language",
                "soundtrack_title",
            ),
        }
    )

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

    result, issues = apply_playlist_policy(
        draft,
        policy,
        allowed_artists=["Metallica"],
        requested_count=2,
    )

    assert [(track["artist"], track["title"]) for track in result["tracks"]] == [
        ("AC/DC", "Highway to Hell"),
        ("Metallica", "One"),
    ]
    assert issues == []


def test_policy_limits_tracks_per_artist_and_reports_unmet_ratio():
    policy = policy_from_payload(
        {
            "minimum_allowed_artist_ratio": 0.75,
            "max_tracks_per_artist": 1,
            "field_confidence": _confidence(
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

    result, issues = apply_playlist_policy(
        draft,
        policy,
        allowed_artists=["Metallica"],
        requested_count=4,
    )

    assert [track["artist"] for track in result["tracks"]] == ["Metallica", "Megadeth", "Anthrax"]
    assert any("allowed artist minimum unmet" in issue for issue in issues)
    assert any("artist quota is impossible" in issue for issue in issues)


def test_low_confidence_policy_fields_are_not_applied():
    policy = policy_from_payload(
        {
            "max_tracks_per_artist": 1,
            "field_confidence": {"max_tracks_per_artist": 0.4},
        }
    )

    assert policy.max_tracks_per_artist is None
    assert policy.active is False
