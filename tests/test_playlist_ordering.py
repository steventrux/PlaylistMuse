from __future__ import annotations

import asyncio

import pytest

from backend import playlist_ordering as ordering
from backend.metadata_validation import TrackMetadata


def _track(title: str, artist: str) -> dict:
    return {
        "title": title,
        "artists": artist,
        "video_id": f"{artist}-{title}",
    }


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


def test_release_date_ordering_uses_original_release_metadata(monkeypatch) -> None:
    tracks = [
        _track("Middle", "Artist B"),
        _track("Newest", "Artist C"),
        _track("Oldest", "Artist A"),
    ]
    dates = {
        ("Artist A", "Oldest"): "1975-03-01",
        ("Artist B", "Middle"): "1990-01-01",
        ("Artist C", "Newest"): "2001-07-15",
    }

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        release_date = dates[(artist, title)]
        return TrackMetadata(
            artist=artist,
            title=title,
            original_release_date=release_date,
            original_release_year=int(release_date[:4]),
            match_score=0.99,
            confidence="high",
        )

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


def test_explicit_chronology_fails_when_a_release_date_cannot_be_verified(monkeypatch) -> None:
    tracks = [_track("Known", "Artist A"), _track("Unknown", "Artist B")]

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        if title == "Known":
            return TrackMetadata(
                artist=artist,
                title=title,
                original_release_date="1988-01-01",
                original_release_year=1988,
                match_score=0.99,
                confidence="high",
            )
        return TrackMetadata(
            artist=artist,
            title=title,
            match_score=0.20,
            confidence="low",
            warnings=["No MusicBrainz match"],
        )

    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)

    with pytest.raises(ValueError, match="could not verify the original release date"):
        asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))
