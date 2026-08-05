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
    generation_state = '<script src="/static/generation-state.js?v=2"></script>'
    app = '<script src="/static/app.js?v=17"></script>'

    assert index.index(common) < index.index(
        '<script src="/static/ai-settings.js?v=12"></script>'
    )
    assert index.index(common) < index.index(
        '<script src="/static/youtube-account.js?v=5"></script>'
    )
    assert index.index(common) < index.index(
        '<script src="/static/home-status.js?v=13"></script>'
    )
    assert generation_state in index
    assert index.index(generation_state) < index.index(app)
    assert index.index(common) < index.index(app)
    assert '<script src="/static/prompt-complexity.js?v=6"></script>' in index
    assert index.index('<script src="/static/home-status.js?v=13"></script>') < (
        index.index(app)
    )

    ai_results = '<script src="/static/ai-results-settings.js?v=2"></script>'
    ai_settings = '<script src="/static/ai-settings.js?v=12"></script>'
    home_status = (
        '<script data-playlistmuse-footer-status '
        'src="/static/home-status.js?v=13"></script>'
    )
    assert playlist.index(common) < playlist.index(ai_results)
    assert playlist.index(ai_results) < playlist.index(ai_settings)
    assert playlist.index(ai_settings) < playlist.index(home_status)
    assert playlist.index(common) < playlist.index(
        '<script src="/static/playlist.js?v=19"></script>'
    )
    assert playlist.index(common) < playlist.index(
        '<script src="/static/youtube-publish.js?v=13"></script>'
    )


def test_prompt_complexity_uses_simple_label_and_hides_positive_clarity_details() -> None:
    script = _script("prompt-complexity.js")

    assert "return level === 'Detailed' ? 'Simple' : level;" in script
    assert "displayLevel(result.level)" in script
    assert "['excellent', 'good'].includes(level.toLowerCase())" in script
    assert "return `Clarity: ${level}`;" in script
    assert "clarity.textContent = clarityText(result);" in script


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


def test_home_and_results_share_narrower_content_width_and_complete_wordmark() -> None:
    index = _html("index.html")
    playlist = _html("playlist.html")
    layout = _style("layout.css")

    assert '<link rel="stylesheet" href="/static/layout.css?v=4">' in index
    assert '<link rel="stylesheet" href="/static/layout.css?v=4">' in playlist
    assert "main,\n.playlist-shell" in layout
    assert "width: min(860px, calc(100% - 32px));" in layout
    assert ".hero" in layout
    assert "max-width: none" in layout
    assert "padding-right: .08em" in layout
    assert "overflow: visible" in layout


def test_seed_search_first_hover_has_top_clearance() -> None:
    style = _style("style.css")
    layout = _style("layout.css")

    assert "overflow-y: auto" in style
    assert ".seed-result:hover { transform: translateY(-1px)" in style
    assert ".seed-results" in layout
    assert "padding-top: 2px" in layout
    assert "scroll-padding-top: 2px" in layout


def test_seed_guidance_follows_search_and_selection() -> None:
    index = _html("index.html")
    app = _script("app.js")
    choose_text = (
        "Choose a track to use as the musical reference for the new playlist."
    )

    assert '<p id="seed-guidance" class="hint hidden" aria-live="polite"></p>' in index
    assert choose_text not in index
    assert "function setSeedGuidance(text = '')" in app
    assert "guidance.classList.toggle('hidden', !text)" in app
    assert choose_text in app
    assert "This playlist will be built around “${seed.title}” by ${seed.artists}." in app
    assert "setSeedGuidance('');\n    message('Searching YouTube Music…');" in app
    assert "change.addEventListener('click'" in app


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


