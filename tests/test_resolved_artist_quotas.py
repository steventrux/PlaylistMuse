from backend import (
    _ACTIVE_ARTIST_QUOTAS,
    _REQUESTED_TRACK_COUNT,
    _RESOLVED_QUOTA_TRACKS,
    _optimized_replenishment_request,
    _resolved_quota_guidance,
)
from backend.artist_quota_detection import ArtistMinimumQuota


def _resolved(artist: str, title: str) -> dict[str, str]:
    return {
        "artists": artist,
        "title": title,
        "video_id": f"{artist}-{title}",
    }


def test_resolved_guidance_reports_independent_artist_deficits():
    _ACTIVE_ARTIST_QUOTAS.set(
        (
            ArtistMinimumQuota("Rolling Stones", 4),
            ArtistMinimumQuota("AC/DC", 3),
        )
    )
    _REQUESTED_TRACK_COUNT.set(15)
    _RESOLVED_QUOTA_TRACKS.set(
        tuple(
            [_resolved("The Rolling Stones", f"RS {index}") for index in range(4)]
            + [_resolved("AC/DC", "Thunderstruck")]
        )
    )

    guidance = _resolved_quota_guidance()

    assert "still need 2 additional resolved tracks by AC/DC" in guidance
    assert "Rolling Stones" not in guidance


def test_replenishment_prompt_includes_catalogue_verified_deficits():
    _ACTIVE_ARTIST_QUOTAS.set(
        (
            ArtistMinimumQuota("Rolling Stones", 4),
            ArtistMinimumQuota("AC/DC", 3),
        )
    )
    _REQUESTED_TRACK_COUNT.set(15)
    _RESOLVED_QUOTA_TRACKS.set(
        tuple(
            [_resolved("The Rolling Stones", f"RS {index}") for index in range(3)]
            + [_resolved("AC-DC", "Thunderstruck")]
        )
    )
    prompt = (
        "The original playlist request is:\n"
        "musica rock anni '90, almeno 4 canzoni devono essere dei Rolling Stones "
        "e 3 canzoni devono essere degli AC/DC\n\n"
        "The playlist still needs 4 resolvable songs. Suggest exactly 8 NEW "
        "replacement candidates."
    )

    optimized, count = _optimized_replenishment_request(prompt, 8)

    assert count == 16
    assert "still need 1 additional resolved tracks by Rolling Stones" in optimized
    assert "still need 2 additional resolved tracks by AC/DC" in optimized
    assert "independent" in optimized
