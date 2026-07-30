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
    normalized = source.casefold()

    assert "representativeindexes" in normalized
    assert "playlist-cover-grid" in source
    assert "track.thumbnail_url" in source
    assert "renderPlaylistCover();" in source
    assert "musicbrainz" not in normalized
    assert "coverartarchive" not in normalized
    assert "/api/artwork" not in source


def test_musicbrainz_files_and_configuration_are_absent() -> None:
    assert not Path("backend/artwork.py").exists()
    assert not Path("backend/artwork_routes.py").exists()

    env_example = Path(".env.example").read_text(encoding="utf-8").casefold()
    readme = Path("README.md").read_text(encoding="utf-8").casefold()

    assert "musicbrainz" not in env_example
    assert "musicbrainz" not in readme
    assert "cover art archive" not in readme
