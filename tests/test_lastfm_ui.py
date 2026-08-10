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


def test_lastfm_restored_settings_wait_for_async_module_without_redirect_loop() -> None:
    status = (FRONTEND / "lastfm-status.js").read_text(encoding="utf-8")
    settings = (FRONTEND / "lastfm-settings.js").read_text(encoding="utf-8")

    assert "function openSettingsWhenReady()" in status
    assert "if (!document.getElementById('setup-dialog')) return false;" in status
    assert "if (openSettingsWhenReady()) return;" in status
    assert "playlistmuse-lastfm-settings-ready" in status
    assert "sessionStorage.removeItem(SETTINGS_REQUEST_KEY);\n    openSettings();" in status
    assert "setTimeout(openSettings, 0)" not in status
    assert "window.dispatchEvent(new Event('playlistmuse-lastfm-settings-ready'));" in settings


def test_lastfm_indicator_uses_the_official_brand_mark_and_red() -> None:
    script = (FRONTEND / "lastfm-status.js").read_text(encoding="utf-8")
    stylesheet = (FRONTEND / "lastfm.css").read_text(encoding="utf-8")

    assert 'class="lastfm-mark" viewBox="0 0 512 512"' in script
    assert "M225.8 367.1l-18.8-51" in script
    assert "color: #d51007" in stylesheet


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


def test_seed_die_is_shown_only_for_valid_lastfm_status() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    status = (FRONTEND / "lastfm-status.js").read_text(encoding="utf-8")
    style = (FRONTEND / "prompt-surprise.css").read_text(encoding="utf-8")
    app_asset = '<script src="/static/app.js?v=19"></script>'
    status_asset = '<script src="/static/lastfm-status.js?v=2"></script>'

    assert 'id="seed-surprise"' in html
    assert 'title="Surprise me with Last.fm"' in html
    assert "hidden\n            >" in html
    assert app_asset in html
    assert status_asset in html
    assert html.index(app_asset) < html.index(status_asset)
    assert "playlistmuse-lastfm-status" in status
    assert "publishAvailability(configured)" in status
    assert "publishAvailability(false)" in status
    assert "state.lastFmConfigured = Boolean(event.detail?.configured)" in app
    assert "button.hidden = !state.lastFmConfigured" in app
    assert "fetch('/api/lastfm/random-seed'" in app
    assert "$('seed-query').value = query" in app
    assert ".seed-surprise" in style
    assert "right: 8px" in style
