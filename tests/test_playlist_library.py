from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import backend.playlist_library as playlist_library_module
from backend.application import app
from backend.playlist_library import PlaylistLibrary, PlaylistWriteRequest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def sample_playlist(name: str = "Night drive") -> dict:
    return {
        "name": name,
        "description": "Warm guitars after dark.",
        "prompt": "A slow-burning night drive",
        "tracks": [
            {
                "video_id": "abc123",
                "title": "Track one",
                "artists": "Artist one",
                "thumbnail_url": "https://example.test/one.jpg",
            },
            {
                "video_id": "def456",
                "title": "Track two",
                "artists": "Artist two",
                "thumbnail_url": "https://example.test/two.jpg",
            },
        ],
    }


def test_library_persists_and_updates_playlists(tmp_path: Path) -> None:
    database = tmp_path / "playlists.db"
    library = PlaylistLibrary(database)
    created = library.create(sample_playlist(), {"mode": "prompt"})

    assert created["status"] == "draft"
    assert created["track_count"] == 2
    assert created["thumbnail_urls"] == [
        "https://example.test/one.jpg",
        "https://example.test/two.jpg",
    ]

    reopened = PlaylistLibrary(database).get(created["id"])
    assert reopened["playlist"]["name"] == "Night drive"
    assert reopened["generation_request"] == {"mode": "prompt"}

    updated_playlist = sample_playlist("Night drive revised")
    updated_playlist["youtube_playlist"] = {
        "playlist_id": "PL123",
        "url": "https://music.youtube.com/playlist?list=PL123",
    }
    updated = library.update(created["id"], updated_playlist, {"mode": "prompt"})

    assert updated["status"] == "published"
    assert updated["youtube_playlist_id"] == "PL123"
    assert library.list("title_asc")[0]["name"] == "Night drive revised"


def test_duplicate_is_an_independent_draft(tmp_path: Path) -> None:
    library = PlaylistLibrary(tmp_path / "playlists.db")
    published = sample_playlist("Published playlist")
    published["youtube_playlist"] = {
        "playlist_id": "PL123",
        "url": "https://music.youtube.com/playlist?list=PL123",
    }
    source = library.create(published, {"mode": "seed"})

    duplicate = library.duplicate(source["id"])

    assert duplicate["id"] != source["id"]
    assert duplicate["name"] == "Published playlist (copy)"
    assert duplicate["status"] == "draft"
    assert "youtube_playlist" not in duplicate["playlist"]
    assert duplicate["generation_request"] == {"mode": "seed"}


def test_delete_and_missing_records(tmp_path: Path) -> None:
    library = PlaylistLibrary(tmp_path / "playlists.db")
    created = library.create(sample_playlist())

    library.delete(created["id"])

    assert library.list() == []
    with pytest.raises(LookupError):
        library.get(created["id"])


def test_playlist_request_rejects_empty_tracks() -> None:
    with pytest.raises(ValidationError):
        PlaylistWriteRequest(playlist={"name": "Empty", "tracks": []})


def test_library_api_crud_and_duplicate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        playlist_library_module,
        "_library",
        PlaylistLibrary(tmp_path / "api-playlists.db"),
    )
    client = TestClient(app)

    created = client.post(
        "/api/library/playlists",
        json={"playlist": sample_playlist(), "generation_request": {"mode": "prompt"}},
    )
    assert created.status_code == 201
    playlist_id = created.json()["id"]

    listing = client.get("/api/library/playlists?sort=title_asc")
    assert listing.status_code == 200
    assert listing.json()["items"][0]["id"] == playlist_id

    duplicate = client.post(f"/api/library/playlists/{playlist_id}/duplicate")
    assert duplicate.status_code == 201
    assert duplicate.json()["status"] == "draft"

    assert client.delete(f"/api/library/playlists/{playlist_id}").status_code == 204
    assert client.get(f"/api/library/playlists/{playlist_id}").status_code == 404


def test_library_ui_and_autosave_hooks_are_present() -> None:
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    page = (FRONTEND / "library.html").read_text(encoding="utf-8")
    library_script = (FRONTEND / "library.js").read_text(encoding="utf-8")
    playlist_script = (FRONTEND / "playlist.js").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert 'href="/static/library.html"' in index
    assert 'id="library-list"' in page
    assert "/api/library/playlists" in library_script
    assert "method: 'DELETE'" in library_script
    assert "async function ensureLibraryRecord()" in playlist_script
    assert "method: 'PUT'" in playlist_script
    assert "data.library_id = record.id" in playlist_script
    assert "backend.application:app" in dockerfile
