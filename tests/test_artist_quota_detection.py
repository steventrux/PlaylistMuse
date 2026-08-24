from backend.artist_quota_detection import (
    ArtistMinimumQuota,
    artist_matches,
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


def test_extracts_three_consecutive_artist_minimums():
    prompt = (
        "almeno 4 brani dei Rolling Stones e 3 brani degli AC/DC "
        "e 2 brani dei Metallica"
    )

    assert extract_artist_minimum_quotas(prompt) == [
        ArtistMinimumQuota("Rolling Stones", 4),
        ArtistMinimumQuota("AC/DC", 3),
        ArtistMinimumQuota("Metallica", 2),
    ]


def test_extracts_consecutive_english_artist_minimums():
    prompt = "at least 4 tracks by Queen and 3 tracks by David Bowie"

    assert extract_artist_minimum_quotas(prompt) == [
        ArtistMinimumQuota("Queen", 4),
        ArtistMinimumQuota("David Bowie", 3),
    ]


def test_second_quota_with_elided_track_word_is_still_independent():
    """Regression: a real generation's second clause dropped "songs" ("...and 2 by the
    zz top" instead of "...and 2 songs by the zz top"), so the whole tail was swallowed
    into the first artist's name -- "the rolling stones and 2 by the zz top" -- instead
    of producing two separate quotas. The system then searched for tracks by a nonexistent
    artist with that literal name and failed to fill the playlist.
    """
    prompt = "6 songs by the rolling stones and 2 by the zz top"

    assert extract_artist_minimum_quotas(prompt) == [
        ArtistMinimumQuota("the rolling stones", 6),
        ArtistMinimumQuota("the zz top", 2),
    ]


def test_second_quota_with_elided_track_word_is_independent_in_italian():
    prompt = "almeno 6 canzoni dei rolling stones e 2 degli zz top"

    assert extract_artist_minimum_quotas(prompt) == [
        ArtistMinimumQuota("rolling stones", 6),
        ArtistMinimumQuota("zz top", 2),
    ]


def test_extracts_consecutive_french_artist_minimums():
    assert extract_artist_minimum_quotas(
        "au moins 4 titres de Queen et 3 titres de David Bowie"
    ) == [
        ArtistMinimumQuota("Queen", 4),
        ArtistMinimumQuota("David Bowie", 3),
    ]

    # Elided second track-word noun, same as the English/Italian regression above.
    assert extract_artist_minimum_quotas(
        "playlist avec au moins 6 chansons de Queen et 3 de David Bowie"
    ) == [
        ArtistMinimumQuota("Queen", 6),
        ArtistMinimumQuota("David Bowie", 3),
    ]


def test_extracts_consecutive_spanish_artist_minimums():
    assert extract_artist_minimum_quotas(
        "al menos 4 temas de Queen y 3 temas de David Bowie"
    ) == [
        ArtistMinimumQuota("Queen", 4),
        ArtistMinimumQuota("David Bowie", 3),
    ]

    assert extract_artist_minimum_quotas(
        "playlist con al menos 6 canciones de Queen y 3 de David Bowie"
    ) == [
        ArtistMinimumQuota("Queen", 6),
        ArtistMinimumQuota("David Bowie", 3),
    ]


def test_extracts_consecutive_german_artist_minimums():
    assert extract_artist_minimum_quotas(
        "mindestens 4 Titel von Queen und 3 Titel von David Bowie"
    ) == [
        ArtistMinimumQuota("Queen", 4),
        ArtistMinimumQuota("David Bowie", 3),
    ]

    # "Liedern" is the dative plural of "Lieder" ("mit ... Liedern"), the grammatically
    # natural form after "mit" -- the track-word pattern must accept the inflected form,
    # not just the bare nominative "Lieder".
    assert extract_artist_minimum_quotas(
        "Playlist mit mindestens 6 Liedern von Queen und 3 von David Bowie"
    ) == [
        ArtistMinimumQuota("Queen", 6),
        ArtistMinimumQuota("David Bowie", 3),
    ]


def test_artist_spelling_variants_are_deduplicated():
    prompt = (
        "almeno 3 canzoni devono essere degli AC/DC e "
        "2 canzoni devono essere degli AC-DC"
    )

    assert extract_artist_minimum_quotas(prompt) == [
        ArtistMinimumQuota("AC/DC", 3)
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


def test_artist_matching_handles_punctuation_accents_articles_and_collaborations():
    assert artist_matches("AC-DC", "AC/DC")
    assert artist_matches("Maneskin", "Måneskin")
    assert artist_matches("P!nk feat. Nate Ruess", "P!nk")
    assert artist_matches("Earth, Wind & Fire", "Earth Wind Fire")
    assert artist_matches("The Beatles", "Beatles")
    assert artist_matches("The Rolling Stones", "Rolling Stones")


def test_artist_matching_avoids_substring_false_positives():
    assert not artist_matches("U2 Tribute Band", "U2")
    assert not artist_matches("Yes Sir Boss", "Yes")
    assert not artist_matches("Beatles Tribute", "Beatles")


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
