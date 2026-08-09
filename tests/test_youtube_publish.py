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


def _patch_publish_client(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyClient:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(youtube_publish.httpx, "Client", lambda *args, **kwargs: DummyClient())
    monkeypatch.setattr(
        youtube_publish,
        "_create_empty_playlist",
        lambda client, title, description: "PL123",
    )


def test_fatal_insert_rolls_back_partially_created_playlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_publish_client(monkeypatch)
    inserted: list[str] = []
    deleted: list[str] = []

    def fake_add_track(client, playlist_id: str, video_id: str) -> None:
        if video_id == "fatal-video":
            raise youtube_publish._GoogleApiError(500, "backendError", "fatal insert")
        inserted.append(video_id)

    monkeypatch.setattr(youtube_publish, "_add_track", fake_add_track)
    monkeypatch.setattr(
        youtube_publish,
        "_delete_quietly",
        lambda client, playlist_id: deleted.append(playlist_id),
    )

    with pytest.raises(youtube_publish.YouTubeAccountError):
        youtube_publish._create_playlist_sync(
            "Night drive",
            "Test playlist",
            "PRIVATE",
            ["first-video", "fatal-video"],
        )

    assert inserted == ["first-video"]
    assert deleted == ["PL123"]


def test_skippable_insert_error_keeps_valid_playlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_publish_client(monkeypatch)
    inserted: list[str] = []
    deleted: list[str] = []

    def fake_add_track(client, playlist_id: str, video_id: str) -> None:
        if video_id == "missing-video":
            raise youtube_publish._GoogleApiError(404, "videoNotFound", "missing")
        inserted.append(video_id)

    monkeypatch.setattr(youtube_publish, "_add_track", fake_add_track)
    monkeypatch.setattr(
        youtube_publish,
        "_delete_quietly",
        lambda client, playlist_id: deleted.append(playlist_id),
    )

    result = youtube_publish._create_playlist_sync(
        "Night drive",
        "Test playlist",
        "PRIVATE",
        ["valid-video", "missing-video"],
    )

    assert inserted == ["valid-video"]
    assert deleted == []
    assert result["track_count"] == 1
    assert result["skipped_count"] == 1
    assert result["playlist_id"] == "PL123"
