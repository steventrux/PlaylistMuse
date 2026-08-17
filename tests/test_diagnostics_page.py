from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_diagnostics_page_exposes_the_moved_support_content() -> None:
    html = _text("diagnostics.html")

    assert 'id="support-build-info"' in html
    assert 'href="/api/diagnostics/report"' in html
    assert 'template=bug_report.yml' in html
    assert 'class="settings-page-content settings-dialog-card"' in html
    assert '/static/diagnostics-client.js?v=1' in html
    assert '/static/support.js?v=' in html


def test_diagnostics_link_in_the_sidebar_navigates_directly_instead_of_opening_the_overlay() -> None:
    script = _text("common.js")

    assert "href=\"/static/diagnostics.html\"" in script
    assert "PlaylistMuseSettingsOverlay.open('support')" not in script
    assert "data-settings-section=\"support\"" not in script


def test_diagnostics_page_is_reachable_from_the_primary_navigation_bar() -> None:
    script = _text("common.js")

    assert "path.endsWith('/diagnostics.html')" in script


def test_sidebar_active_link_has_no_colored_accent_bar() -> None:
    style = _text("header-navigation.css")

    assert ".sidebar-link.active::before" not in style
    assert "background: var(--brand-gradient);" in style  # still used elsewhere (e.g. hero text)


def test_statistics_is_the_last_sidebar_group() -> None:
    # Integrations is authored before Insights in the static template, and the
    # dynamically-injected Support group is inserted before Insights rather than
    # appended -- so Statistics ends up last, right above the sidebar footer.
    home_status = _text("home-status.js")
    common = _text("common.js")

    assert home_status.index('aria-labelledby="sidebar-integrations-label"') < home_status.index(
        'aria-labelledby="sidebar-insights-label"'
    )
    assert "insightsGroup.before(group);" in common
