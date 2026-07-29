"""Regression tests for strong active MusicBrainz evidence."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from backend.metadata import musicbrainz_active_evidence as evidence
from backend.services import musicbrainz_filter


def _history_item(artist: str, year: int, mbid: str) -> dict[str, Any]:
    return {
        "recording_mbid": mbid,
        "recording_title": "Title",
        "artists": artist,
        "artist_mbids": [],
        "first_release_year": year,
        "search_score": 100.0,
    }


def test_release_container_remix_is_not_strong_active_evidence() -> None:
    match = {
        "recording_title": "With a Little Help From My Friends",
        "recording_disambiguation": None,
        "release_title": "Sgt. Pepper’s Lonely Hearts Club Band",
        "release_group_secondary_types": ["Remix"],
        "version_categories": ["remix"],
        "relationship_version_categories": [],
    }

    assert evidence.strong_version_categories(match) == []


def test_relationship_cover_is_strong_active_evidence() -> None:
    match = {
        "recording_title": "The Sound of Silence",
        "relationship_version_categories": ["cover"],
    }

    assert evidence.strong_version_categories(match) == ["cover"]


def test_van_halen_cover_is_inferred_from_earlier_exact_title_artist() -> None:
    match = {"effective_release_year": 1978, "work_relationships": []}
    history = [
        _history_item("The Kinks", 1964, "kinks"),
        _history_item("Van Halen", 1978, "van-halen"),
    ]

    result = evidence.infer_cover_from_history(
        match,
        title="You Really Got Me",
        artists="Van Halen",
        history=history,
    )

    assert result is not None
    assert result["earlier_artists"] == "The Kinks"
    assert result["year_gap"] == 14
    assert result["work_relationship_present"] is False


def test_beatles_original_is_not_inferred_as_cover() -> None:
    match = {"effective_release_year": 1967, "work_relationships": []}
    history = [
        _history_item("The Beatles", 1967, "beatles"),
        _history_item("Joe Cocker", 1968, "joe-cocker"),
    ]

    result = evidence.infer_cover_from_history(
        match,
        title="With a Little Help From My Friends",
        artists="The Beatles",
        history=history,
    )

    assert result is None


def test_work_link_allows_one_year_cover_gap_for_joe_cocker() -> None:
    match = {
        "effective_release_year": 1984,
        "work_relationships": [{"work_mbid": "work"}],
    }
    history = [
        _history_item("The Beatles", 1967, "beatles"),
        _history_item("Joe Cocker", 1968, "joe-cocker"),
        _history_item("Joe Cocker", 1984, "joe-cocker-compilation"),
    ]

    result = evidence.infer_cover_from_history(
        match,
        title="With a Little Help From My Friends",
        artists="Joe Cocker",
        history=history,
    )

    assert result is not None
    assert result["current_earliest_year"] == 1968
    assert result["earlier_artists"] == "The Beatles"
    assert result["year_gap"] == 1
    assert result["work_relationship_present"] is True


def test_short_title_without_work_is_not_inferred_from_chronology() -> None:
    match = {"effective_release_year": 1996, "work_relationships": []}
    history = [
        _history_item("Earlier Artist", 1980, "earlier"),
        _history_item("Current Artist", 1996, "current"),
    ]

    result = evidence.infer_cover_from_history(
        match,
        title="Same Title",
        artists="Current Artist",
        history=history,
    )

    assert result is None


class FakeClient:
    def __init__(self, match: dict[str, Any]) -> None:
        self.match = match

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback

    async def search_track(
        self,
        title: str,
        artists: str,
        *,
        duration_ms: int | None = None,
        exclusions: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        del title, artists, duration_ms
        assert exclusions == {
            "exclude_live": False,
            "exclude_covers": False,
            "exclude_remixes": False,
        }
        return self.match


def _base_match(title: str) -> dict[str, Any]:
    return {
        "recording_mbid": "recording-mbid",
        "recording_title": title,
        "recording_disambiguation": None,
        "matched": True,
        "lexical_score": 100.0,
        "confidence": 98.0,
        "duration_delta_ms": 0,
        "relationship_version_categories": [],
        "work_relationships": [],
    }


def test_filter_preserves_beatles_when_only_release_is_marked_remix(tmp_path: Path) -> None:
    track = {
        "video_id": "beatles",
        "title": "With a Little Help From My Friends",
        "artists": "The Beatles",
        "duration": "2:46",
    }
    match = {
        **_base_match(track["title"]),
        "version_categories": ["remix"],
        "release_group_secondary_types": ["Remix"],
    }

    async def no_cover(client, received_match, source):
        del client, received_match, source
        return None

    output = tmp_path / "active.ndjson"
    accepted, rejected = asyncio.run(
        musicbrainz_filter.filter_musicbrainz_tracks(
            [track],
            {
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
            client_factory=lambda: FakeClient(match),
            cover_evidence_fn=no_cover,
            output_path=output,
            force=True,
        )
    )

    assert accepted == [track]
    assert rejected == []
    stored = json.loads(output.read_text(encoding="utf-8"))
    item = stored["results"][0]
    assert item["active_version_categories"] == []
    assert item["blocked_categories"] == []


def test_filter_blocks_cover_inferred_from_history(tmp_path: Path) -> None:
    track = {
        "video_id": "van-halen",
        "title": "You Really Got Me",
        "artists": "Van Halen",
        "duration": "2:37",
    }
    match = _base_match(track["title"])

    async def inferred_cover(client, received_match, source):
        del client, received_match, source
        return {
            "basis": "exact_title_earlier_different_artist",
            "earlier_artists": "The Kinks",
            "earlier_year": 1964,
            "current_earliest_year": 1978,
            "year_gap": 14,
        }

    output = tmp_path / "active.ndjson"
    accepted, rejected = asyncio.run(
        musicbrainz_filter.filter_musicbrainz_tracks(
            [track],
            {
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
            client_factory=lambda: FakeClient(match),
            cover_evidence_fn=inferred_cover,
            output_path=output,
            force=True,
        )
    )

    assert accepted == []
    assert rejected == [track]
    stored = json.loads(output.read_text(encoding="utf-8"))
    item = stored["results"][0]
    assert item["active_version_categories"] == ["cover"]
    assert item["blocked_categories"] == ["cover"]
    assert item["musicbrainz"]["active_cover_evidence"]["earlier_artists"] == "The Kinks"
