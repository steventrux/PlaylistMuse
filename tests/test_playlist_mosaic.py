from pathlib import Path

from backend.main import app


ROOT = Path(__file__).resolve().parents[1]


def test_artwork_api_is_not_exposed() -> None:
    paths = set(app.openapi()["paths"])

    assert not any(path.startswith("/api/artwork") for path in paths)
    assert "/api/youtube/settings" in paths
    assert "/api/youtube/status" in paths
    assert "/api/youtube/connect/start" in paths
    assert "/api/youtube/connect/poll" in paths
    assert "/api/youtube/connection" in paths
    assert "/api/youtube/playlists" in paths


def test_removed_artwork_backend_is_absent() -> None:
    assert not (ROOT / "backend/artwork.py").exists()
    assert not (ROOT / "backend/artwork_routes.py").exists()


def test_playlist_loads_mosaic_helper_before_playlist_code() -> None:
    html = (ROOT / "frontend/playlist.html").read_text(encoding="utf-8")
    helper = '<script src="/static/playlist-mosaic.js?v=1"></script>'
    playlist = '<script src="/static/playlist.js?v=25"></script>'

    assert helper in html
    assert playlist in html
    assert html.index(helper) < html.index(playlist)
    assert 'role="img"' in html
    assert "playlist-cover-grid" in html


def test_external_artwork_services_are_not_referenced() -> None:
    paths = (
        ROOT / ".env.example",
        ROOT / "README.md",
        ROOT / "frontend/playlist.html",
        ROOT / "frontend/playlist.js",
        ROOT / "frontend/playlist-mosaic.js",
    )

    for path in paths:
        content = path.read_text(encoding="utf-8").casefold()
        assert "musicbrainz" not in content
        assert "coverartarchive" not in content
        assert "/api/artwork" not in content
