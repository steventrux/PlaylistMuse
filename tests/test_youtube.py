"""Regression tests for YouTube Music catalogue matching."""

from __future__ import annotations

import asyncio
from typing import Any

from backend import youtube


class FakeClient:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = results
        self.calls: list[tuple[str, str | None, int | None]] = []

    def search(
        self,
        query: str,
        *,
        filter: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((query, filter, limit))
        return self.results


def _song(
    video_id: str,
    title: str,
    artist: str,
    *,
    album: str = "Album",
    duration: str = "3:30",
) -> dict[str, Any]:
    return {
        "videoId": video_id,
        "title": title,
        "artists": [{"name": artist}],
        "album": {"name": album},
        "duration": duration,
        "thumbnails": [{"url": "small"}, {"url": "large"}],
    }


def test_track_identity_ignores_case_accents_and_punctuation() -> None:
    assert youtube.track_identity_key("Halo!", "Beyoncé") == youtube.track_identity_key(
        "halo", "beyonce"
    )


def test_exclusion_filters_keep_current_meaning() -> None:
    assert youtube._is_excluded("Song (Live)", live=True, covers=False, remixes=False)
    assert youtube._is_excluded("Song - Radio Edit", live=False, covers=False, remixes=True)
    assert youtube._is_excluded("Song (Karaoke)", live=False, covers=True, remixes=False)
    assert not youtube._is_excluded(
        "Song (Acoustic Version)", live=True, covers=True, remixes=True
    )


def test_collection_detection_rejects_unrequested_compilations() -> None:
    assert youtube._looks_like_collection("Thunderstruck", "AC/DC Greatest Hits")
    assert not youtube._looks_like_collection("Greatest Hits Medley", "Greatest Hits Medley")


def test_title_score_penalizes_noisy_upload_suffixes() -> None:
    clean = youtube._title_score("Thunderstruck", "Thunderstruck")
    noisy = youtube._title_score(
        "Thunderstruck", "Thunderstruck Official Music Video 4K Remastered"
    )
    assert clean > noisy


def test_search_serializes_and_deduplicates_results(monkeypatch) -> None:
    client = FakeClient(
        [
            _song("video-1", "Halo", "Beyoncé", album="I Am... Sasha Fierce"),
            _song("video-2", "Halo!", "Beyonce", album="Duplicate upload"),
            _song("video-1", "Halo", "Beyoncé"),
            {"videoId": "missing-artist", "title": "Incomplete", "artists": []},
        ]
    )
    monkeypatch.setattr(youtube, "_client", lambda: client)

    songs = youtube._search_songs("Beyoncé Halo", 8)

    assert len(songs) == 1
    assert songs[0] == {
        "video_id": "video-1",
        "title": "Halo",
        "artists": "Beyoncé",
        "album": "I Am... Sasha Fierce",
        "duration": "3:30",
        "thumbnail_url": "large",
        "url": "https://music.youtube.com/watch?v=video-1",
    }
    assert client.calls == [("Beyoncé Halo", "songs", 8)]


def test_resolve_one_keeps_best_allowed_song(monkeypatch) -> None:
    client = FakeClient(
        [
            _song("live", "Back in Black (Live)", "AC/DC"),
            _song("wrong", "Back in Black", "The Cover Band"),
            _song("studio", "Back in Black", "AC/DC", album="Back in Black"),
        ]
    )
    monkeypatch.setattr(youtube, "_client", lambda: client)

    result = youtube._resolve_one(
        {
            "artist": "AC/DC",
            "title": "Back in Black",
            "description": "A hard-rock anthem.",
            "reason": "It anchors the playlist.",
        },
        {"exclude_live": True, "exclude_covers": True, "exclude_remixes": True},
    )

    assert result is not None
    assert result["video_id"] == "studio"
    assert result["album"] == "Back in Black"
    assert result["description"] == "A hard-rock anthem."
    assert result["reason"] == "It anchors the playlist."
    assert result["match_score"] >= 65


def test_resolve_one_rejects_low_confidence_result(monkeypatch) -> None:
    monkeypatch.setattr(
        youtube,
        "_client",
        lambda: FakeClient([_song("wrong", "Completely Different", "Another Artist")]),
    )

    result = youtube._resolve_one(
        {"artist": "Beyoncé", "title": "Halo"},
        {"exclude_live": True, "exclude_covers": True, "exclude_remixes": True},
    )

    assert result is None


def test_resolve_candidates_deduplicates_catalogue_matches(monkeypatch) -> None:
    def fake_resolve(candidate: dict[str, str], exclusions: dict[str, bool]):
        del exclusions
        if candidate["title"] == "Missing":
            return None
        return {
            "video_id": "shared-video",
            "title": "Canonical Song",
            "artists": "Canonical Artist",
        }

    monkeypatch.setattr(youtube, "_resolve_one", fake_resolve)

    resolved, unresolved = asyncio.run(
        youtube.resolve_candidates(
            [
                {"artist": "Artist One", "title": "Candidate One"},
                {"artist": "Artist Two", "title": "Candidate Two"},
                {"artist": "Artist Three", "title": "Missing"},
            ],
            {"exclude_live": True, "exclude_covers": True, "exclude_remixes": True},
        )
    )

    assert len(resolved) == 1
    assert resolved[0]["video_id"] == "shared-video"
    assert unresolved == [{"artist": "Artist Three", "title": "Missing"}]
