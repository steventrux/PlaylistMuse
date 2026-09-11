from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import backend.youtube_routes as youtube_routes
from backend.application import app
from backend.playlist_library import PlaylistLibrary
from backend.youtube_account import YouTubeAccountError

VALID_URL = "https://music.youtube.com/playlist?list=PLabc1234567"


def _use_temp_library(monkeypatch, tmp_path: Path) -> PlaylistLibrary:
    library = PlaylistLibrary(tmp_path / "playlists.db")
    monkeypatch.setattr(youtube_routes, "get_library", lambda: library)
    return library


def test_import_preview_returns_fetched_playlist_without_persisting(monkeypatch, tmp_path: Path) -> None:
    _use_temp_library(monkeypatch, tmp_path)

    async def _fake_fetch(url: str) -> dict:
        assert url == VALID_URL
        return {
            "name": "My Playlist",
            "description": "",
            "prompt": "",
            "tracks": [{"video_id": "v1", "title": "Song", "artists": "Artist"}],
            "youtube_import": {"source_playlist_id": "PLabc1234567"},
            "warning": None,
        }

    monkeypatch.setattr(youtube_routes, "fetch_playlist_for_import", _fake_fetch)

    client = TestClient(app)
    response = client.post("/api/youtube/playlists/import-preview", json={"url": VALID_URL})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "My Playlist"
    assert body["youtube_import"]["source_playlist_id"] == "PLabc1234567"
    assert "id" not in body
    assert "created_at" not in body


def test_import_preview_rejects_an_invalid_url_before_touching_the_library(monkeypatch, tmp_path: Path) -> None:
    _use_temp_library(monkeypatch, tmp_path)

    async def _unexpected_fetch(url: str) -> dict:
        raise AssertionError("fetch must not run for an unparsable URL")

    monkeypatch.setattr(youtube_routes, "fetch_playlist_for_import", _unexpected_fetch)

    client = TestClient(app)
    response = client.post("/api/youtube/playlists/import-preview", json={"url": "not a url"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Enter a valid YouTube Music playlist link."


def test_import_preview_maps_unexpected_fetch_error_to_sanitized_502(monkeypatch, tmp_path: Path) -> None:
    _use_temp_library(monkeypatch, tmp_path)

    async def _fake_fetch(url: str) -> dict:
        raise RuntimeError("super secret internal detail")

    monkeypatch.setattr(youtube_routes, "fetch_playlist_for_import", _fake_fetch)

    client = TestClient(app)
    response = client.post("/api/youtube/playlists/import-preview", json={"url": VALID_URL})

    assert response.status_code == 502
    assert "super secret internal detail" not in response.text


def test_import_preview_maps_account_error_from_fetch_to_400(monkeypatch, tmp_path: Path) -> None:
    _use_temp_library(monkeypatch, tmp_path)

    async def _fake_fetch(url: str) -> dict:
        raise YouTubeAccountError("This playlist has no importable tracks.")

    monkeypatch.setattr(youtube_routes, "fetch_playlist_for_import", _fake_fetch)

    client = TestClient(app)
    response = client.post("/api/youtube/playlists/import-preview", json={"url": VALID_URL})

    assert response.status_code == 400
    assert response.json()["detail"] == "This playlist has no importable tracks."


def test_import_preview_rejects_a_playlist_already_in_the_library(monkeypatch, tmp_path: Path) -> None:
    library = _use_temp_library(monkeypatch, tmp_path)
    created = library.create({
        "name": "Already here",
        "tracks": [{"video_id": "v1", "title": "Song", "artists": "Artist"}],
        "youtube_import": {"source_playlist_id": "PLabc1234567"},
    })

    async def _unexpected_fetch(url: str) -> dict:
        raise AssertionError("fetch must not run for an already-imported playlist")

    monkeypatch.setattr(youtube_routes, "fetch_playlist_for_import", _unexpected_fetch)

    client = TestClient(app)
    response = client.post("/api/youtube/playlists/import-preview", json={"url": VALID_URL})

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "playlist_id": created["id"],
        "playlist_name": "Already here",
    }
