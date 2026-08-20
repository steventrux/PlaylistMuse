from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import backend.favorites as favorites_module
from backend.application import app
from backend.playlist_library import PlaylistLibrary


def _use_temporary_favorites(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "favorites.json"
    monkeypatch.setattr(favorites_module, "FAVORITES_PATH", path)
    return path


def test_add_and_remove_favorite_artist(monkeypatch, tmp_path) -> None:
    path = _use_temporary_favorites(monkeypatch, tmp_path)

    state = favorites_module.add_favorite_artist("Radiohead")
    assert [entry["name"] for entry in state["artists"]] == ["Radiohead"]
    assert path.exists()
    assert path.stat().st_mode & 0o777 == 0o600

    state = favorites_module.remove_favorite_artist("radiohead")
    assert state["artists"] == []


def test_favorite_artist_is_deduplicated_case_insensitively(monkeypatch, tmp_path) -> None:
    _use_temporary_favorites(monkeypatch, tmp_path)
    favorites_module.add_favorite_artist("Radiohead")

    try:
        favorites_module.add_favorite_artist("  radiohead  ")
        raise AssertionError("Expected a duplicate favorite artist to be rejected.")
    except ValueError as error:
        assert "already" in str(error)


def test_favorite_artist_name_is_required(monkeypatch, tmp_path) -> None:
    _use_temporary_favorites(monkeypatch, tmp_path)
    try:
        favorites_module.add_favorite_artist("   ")
        raise AssertionError("Expected an empty artist name to be rejected.")
    except ValueError as error:
        assert "Enter an artist name" in str(error)


def test_favorite_artist_cap_is_enforced(monkeypatch, tmp_path) -> None:
    _use_temporary_favorites(monkeypatch, tmp_path)
    monkeypatch.setattr(favorites_module, "MAX_FAVORITE_ARTISTS", 2)

    favorites_module.add_favorite_artist("Artist One")
    favorites_module.add_favorite_artist("Artist Two")
    try:
        favorites_module.add_favorite_artist("Artist Three")
        raise AssertionError("Expected the favorite artist cap to be enforced.")
    except ValueError as error:
        assert "at most" in str(error)


def test_add_and_remove_favorite_track(monkeypatch, tmp_path) -> None:
    _use_temporary_favorites(monkeypatch, tmp_path)
    track = {
        "video_id": "abc123",
        "title": "Idioteque",
        "artists": "Radiohead",
        "album": "Kid A",
        "thumbnail_url": "https://example.com/thumb.jpg",
    }

    state = favorites_module.add_favorite_track(track)
    assert [entry["video_id"] for entry in state["tracks"]] == ["abc123"]

    state = favorites_module.remove_favorite_track("abc123")
    assert state["tracks"] == []


def test_favorite_track_is_deduplicated_by_video_id(monkeypatch, tmp_path) -> None:
    _use_temporary_favorites(monkeypatch, tmp_path)
    track = {"video_id": "abc123", "title": "Idioteque", "artists": "Radiohead"}
    favorites_module.add_favorite_track(track)

    try:
        favorites_module.add_favorite_track(track)
        raise AssertionError("Expected a duplicate favorite track to be rejected.")
    except ValueError as error:
        assert "already" in str(error)


def test_favorite_track_requires_identity_fields(monkeypatch, tmp_path) -> None:
    _use_temporary_favorites(monkeypatch, tmp_path)
    try:
        favorites_module.add_favorite_track({"video_id": "", "title": "X", "artists": "Y"})
        raise AssertionError("Expected a missing video ID to be rejected.")
    except ValueError as error:
        assert "video ID" in str(error)


def test_favorite_summaries_are_truncated_to_the_requested_limit(monkeypatch, tmp_path) -> None:
    _use_temporary_favorites(monkeypatch, tmp_path)
    for index in range(5):
        favorites_module.add_favorite_artist(f"Artist {index}")
        favorites_module.add_favorite_track(
            {"video_id": f"id{index}", "title": f"Track {index}", "artists": f"Artist {index}"},
        )

    assert len(favorites_module.favorite_artist_names(limit=3)) == 3
    assert len(favorites_module.favorite_track_summaries(limit=2)) == 2


def test_favorites_endpoints_add_list_and_remove(monkeypatch, tmp_path) -> None:
    _use_temporary_favorites(monkeypatch, tmp_path)
    client = TestClient(app)

    empty = client.get("/api/favorites")
    assert empty.status_code == 200
    assert empty.json() == {"artists": [], "tracks": []}

    added_artist = client.post("/api/favorites/artists", json={"name": "Radiohead"})
    assert added_artist.status_code == 200
    assert [entry["name"] for entry in added_artist.json()["artists"]] == ["Radiohead"]

    duplicate_artist = client.post("/api/favorites/artists", json={"name": "Radiohead"})
    assert duplicate_artist.status_code == 400

    added_track = client.post(
        "/api/favorites/tracks",
        json={"video_id": "abc123", "title": "Idioteque", "artists": "Radiohead"},
    )
    assert added_track.status_code == 200
    assert [entry["video_id"] for entry in added_track.json()["tracks"]] == ["abc123"]

    listed = client.get("/api/favorites")
    assert listed.json()["artists"][0]["name"] == "Radiohead"
    assert listed.json()["tracks"][0]["video_id"] == "abc123"

    removed_artist = client.delete("/api/favorites/artists", params={"name": "Radiohead"})
    assert removed_artist.status_code == 200
    assert removed_artist.json()["artists"] == []

    removed_track = client.delete("/api/favorites/tracks/abc123")
    assert removed_track.status_code == 200
    assert removed_track.json()["tracks"] == []


def test_favorite_artist_names_containing_a_slash_can_be_removed(monkeypatch, tmp_path) -> None:
    """Regression test: a query-param DELETE avoids path-routing breaking on "/" in a name
    (e.g. "AC/DC"), which a path-segment DELETE (/artists/{name}) could never match."""
    _use_temporary_favorites(monkeypatch, tmp_path)
    client = TestClient(app)

    added = client.post("/api/favorites/artists", json={"name": "AC/DC"})
    assert added.status_code == 200

    removed = client.delete("/api/favorites/artists", params={"name": "AC/DC"})
    assert removed.status_code == 200
    assert removed.json()["artists"] == []


def test_favorites_include_playlist_counts_from_a_single_library_scan(monkeypatch, tmp_path) -> None:
    _use_temporary_favorites(monkeypatch, tmp_path)
    database_path = tmp_path / "playlists.db"
    monkeypatch.setattr(favorites_module, "DATABASE_PATH", database_path)

    library = PlaylistLibrary(database_path)
    library.create({
        "name": "Groove",
        "description": "",
        "prompt": "",
        "tracks": [{"video_id": "abc123", "title": "Idioteque", "artists": "Radiohead"}],
    })
    library.create({
        "name": "Chill",
        "description": "",
        "prompt": "",
        "tracks": [
            {"video_id": "abc123", "title": "Idioteque", "artists": "Radiohead"},
            {"video_id": "xyz789", "title": "September", "artists": "Earth, Wind & Fire"},
        ],
    })

    client = TestClient(app)
    client.post("/api/favorites/artists", json={"name": "Radiohead"})
    client.post("/api/favorites/artists", json={"name": "Earth, Wind & Fire"})
    added_track = client.post(
        "/api/favorites/tracks",
        json={"video_id": "abc123", "title": "Idioteque", "artists": "Radiohead"},
    )

    payload = added_track.json()
    artist_counts = {entry["name"]: entry["playlist_count"] for entry in payload["artists"]}
    assert artist_counts["Radiohead"] == 2
    assert artist_counts["Earth, Wind & Fire"] == 1
    track_counts = {entry["video_id"]: entry["playlist_count"] for entry in payload["tracks"]}
    assert track_counts["abc123"] == 2


def test_favorite_artists_get_a_thumbnail_from_one_of_their_library_tracks(monkeypatch, tmp_path) -> None:
    _use_temporary_favorites(monkeypatch, tmp_path)
    database_path = tmp_path / "playlists.db"
    monkeypatch.setattr(favorites_module, "DATABASE_PATH", database_path)

    library = PlaylistLibrary(database_path)
    library.create({
        "name": "Groove",
        "description": "",
        "prompt": "",
        "tracks": [
            {
                "video_id": "abc123",
                "title": "Idioteque",
                "artists": "Radiohead",
                "thumbnail_url": "https://example.test/radiohead.jpg",
            },
        ],
    })

    client = TestClient(app)
    added = client.post("/api/favorites/artists", json={"name": "Radiohead"})
    added_unmatched = client.post("/api/favorites/artists", json={"name": "Nobody Yet"})

    artists = added.json()["artists"]
    assert next(e["thumbnail_url"] for e in artists if e["name"] == "Radiohead") == (
        "https://example.test/radiohead.jpg"
    )
    unmatched_artists = added_unmatched.json()["artists"]
    assert next(e["thumbnail_url"] for e in unmatched_artists if e["name"] == "Nobody Yet") == ""
