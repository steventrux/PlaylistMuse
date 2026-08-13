from __future__ import annotations

import asyncio

import backend.youtube as youtube
from backend.metadata_validation import (
    TrackMetadata,
    ValidationResult,
    activate_constraints_from_prompt,
)


class _SearchClient:
    def __init__(self, results):
        self.results = results

    def search(self, query, filter=None, limit=None):
        return list(self.results)


def _resolution_options() -> dict[str, bool]:
    return {
        "exclude_live": True,
        "exclude_covers": True,
        "exclude_remixes": True,
    }


def test_youtube_resolution_reports_artist_mismatch_with_paired_candidate(monkeypatch) -> None:
    monkeypatch.setattr(
        youtube,
        "_read_youtube_cache_entry",
        lambda *args, **kwargs: (False, None, None),
    )
    monkeypatch.setattr(youtube, "_write_youtube_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        youtube,
        "_thread_client",
        lambda: _SearchClient(
            [
                {
                    "videoId": "video-1",
                    "title": "Right Song",
                    "artists": [{"name": "Wrong Artist"}],
                    "album": {"name": "Album"},
                }
            ]
        ),
    )

    track, diagnostic = youtube._resolve_one_with_diagnostic(
        {"artist": "Expected Artist", "title": "Right Song"},
        _resolution_options(),
    )

    assert track is None
    assert diagnostic is not None
    assert diagnostic["reason"] == "artist_mismatch"
    assert diagnostic["best_title_score"] >= youtube.MIN_TITLE_SCORE
    assert diagnostic["best_artist_score"] < youtube.MIN_ARTIST_SCORE
    assert diagnostic["best_pair"]["result_title"] == "Right Song"
    assert diagnostic["best_pair"]["result_artists"] == "Wrong Artist"


def test_youtube_diagnostic_keeps_scores_from_one_concrete_result(monkeypatch) -> None:
    monkeypatch.setattr(
        youtube,
        "_read_youtube_cache_entry",
        lambda *args, **kwargs: (False, None, None),
    )
    monkeypatch.setattr(youtube, "_write_youtube_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        youtube,
        "_thread_client",
        lambda: _SearchClient(
            [
                {
                    "videoId": "title-match",
                    "title": "Exact Song",
                    "artists": [{"name": "Completely Different"}],
                    "album": {"name": "Album A"},
                },
                {
                    "videoId": "artist-match",
                    "title": "Completely Different Song Name",
                    "artists": [{"name": "Exact Artist"}],
                    "album": {"name": "Album B"},
                },
            ]
        ),
    )

    track, diagnostic = youtube._resolve_one_with_diagnostic(
        {"artist": "Exact Artist", "title": "Exact Song"},
        _resolution_options(),
    )

    assert track is None
    assert diagnostic is not None
    pair = diagnostic["best_pair"]
    assert pair["video_id"] in {"title-match", "artist-match"}
    if pair["video_id"] == "title-match":
        assert pair["result_title"] == "Exact Song"
        assert pair["result_artists"] == "Completely Different"
    else:
        assert pair["result_title"] == "Completely Different Song Name"
        assert pair["result_artists"] == "Exact Artist"
    assert pair["combined_score"] == round(
        pair["title_score"] * 0.68 + pair["artist_score"] * 0.32,
        1,
    )


def test_musicbrainz_retries_primary_artist_after_canonical_credit_miss(monkeypatch) -> None:
    activate_constraints_from_prompt("songs released in 2026 only")
    calls: list[str] = []

    monkeypatch.setattr(youtube, "_read_cache", lambda *args, **kwargs: None)

    async def fake_validate(candidate, constraints, client=None):
        artist = candidate["artist"]
        calls.append(artist)
        if artist == "Artist A":
            return ValidationResult(
                status="valid",
                violations=[],
                metadata=TrackMetadata(
                    artist=artist,
                    title=candidate["title"],
                    matched_artist="Artist A",
                    original_release_year=2026,
                    match_score=0.97,
                    confidence="high",
                ),
            )
        return ValidationResult(
            status="unknown",
            violations=[],
            metadata=TrackMetadata(
                artist=artist,
                title=candidate["title"],
                match_score=0.0,
                confidence="low",
                warnings=["No MusicBrainz match"],
            ),
        )

    monkeypatch.setattr(youtube, "validate_candidate", fake_validate)

    accepted, rejected = asyncio.run(
        youtube._metadata_filter(
            [
                {
                    "artist": "Artist A, Guest B",
                    "title": "Song",
                    "requested_artist": "Artist A",
                }
            ]
        )
    )

    assert rejected == []
    assert len(accepted) == 1
    assert calls == ["Artist A, Guest B", "Artist A"]
    metadata = accepted[0]["metadata_validation"]
    assert metadata["original_release_year"] == 2026
    assert metadata["artist"] == "Artist A, Guest B"
    assert "MusicBrainz artist fallback used: Artist A" in metadata["warnings"]


