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

    assert index.index(common) < index.index('<script src="/static/app.js?v=11"></script>')
    assert index.index(common) < index.index(
        '<script src="/static/ai-settings.js?v=10"></script>'
    )
    assert index.index(common) < index.index(
        '<script src="/static/youtube-account.js?v=4"></script>'
    )
    assert playlist.index(common) < playlist.index(
        '<script src="/static/playlist.js?v=18"></script>'
    )
    assert playlist.index(common) < playlist.index(
        '<script src="/static/youtube-publish.js?v=10"></script>'
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
    assert "setGenerationAvailability(connected ? 'configured' : 'unconfigured')" in (
        home_status
    )
    assert "button.disabled = !configured" in home_status
    assert "button.classList.toggle('hidden', !configured)" in home_status
    assert "if (button.disabled) return;" in app


def test_home_settings_are_split_by_service() -> None:
    index = _html("index.html")
    app = _script("app.js")
    ai_settings = _script("ai-settings.js")
    youtube_account = _script("youtube-account.js")

    assert 'id="settings-dialog"' in index
    assert 'id="ai-settings-dialog"' in index
    assert 'id="youtube-settings-dialog"' in index
    assert 'id="open-ai-settings"' in index
    assert 'id="open-youtube-settings"' in index
    assert "openDialog('ai-settings-dialog', 'playlistmuse-ai-settings-opened')" in app
    assert (
        "openDialog('youtube-settings-dialog', "
        "'playlistmuse-youtube-settings-opened')" in app
    )
    assert "playlistmuse-ai-settings-opened" in ai_settings
    assert "playlistmuse-youtube-settings-opened" in youtube_account


def test_results_page_exposes_only_youtube_settings() -> None:
    playlist = _html("playlist.html")
    youtube_publish = _script("youtube-publish.js")

    assert 'id="youtube-settings-dialog"' in playlist
    assert 'id="ai-settings-dialog"' not in playlist
    assert "playlistmuse-youtube-settings-opened" in youtube_publish
