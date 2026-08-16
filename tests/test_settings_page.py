from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_settings_page_exposes_all_current_sections() -> None:
    html = _text("settings.html")

    assert 'data-settings-section="ai"' in html
    assert 'data-settings-section="youtube"' in html
    assert 'data-settings-section="lastfm"' in html
    assert 'data-settings-section="support"' in html
    assert 'id="setup-ai-step"' in html
    assert 'id="setup-youtube-step"' in html
    assert 'id="settings-lastfm-host"' in html
    assert 'id="settings-support-panel"' in html
    assert 'href="/api/diagnostics/report"' in html
    assert 'template=bug_report.yml' in html
    assert '/static/diagnostics-client.js?v=1' in html
    assert '/static/support.js?v=' in html
    assert '/static/ai-settings.js?v=12' in html
    assert '/static/youtube-account.js?v=5' in html
    assert '/static/lastfm-settings.js?v=2' in html
    assert '/static/settings-page.css?v=' in html
    assert '/static/settings-page.js?v=3' in html


def test_settings_page_switches_sections_without_navigation_reload() -> None:
    script = _text("settings-page.js")

    assert "const SECTIONS = new Set(['ai', 'youtube', 'lastfm', 'support']);" in script
    assert "function selectSection(section" in script
    assert "panel?.classList.toggle('hidden', name !== selected);" in script
    assert "return $('settings-support-panel');" in script
    assert "window.history.replaceState" in script
    assert "if (embedded) return;" in script
    assert "window.PlaylistMuseSettingsSelect = selectSection;" in script
    assert "playlistmuse-ai-settings-opened" in script
    assert "playlistmuse-youtube-settings-opened" in script
    assert "playlistmuse-lastfm-settings-opened" in script


def test_integration_menu_opens_settings_overlay_without_page_navigation() -> None:
    home_status = _text("home-status.js")
    overlay = _text("settings-overlay.js")

    assert "window.PlaylistMuseSettingsOverlay?.open(section);" in home_status
    assert "function settingsPageUrl(section)" not in home_status
    assert "window.location.assign(settingsPageUrl(section));" not in home_status
    assert "/static/settings-overlay.css?v=1" in home_status
    assert "target.searchParams.set('embedded', '1');" in overlay
    assert "frame.src = settingsFrameUrl(requestedSection);" in overlay
    assert "window.location.assign" not in overlay


def test_settings_overlay_supports_diagnostics_section() -> None:
    overlay = _text("settings-overlay.js")

    assert "const SECTIONS = new Set(['ai', 'youtube', 'lastfm', 'support']);" in overlay
    assert "/static/diagnostics-client.js?v=1" in overlay
    assert "installDiagnosticsClient();" in overlay


def test_settings_overlay_is_loaded_on_all_primary_pages() -> None:
    index = _text("index.html")
    library = _text("library.html")
    playlist = _text("playlist.html")

    overlay = '<script src="/static/settings-overlay.js?v=2"></script>'
    home_status = '/static/home-status.js?v=23'
    for html in (index, library, playlist):
        assert overlay in html
        assert home_status in html
        assert html.index(overlay) < html.index(home_status)


def test_embedded_settings_close_without_navigating_parent_page() -> None:
    html = _text("settings.html")
    script = _text("settings-page.js")
    overlay = _text("settings-overlay.js")
    style = _text("settings-page.css")

    assert "document.documentElement.classList.add('settings-embedded');" in html
    assert "query.get('embedded') === '1'" in script
    assert "window.parent.postMessage({type: 'playlistmuse-settings-close'}" in script
    assert "if (embedded) {" in script
    assert "window.location.assign(safeReturnTarget());" in script
    assert "if (event.data?.type === 'playlistmuse-settings-close') close();" in overlay
    assert "overlay.hidden = true;" in overlay
    assert "html.settings-embedded .settings-page-header" in style
    assert "display: none;" in style


def test_mobile_settings_layout_keeps_navigation_compact_and_clear() -> None:
    style = _text("settings-page.css")

    assert "grid-template-rows: auto minmax(0, 1fr);" in style
    assert "scroll-snap-type: x proximity;" in style
    assert "html.settings-embedded .settings-page-navigation" in style
    assert "padding-top: 58px;" in style
    assert "#settings-support-panel .settings-actions" in style
    assert "grid-template-columns: minmax(0, 1fr);" in style


def test_diagnostics_actions_leave_space_before_support_note() -> None:
    style = _text("settings-page.css")

    assert "#settings-support-panel .settings-actions + .field-hint" in style
    assert "margin-top: 16px;" in style


def test_youtube_publish_uses_same_settings_overlay() -> None:
    script = _text("youtube-publish.js")

    assert "window.PlaylistMuseSettingsOverlay?.open('youtube');" in script
    assert "new URL('/static/settings.html'" not in script
    assert "window.location.assign(`${target.pathname}${target.search}`);" not in script


def test_lastfm_settings_reuse_existing_logic_inside_settings_page() -> None:
    script = _text("lastfm-settings.js")

    assert "const pageHost = $('settings-lastfm-host');" in script
    assert "if (!pageHost) return;" in script
    assert "pageHost.append(panel);" in script
    assert "window.addEventListener('playlistmuse-lastfm-settings-opened'" in script
    assert "fetch('/api/lastfm/settings'" in script
    assert "method: 'PUT'" in script
    assert "method: 'DELETE'" in script


def test_support_page_reads_running_build_without_duplication() -> None:
    script = _text("support.js")

    assert "fetch('/api/version', {cache: 'no-store'})" in script
    assert "support-build-info" in script
    assert "const display = info.display || info.version || 'Version unavailable';" in script
    assert "target.textContent = `Running build: ${display}`;" in script
    assert "info.commit" not in script
    assert "info.api_key" not in script
    assert "info.token" not in script


def test_support_page_uses_template_on_stable_and_prefill_on_dev() -> None:
    script = _text("support.js")

    assert "const STABLE_TEMPLATE_URL = `${ISSUE_URL}?template=bug_report.yml`;" in script
    assert "function developmentBugReportUrl(build)" in script
    assert "info.channel === 'stable'" in script
    assert "developmentBugReportUrl(display)" in script
    assert "url.searchParams.set('title', '[Bug] ');" in script
    assert "url.searchParams.set('body'" in script
    assert "## Running build" in script
    assert "## Diagnostic report" in script
