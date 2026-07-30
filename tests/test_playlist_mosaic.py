from pathlib import Path

from backend.main import app


def test_artwork_api_is_not_exposed() -> None:
    paths = set(app.openapi()["paths"])

    assert not any(path.startswith("/api/artwork") for path in paths)
    assert "/api/youtube/settings" in paths
    assert "/api/youtube/status" in paths
    assert "/api/youtube/connect/start" in paths
    assert "/api/youtube/connect/poll" in paths
    assert "/api/youtube/connection" in paths
    assert "/api/youtube/playlists" in paths


def test_playlist_mosaic_uses_youtube_thumbnails_without_remote_lookup() -> None:
    source = Path("frontend/playlist.js").read_text(encoding="utf-8")

    assert "representativeIndexes" in source
    assert "Math.round(last / 3)" in source
    assert "Math.round((last * 2) / 3)" in source
    assert "playlist-cover-grid" in source
    assert "track.thumbnail_url" in source
    assert "renderPlaylistCover();" in source
    assert "/api/artwork" not in source


def test_removed_artwork_modules_are_absent() -> None:
    assert not Path("backend/artwork.py").exists()
    assert not Path("backend/artwork_routes.py").exists()
