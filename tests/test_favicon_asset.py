from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_runtime_favicon_asset_exists() -> None:
    status = (FRONTEND / "home-status.js").read_text(encoding="utf-8")
    favicon = FRONTEND / "playlistmuse-favicon.svg"

    assert "const FAVICON_URL = '/static/playlistmuse-favicon.svg?v=1';" in status
    assert favicon.is_file()
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in favicon.read_text(encoding="utf-8")
