from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
STATIC_REFERENCE_RE = re.compile(r'(?:src|href)="/static/([^"?]+)(?:\?[^" ]*)?"')


def _html(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def _script(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def _style(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_html_static_references_exist() -> None:
    for html_name in ("index.html", "playlist.html"):
        for relative_path in STATIC_REFERENCE_RE.findall(_html(html_name)):
            assert (FRONTEND / relative_path).is_file(), (
                f"{html_name} references missing static asset {relative_path}"
            )


def test_shared_frontend_helpers_load_before_dependents() -> None:
    index = _html("index.html")
    playlist = _html("playlist.html")
    common = '<script src="/static/common.js?v=1"></script>'

    assert index.index(common) < index.index(
        '<script src="/static/ai-settings.js?v=11"></script>'
    )
    assert index.index(common) < index.index(
        '<script src="/static/youtube-account.js?v=4"></script>'
    )
    assert index.index(common) < index.index(
        '<script src="/static/home-status.js?v=13"></script>'
    )
    assert index.index(common) < index.index('<script src="/static/app.js?v=13"></script>')
    assert index.index('<script src="/static/home-status.js?v=13"></script>') < (
        index.index('<script src="/static/app.js?v=13"></script>')
    )

    ai_results = '<script src="/static/ai-results-settings.js?v=1"></script>'
    ai_settings = '<script src="/static/ai-settings.js?v=11"></script>'
    home_status = (
        '<script data-playlistmuse-footer-status '
        'src="/static/home-status.js?v=13"></script>'
    )
    assert playlist.index(common) < playlist.index(ai_results)
    assert playlist.index(ai_results) < playlist.index(ai_settings)
    assert playlist.index(ai_settings) < playlist.index(home_status)
    assert playlist.index(common) < playlist.index(
        '<script src="/static/playlist.js?v=18"></script>'
    )
    assert playlist.index(common) < playlist.index(
        '<script src="/static/youtube-publish.js?v=11"></script>'
    )


def test_generation_requires_configured_ai_provider() -> None:
    index = _html("index.html")
    app = _script("app.js")
    home_status = _script("home-status.js")

    assert 'id="ai-generation-warning"' in index
    assert 'id="ai-open-settings"' in index
    assert re.search(
        r'<button id="generate"[^>]*\bhidden\b[^>]*\bdisabled\b[^>]*>',
        index,
    )
    assert "setGenerationAvailability(configured ? 'configured' : 'unconfigured')" in (
        home_status
    )
    assert "button.disabled = !configured" in home_status
    assert "button.classList.toggle('hidden', !configured)" in home_status
    assert "if (button.disabled) return;" in app
    assert "openSetup('ai', 'single')" in app


def test_first_run_setup_is_persistent_and_two_step() -> None:
    index = _html("index.html")
    app = _script("app.js")
    ai_settings = _script("ai-settings.js")
    youtube_account = _script("youtube-account.js")

    assert 'id="settings-btn"' not in index
    assert 'id="settings-dialog"' not in index
    assert 'id="setup-dialog"' in index
    assert 'id="setup-progress-ai"' in index
    assert 'id="setup-progress-youtube"' in index
    assert 'id="setup-ai-step"' in index
    assert 'id="setup-youtube-step"' in index
    assert 'id="setup-next"' in index
    assert 'id="setup-back"' in index
    assert 'id="setup-finish"' in index
    assert "/api/onboarding" in app
    assert "/api/onboarding/acknowledge" in app
    assert "openSetup('ai', 'onboarding')" in app
    assert app.index("openSetup('ai', 'onboarding')") < app.index(
        "void acknowledgeInitialSetup()"
    )
    assert "playlistmuse-ai-settings-opened" in ai_settings
    assert "playlistmuse-youtube-settings-opened" in youtube_account


def test_home_and_results_share_page_width_and_complete_wordmark() -> None:
    index = _html("index.html")
    playlist = _html("playlist.html")
    layout = _style("layout.css")

    assert '<link rel="stylesheet" href="/static/layout.css?v=3">' in index
    assert '<link rel="stylesheet" href="/static/layout.css?v=3">' in playlist
    assert ".hero" in layout
    assert "max-width: none" in layout
    assert "padding-right: .08em" in layout
    assert "overflow: visible" in layout


def test_header_indicators_show_active_provider_without_neon() -> None:
    index = _html("index.html")
    status = _script("home-status.js")
    layout = _style("layout.css")

    assert 'id="home-ai-status"' not in index
    assert 'id="home-yt-status"' not in index
    assert "header-ai-status" in status
    assert "header-youtube-status" in status
    assert "header-service-status" in status
    assert "createHeaderStatus" in status
    assert "document.body.append(footer)" not in status
    assert "brain-outline" in status
    assert "providerIcons" in status
    assert "gemini:" in status
    assert "openai:" in status
    assert "anthropic:" in status
    assert "openrouter_auto:" in status
    assert "ollama:" in status
    assert "custom:" in status
    assert "providerIcons[provider] || brainIcon" in status
    assert "youtube-body" in status
    assert "element.dataset.tooltip = tooltip" in status
    assert "homeAiSettings.click()" in status
    assert "$('setup-next')?.click()" in status
    assert "$('youtube-open-settings').click()" in status
    assert "window.location.assign('/')" in status
    assert ".header-indicator.ai.on" in layout
    assert ".header-indicator.youtube.on" in layout
    assert "width: 32px" in layout
    assert "height: 32px" in layout
    assert "width: 19px" in layout
    assert layout.count("box-shadow: none;") >= 3
    assert "0 0 14px" not in layout
    assert "0 0 20px" not in layout
    assert "#ff0000" not in layout.lower()


def test_ai_settings_can_manage_and_activate_multiple_profiles() -> None:
    ai_settings = _script("ai-settings.js")

    assert "/api/ai/profiles" in ai_settings
    assert "/api/ai/activate" in ai_settings
    assert "/api/ai/providers/" in ai_settings
    assert "providerProfiles" in ai_settings
    assert "activeProvider" in ai_settings
    assert "Use this AI" in ai_settings
    assert "Disconnect" in ai_settings
    assert "activateSelectedProvider" in ai_settings
    assert "disconnectSelectedProvider" in ai_settings
    assert "profile.active ? '✓ ' : profile.configured ? '● ' : ''" in ai_settings
    assert "playlistmuse-status-changed" in ai_settings


def test_results_page_opens_ai_settings_without_losing_playlist() -> None:
    playlist = _html("playlist.html")
    bridge = _script("ai-results-settings.js")

    assert 'id="youtube-settings-dialog"' in playlist
    assert '/static/ai-results-settings.js?v=1' in playlist
    assert '/static/ai-settings.js?v=11' in playlist
    assert "ai-settings-dialog" in bridge
    assert "#header-ai-status" in bridge
    assert "dialog.showModal()" in bridge
    assert "event.stopImmediatePropagation()" in bridge
    assert "playlistmuse-ai-settings-opened" in bridge
    assert "window.location" not in bridge
    assert "sessionStorage.removeItem" not in bridge
    assert "playlistmuse-generated-playlist" not in bridge


def test_results_page_exposes_youtube_settings() -> None:
    playlist = _html("playlist.html")
    youtube_publish = _script("youtube-publish.js")

    assert 'id="youtube-settings-dialog"' in playlist
    assert "playlistmuse-youtube-settings-opened" in youtube_publish
