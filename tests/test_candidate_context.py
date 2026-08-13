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
