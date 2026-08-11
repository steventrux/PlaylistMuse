from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_runtime_favicon_asset_exists() -> None:
    status = (FRONTEND / "home-status.js").read_text(encoding="utf-8")
    favicon = FRONTEND / "playlistmuse-favicon.png"

    assert "const FAVICON_URL = '/static/playlistmuse-favicon.png?v=1';" in status
    assert "favicon.type = 'image/png';" in status
    assert favicon.is_file()
    assert favicon.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
