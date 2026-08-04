from __future__ import annotations

from types import SimpleNamespace

import backend
from backend import generation_runtime, llm
from backend.artist_quota_detection import (
    ArtistMinimumQuota,
    artist_matches,
    extract_artist_minimum_quotas,
    quota_deficits,
)
from backend.metadata_runtime import metadata_lookup_limit
from backend.playlist_policy import apply_playlist_policy, policy_from_payload
from backend.policy_enforcement import (
    _ACTIVE_POLICY,
    _POLICY_BASE_TRACKS,
    _REPLACEMENT_FINAL_COUNT,
    _REPLACEMENT_MODE,
    replacement_candidate_valid,
)
from backend.prompt_validation import _local_temporal_assessment
from backend.selection_guard import guarded_select_resolved_tracks


def _confidence(*fields: str) -> dict[str, float]:
    return {field: 0.95 for field in fields}


def _track(artist: str, title: str, album: str = "Album") -> dict[str, str]:
    return {
        "artists": artist,
        "title": title,
        "album": album,
        "video_id": f"{artist}-{title}",
    }


def _youtube() -> SimpleNamespace:
    return SimpleNamespace(
        track_identity_key=lambda title, artists: (
            f"{artists.casefold()}::{title.casefold()}"
        )
    )


def test_multiple_decades_are_treated_as_a_valid_union() -> None:
    assert _local_temporal_assessment("rock degli anni '80 e degli anni '90") is None
    assert _local_temporal_assessment("rock from the 1980s and 1990s") is None


def test_required_track_is_kept_inside_requested_cutoff() -> None:
    policy = policy_from_payload(
        {
            "required_tracks": [
                {"artist": "AC/DC", "title": "Highway to Hell"}
            ],
            "field_confidence": _confidence("required_tracks"),
        }
    )
    draft = {
        "title": "Test",
        "description": "Test",
        "tracks": [
            {"artist": "Artist A", "title": "One"},
            {"artist": "Artist B", "title": "Two"},
            {"artist": "AC/DC", "title": "Highway to Hell"},
        ],
    }

    result, _ = apply_playlist_policy(draft, policy, requested_count=2)

    assert result["tracks"][0]["artist"] == "AC/DC"
    assert result["tracks"][0]["title"] == "Highway to Hell"


def test_numeric_quotas_accept_comma_and_semicolon_separators() -> None:
    comma = extract_artist_minimum_quotas(
        "4 canzoni dei Rolling Stones, 3 canzoni degli AC/DC"
    )
    semicolon = extract_artist_minimum_quotas(
        "4 canzoni dei Rolling Stones; 3 canzoni degli AC/DC"
    )

    assert [(item.artist, item.minimum) for item in comma] == [
        ("Rolling Stones", 4),
        ("AC/DC", 3),
    ]
    assert [(item.artist, item.minimum) for item in semicolon] == [
        ("Rolling Stones", 4),
        ("AC/DC", 3),
    ]


def test_quota_selection_never_records_more_tracks_than_capacity() -> None:
    generation_runtime._ACTIVE_RESOLUTION_QUOTAS.set(
        (ArtistMinimumQuota("AC/DC", 1),)
    )
    generation_runtime._REQUESTED_SESSION_COUNT.set(2)
    generation_runtime._RESOLVED_SESSION_TRACKS.set(
        (_track("Other Artist", "Existing"),)
    )
    _ACTIVE_POLICY.set(None)
    _POLICY_BASE_TRACKS.set(())
    _REPLACEMENT_MODE.set(False)
    _REPLACEMENT_FINAL_COUNT.set(0)

    selected = guarded_select_resolved_tracks(
        [
            _track("AC/DC", "One"),
            _track("AC/DC", "Two"),
            _track("AC/DC", "Three"),
        ],
        youtube=_youtube(),
        artist_matches=artist_matches,
        quota_deficits=quota_deficits,
    )

    assert len(selected) == 1
    assert len(generation_runtime._RESOLVED_SESSION_TRACKS.get()) == 2


def test_combined_required_track_and_quota_reserve_separate_slots() -> None:
    policy = policy_from_payload(
        {
            "required_tracks": [
                {"artist": "AC/DC", "title": "Highway to Hell"}
            ],
            "field_confidence": _confidence("required_tracks"),
        }
    )
    _ACTIVE_POLICY.set(policy)
    _POLICY_BASE_TRACKS.set(())
    _REPLACEMENT_MODE.set(False)
    _REPLACEMENT_FINAL_COUNT.set(0)
    generation_runtime._ACTIVE_RESOLUTION_QUOTAS.set(
        (ArtistMinimumQuota("Metallica", 1),)
    )
    generation_runtime._REQUESTED_SESSION_COUNT.set(4)
    generation_runtime._RESOLVED_SESSION_TRACKS.set(
        (_track("Existing Artist", "Existing"),)
    )

    selected = guarded_select_resolved_tracks(
        [
            _track("General Artist", "General One"),
            _track("Another Artist", "General Two"),
        ],
        youtube=_youtube(),
        artist_matches=artist_matches,
        quota_deficits=quota_deficits,
    )

    assert len(selected) == 1
    assert len(generation_runtime._RESOLVED_SESSION_TRACKS.get()) == 2


def test_replacement_candidate_cannot_break_artist_maximum() -> None:
    policy = policy_from_payload(
        {
            "max_tracks_per_artist": 2,
            "field_confidence": _confidence("max_tracks_per_artist"),
        }
    )
    base = [
        _track("Metallica", "One"),
        _track("Metallica", "Fuel"),
        _track("Megadeth", "Peace Sells"),
    ]

    assert not replacement_candidate_valid(
        _track("Metallica", "Battery"),
        base,
        policy,
        playlist_size=4,
    )
    assert replacement_candidate_valid(
        _track("Anthrax", "Madhouse"),
        base,
        policy,
        playlist_size=4,
    )


def test_metadata_validation_has_no_implicit_twelve_lookup_ceiling(monkeypatch) -> None:
    monkeypatch.delenv("METADATA_VALIDATION_MAX_LOOKUPS", raising=False)
    assert metadata_lookup_limit(100) == 100

    monkeypatch.setenv("METADATA_VALIDATION_MAX_LOOKUPS", "12")
    assert metadata_lookup_limit(100) == 12


def test_provider_request_errors_are_sanitized() -> None:
    error = llm.ProviderRequestError(
        "Compatible provider",
        200,
        "request failed at https://example.test/path?key=secret sk-abcdefghijklmnop",
    )

    message = llm.safe_error_message(error)

    assert "https://" not in message
    assert "secret" not in message
    assert "sk-abcdefghijklmnop" not in message


def test_runtime_guards_are_installed_on_backend_import() -> None:
    from backend import constraint_relationships, entity_resolution, metadata_validation

    assert getattr(
        llm.generate_playlist_draft,
        "_playlistmuse_policy_persistence_wrapper",
        False,
    )
    assert metadata_validation._rate_limited_get.__module__ == "backend.metadata_runtime"
    assert entity_resolution._search_artist.__module__ == "backend.metadata_runtime"
    assert (
        constraint_relationships._verify_album_artist_pair.__module__
        == "backend.metadata_runtime"
    )
    assert backend._select_resolved_tracks is guarded_select_resolved_tracks
