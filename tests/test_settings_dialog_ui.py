from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_settings_dialogs_share_the_same_visual_system() -> None:
    ai_styles = (FRONTEND / "ai-settings.css").read_text(encoding="utf-8")
    shared_styles = (FRONTEND / "settings-dialog.css").read_text(encoding="utf-8")
    youtube_script = (FRONTEND / "youtube-account.js").read_text(encoding="utf-8")
    lastfm_script = (FRONTEND / "lastfm-settings.js").read_text(encoding="utf-8")

    assert '@import url("/static/settings-dialog.css?v=2");' in ai_styles
    assert ".settings-dialog-card .ai-active-summary" in shared_styles
    assert ".settings-dialog-card .youtube-account-summary" in shared_styles
    assert ".settings-dialog-card .settings-summary" in shared_styles
    assert ".settings-dialog-card .settings-state.ok" in shared_styles
    assert "padding-top: 24px" in shared_styles
    assert ".youtube-account-summary-heading h3" in shared_styles
    assert "display: none" in shared_styles
    assert "#ai-settings-dialog .dialog-head h2::before" in shared_styles
    assert "#youtube-settings-dialog .dialog-head h2::before" in shared_styles

    assert '.settings-fields > label[for="ai-provider"]' in ai_styles
    assert ".ai-provider-selection > .settings-status.ok" in ai_styles

    assert "YouTube Music account connected." in youtube_script
    assert "saveButton.classList.add('primary')" in youtube_script
    assert "setAccountStatus('Connected', 'ok')" in youtube_script

    assert 'class="settings-summary"' in lastfm_script
    assert 'class="settings-status settings-state"' in lastfm_script
    assert "Last.fm API connected." in lastfm_script
    assert "setStatus('Configured', 'ok')" in lastfm_script
    assert "setStatus('Not configured')" in lastfm_script