def test_musicbrainz_retries_requested_title_after_featured_canonical_title(monkeypatch) -> None:
    activate_constraints_from_prompt("songs from 2000 to 2026")
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(youtube, "_read_cache", lambda *args, **kwargs: None)

    async def fake_validate(candidate, constraints, client=None):
        artist = candidate["artist"]
        title = candidate["title"]
        calls.append((artist, title))
        if title == "Rolls Royce":
            return ValidationResult(
                status="valid",
                violations=[],
                metadata=TrackMetadata(
                    artist=artist,
                    title=title,
                    matched_artist="Achille Lauro",
                    original_release_year=2019,
                    match_score=0.96,
                    confidence="high",
                ),
            )
        return ValidationResult(
            status="unknown",
            violations=[],
            metadata=TrackMetadata(
                artist=artist,
                title=title,
                match_score=0.0,
                confidence="low",
                warnings=["No MusicBrainz match"],
            ),
        )

    monkeypatch.setattr(youtube, "validate_candidate", fake_validate)

    canonical_title = "Rolls Royce (feat. Boss Doms & Frenetik&Orang3)"
    accepted, rejected = asyncio.run(
        youtube._metadata_filter(
            [
                {
                    "artist": "Achille Lauro",
                    "title": canonical_title,
                    "requested_artist": "Achille Lauro",
                    "requested_title": "Rolls Royce",
                }
            ]
        )
    )

    assert rejected == []
    assert calls[:2] == [
        ("Achille Lauro", canonical_title),
        ("Achille Lauro", "Rolls Royce"),
    ]
    metadata = accepted[0]["metadata_validation"]
    assert metadata["original_release_year"] == 2019
    assert metadata["title"] == canonical_title
    assert "MusicBrainz title fallback used: Rolls Royce" in metadata["warnings"]


def test_title_suffix_cleanup_is_limited_to_feature_credits() -> None:
    assert youtube._strip_feature_suffix("Rolls Royce (feat. Boss Doms)") == "Rolls Royce"
    assert youtube._strip_feature_suffix("Song Title - ft. Guest") == "Song Title"
    assert youtube._strip_feature_suffix("Dance With Me") == "Dance With Me"


def test_musicbrainz_does_not_retry_verified_constraint_violation(monkeypatch) -> None:
    activate_constraints_from_prompt("songs released in 2026 only")
    calls = 0

    monkeypatch.setattr(youtube, "_read_cache", lambda *args, **kwargs: None)

    async def fake_validate(candidate, constraints, client=None):
        nonlocal calls
        calls += 1
        return ValidationResult(
            status="invalid",
            violations=["release year 1997 does not match 2026"],
            metadata=TrackMetadata(
                artist=candidate["artist"],
                title=candidate["title"],
                original_release_year=1997,
                match_score=0.98,
                confidence="high",
            ),
        )

    monkeypatch.setattr(youtube, "validate_candidate", fake_validate)

    accepted, rejected = asyncio.run(
        youtube._metadata_filter(
            [
                {
                    "artist": "Artist A, Guest B",
                    "title": "Old Song (feat. Guest B)",
                    "requested_artist": "Artist A",
                    "requested_title": "Old Song",
                }
            ]
        )
    )

    assert accepted == []
    assert len(rejected) == 1
    assert calls == 1
    assert rejected[0]["metadata_validation"]["violations"] == [
        "release year 1997 does not match 2026"
    ]
