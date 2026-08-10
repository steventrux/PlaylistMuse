from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_sidebar_reuses_banner_and_shows_runtime_build_metadata() -> None:
    script = (FRONTEND / "home-status.js").read_text(encoding="utf-8")
    style = (FRONTEND / "header-navigation.css").read_text(encoding="utf-8")

    assert "const HEADER_BANNER_URL = '/static/playlistmuse-banner.svg?v=1';" in script
    assert 'class="sidebar-brand-banner" src="${HEADER_BANNER_URL}"' in script
    assert 'id="sidebar-build-version"' in script
    assert "fetch('/api/version', {cache: 'no-store'})" in script
    assert "version.textContent = info.display" in script
    assert "https://github.com/steventrux/PlaylistMuse" in script
    assert 'class="sidebar-repo-link"' in script
    assert "const githubIcon = `" in script
    assert ".sidebar-brand-banner" in style
    assert ".sidebar-build-version" in style
    assert ".sidebar-repo-link" in style


def test_sidebar_footer_no_longer_contains_configuration_hint() -> None:
    script = (FRONTEND / "home-status.js").read_text(encoding="utf-8")

    assert "Select an integration to open its configuration." not in script
