from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_settings_dialogs_share_the_same_visual_system() -> None:
    ai_styles = (FRONTEND / "ai-settings.css").read_text(encoding="utf-8")
    shared_styles = (FRONTEND / "settings-dialog.css").read_text(encoding="utf-8")
    youtube_styles = (FRONTEND / "youtube-settings.css").read_text(
        encoding="utf-8"
    )
    youtube_script = (FRONTEND / "youtube-account.js").read_text(encoding="utf-8")
    lastfm_script = (FRONTEND / "lastfm-settings.js").read_text(encoding="utf-8")

    assert '@import url("/static/settings-dialog.css?v=7");' in ai_styles
    assert ".settings-dialog-card .ai-active-summary" in shared_styles
    assert ".settings-dialog-card .youtube-account-summary" in shared_styles
    assert ".settings-dialog-card .settings-summary" in shared_styles
    assert ".settings-dialog-card .settings-state.ok" in shared_styles
    assert ":has(#setup-progress.hidden) .dialog-head" in shared_styles
    assert "#setup-dialog .setup-step.settings-block" in shared_styles
    assert "padding: 12px 0" in shared_styles
    assert "margin: 0 0 16px" in shared_styles
    assert "font-size: 1rem" in shared_styles
    assert "min-height: 36px" in shared_styles
    assert ".youtube-account-summary-heading h3" in shared_styles
    assert ".youtube-credentials-section > h3" in shared_styles
    assert "display: none" in shared_styles
    assert "#ai-settings-dialog" not in shared_styles
    assert "#youtube-settings-dialog" not in shared_styles

    assert ".ai-active-summary" not in ai_styles
    assert '.settings-fields > label[for="ai-provider"]' in ai_styles
    assert ".ai-provider-selection > .settings-status.ok" in ai_styles

    assert ".youtube-account-state" not in youtube_styles
    assert ".youtube-account-summary" not in youtube_styles
    assert ".youtube-account-profile" in youtube_styles

    assert "YouTube Music account connected." in youtube_script
    assert "saveButton.classList.add('primary')" in youtube_script
    assert "setAccountStatus('Connected', 'ok')" in youtube_script

    assert 'class="settings-summary"' in lastfm_script
    assert 'class="settings-status settings-state"' in lastfm_script
    assert "Last.fm API connected." in lastfm_script
    assert "setStatus('Configured', 'ok')" in lastfm_script
    assert "setStatus('Not configured')" in lastfm_script


def test_youtube_settings_panel_lives_on_dedicated_settings_page() -> None:
    settings_html = (FRONTEND / "settings.html").read_text(encoding="utf-8")
    playlist_html = (FRONTEND / "playlist.html").read_text(encoding="utf-8")

    assert 'id="setup-youtube-step"' in settings_html
    assert 'data-settings-section="youtube"' in settings_html
    assert 'id="youtube-settings-dialog"' not in playlist_html


def test_settings_page_reuses_shared_button_components() -> None:
    settings_html = (FRONTEND / "settings.html").read_text(encoding="utf-8")
    settings_styles = (FRONTEND / "settings-page.css").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="/static/controls.css?v=11">' in settings_html
    assert 'id="settings-close"' not in settings_html
    assert "settings-close-button" not in settings_html
    assert ".settings-close-button" not in settings_styles
