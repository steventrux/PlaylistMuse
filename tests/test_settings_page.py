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
    assert 'data-settings-section="support"' not in html
    assert 'id="setup-ai-step"' in html
    assert 'id="setup-youtube-step"' in html
    assert 'id="settings-lastfm-host"' in html
    assert 'id="settings-support-panel"' not in html
    assert '/static/ai-settings.js?v=13' in html
    assert '/static/youtube-account.js?v=5' in html
    assert '/static/lastfm-settings.js?v=2' in html
    assert '/static/settings-page.css?v=' in html
    assert '/static/settings-page.js?v=5' in html


def test_settings_page_is_a_standalone_page_like_statistics_and_diagnostics() -> None:
    # Settings used to open in an iframe overlay; it now behaves like
    # statistics.html/diagnostics.html -- a real page reached via navigation, with
    # the same app-header/sidebar shell and no embedded/overlay-close machinery.
    html = _text("settings.html")
    script = _text("settings-page.js")
    style = _text("settings-page.css")

    assert '<header class="app-header">' in html
    assert 'id="settings-close"' not in html
    assert '/static/home-status.js?v=35' in html
    assert "settings-embedded" not in html
    assert "settings-embedded" not in script
    assert "settings-embedded" not in style
    assert "postMessage" not in script
    assert "PlaylistMuseSettingsOverlay" not in script


def test_settings_page_switches_sections_without_navigation_reload() -> None:
    script = _text("settings-page.js")

    assert "const SECTIONS = new Set(['ai', 'youtube', 'lastfm']);" in script
    assert "function selectSection(section" in script
    assert "panel?.classList.toggle('hidden', name !== selected);" in script
    assert "return $('settings-lastfm-host');" in script
    assert "window.history.replaceState" in script
    assert "window.PlaylistMuseSettingsSelect = selectSection;" in script
    assert "playlistmuse-ai-settings-opened" in script
    assert "playlistmuse-youtube-settings-opened" in script
    assert "playlistmuse-lastfm-settings-opened" in script


def test_integration_menu_opens_settings_page_via_shared_navigation_helper() -> None:
    common = _text("common.js")
    home_status = _text("home-status.js")

    assert "function openSettings(section)" in common
    assert "new URL('/static/settings.html', window.location.origin);" in common
    assert "window.location.assign(`${url.pathname}${url.search}`);" in common
    assert "window.PlaylistMuseSettingsSelect(target);" in common
    assert "readJson, setLoadingButton, openSettings" in common
    assert "window.PlaylistMuseCommon.openSettings(section);" in home_status
    assert "PlaylistMuseSettingsOverlay" not in home_status


def test_settings_overlay_files_are_removed() -> None:
    assert not (FRONTEND / "settings-overlay.js").exists()
    assert not (FRONTEND / "settings-overlay.css").exists()


def test_mobile_settings_layout_keeps_navigation_compact_and_clear() -> None:
    style = _text("settings-page.css")

    assert "grid-template-rows: auto minmax(0, 1fr);" in style
    assert "scroll-snap-type: x proximity;" in style


def test_diagnostics_actions_leave_space_before_following_hint() -> None:
    # Diagnostics moved to its own page, but its markup still relies on this shared
    # rule (settings-dialog.css, scoped to .settings-dialog-card so both diagnostics.html
    # and the AI/YouTube panels inside settings.html get consistent spacing) and on
    # settings-actions links stacking full-width on narrow screens.
    style = _text("settings-dialog.css")

    assert ".settings-dialog-card .settings-actions + .field-hint" in style
    assert "margin-top: 16px;" in style
    assert ".settings-dialog-card .settings-actions > a" in style


def test_youtube_publish_uses_the_shared_settings_navigation_helper() -> None:
    script = _text("youtube-publish.js")

    assert "window.PlaylistMuseCommon.openSettings('youtube');" in script
    assert "PlaylistMuseSettingsOverlay" not in script


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
