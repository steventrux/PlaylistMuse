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

    def fake_rollback(client, playlist_id: str, diagnostic: str) -> bool:
        deleted.append(playlist_id)
        return True

    monkeypatch.setattr(youtube_publish, "_add_track", fake_add_track)
    monkeypatch.setattr(youtube_publish, "_rollback_playlist", fake_rollback)

    with pytest.raises(youtube_publish.YouTubeAccountError):
        youtube_publish._create_playlist_sync(
            "Night drive",
            "Test playlist",
            "PRIVATE",
            ["first-video", "fatal-video"],
        )

    assert inserted == ["first-video"]
    assert deleted == ["PL123"]


def test_rejected_track_rolls_back_instead_of_publishing_partial_playlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_publish_client(monkeypatch)
    inserted: list[str] = []
    deleted: list[str] = []

    def fake_add_track(client, playlist_id: str, video_id: str) -> None:
        if video_id == "missing-video":
            raise youtube_publish._GoogleApiError(404, "videoNotFound", "missing")
        inserted.append(video_id)

    def fake_rollback(client, playlist_id: str, diagnostic: str) -> bool:
        deleted.append(playlist_id)
        return True

    monkeypatch.setattr(youtube_publish, "_add_track", fake_add_track)
    monkeypatch.setattr(youtube_publish, "_rollback_playlist", fake_rollback)

    with pytest.raises(youtube_publish.YouTubeAccountError) as raised:
        youtube_publish._create_playlist_sync(
            "Night drive",
            "Test playlist",
            "PRIVATE",
            ["valid-video", "missing-video"],
        )

    assert inserted == ["valid-video"]
    assert deleted == ["PL123"]
    message = str(raised.value)
    assert "track 2 of 2" in message
    assert "missing-video" in message
    assert "incomplete YouTube playlist was removed" in message
    assert "draft was left unchanged" in message


def test_rejected_track_reports_when_rollback_cannot_be_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_publish_client(monkeypatch)

    def reject_track(client, playlist_id: str, video_id: str) -> None:
        raise youtube_publish._GoogleApiError(404, "videoNotFound", "missing")

    monkeypatch.setattr(youtube_publish, "_add_track", reject_track)
    monkeypatch.setattr(
        youtube_publish,
        "_rollback_playlist",
        lambda client, playlist_id, diagnostic: False,
    )

    with pytest.raises(youtube_publish.YouTubeAccountError) as raised:
        youtube_publish._create_playlist_sync(
            "Night drive",
            "Test playlist",
            "PRIVATE",
            ["missing-video"],
        )

    message = str(raised.value)
    assert "could not confirm deletion" in message
    assert "Check YouTube Music and remove it if present" in message
    assert "draft was left unchanged" in message


def test_successful_publish_reports_complete_track_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_publish_client(monkeypatch)
    inserted: list[str] = []

    monkeypatch.setattr(
        youtube_publish,
        "_add_track",
        lambda client, playlist_id, video_id: inserted.append(video_id),
    )

    result = youtube_publish._create_playlist_sync(
        "Night drive",
        "Test playlist",
        "PRIVATE",
        ["first-video", "second-video"],
    )

    assert inserted == ["first-video", "second-video"]
    assert result["track_count"] == 2
    assert result["requested_track_count"] == 2
    assert result["skipped_count"] == 0
    assert result["warning"] is None
    assert result["playlist_id"] == "PL123"