def test_ai_settings_separate_active_and_selected_provider_states() -> None:
    index = _html("index.html")
    playlist = _html("playlist.html")
    bridge = _script("ai-results-settings.js")
    ai_settings = _script("ai-settings.js")
    ai_style = _style("ai-settings.css")
    shared_style = _style("settings-dialog.css")
    app = _script("app.js")

    assert '/static/ai-settings.css?v=3' in index
    assert '/static/ai-settings.css?v=3' in playlist
    assert '/static/app.js?v=17' in index
    assert 'id="ai-active-status"' in index
    assert 'id="ai-active-status"' in bridge
    assert "Choose or configure a provider" in index
    assert "Choose or configure a provider" in bridge
    assert "<strong>✓</strong> In use" in index
    assert "<strong>●</strong> Configured" in index
    assert "function renderActiveProviderStatus()" in ai_settings
    assert "Active AI provider: ${defaults.label}" in ai_settings
    assert "is configured and currently in use" in ai_settings
    assert "is configured and ready to activate" in ai_settings
    assert "is not configured. Save its settings" in ai_settings
    assert "intro.classList.toggle('hidden', !onboarding)" in app
    assert "Configure the AI provider used to generate and refine playlists." not in app
    assert "Configure and connect the YouTube Music account used for direct publishing." not in app
    assert '@import url("/static/settings-dialog.css?v=4");' in ai_style
    assert ".ai-active-summary" not in ai_style
    assert ".settings-dialog-card .ai-active-summary" in shared_style
    assert "margin: 0 0 20px" in shared_style
    assert "padding: 14px 0" in shared_style
    assert "border-bottom: 1px solid var(--border)" in shared_style
    assert "font-size: 1rem" in shared_style
    assert "font-weight: 800" in shared_style
    assert "padding: 8px 10px" in shared_style
    assert ":has(#setup-progress.hidden) .dialog-head" in shared_style


def test_results_page_opens_ai_settings_without_losing_playlist() -> None:
    playlist = _html("playlist.html")
    bridge = _script("ai-results-settings.js")

    assert 'id="youtube-settings-dialog"' in playlist
    assert '/static/ai-results-settings.js?v=2' in playlist
    assert '/static/ai-settings.js?v=12' in playlist
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


def test_youtube_settings_show_account_and_relevant_actions() -> None:
    index = _html("index.html")
    playlist = _html("playlist.html")
    youtube_account = _script("youtube-account.js")
    youtube_style = _style("youtube-settings.css")
    shared_style = _style("settings-dialog.css")

    assert '/static/youtube-settings.css?v=1' in index
    assert '/static/youtube-settings.css?v=1' in playlist
    assert '/static/youtube-account.js?v=5' in index
    assert '/static/youtube-account.js?v=5' in playlist
    assert "youtube-account-summary" in index
    assert "youtube-account-summary" in playlist
    assert "Google OAuth credentials" in index
    assert "Google OAuth credentials" in playlist
    assert ".youtube-credentials-section > h3" in shared_style
    assert "display: none" in shared_style
    assert "status.account_name || 'Connected YouTube Music account'" in youtube_account
    assert "status.channel_handle || 'Google account details unavailable'" in youtube_account
    assert "profile.classList.toggle('no-photo', !photoUrl)" in youtube_account
    assert "connect.classList.toggle('hidden', connected)" in youtube_account
    assert "disconnect.classList.toggle('hidden', !connected)" in youtube_account
    assert "setAccountStatus('Connected', 'ok')" in youtube_account
    assert ".youtube-account-summary" not in youtube_style
    assert ".youtube-account-state" not in youtube_style
    assert ".settings-dialog-card .youtube-account-summary" in shared_style
    assert ".youtube-account-profile.no-photo" in youtube_style
    assert "width: 100%" in youtube_style


def test_youtube_publish_progress_is_compact_and_not_redundant() -> None:
    playlist = _html("playlist.html")
    youtube_publish = _script("youtube-publish.js")
    youtube_results = _style("youtube-results.css")

    assert '/static/youtube-results.css?v=4' in playlist
    assert '/static/youtube-publish.js?v=13' in playlist
    assert (
        'id="youtube-publish-status" class="youtube-publish-status hidden"'
        in playlist
    )
    assert "Creating the playlist in your YouTube Music account" not in youtube_publish
    assert "setPublishState('publishing')" in youtube_publish
    assert "setPublishState('success')" in youtube_publish
    assert "setStatus('');" in youtube_publish
    assert (
        ".youtube-publish:not(.is-success) + "
        ".youtube-publish-status.hidden + .track-list"
        in youtube_results
    )
    assert "margin-top: 12px" in youtube_results


def test_published_playlist_hides_track_replacement_controls() -> None:
    playlist = _html("playlist.html")
    playlist_script = _script("playlist.js")
    youtube_publish = _script("youtube-publish.js")

    assert '/static/playlist.js?v=19' in playlist
    assert '/static/youtube-publish.js?v=13' in playlist
    assert 'id="youtube-publish-account"' not in playlist
    assert "YouTube Music account connected" not in playlist
    assert "function isPublished()" in playlist_script
    assert "if (!isPublished())" in playlist_script
    assert "replace-track-button" in playlist_script
    assert "playlistmuse-playlist-published" in playlist_script
    assert "playlistmuse-playlist-published" in youtube_publish
    assert "new CustomEvent" in youtube_publish
