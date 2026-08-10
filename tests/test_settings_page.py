from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_settings_page_exposes_all_current_integrations() -> None:
    html = _text("settings.html")

    assert 'data-settings-section="ai"' in html
    assert 'data-settings-section="youtube"' in html
    assert 'data-settings-section="lastfm"' in html
    assert 'id="setup-ai-step"' in html
    assert 'id="setup-youtube-step"' in html
    assert 'id="settings-lastfm-host"' in html
    assert '/static/ai-settings.js?v=12' in html
    assert '/static/youtube-account.js?v=5' in html
    assert '/static/lastfm-settings.js?v=2' in html
    assert '/static/settings-page.js?v=1' in html


def test_settings_page_switches_sections_without_navigation_reload() -> None:
    script = _text("settings-page.js")

    assert "const SECTIONS = new Set(['ai', 'youtube', 'lastfm']);" in script
    assert "function selectSection(section" in script
    assert "panel?.classList.toggle('hidden', name !== selected);" in script
    assert "window.history.replaceState" in script
    assert "window.PlaylistMuseSettingsSelect = selectSection;" in script
    assert "playlistmuse-ai-settings-opened" in script
    assert "playlistmuse-youtube-settings-opened" in script
    assert "playlistmuse-lastfm-settings-opened" in script


def test_integration_menu_routes_to_settings_and_preserves_origin() -> None:
    script = _text("home-status.js")

    assert "function settingsPageUrl(section)" in script
    assert "new URL('/static/settings.html', window.location.origin)" in script
    assert "target.searchParams.set('section', section);" in script
    assert "window.location.pathname" in script
    assert "target.searchParams.set('return', returnTarget);" in script
    assert "window.location.assign(settingsPageUrl(section));" in script
    assert "SETTINGS_REQUEST_KEY" not in script


def test_closing_settings_returns_only_to_safe_local_page() -> None:
    script = _text("settings-page.js")

    assert "function safeReturnTarget()" in script
    assert "if (!raw.startsWith('/') || raw.startsWith('//')) return '/';" in script
    assert "if (raw.startsWith('/static/settings.html')) return '/';" in script
    assert "window.location.assign(safeReturnTarget());" in script


def test_lastfm_settings_reuse_existing_logic_inside_settings_page() -> None:
    script = _text("lastfm-settings.js")

    assert "const pageHost = $('settings-lastfm-host');" in script
    assert "if (pageHost) pageHost.append(panel);" in script
    assert "window.PlaylistMuseSettingsSelect?.('lastfm');" in script
    assert "fetch('/api/lastfm/settings'" in script
    assert "method: 'PUT'" in script
    assert "method: 'DELETE'" in script
