from backend.artist_quota_detection import ArtistMinimumQuota
from backend.request_constraints import (
    buffered_artist_quotas,
    open_ended_year_range,
)


def test_italian_decade_to_today_becomes_open_ended_range():
    assert open_ended_year_range(
        "un viaggio nella storia del rock, dagli anni 60 ad oggi",
        current_year=2026,
    ) == (1960, 2026)


def test_english_decade_to_today_becomes_open_ended_range():
    assert open_ended_year_range(
        "a journey through rock from the 60s to today",
        current_year=2026,
    ) == (1960, 2026)


def test_four_digit_decade_to_now_becomes_open_ended_range():
    """Regression: "the 1960s" (four-digit form) must be recognized like "the 60s".

    Real bug: "rock blues playlist with increasing energy from the 1960s to now" was
    silently collapsed to a closed 1960-1969 range because the open-ended pattern only
    matched the two-digit shorthand, not the four-digit decade form used here.
    """
    assert open_ended_year_range(
        "rock blues playlist with increasing energy from the 1960s to now",
        current_year=2026,
    ) == (1960, 2026)
    assert open_ended_year_range(
        "Crea una playlist dagli anni 1960 ad oggi",
        current_year=2026,
    ) == (1960, 2026)


def test_now_and_the_present_are_recognized_alongside_today():
    assert open_ended_year_range(
        "rock from the 1960s until today", current_year=2026
    ) == (1960, 2026)
    assert open_ended_year_range(
        "rock from the 1960s through the present", current_year=2026
    ) == (1960, 2026)
    assert open_ended_year_range(
        "Crea una playlist dagli anni 60 ad ora", current_year=2026
    ) == (1960, 2026)


def test_genre_era_ending_is_treated_as_open_ended():
    """A decade/year followed by a genre-era label meaning today's music (e.g.
    "modern jazz") must be treated as open-ended, just like literal "to now" wording.

    Real bug: "drawing mainly from the 1970s through modern jazz" was silently
    collapsed to a closed 1970-1979 range in the deterministic fallback that
    overrides the LLM's own (correct) open-ended interpretation, dropping every
    modern-jazz track the user actually asked for.
    """
    assert open_ended_year_range(
        "Curate a soul jazz and big band playlist drawing mainly from the 1970s "
        "through modern jazz, for an evening walk.",
        current_year=2026,
    ) == (1970, 2026)
    assert open_ended_year_range(
        "rock from the 1960s through contemporary rock", current_year=2026
    ) == (1960, 2026)
    assert open_ended_year_range(
        "pop from 1975 to current pop", current_year=2026
    ) == (1975, 2026)
    assert open_ended_year_range(
        "dagli anni 70 fino al jazz moderno", current_year=2026
    ) == (1970, 2026)


def test_genre_era_ending_is_multilingual():
    """The genre-era open-ended ending must cover every language this project's
    prompt parsing supports (EN/IT/FR/ES/DE), not just EN+IT."""
    assert open_ended_year_range(
        "des années 70 jusqu'au jazz moderne", current_year=2026
    ) == (1970, 2026)
    assert open_ended_year_range(
        "de 1975 jusqu'au jazz contemporain", current_year=2026
    ) == (1975, 2026)
    assert open_ended_year_range(
        "desde los años 70 hasta el jazz moderno", current_year=2026
    ) == (1970, 2026)
    assert open_ended_year_range(
        "desde 1975 hasta el jazz actual", current_year=2026
    ) == (1975, 2026)
    assert open_ended_year_range(
        "aus den 70er Jahren bis zum modernen Jazz", current_year=2026
    ) == (1970, 2026)
    assert open_ended_year_range(
        "von 1975 bis zum modernen Jazz", current_year=2026
    ) == (1975, 2026)
    assert open_ended_year_range(
        "desde 1975 até o jazz moderno", current_year=2026
    ) == (1975, 2026)


def test_exact_year_to_present_is_multilingual():
    prompts = (
        "musica italiana dal 2000 ad oggi",
        "music from 2000 to today",
        "musique de 2000 à aujourd'hui",
        "música desde 2000 hasta hoy",
        "Musik von 2000 bis heute",
        "música desde 2000 até hoje",
    )

    for prompt in prompts:
        assert open_ended_year_range(prompt, current_year=2026) == (2000, 2026)


def test_fixed_year_range_is_not_misread_as_to_present():
    assert open_ended_year_range("music from 2000 to 2010", current_year=2026) is None


def test_plain_decade_does_not_become_open_ended():
    assert open_ended_year_range("musica rock anni 60", current_year=2026) is None


def test_artist_quotas_receive_bounded_resolution_margin():
    quotas = [
        ArtistMinimumQuota("Rolling Stones", 4),
        ArtistMinimumQuota("AC/DC", 3),
    ]

    assert buffered_artist_quotas(quotas, 15) == [
        ArtistMinimumQuota("Rolling Stones", 6),
        ArtistMinimumQuota("AC/DC", 5),
    ]


def test_quota_margin_never_exceeds_playlist_capacity():
    quotas = [
        ArtistMinimumQuota("Artist A", 6),
        ArtistMinimumQuota("Artist B", 4),
    ]

    buffered = buffered_artist_quotas(quotas, 11)

    assert sum(quota.minimum for quota in buffered) == 11
    assert buffered == [
        ArtistMinimumQuota("Artist A", 7),
        ArtistMinimumQuota("Artist B", 4),
    ]
