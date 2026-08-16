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
