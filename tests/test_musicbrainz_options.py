"""Tests for policy-aware MusicBrainz live, remix and cover handling."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.metadata.musicbrainz_decision import classify_musicbrainz_match
from backend.metadata.musicbrainz_policy import apply_musicbrainz_policy
from backend.schemas import PlaylistOptions
from backend.services.musicbrainz_shadow import run_musicbrainz_shadow
from backend.services.playlist_generation import _schedule_shadow


def _candidate(version_text: str) -> dict[str, Any]:
    return {
        "recording_mbid": "recording",
        "recording_disambiguation": version_text,
        "release_title": "Official release",
        "release_status": "Official",
        "release_group_secondary_types": [],
        "lexical_score": 100.0,
        "duration_score": 100.0,
        "duration_delta_ms": 0,
        "release_quality_score": 100.0,
    }


def test_live_is_blocked_only_when_requested() -> None:
    excluded = apply_musicbrainz_policy(
        _candidate("live at Wembley"),
        {"exclude_live": True, "exclude_covers": False, "exclude_remixes": False},
    )
    allowed = apply_musicbrainz_policy(
        _candidate("live at Wembley"),
        {"exclude_live": False, "exclude_covers": False, "exclude_remixes": False},
    )

    assert excluded["version_categories"] == ["live"]
    assert excluded["policy_excluded_categories"] == ["live"]
    assert excluded["matched"] is False
    assert allowed["policy_excluded_categories"] == []
    assert allowed["version_penalty"] == 0
    assert allowed["matched"] is True


def test_remix_is_blocked_only_when_requested() -> None:
    excluded = apply_musicbrainz_policy(
        _candidate("club remix"),
        {"exclude_live": False, "exclude_covers": False, "exclude_remixes": True},
    )
    allowed = apply_musicbrainz_policy(
        _candidate("club remix"),
        {"exclude_live": False, "exclude_covers": False, "exclude_remixes": False},
    )

    assert excluded["policy_excluded_categories"] == ["remix"]
    assert excluded["matched"] is False
    assert allowed["policy_excluded_categories"] == []
    assert allowed["matched"] is True


def test_cover_is_blocked_only_when_requested() -> None:
    excluded = apply_musicbrainz_policy(
        _candidate("tribute cover"),
        {"exclude_live": False, "exclude_covers": True, "exclude_remixes": False},
    )
    allowed = apply_musicbrainz_policy(
        _candidate("tribute cover"),
        {"exclude_live": False, "exclude_covers": False, "exclude_remixes": False},
    )

    assert excluded["policy_excluded_categories"] == ["cover"]
    assert excluded["matched"] is False
    assert allowed["policy_excluded_categories"] == []
    assert allowed["matched"] is True


def test_decision_reports_the_specific_user_exclusion() -> None:
    match = apply_musicbrainz_policy(
        _candidate("live performance remix"),
        {"exclude_live": True, "exclude_covers": False, "exclude_remixes": True},
    )
    decision = classify_musicbrainz_match(
        match,
        {"exclude_live": True, "exclude_covers": False, "exclude_remixes": True},
    )

    assert decision["decision"] == "ambiguous"
    assert decision["decision_reasons"] == ["excluded_live", "excluded_remix"]


def test_playlist_generation_forwards_options_without_breaking_old_hooks() -> None:
    tracks = [{"title": "Song", "artists": "Artist"}]
    options = PlaylistOptions(
        exclude_live=False,
        exclude_covers=True,
        exclude_remixes=False,
    )
    captured: list[Any] = []

    _schedule_shadow(lambda final, selected: captured.append((final, selected)), tracks, options)
    _schedule_shadow(lambda final: captured.append(final), tracks, options)

    assert captured[0][0] == tracks
    assert captured[0][1] is options
    assert captured[1] == tracks


def test_shadow_records_and_passes_selected_exclusions(tmp_path) -> None:
    captured: list[dict[str, bool]] = []

    class FakeClient:
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
            captured.append(dict(exclusions or {}))
            return apply_musicbrainz_policy(_candidate("live at Wembley"), exclusions)

    options = PlaylistOptions(
        exclude_live=False,
        exclude_covers=True,
        exclude_remixes=True,
    )
    payload = asyncio.run(
        run_musicbrainz_shadow(
            [
                {
                    "video_id": "video",
                    "title": "Song",
                    "artists": "Artist",
                    "duration": "4:00",
                }
            ],
            options=options,
            client_factory=FakeClient,
            output_path=tmp_path / "shadow.ndjson",
            sample_size=1,
        )
    )

    assert captured == [
        {
            "exclude_live": False,
            "exclude_covers": True,
            "exclude_remixes": True,
        }
    ]
    assert payload["exclusions"] == captured[0]
    assert payload["matched_count"] == 1
    assert payload["ambiguous_count"] == 0
