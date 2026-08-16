from __future__ import annotations

from backend.candidate_context import (
    annotate_resolved_candidate_context,
    filter_resolved_recording_variants_contextual,
)
from backend.recording_variants import RecordingVariantPolicy


def _artist_matches(actual: str, expected: str) -> bool:
    return actual.casefold().strip() == expected.casefold().strip()


def test_requested_identity_and_popularity_survive_catalogue_canonicalization() -> None:
    candidates = [
        {
            "artist": "Colapesce",
            "title": "Musica leggerissima",
            "description": "A bright pop song.",
            "reason": "Fits the brief.",
            "popularity": 44,
        }
    ]
    resolved = [
        {
            "artists": "Colapesce, Dimartino",
            "title": "Musica leggerissima",
            "description": "A bright pop song.",
            "reason": "Fits the brief.",
            "video_id": "track-1",
        }
    ]

    result = annotate_resolved_candidate_context(
        resolved,
        candidates,
        artist_matches=_artist_matches,
    )

    assert result[0]["requested_artist"] == "Colapesce"
    assert result[0]["requested_title"] == "Musica leggerissima"
    assert result[0]["popularity"] == 44


def test_exact_signature_match_skips_the_fuzzy_scan_entirely() -> None:
    """An exact (description, reason) match is an unbeatable 1_000.0 score -- confirm the
    O(candidates) fuzzy fallback (which calls artist_matches) never runs when one exists,
    by making artist_matches raise if it's ever called."""

    def fail_if_called(actual: str, expected: str) -> bool:
        raise AssertionError("fuzzy fallback should not run when an exact match exists")

    candidates = [
        {
            "artist": "Wrong Artist",
            "title": "Wrong Title",
            "description": "The one true description.",
            "reason": "The one true reason.",
            "popularity": 10,
        },
    ]
    resolved = [
        {
            "artists": "Whoever Actually Resolved",
            "title": "Whatever Title",
            "description": "The one true description.",
            "reason": "The one true reason.",
            "video_id": "track-1",
        }
    ]

    result = annotate_resolved_candidate_context(
        resolved, candidates, artist_matches=fail_if_called
    )

    assert result[0]["requested_artist"] == "Wrong Artist"
    assert result[0]["popularity"] == 10


def test_fuzzy_fallback_still_matches_without_an_exact_signature() -> None:
    candidates = [
        {
            "artist": "Colapesce",
            "title": "Musica Leggerissima",
            "description": "Different description text.",
            "reason": "Different reason text.",
            "popularity": 44,
        }
    ]
    resolved = [
        {
            "artists": "Colapesce",
            "title": "Musica leggerissima",
            "description": "Canonical catalogue description.",
            "reason": "Canonical catalogue reason.",
            "video_id": "track-1",
        }
    ]

    result = annotate_resolved_candidate_context(
        resolved, candidates, artist_matches=_artist_matches
    )

    assert result[0]["requested_artist"] == "Colapesce"
    assert result[0]["popularity"] == 44


def test_song_title_marker_is_not_mistaken_for_cover_version() -> None:
    track = {
        "artists": "Boomdabash, Alessandra Amoroso",
        "title": "Karaoke",
        "album": "Studio Album",
        "requested_artist": "Boomdabash",
        "requested_title": "Karaoke",
        "video_id": "original-song",
    }
    policy = RecordingVariantPolicy(excluded=frozenset({"cover"}))

    accepted, rejected = filter_resolved_recording_variants_contextual([track], policy)

    assert accepted == [track]
    assert rejected == []


def test_added_cover_marker_is_still_rejected() -> None:
    track = {
        "artists": "Test Artist",
        "title": "Party Song (Karaoke Version)",
        "album": "Studio Album",
        "requested_artist": "Test Artist",
        "requested_title": "Party Song",
        "video_id": "alternate-version",
    }
    policy = RecordingVariantPolicy(excluded=frozenset({"cover"}))

    accepted, rejected = filter_resolved_recording_variants_contextual([track], policy)

    assert accepted == []
    assert rejected[0]["unresolved_reason"] == "recording_variant_validation"
