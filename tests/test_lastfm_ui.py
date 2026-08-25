from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_shared_frontend_loader_only_adds_lastfm_styles() -> None:
    script = (FRONTEND / "common.js").read_text(encoding="utf-8")

    assert "function ensureLastFmStyles()" in script
    assert "/static/lastfm.css?v=1" in script
    assert "ensureLastFmStyles();" in script
    assert "function loadScript(" not in script
    assert "/static/lastfm-settings.js" not in script
    assert "/static/lastfm-status.js" not in script


def test_lastfm_home_status_updates_existing_shared_indicator() -> None:
    script = (FRONTEND / "lastfm-status.js").read_text(encoding="utf-8")
    stylesheet = (FRONTEND / "lastfm.css").read_text(encoding="utf-8")

    assert "if (!document.getElementById('setup-dialog')) return;" in script
    assert "document.getElementById('header-lastfm-status')" in script
    assert "fetch('/api/lastfm/status'" in script
    assert "configured ? 'on' : 'off'" in script
    assert "playlistmuse-lastfm-status" in script
    assert "PlaylistMuseOpenLastFmSettings" not in script
    assert "window.location.assign('/')" not in script
    assert ".header-indicator.lastfm.on" in stylesheet


def test_lastfm_settings_module_is_scoped_to_settings_page() -> None:
    settings = (FRONTEND / "lastfm-settings.js").read_text(encoding="utf-8")

    assert "const pageHost = $('settings-lastfm-host');" in settings
    assert "if (!pageHost) return;" in settings
    assert "pageHost.append(panel);" in settings
    assert "playlistmuse-lastfm-settings-opened" in settings
    assert "setup-dialog" not in settings
    assert "PlaylistMuseOpenLastFmSettings" not in settings
    assert "playlistmuse-lastfm-settings-ready" not in settings
    assert "playlistmuse-ai-settings-opened" not in settings
    assert "playlistmuse-youtube-settings-opened" not in settings


def test_lastfm_indicator_uses_the_official_brand_mark_and_red() -> None:
    shared_status = (FRONTEND / "home-status.js").read_text(encoding="utf-8")
    stylesheet = (FRONTEND / "lastfm.css").read_text(encoding="utf-8")

    assert 'class="lastfm-mark" viewBox="0 0 512 512"' in shared_status
    assert "M225.8 367.1l-18.8-51" in shared_status
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
    assert "window.addEventListener('playlistmuse-lastfm-settings-opened'" in script


def test_seed_die_is_shown_only_for_valid_lastfm_status() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    status = (FRONTEND / "lastfm-status.js").read_text(encoding="utf-8")
    style = (FRONTEND / "prompt-surprise.css").read_text(encoding="utf-8")
    app_asset = '<script src="/static/app.js?v=22"></script>'
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
