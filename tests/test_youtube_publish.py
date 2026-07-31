from __future__ import annotations

import pytest

from backend import youtube_publish


def _aborted_error() -> youtube_publish._GoogleApiError:
    return youtube_publish._GoogleApiError(
        409,
        "SERVICE_UNAVAILABLE",
        "The operation was aborted.",
    )


def test_retryable_track_insert_error_is_narrow() -> None:
    assert youtube_publish._is_retryable_track_insert_error(_aborted_error())
    assert not youtube_publish._is_retryable_track_insert_error(
        youtube_publish._GoogleApiError(409, "conflict", "Duplicate item")
    )
    assert not youtube_publish._is_retryable_track_insert_error(
        youtube_publish._GoogleApiError(503, "SERVICE_UNAVAILABLE", "Backend unavailable")
    )


def test_add_track_retries_one_aborted_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_request(*args, **kwargs):
        calls.append(kwargs["json_body"]["snippet"]["resourceId"]["videoId"])
        if len(calls) == 1:
            raise _aborted_error()
        return object()

    monkeypatch.setattr(youtube_publish, "_request", fake_request)
    monkeypatch.setattr(youtube_publish.time, "sleep", sleeps.append)

    youtube_publish._add_track(object(), "playlist-id", "video-id")

    assert calls == ["video-id", "video-id"]
    assert sleeps == [youtube_publish.TRACK_INSERT_RETRY_DELAY_SECONDS]


def test_add_track_does_not_retry_generic_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    sleeps: list[float] = []
    conflict = youtube_publish._GoogleApiError(409, "conflict", "Duplicate item")

    def fake_request(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise conflict

    monkeypatch.setattr(youtube_publish, "_request", fake_request)
    monkeypatch.setattr(youtube_publish.time, "sleep", sleeps.append)

    with pytest.raises(youtube_publish._GoogleApiError) as raised:
        youtube_publish._add_track(object(), "playlist-id", "video-id")

    assert raised.value is conflict
    assert calls == 1
    assert sleeps == []


def test_add_track_stops_after_retry_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def fake_request(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise _aborted_error()

    monkeypatch.setattr(youtube_publish, "_request", fake_request)
    monkeypatch.setattr(youtube_publish.time, "sleep", sleeps.append)

    with pytest.raises(youtube_publish._GoogleApiError):
        youtube_publish._add_track(object(), "playlist-id", "video-id")

    assert calls == youtube_publish.TRACK_INSERT_MAX_ATTEMPTS
    assert sleeps == [youtube_publish.TRACK_INSERT_RETRY_DELAY_SECONDS]
