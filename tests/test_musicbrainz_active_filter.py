"""Tests for the opt-in active MusicBrainz exclusion validation layer."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from backend.catalogs import youtube_music
from backend.services import musicbrainz_filter


def _track() -> dict[str, Any]:
    return {
        "video_id": "video-cover",
        "title": "The Sound of Silence",
        "artists": "Disturbed",
        "duration": "4:09",
        "description": "A resolved YouTube Music track.",
        "reason": "It fits the playlist.",
    }


class FakeClient:
    def __init__(self, responses: list[Any], received: list[dict[str, bool]]) -> None:
        self.responses = list(responses)
        self.received = received

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
    ) -> dict[str, Any] | None:
        assert title == "The Sound of Silence"
        assert artists == "Disturbed"
        assert duration_ms == 249000
        self.received.append(dict(exclusions or {}))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _cover_match() -> dict[str, Any]:
    return {
        "recording_mbid": "disturbed-cover-mbid",
        "recording_title": "The Sound of Silence",
        "matched": True,
        "lexical_score": 100.0,
        "duration_delta_ms": 0,
        "version_categories": ["cover"],
        "policy_excluded_categories": [],
        "active_exclusions": {
            "exclude_live": False,
            "exclude_covers": False,
            "exclude_remixes": False,
        },
    }


def test_active_filter_disabled_preserves_tracks_without_creating_client() -> None:
    called = False

    def client_factory():
        nonlocal called
        called = True
        raise AssertionError("client must not be created")

    accepted, rejected = asyncio.run(
        musicbrainz_filter.filter_musicbrainz_tracks(
            [_track()],
            {
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
            client_factory=client_factory,
            force=False,
        )
    )

    assert accepted == [_track()]
    assert rejected == []
    assert called is False


def test_cover_is_blocked_when_selector_is_enabled(tmp_path: Path) -> None:
    received: list[dict[str, bool]] = []
    output = tmp_path / "active.ndjson"

    accepted, rejected = asyncio.run(
        musicbrainz_filter.filter_musicbrainz_tracks(
            [_track()],
            {
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
            client_factory=lambda: FakeClient([_cover_match()], received),
            output_path=output,
            force=True,
        )
    )

    assert accepted == []
    assert rejected == [_track()]
    assert received == [
        {
            "exclude_live": False,
            "exclude_covers": False,
            "exclude_remixes": False,
        }
    ]
    assert '"blocked_categories":["cover"]' in output.read_text(encoding="utf-8")


def test_cover_is_preserved_when_selector_is_disabled(tmp_path: Path) -> None:
    received: list[dict[str, bool]] = []

    accepted, rejected = asyncio.run(
        musicbrainz_filter.filter_musicbrainz_tracks(
            [_track()],
            {
                "exclude_live": True,
                "exclude_covers": False,
                "exclude_remixes": True,
            },
            client_factory=lambda: FakeClient([_cover_match()], received),
            output_path=tmp_path / "active.ndjson",
            force=True,
        )
    )

    assert accepted == [_track()]
    assert rejected == []


def test_transport_failure_retries_then_fails_open(tmp_path: Path) -> None:
    received: list[dict[str, bool]] = []
    request = httpx.Request("GET", "https://musicbrainz.org/ws/2/recording")
    error = httpx.ReadTimeout("slow", request=request)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    accepted, rejected = asyncio.run(
        musicbrainz_filter.filter_musicbrainz_tracks(
            [_track()],
            {
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
            client_factory=lambda: FakeClient([error, error, error], received),
            output_path=tmp_path / "active.ndjson",
            sleep_fn=fake_sleep,
            force=True,
        )
    )

    assert accepted == [_track()]
    assert rejected == []
    assert sleeps == [1.0, 2.0]


def test_catalog_moves_musicbrainz_rejections_to_unresolved(monkeypatch) -> None:
    candidate = {
        "artist": "Disturbed",
        "title": "The Sound of Silence",
        "description": "Description",
        "reason": "Reason",
    }
    resolved = _track()

    async def fake_youtube_resolve(candidates, exclusions):
        assert candidates == [candidate]
        assert exclusions["exclude_covers"] is True
        return [resolved], []

    async def fake_filter(tracks, exclusions):
        assert tracks == [resolved]
        assert exclusions["exclude_covers"] is True
        return [], [resolved]

    monkeypatch.setattr(youtube_music.youtube, "resolve_candidates", fake_youtube_resolve)
    monkeypatch.setattr(youtube_music, "filter_musicbrainz_tracks", fake_filter)

    accepted, unresolved = asyncio.run(
        youtube_music.YouTubeMusicCatalog().resolve_candidates(
            [candidate],
            {
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
        )
    )

    assert accepted == []
    assert unresolved == [candidate]
