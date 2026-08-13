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


def test_youtube_resolution_reports_artist_mismatch(monkeypatch) -> None:
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
        {
            "exclude_live": True,
            "exclude_covers": True,
            "exclude_remixes": True,
        },
    )

    assert track is None
    assert diagnostic is not None
    assert diagnostic["reason"] == "artist_mismatch"
    assert diagnostic["best_title_score"] >= youtube.MIN_TITLE_SCORE
    assert diagnostic["best_artist_score"] < youtube.MIN_ARTIST_SCORE


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
                    "title": "Old Song",
                    "requested_artist": "Artist A",
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
