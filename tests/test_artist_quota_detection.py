from backend.artist_quota_detection import (
    ArtistMinimumQuota,
    extract_artist_minimum_quotas,
    quota_counts,
    quota_deficits,
    quota_guidance,
    user_request_text,
)


def test_extracts_independent_italian_artist_minimums():
    prompt = (
        "musica rock anni '90, almeno 4 canzoni devono essere dei Rolling Stones "
        "e 3 canzoni devono essere degli AC/DC"
    )

    quotas = extract_artist_minimum_quotas(prompt)

    assert quotas == [
        ArtistMinimumQuota("Rolling Stones", 4),
        ArtistMinimumQuota("AC/DC", 3),
    ]


def test_internal_generation_prompt_keeps_only_original_request():
    prompt = (
        "The original playlist request is:\n"
        "musica rock anni '90, almeno 4 canzoni devono essere dei Rolling Stones "
        "e 3 canzoni devono essere degli AC/DC\n\n"
        "The playlist still needs 2 resolvable songs."
    )

    request = user_request_text(prompt)

    assert request.endswith("3 canzoni devono essere degli AC/DC")
    assert "still needs" not in request


def test_counts_and_deficits_are_kept_separate_per_artist():
    quotas = [
        ArtistMinimumQuota("Rolling Stones", 4),
        ArtistMinimumQuota("AC/DC", 3),
    ]
    tracks = [
        {"artist": "The Rolling Stones", "title": f"RS {index}"}
        for index in range(4)
    ] + [{"artist": "AC/DC", "title": "Thunderstruck"}]

    assert quota_counts(tracks, quotas) == {
        "Rolling Stones": 4,
        "AC/DC": 1,
    }
    assert quota_deficits(tracks, quotas) == [ArtistMinimumQuota("AC/DC", 2)]


def test_guidance_does_not_merge_artist_minimums():
    guidance = quota_guidance(
        [
            ArtistMinimumQuota("Rolling Stones", 4),
            ArtistMinimumQuota("AC/DC", 3),
        ]
    )

    assert "at least 4 tracks by Rolling Stones" in guidance
    assert "at least 3 tracks by AC/DC" in guidance
    assert "independent mandatory minimums" in guidance
