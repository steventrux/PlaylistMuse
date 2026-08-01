from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_shared_frontend_loader_adds_lastfm_assets() -> None:
    script = (FRONTEND / "common.js").read_text(encoding="utf-8")

    assert "/static/lastfm.css?v=1" in script
    assert "await loadScript('/static/lastfm-settings.js')" in script
    assert "await loadScript('/static/lastfm-status.js')" in script
    assert "document.getElementById('setup-dialog')" in script


def test_lastfm_header_indicator_matches_existing_status_behavior() -> None:
    script = (FRONTEND / "lastfm-status.js").read_text(encoding="utf-8")
    stylesheet = (FRONTEND / "lastfm.css").read_text(encoding="utf-8")

    assert "header-lastfm-status" in script
    assert "header-indicator lastfm pending" in script
    assert "controls.append(button)" in script
    assert "fetch('/api/lastfm/status'" in script
    assert "configured ? 'on' : 'off'" in script
    assert "PlaylistMuseOpenLastFmSettings" in script
    assert "sessionStorage.setItem(SETTINGS_REQUEST_KEY, 'lastfm')" in script
    assert ".header-indicator.lastfm.on" in stylesheet


def test_lastfm_settings_panel_saves_without_exposing_the_key() -> None:
    script = (FRONTEND / "lastfm-settings.js").read_text(encoding="utf-8")

    assert "setup-lastfm-step" in script
    assert 'type="password"' in script
    assert "Save Last.fm key" in script
    assert "fetch('/api/lastfm/settings'" in script
    assert "method: 'PUT'" in script
    assert "method: 'DELETE'" in script
    assert "input.value = ''" in script
    assert "PlaylistMuseOpenLastFmSettings" in script
    assert "playlistmuse-ai-settings-opened" in script
    assert "playlistmuse-youtube-settings-opened" in script
