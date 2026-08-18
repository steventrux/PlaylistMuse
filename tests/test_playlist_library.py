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


def test_library_cover_uses_representative_tracks_and_refreshes_on_update(
    tmp_path: Path,
) -> None:
    library = PlaylistLibrary(tmp_path / "playlists.db")
    playlist = sample_playlist("Representative cover")
    playlist["tracks"] = [
        {
            "video_id": f"track-{index}",
            "title": f"Track {index}",
            "artists": f"Artist {index}",
            "thumbnail_url": f"https://example.test/{index}.jpg",
        }
        for index in range(15)
    ]

    created = library.create(playlist)
    assert created["thumbnail_urls"] == [
        "https://example.test/0.jpg",
        "https://example.test/5.jpg",
        "https://example.test/9.jpg",
        "https://example.test/14.jpg",
    ]

    playlist["tracks"][5]["thumbnail_url"] = "https://example.test/replacement.jpg"
    library.update(created["id"], playlist)

    assert library.list()[0]["thumbnail_urls"] == [
        "https://example.test/0.jpg",
        "https://example.test/replacement.jpg",
        "https://example.test/9.jpg",
        "https://example.test/14.jpg",
    ]


def test_split_artist_credit_preserves_known_comma_containing_band_names() -> None:
    from backend.playlist_library import split_artist_credit

    assert split_artist_credit("Earth, Wind & Fire") == ["Earth, Wind & Fire"]
    assert split_artist_credit("Daft Punk, Julian Casablancas") == [
        "Daft Punk",
        "Julian Casablancas",
    ]
    assert split_artist_credit("  Solo Artist  ") == ["Solo Artist"]
    assert split_artist_credit("") == []


def test_list_filters_by_artist_case_insensitively(tmp_path: Path) -> None:
    database = tmp_path / "playlists.db"
    library = PlaylistLibrary(database)
    library.create(sample_playlist("Night drive"))  # tracks: "Artist one", "Artist two"
    library.create({
        **sample_playlist("Focus flow"),
        "tracks": [
            {"video_id": "ghi789", "title": "Track three", "artists": "Artist Two, Artist Three"},
        ],
    })
    library.create({
        **sample_playlist("Untagged"),
        "tracks": [{"video_id": "jkl012", "title": "Track four", "artists": "Someone Else"}],
    })

    matches = library.list(artist="artist two")
    assert {item["name"] for item in matches} == {"Night drive", "Focus flow"}
    assert library.list(artist="Artist Three")[0]["name"] == "Focus flow"
    assert library.list(artist="Nonexistent") == []


def test_list_filters_by_a_band_name_containing_a_comma(tmp_path: Path) -> None:
    database = tmp_path / "playlists.db"
    library = PlaylistLibrary(database)
    library.create({
        **sample_playlist("Groove"),
        "tracks": [
            {"video_id": "mno345", "title": "September", "artists": "Earth, Wind & Fire"},
        ],
    })

    assert library.list(artist="Earth, Wind & Fire")[0]["name"] == "Groove"
    assert library.list(artist="Earth") == []
    assert library.list(artist="Wind & Fire") == []


def test_list_filters_by_track_video_id(tmp_path: Path) -> None:
    database = tmp_path / "playlists.db"
    library = PlaylistLibrary(database)
    library.create(sample_playlist("Night drive"))  # tracks: video_id "abc123", "def456"
    library.create({
        **sample_playlist("Focus flow"),
        "tracks": [
            {"video_id": "ghi789", "title": "Track three", "artists": "Artist Three"},
        ],
    })

    assert library.list(video_id="abc123")[0]["name"] == "Night drive"
    assert library.list(video_id="ghi789")[0]["name"] == "Focus flow"
    assert library.list(video_id="nonexistent") == []


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

    matching = client.get("/api/library/playlists?artist=Artist+one")
    assert [item["id"] for item in matching.json()["items"]] == [playlist_id]
    empty = client.get("/api/library/playlists?artist=Nobody")
    assert empty.json()["items"] == []

    track_matching = client.get("/api/library/playlists?video_id=abc123")
    assert [item["id"] for item in track_matching.json()["items"]] == [playlist_id]
    track_empty = client.get("/api/library/playlists?video_id=nonexistent")
    assert track_empty.json()["items"] == []

    duplicate = client.post(f"/api/library/playlists/{playlist_id}/duplicate")
    assert duplicate.status_code == 201
    assert duplicate.json()["status"] == "draft"

    assert client.delete(f"/api/library/playlists/{playlist_id}").status_code == 204
    assert client.get(f"/api/library/playlists/{playlist_id}").status_code == 404


def test_published_playlist_api_is_read_only_but_can_be_duplicated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        playlist_library_module,
        "_library",
        PlaylistLibrary(tmp_path / "published-readonly.db"),
    )
    client = TestClient(app)

    created = client.post(
        "/api/library/playlists",
        json={"playlist": sample_playlist(), "generation_request": {"mode": "prompt"}},
    )
    assert created.status_code == 201
    playlist_id = created.json()["id"]

    published = sample_playlist("Published snapshot")
    published["youtube_playlist"] = {
        "playlist_id": "PL123",
        "url": "https://music.youtube.com/playlist?list=PL123",
    }
    publish = client.put(
        f"/api/library/playlists/{playlist_id}",
        json={"playlist": published, "generation_request": {"mode": "prompt"}},
    )
    assert publish.status_code == 200
    assert publish.json()["status"] == "published"

    modified = sample_playlist("Changed after publish")
    modified["youtube_playlist"] = published["youtube_playlist"]
    blocked = client.put(
        f"/api/library/playlists/{playlist_id}",
        json={"playlist": modified, "generation_request": {"mode": "prompt"}},
    )
    assert blocked.status_code == 409
    assert "read-only" in blocked.json()["detail"].lower()

    tag_refresh = client.post(f"/api/library/playlists/{playlist_id}/tags/suggest")
    assert tag_refresh.status_code == 409

    reopened = client.get(f"/api/library/playlists/{playlist_id}")
    assert reopened.status_code == 200
    assert reopened.json()["name"] == "Published snapshot"

    duplicate = client.post(f"/api/library/playlists/{playlist_id}/duplicate")
    assert duplicate.status_code == 201
    assert duplicate.json()["status"] == "draft"
    assert "youtube_playlist" not in duplicate.json()["playlist"]


def test_library_ui_and_autosave_hooks_are_present() -> None:
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    page = (FRONTEND / "library.html").read_text(encoding="utf-8")
    library_script = (FRONTEND / "library.js").read_text(encoding="utf-8")
    playlist_script = (FRONTEND / "playlist.js").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert 'href="/static/library.html"' in index
    assert 'id="library-list"' in page
    assert 'id="library-pagination"' in page
    assert '/static/library-pagination.js?v=2' in page
    assert "/api/library/playlists" in library_script
    assert "const PAGE_SIZE = paginationTools.DEFAULT_PAGE_SIZE;" in library_script
    assert "method: 'DELETE'" in library_script
    assert "async function ensureLibraryRecord()" in playlist_script
    assert "method: 'PUT'" in playlist_script
    assert "data.library_id = record.id" in playlist_script
    assert "backend.application:app" in dockerfile
