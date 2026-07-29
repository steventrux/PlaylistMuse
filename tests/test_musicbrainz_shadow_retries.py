"""Retry regression tests for MusicBrainz shadow collection."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from backend.services import musicbrainz_shadow


def _track() -> dict[str, Any]:
    return {
        "video_id": "video-1",
        "title": "Back in Black",
        "artists": "AC/DC",
        "duration": "4:15",
    }


def _match() -> dict[str, Any]:
    return {
        "matched": True,
        "recording_mbid": "recording-mbid",
        "recording_title": "Back in Black",
        "lexical_score": 100.0,
        "duration_delta_ms": 0,
        "version_penalty": 0,
        "version_categories": [],
    }


def test_shadow_retries_transient_timeout_then_succeeds(tmp_path) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    class FlakyClient:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        async def search_track(self, *args, **kwargs):
            del args, kwargs
            type(self).calls += 1
            if type(self).calls == 1:
                raise httpx.ReadTimeout("temporary MusicBrainz timeout")
            return _match()

    payload = asyncio.run(
        musicbrainz_shadow.run_musicbrainz_shadow(
            [_track()],
            client_factory=FlakyClient,
            output_path=tmp_path / "shadow.ndjson",
            sample_size=1,
            sleep_fn=fake_sleep,
        )
    )

    assert FlakyClient.calls == 2
    assert sleeps == [1.0]
    assert payload["matched_count"] == 1
    assert payload["error_count"] == 0
    assert payload["results"][0]["attempts"] == 2
    assert payload["results"][0]["musicbrainz"]["decision"] == "matched"


def test_shadow_stops_after_three_transient_failures(tmp_path) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    class TimeoutClient:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        async def search_track(self, *args, **kwargs):
            del args, kwargs
            type(self).calls += 1
            raise httpx.ReadTimeout("persistent MusicBrainz timeout")

    payload = asyncio.run(
        musicbrainz_shadow.run_musicbrainz_shadow(
            [_track()],
            client_factory=TimeoutClient,
            output_path=tmp_path / "shadow.ndjson",
            sample_size=1,
            sleep_fn=fake_sleep,
        )
    )

    assert TimeoutClient.calls == 3
    assert sleeps == [1.0, 2.0]
    assert payload["matched_count"] == 0
    assert payload["error_count"] == 1
    assert payload["results"][0]["attempts"] == 3
    assert payload["results"][0]["error"] == "ReadTimeout"


def test_shadow_does_not_retry_non_transient_errors(tmp_path) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    class InvalidClient:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        async def search_track(self, *args, **kwargs):
            del args, kwargs
            type(self).calls += 1
            raise ValueError("invalid diagnostic input")

    payload = asyncio.run(
        musicbrainz_shadow.run_musicbrainz_shadow(
            [_track()],
            client_factory=InvalidClient,
            output_path=tmp_path / "shadow.ndjson",
            sample_size=1,
            sleep_fn=fake_sleep,
        )
    )

    assert InvalidClient.calls == 1
    assert sleeps == []
    assert payload["error_count"] == 1
    assert payload["results"][0]["attempts"] == 1
    assert payload["results"][0]["error"] == "ValueError"
