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
        '<script src="/static/ai-settings.js?v=10"></script>'
    )
    assert index.index(common) < index.index(
        '<script src="/static/youtube-account.js?v=4"></script>'
    )
    assert index.index(common) < index.index(
        '<script src="/static/home-status.js?v=12"></script>'
    )
    assert index.index(common) < index.index('<script src="/static/app.js?v=13"></script>')
    assert index.index('<script src="/static/home-status.js?v=12"></script>') < (
        index.index('<script src="/static/app.js?v=13"></script>')
    )
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

    assert '<link rel="stylesheet" href="/static/layout.css?v=2">' in index
    assert '<link rel="stylesheet" href="/static/layout.css?v=2">' in playlist
    assert ".hero" in layout
    assert "max-width: none" in layout
    assert "padding-right: .08em" in layout
    assert "overflow: visible" in layout


def test_footer_indicators_replace_header_badges_and_open_settings() -> None:
    index = _html("index.html")
    playlist = _html("playlist.html")
    status = _script("home-status.js")
    publish = _script("youtube-publish.js")
    layout = _style("layout.css")

    assert 'id="home-ai-status"' not in index
    assert 'id="home-yt-status"' not in index
    assert 'class="home-status"' not in index
    assert "footer-ai-status" in status
    assert "footer-youtube-status" in status
    assert "brain-outline" in status
    assert "brain-bolt" in status
    assert "youtube-body" in status
    assert "data-tooltip" in status
    assert "element.dataset.tooltip = tooltip" in status
    assert "homeAiSettings.click()" in status
    assert "$('setup-next')?.click()" in status
    assert "$('youtube-open-settings').click()" in status
    assert "window.location.assign('/')" in status
    assert "home-status.js?v=12" in publish
    assert '<script src="/static/youtube-publish.js?v=11"></script>' in playlist
    assert ".footer-indicator.youtube.on" in layout
    assert "var(--brand-gradient-soft)" not in layout or "#ff0000" not in layout
    assert "rgba(236, 72, 153" in layout
    assert "rgba(56, 189, 248" in layout
    assert "#ff0000" not in layout.lower()


def test_results_page_exposes_only_youtube_settings() -> None:
    playlist = _html("playlist.html")
    youtube_publish = _script("youtube-publish.js")

    assert 'id="youtube-settings-dialog"' in playlist
    assert 'id="ai-settings-dialog"' not in playlist
    assert 'id="setup-dialog"' not in playlist
    assert "playlistmuse-youtube-settings-opened" in youtube_publish
