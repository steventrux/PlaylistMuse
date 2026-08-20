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


def test_support_is_the_last_sidebar_group() -> None:
    # Integrations is authored before Library (Favorites/Statistics) in the
    # static template, and the dynamically-injected Support group is inserted
    # right after Library rather than appended blindly -- so Support ends up
    # last, right above the sidebar footer, with Library immediately before it.
    home_status = _text("home-status.js")
    common = _text("common.js")

    assert home_status.index('aria-labelledby="sidebar-integrations-label"') < home_status.index(
        'aria-labelledby="sidebar-library-label"'
    )
    assert "libraryGroup.after(group);" in common


def test_sidebar_links_have_no_tooltip() -> None:
    # Favorites/Statistics/Diagnostics each got a descriptive tooltip, tried as
    # both a `::after { content: attr(data-tooltip) }` pseudo-element and (after
    # that rendered translucent in one browser) as a real child <span> with a
    # solid rgb() background and a visibility-based (non-fading) reveal instead
    # of opacity. Both still rendered translucent, reproducing identically
    # across multiple browsers and in incognito -- ruling out caching, a
    # browser extension, and a mid-fade screenshot timing race. With the root
    # cause unresolved, the feature was removed rather than left half-broken;
    # these links are back to plain, tooltip-less `.sidebar-link`s.
    home_status = _text("home-status.js")
    common = _text("common.js")
    style = _text("header-navigation.css")

    assert "sidebar-link-tooltip" not in home_status
    assert "sidebar-link-tooltip" not in common
    assert "sidebar-link-tooltip" not in style
    assert 'data-tooltip="' not in home_status
    assert 'data-tooltip="' not in common

    favorites_link_start = home_status.index('data-page="favorites"')
    favorites_link_markup = home_status[favorites_link_start:favorites_link_start + 300]
    assert "title=" not in favorites_link_markup
    assert "content: attr(data-tooltip)" not in style


def test_integration_indicators_use_only_the_custom_tooltip() -> None:
    # Regression: setIndicatorState() also set the native `title` attribute,
    # stacking Chrome's own tooltip on top of the custom CSS one for the
    # Integrations status rows (AI/YouTube Music/Last.fm).
    home_status = _text("home-status.js")

    assert "function setIndicatorState(element, state, tooltip) {" in home_status
    set_indicator_start = home_status.index("function setIndicatorState(element, state, tooltip) {")
    set_indicator_body = home_status[set_indicator_start:set_indicator_start + 300]
    assert "element.dataset.tooltip = tooltip;" in set_indicator_body
    assert "element.title = tooltip;" not in set_indicator_body


def test_all_site_tooltips_are_fully_opaque() -> None:
    # Regression: a translucent tooltip background (rgba(8, 11, 27, .96)) was
    # hard to read when it opened over other sidebar text underneath it.
    header_navigation_style = _text("header-navigation.css")
    layout_style = _text("layout.css")

    assert "rgba(8, 11, 27, .96)" not in header_navigation_style
    assert "rgba(8, 11, 27, .96)" not in layout_style
    assert "background: rgba(8, 11, 27, 1);" in layout_style


def test_remaining_tooltips_toggle_with_visibility_not_an_opacity_fade() -> None:
    # The Integrations status tooltip (layout.css) and the Favorites Overview
    # info icon (favorites.css) still use the visibility-based (non-fading)
    # reveal adopted while chasing the sidebar-link tooltip transparency bug --
    # a screenshot taken right after a simulated hover, with no artificial
    # delay, can land mid opacity-transition and render an otherwise fully
    # opaque tooltip as partly see-through. Neither of these two was reported
    # broken, so they were left as-is when the unrelated sidebar-link tooltips
    # were removed.
    layout_style = _text("layout.css")
    favorites_style = _text("favorites.css")

    for style in (layout_style, favorites_style):
        assert "visibility: hidden;" in style
        assert "visibility: visible;" in style
        assert "transition: opacity 150ms ease, transform 150ms ease;" not in style


def test_sidebar_integration_status_pills_stay_visible_without_hovering() -> None:
    # Regression: .header-indicator::after means two different things depending
    # on context -- outside the sidebar it's a hover tooltip (now visibility:
    # hidden by default, see the fade-fix tests above); *inside* the sidebar a
    # more specific rule repurposes the same pseudo-element as an always-visible
    # "Configured"/"Not configured" status pill under each service name. That
    # more specific rule never declared its own `visibility`, so it silently
    # inherited `visibility: hidden` from the (unrelated) hover-tooltip default
    # once that was added -- hiding the AI/YouTube Music/Last.fm status pills
    # entirely except while actively hovering that exact row.
    style = _text("header-navigation.css")

    pill_rule_start = style.index(".playlistmuse-sidebar .header-indicator::after {")
    pill_rule_end = style.index("}", pill_rule_start)
    pill_rule = style[pill_rule_start:pill_rule_end]
    assert "visibility: visible;" in pill_rule
