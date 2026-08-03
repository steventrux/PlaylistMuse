from backend import (
    _album_key,
    _diversity_rank,
    _reset_resolution_session,
)
from backend.artist_quota_detection import ArtistMinimumQuota, quota_deficits


def _track(artist: str, title: str, album: str) -> dict[str, str]:
    return {
        "artists": artist,
        "title": title,
        "album": album,
        "video_id": f"{artist}-{title}",
    }


def test_resolved_quota_deficit_reserves_missing_artist_slot():
    quotas = [
        ArtistMinimumQuota("Rolling Stones", 4),
        ArtistMinimumQuota("AC/DC", 3),
    ]
    resolved = [
        *[_track("The Rolling Stones", f"RS {index}", f"RS Album {index}") for index in range(4)],
        _track("AC/DC", "Thunderstruck", "The Razors Edge"),
        _track("AC/DC", "Hard as a Rock", "Ballbreaker"),
        *[_track("Other Artist", f"Other {index}", f"Other Album {index}") for index in range(8)],
    ]

    deficits = quota_deficits(resolved, quotas)
    reserved_slots = sum(item.minimum for item in deficits)

    assert reserved_slots == 1
    assert deficits[0].artist == "AC/DC"
    assert deficits[0].minimum == 1


def test_album_diversity_prefers_less_represented_album():
    existing = [
        _track("Rolling Stones", "One", "Voodoo Lounge"),
        _track("Rolling Stones", "Two", "Voodoo Lounge"),
        _track("AC/DC", "Three", "Ballbreaker"),
    ]
    repeated = _track("Rolling Stones", "Four", "Voodoo Lounge")
    varied = _track("Rolling Stones", "Five", "Bridges to Babylon")

    assert _diversity_rank(varied, existing) < _diversity_rank(repeated, existing)
    assert _album_key(varied) != _album_key(repeated)


def test_new_generation_resets_request_local_selection_state():
    _reset_resolution_session([ArtistMinimumQuota("AC/DC", 3)], 15)
    _reset_resolution_session([], 20)

    # A generic request starts clean and remains eligible for the full requested count.
    from backend import _ACTIVE_RESOLUTION_QUOTAS, _REQUESTED_SESSION_COUNT, _RESOLVED_SESSION_TRACKS

    assert _ACTIVE_RESOLUTION_QUOTAS.get() == ()
    assert _RESOLVED_SESSION_TRACKS.get() == ()
    assert _REQUESTED_SESSION_COUNT.get() == 20
