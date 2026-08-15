from __future__ import annotations

import asyncio

import pytest

from backend import playlist_ordering as ordering
from backend.metadata_validation import TrackMetadata, ValidationResult


def _track(title: str, artist: str) -> dict:
    return {
        "title": title,
        "artists": artist,
        "video_id": f"{artist}-{title}",
    }


def _metadata(
    artist: str,
    title: str,
    *,
    year: int | None,
    score: float = 0.99,
) -> TrackMetadata:
    return TrackMetadata(
        artist=artist,
        title=title,
        original_release_date=f"{year}-01-01" if year is not None else None,
        original_release_year=year,
        match_score=score,
        confidence="high" if score >= 0.90 else "low",
    )


def test_structured_chronological_order_requires_trusted_confidence() -> None:
    oldest = {
        "chronological_order": "oldest_first",
        "field_confidence": {"chronological_order": 0.99},
    }
    newest = {
        "chronological_order": "newest_first",
        "field_confidence": {"chronological_order": 0.96},
    }
    uncertain = {
        "chronological_order": "oldest_first",
        "field_confidence": {"chronological_order": 0.40},
        "confidence": "medium",
    }

    assert ordering.chronological_order_from_payload(oldest) == "oldest_first"
    assert ordering.chronological_order_from_payload(newest) == "newest_first"
    assert ordering.chronological_order_from_payload(uncertain) is None


def test_local_fallback_recognizes_common_chronological_requests() -> None:
    assert (
        ordering.chronological_order_from_payload(
            None,
            "Riordina le canzoni dalla più vecchia alla più recente",
        )
        == "oldest_first"
    )
    assert (
        ordering.chronological_order_from_payload(
            None,
            "Ordinale dalla più recente alla più vecchia",
        )
        == "newest_first"
    )
    assert (
        ordering.chronological_order_from_payload(
            None,
            "Make the playlist grow gradually in energy toward the end",
        )
        is None
    )


def test_release_year_ordering_uses_original_release_metadata(monkeypatch) -> None:
    tracks = [
        _track("Middle", "Artist B"),
        _track("Newest", "Artist C"),
        _track("Oldest", "Artist A"),
    ]
    years = {
        ("Artist A", "Oldest"): 1975,
        ("Artist B", "Middle"): 1990,
        ("Artist C", "Newest"): 2001,
    }

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        return _metadata(artist, title, year=years[(artist, title)])

    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)

    oldest_first = asyncio.run(
        ordering.order_tracks_by_release_date(tracks, "oldest_first")
    )
    newest_first = asyncio.run(
        ordering.order_tracks_by_release_date(tracks, "newest_first")
    )

    assert [track["title"] for track in oldest_first] == [
        "Oldest",
        "Middle",
        "Newest",
    ]
    assert [track["title"] for track in newest_first] == [
        "Newest",
        "Middle",
        "Oldest",
    ]


def test_embedded_verified_metadata_avoids_lookup(monkeypatch) -> None:
    tracks = [
        {
            **_track("Later", "Artist B"),
            "metadata_validation": {
                "original_release_date": "1999-02-01",
                "original_release_year": 1999,
                "match_score": 0.97,
                "confidence": "high",
            },
        },
        {
            **_track("Earlier", "Artist A"),
            "metadata_validation": {
                "original_release_date": "1982-06-01",
                "original_release_year": 1982,
                "match_score": 0.96,
                "confidence": "high",
            },
        },
    ]

    async def unexpected_lookup(*args, **kwargs):
        raise AssertionError("embedded verified metadata should avoid a lookup")

    monkeypatch.setattr(ordering, "lookup_track_metadata", unexpected_lookup)

    result = asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))
    assert [track["title"] for track in result] == ["Earlier", "Later"]


def test_live_version_always_uses_underlying_song_original_year(monkeypatch) -> None:
    tracks = [
        {
            **_track("Other Song", "Other Artist"),
            "metadata_validation": {
                "original_release_date": "2010-01-01",
                "original_release_year": 2010,
                "match_score": 0.98,
                "confidence": "high",
            },
        },
        {
            **_track("Eccoti (Live)", "Max Pezzali"),
            "album": "Live Tour 2015",
            "metadata_validation": {
                "original_release_date": "2015-05-01",
                "original_release_year": 2015,
                "match_score": 0.99,
                "confidence": "high",
            },
        },
    ]
    lookups: list[tuple[str, str]] = []

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        lookups.append((artist, title))
        assert (artist, title) == ("Max Pezzali", "Eccoti")
        return _metadata(artist, title, year=2005)

    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)

    result = asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))

    assert lookups == [("Max Pezzali", "Eccoti")]
    assert [track["title"] for track in result] == ["Eccoti (Live)", "Other Song"]
    assert result[0]["video_id"] == "Max Pezzali-Eccoti (Live)"


