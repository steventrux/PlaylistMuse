from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_settings_dialogs_share_the_same_visual_system() -> None:
    ai_styles = (FRONTEND / "ai-settings.css").read_text(encoding="utf-8")
    shared_styles = (FRONTEND / "settings-dialog.css").read_text(encoding="utf-8")
    lastfm_script = (FRONTEND / "lastfm-settings.js").read_text(encoding="utf-8")

    assert '@import url("/static/settings-dialog.css?v=1");' in ai_styles
    assert ".settings-dialog-card .ai-active-summary" in shared_styles
    assert ".settings-dialog-card .youtube-account-summary" in shared_styles
    assert ".settings-dialog-card .settings-summary" in shared_styles
    assert ".settings-dialog-card .settings-state.ok" in shared_styles
    assert "#ai-settings-dialog .dialog-head h2::before" in shared_styles
    assert "#youtube-settings-dialog .dialog-head h2::before" in shared_styles

    assert 'class="settings-summary"' in lastfm_script
    assert 'class="settings-status settings-state"' in lastfm_script
    assert "setStatus('Configured', 'ok')" in lastfm_script
    assert "setStatus('Not configured')" in lastfm_script
