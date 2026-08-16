from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_overview_shows_top_five_and_links_to_the_full_detail_page() -> None:
    html = _text("statistics.html")
    script = _text("statistics.js")

    assert 'href="/static/statistics-detail.html?dim=artists"' in html
    assert 'href="/static/statistics-detail.html?dim=genres"' in html
    assert 'href="/static/statistics-detail.html?dim=moods"' in html
    assert 'href="/static/statistics-detail.html?dim=periods"' in html
    assert "See all" in html
    assert "const OVERVIEW_LIMIT = 5;" in script
    assert "function top(items)" in script


def test_top_artists_is_shown_before_top_genres() -> None:
    html = _text("statistics.html")

    assert html.index(">Top artists<") < html.index(">Top genres<")


def test_detail_page_renders_the_untruncated_list_for_each_dimension() -> None:
    html = _text("statistics-detail.html")
    script = _text("statistics-detail.js")

    assert "id=\"stats-detail-list\"" in html
    assert "genres: {title: 'All genres', key: 'top_genres'" in script
    assert "artists: {title: 'All artists', key: 'top_artists'" in script
    assert "moods: {title: 'All moods', key: 'top_moods'" in script
    assert "periods: {title: 'All periods', key: 'top_periods'" in script
    assert "renderRankList('stats-detail-list', 'stats-detail-empty', items);" in script


def test_every_stat_is_normalized_to_a_numbered_list() -> None:
    # Genres/moods/periods used to be chip clouds and the nerd page's provider/error
    # breakdowns used to be horizontal bars -- every stat now renders through the
    # same ranked-list component so the page doesn't mix three different visual
    # languages for the same kind of data.
    render = _text("statistics-render.js")
    statistics_js = _text("statistics.js")
    detail_js = _text("statistics-detail.js")
    nerd_html = _text("statistics-nerd.html")
    nerd_js = _text("statistics-nerd.js")
    nerd_style = _text("statistics-nerd.css")
    style = _text("statistics.css")

    assert "function renderChips" not in render
    assert "renderChips" not in statistics_js
    assert "renderChips" not in detail_js
    assert "class=\"stats-rank-list\"" in nerd_html
    assert "stats-mono-bar-list" not in nerd_html
    assert "renderRankList" in nerd_js
    assert "renderMonoBarList" not in nerd_js
    assert ".stats-mono-bar-list" not in nerd_style
    assert ".stats-chip-cloud" not in style
    assert ".stats-chip {" not in style


def test_telemetry_is_a_real_switch_with_an_explanation() -> None:
    html = _text("statistics.html")
    script = _text("statistics.js")
    style = _text("statistics.css")

    assert 'role="switch"' in html
    assert 'aria-checked="false"' in html
    assert "no installation ID, no prompt, and no playlist content attached" in html
    assert "It cannot identify you or this installation" in html
    assert "<input type=\"checkbox\"" not in html
    assert "function setToggleChecked(toggle, checked)" in script
    assert "toggle.setAttribute('aria-checked', String(checked));" in script
    assert ".stats-switch[aria-checked=\"true\"]" in style


def test_the_local_only_note_is_folded_into_the_telemetry_explanation() -> None:
    # The standalone "Local only" pill was redundant with the telemetry toggle's own
    # explanation -- the fact that everything else on the page stays local now lives
    # as the lead sentence of that explanation instead of a separate note.
    html = _text("statistics.html")
    style = _text("statistics.css")

    assert "Local only" not in html
    assert "nothing on this page is sent anywhere" not in html
    assert "Every statistic on this page is computed locally" in html
    assert ".stats-privacy-note" not in style


def test_nerd_stats_has_no_recorded_since_hint() -> None:
    html = _text("statistics-nerd.html")
    style = _text("statistics-nerd.css")

    assert "only recorded for generations" not in html
    assert "stats-nerd-hint" not in html
    assert "stats-nerd-hint" not in style


def test_stat_section_cards_have_breathing_room_between_them() -> None:
    # The section cards used to sit flush against each other (no gap between
    # boxes); #stats-content is shared by statistics.html and statistics-nerd.html
    # so both pick up the spacing.
    style = _text("statistics.css")

    assert "#stats-content {" in style
    assert "display: grid;" in style
    assert "gap: 20px;" in style


def test_timeline_bar_height_reserves_room_for_the_month_label() -> None:
    # A 100%-of-max bar used to overflow its column and get clipped by the card's
    # rounded corners; the bar height must leave room for the label + gap below it.
    script = _text("statistics.js")
    style = _text("statistics.css")

    assert "calc((100% - 20px) * ${ratio})" in script
    assert ".stats-timeline-col {" in style
    assert ".stats-timeline-month {" in style