def test_live_album_marker_uses_original_song_even_without_live_in_title(monkeypatch) -> None:
    tracks = [
        {**_track("Song", "Artist"), "album": "Artist Live at Home"},
        {
            **_track("Later", "Artist B"),
            "metadata_validation": {
                "original_release_year": 2000,
                "match_score": 0.99,
                "confidence": "high",
            },
        },
    ]

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        assert (artist, title) == ("Artist", "Song")
        return _metadata(artist, title, year=1980)

    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)

    result = asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))
    assert [track["title"] for track in result] == ["Song", "Later"]


def test_remaster_compares_exact_and_versionless_years(monkeypatch) -> None:
    tracks = [
        _track("Original Song (2011 Remastered)", "Artist"),
        {
            **_track("Middle Song", "Other"),
            "metadata_validation": {
                "original_release_year": 1990,
                "match_score": 0.99,
                "confidence": "high",
            },
        },
    ]
    lookups: list[str] = []

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        lookups.append(title)
        year = 2011 if "Remastered" in title else 1978
        return _metadata(artist, title, year=year)

    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)

    result = asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))

    assert lookups == ["Original Song (2011 Remastered)", "Original Song"]
    assert [track["title"] for track in result] == [
        "Original Song (2011 Remastered)",
        "Middle Song",
    ]


def test_weak_exact_match_uses_historical_fallback(monkeypatch) -> None:
    tracks = [
        _track("Known Song", "Artist"),
        {
            **_track("Later", "Other"),
            "metadata_validation": {
                "original_release_year": 2002,
                "match_score": 0.99,
                "confidence": "high",
            },
        },
    ]
    fallback_calls: list[tuple[str, str]] = []

    async def weak_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        return _metadata(artist, title, year=None, score=0.20)

    async def fake_validate(candidate, constraints, **kwargs) -> ValidationResult:
        del constraints, kwargs
        fallback_calls.append((candidate["artist"], candidate["title"]))
        metadata = _metadata(candidate["artist"], candidate["title"], year=1984)
        return ValidationResult(status="valid", violations=[], metadata=metadata)

    monkeypatch.setattr(ordering, "lookup_track_metadata", weak_lookup)
    monkeypatch.setattr(ordering, "validate_candidate", fake_validate)

    result = asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))

    assert fallback_calls == [("Artist", "Known Song")]
    assert [track["title"] for track in result] == ["Known Song", "Later"]


def test_year_only_metadata_is_sufficient_and_equal_years_keep_relative_order(monkeypatch) -> None:
    tracks = [
        _track("Same Year A", "Artist A"),
        _track("Newer", "Artist C"),
        _track("Same Year B", "Artist B"),
    ]
    years = {
        "Same Year A": 1995,
        "Same Year B": 1995,
        "Newer": 2000,
    }

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        return TrackMetadata(
            artist=artist,
            title=title,
            original_release_year=years[title],
            original_release_date=None,
            match_score=0.99,
            confidence="high",
        )

    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)

    oldest = asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))
    newest = asyncio.run(ordering.order_tracks_by_release_date(tracks, "newest_first"))

    assert [track["title"] for track in oldest] == [
        "Same Year A",
        "Same Year B",
        "Newer",
    ]
    assert [track["title"] for track in newest] == [
        "Newer",
        "Same Year A",
        "Same Year B",
    ]


def test_explicit_chronology_fails_only_after_fallback_is_exhausted(monkeypatch) -> None:
    tracks = [_track("Known", "Artist A"), _track("Unknown", "Artist B")]
    fallback_titles: list[str] = []

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        if title == "Known":
            return _metadata(artist, title, year=1988)
        return _metadata(artist, title, year=None, score=0.20)

    async def fake_validate(candidate, constraints, **kwargs) -> ValidationResult:
        del constraints, kwargs
        fallback_titles.append(candidate["title"])
        metadata = _metadata(
            candidate["artist"],
            candidate["title"],
            year=None,
            score=0.20,
        )
        return ValidationResult(status="unknown", violations=[], metadata=metadata)

    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)
    monkeypatch.setattr(ordering, "validate_candidate", fake_validate)

    with pytest.raises(ValueError, match="could not verify the original release year"):
        asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))

    assert fallback_titles == ["Unknown"]


def test_strip_version_suffix_recognizes_classic_and_extended_editions() -> None:
    assert ordering._strip_version_suffix("Song (Classic Version)") == "Song"
    assert ordering._strip_version_suffix("Song (Extended Version)") == "Song"
    assert ordering._strip_version_suffix("Song (Anniversary Version)") == "Song"
    assert ordering._strip_version_suffix("Song (Deluxe Version)") == "Song"
    # Already-covered terms must keep working after widening the pattern.
    assert ordering._strip_version_suffix("Song (Remastered)") == "Song"
    assert ordering._strip_version_suffix("Take on Me") == "Take on Me"
