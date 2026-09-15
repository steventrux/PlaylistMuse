from __future__ import annotations

import asyncio
import inspect

import pytest

from backend import youtube_playlist_import
from backend.youtube_account import YouTubeAccountError


class _FakeClient:
    def __init__(self, tracks: list[dict], **extra) -> None:
        self._payload = {"title": "My Playlist", "description": "Nice tunes", "tracks": tracks, **extra}
        self.calls: list[tuple] = []

    def get_playlist(self, playlist_id: str, limit=None, **kwargs):
        self.calls.append((playlist_id, limit, kwargs))
        return self._payload


def _track(video_id="v1", title="Song", artist="Artist") -> dict:
    return {
        "videoId": video_id,
        "title": title,
        "artists": [{"name": artist}],
        "album": {"name": "Album"},
        "duration": "3:30",
        "thumbnails": [{"url": "https://example.com/thumb.jpg"}],
    }


def _patch_client(monkeypatch, client: _FakeClient) -> None:
    monkeypatch.setattr(youtube_playlist_import, "anonymous_client", lambda: client)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://music.youtube.com/playlist?list=PLabc123_-XYZ", "PLabc123_-XYZ"),
        ("https://www.youtube.com/playlist?list=PLabc123_-XYZ", "PLabc123_-XYZ"),
        ("PLabc123_-XYZ", "PLabc123_-XYZ"),
        ("https://music.youtube.com/playlist?list=VLPLabc123_-XYZ", "PLabc123_-XYZ"),
        (
            "https://music.youtube.com/playlist?list=RDCLAK5uy_nfzp61bRQ-xurtvhOYDbtlXpDAZFDTLuc",
            "RDCLAK5uy_nfzp61bRQ-xurtvhOYDbtlXpDAZFDTLuc",
        ),
        ("https://music.youtube.com/playlist?list=OLAK5uy_lAbc123XYZdef456", "OLAK5uy_lAbc123XYZdef456"),
    ],
)
def test_parse_playlist_id_accepts_known_formats(value: str, expected: str) -> None:
    assert youtube_playlist_import.parse_playlist_id(value) == expected


@pytest.mark.parametrize("value", ["", "not a url", "https://example.com/playlist?list=", "12345"])
def test_parse_playlist_id_rejects_invalid_input(value: str) -> None:
    with pytest.raises(YouTubeAccountError, match="valid YouTube Music playlist link"):
        youtube_playlist_import.parse_playlist_id(value)


def test_fetch_playlist_for_import_maps_tracks_and_requests_unbounded_limits(monkeypatch) -> None:
    client = _FakeClient([_track(), _track(video_id="v2", title="Song 2")])
    _patch_client(monkeypatch, client)

    result = asyncio.run(youtube_playlist_import.fetch_playlist_for_import("PLabc1234567"))

    assert client.calls == [("PLabc1234567", None, {})]
    assert [t["video_id"] for t in result["tracks"]] == ["v1", "v2"]
    assert result["tracks"][0] == {
        "video_id": "v1",
        "title": "Song",
        "artists": "Artist",
        "album": "Album",
        "duration": "3:30",
        "thumbnail_url": "https://example.com/thumb.jpg",
        "url": "https://music.youtube.com/watch?v=v1",
    }
    assert result["warning"] is None


def test_fetch_playlist_for_import_drops_unavailable_tracks_with_warning(monkeypatch) -> None:
    incomplete_track = {"videoId": None, "title": "Gone", "artists": []}
    client = _FakeClient([_track(), incomplete_track])
    _patch_client(monkeypatch, client)

    result = asyncio.run(youtube_playlist_import.fetch_playlist_for_import("PLabc1234567"))

    assert len(result["tracks"]) == 1
    assert "1 track(s) could not be imported" in result["warning"]


def test_fetch_playlist_for_import_truncates_over_300_tracks(monkeypatch) -> None:
    tracks = [_track(video_id=f"v{i}", title=f"Song {i}") for i in range(310)]
    client = _FakeClient(tracks)
    _patch_client(monkeypatch, client)

    result = asyncio.run(youtube_playlist_import.fetch_playlist_for_import("PLabc1234567"))

    assert len(result["tracks"]) == 300
    assert "Only the first 300 of 310 tracks" in result["warning"]


def test_fetch_playlist_for_import_raises_for_empty_result(monkeypatch) -> None:
    client = _FakeClient([])
    _patch_client(monkeypatch, client)

    with pytest.raises(YouTubeAccountError, match="no importable tracks"):
        asyncio.run(youtube_playlist_import.fetch_playlist_for_import("PLabc1234567"))


def test_fetch_playlist_for_import_does_not_apply_playlist_signature(monkeypatch) -> None:
    client = _FakeClient([_track()], description="Original description only")
    _patch_client(monkeypatch, client)

    result = asyncio.run(youtube_playlist_import.fetch_playlist_for_import("PLabc1234567"))

    assert result["description"] == "Original description only"
    assert "PlaylistMuse" not in result["description"]


def test_fetch_playlist_for_import_omits_youtube_playlist_and_carries_provenance(monkeypatch) -> None:
    client = _FakeClient([_track()])
    _patch_client(monkeypatch, client)

    result = asyncio.run(youtube_playlist_import.fetch_playlist_for_import("PLabc1234567"))

    assert "youtube_playlist" not in result
    assert result["youtube_import"]["source_playlist_id"] == "PLabc1234567"
    assert result["youtube_import"]["source_url"] == "https://music.youtube.com/playlist?list=PLabc1234567"
    assert result["prompt"] == ""


def test_fetch_playlist_for_import_wraps_lookup_failures(monkeypatch) -> None:
    class _BrokenClient:
        def get_playlist(self, playlist_id, limit=None):
            raise RuntimeError("boom")

    _patch_client(monkeypatch, _BrokenClient())

    with pytest.raises(YouTubeAccountError, match="no longer available"):
        asyncio.run(youtube_playlist_import.fetch_playlist_for_import("PLabc1234567"))


def test_module_never_imports_playlist_library() -> None:
    source = inspect.getsource(youtube_playlist_import)
    assert "playlist_library" not in source
