from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_music_rankings_show_top_ten_and_paginate_in_place() -> None:
    # "See all" used to navigate to statistics-detail.html, then it expanded the
    # full ranking inline in one jump; a list with 1000+ entries (e.g. artists)
    # made that jump unwieldy, so it now reveals SHOW_MORE_INCREMENT items at a
    # time instead of the whole list at once.
    html = _text("statistics.html")
    script = _text("statistics.js")

    for toggle_id in (
        "stats-artist-list-toggle",
        "stats-genre-chips-toggle",
        "stats-mood-chips-toggle",
        "stats-period-chips-toggle",
        "stats-custom-tag-list-toggle",
    ):
        assert f'id="{toggle_id}"' in html
        assert f'<a class="stats-see-all-link" id="{toggle_id}"' not in html
    assert "Show more" in html
    assert "href=\"/static/statistics-detail.html" not in html
    assert "const OVERVIEW_LIMIT = 10;" in script
    assert "const SHOW_MORE_INCREMENT = 10;" in script
    assert "function toggleRanking(ranking)" in script
    assert "state.visibleCount + SHOW_MORE_INCREMENT" in script


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


def test_genres_moods_periods_avoid_chip_clouds() -> None:
    # Genres/moods/periods used to be chip clouds -- the detail drill-down page
    # (the untruncated "See all" list) still renders through the shared
    # ranked-list component; the Music panels themselves use bar charts (see
    # test_music_top_dimensions_use_bar_charts_like_advanced_stats below).
    render = _text("statistics-render.js")
    statistics_js = _text("statistics.js")
    detail_js = _text("statistics-detail.js")
    style = _text("statistics.css")

    assert "function renderChips" not in render
    assert "renderChips" not in statistics_js
    assert "renderChips" not in detail_js
    assert "renderRankList" in detail_js
    assert ".stats-chip-cloud" not in style
    assert ".stats-chip {" not in style


def test_music_top_dimensions_use_bar_charts_like_advanced_stats() -> None:
    # Top artists/genres/moods/periods now adopt the same horizontal-bar visual
    # language as the Advanced/Cache panels (proportional bars, not numbered
    # lists), per an explicit request to make every Music subcategory match the
    # Advanced page's style.
    html = _text("statistics.html")
    statistics_js = _text("statistics.js")

    assert "renderRankList" not in statistics_js
    assert "function renderBarRanking(" in statistics_js
    assert "stats-bar-row" in statistics_js
    assert 'id="stats-artist-list" class="stats-bar-list"' in html
    assert 'id="stats-genre-chips" class="stats-bar-list"' in html
    assert 'id="stats-mood-chips" class="stats-bar-list"' in html
    assert 'id="stats-period-chips" class="stats-bar-list"' in html
    assert 'id="stats-custom-tag-list" class="stats-bar-list"' in html


def test_music_ranking_rows_link_to_a_filtered_library() -> None:
    # Clicking an artist/genre/mood/period/personal-tag entry should navigate to
    # the Library page pre-filtered to that value, rather than being inert text.
    script = _text("statistics.js")

    assert "linkParam: 'artist'" in script
    assert "linkParam: 'tag'" in script
    assert "document.createElement(linkParam ? 'a' : 'div')" in script
    assert "/static/library.html?${linkParam}=${encodeURIComponent(item.label)}" in script


def test_advanced_stats_uses_bar_charts_instead_of_ranked_lists() -> None:
    # Advanced statistics visualizes proportional/comparative technical data
    # (per-stage timing, cache hit rate) as horizontal bars rather than the
    # ranked-list component used for rankings elsewhere -- a deliberate departure
    # for this page's more visual, dashboard-style presentation.
    advanced_js = _text("statistics-advanced.js")
    advanced_style = _text("statistics-advanced.css")

    assert "renderRankList" not in advanced_js
    assert "stats-bar-list" in advanced_js
    assert ".stats-bar-fill" in advanced_style
    assert ".stats-bar-track" in advanced_style


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


def test_advanced_stats_has_no_recorded_since_hint() -> None:
    html = _text("statistics.html")
    style = _text("statistics-advanced.css")

    assert "only recorded for generations" not in html
    assert "stats-nerd-hint" not in html
    assert "stats-nerd-hint" not in style


def test_multi_child_panels_have_breathing_room_between_their_sections() -> None:
    # #stats-advanced-content and #stats-cache-content each stack more than one
    # top-level block (tabs + detail card, or the cache card) inside one panel,
    # so they need the same gap the old flush-card layout was missing.
    style = _text("statistics.css")

    assert "display: grid;" in style
    assert "gap: 20px;" in style
    assert "#stats-advanced-content," in style
    assert "#stats-cache-content {" in style


def test_statistics_page_is_organized_into_sidebar_categories() -> None:
    # Statistics mirrors the Diagnostics page's shell: one page, a sidebar with
    # icon + label categories grouped under "Music" and "Technical", and a
    # single visible panel switched client-side instead of separate
    # de-emphasized pages -- every music dimension (artists/genres/moods/
    # periods/timeline) is its own subcategory of Music, not one long panel.
    html = _text("statistics.html")
    script = _text("statistics-page.js")

    assert "settings-page-shell" in html
    for section in (
        "overview", "timeline", "artists", "genres", "moods", "periods", "tags", "taste", "advanced", "cache",
    ):
        assert f'data-stats-section="{section}"' in html
        assert f'id="stats-{section}-panel"' in html
    assert (
        "SECTIONS = new Set(['overview', 'timeline', 'artists', 'genres', "
        "'moods', 'periods', 'tags', 'taste', 'advanced', 'cache'])"
    ) in script
    assert "function selectSection(section" in script


def test_timeline_bar_height_reserves_room_for_the_month_label() -> None:
    # A 100%-of-max bar used to overflow its column and get clipped by the card's
    # rounded corners; the bar height must leave room for the label + gap below it.
    script = _text("statistics.js")
    style = _text("statistics.css")

    assert "calc((100% - 20px) * ${ratio})" in script
    assert ".stats-timeline-col {" in style
    assert ".stats-timeline-month {" in style


def test_taste_memory_section_is_wired_like_every_other_stats_section() -> None:
    html = _text("statistics.html")
    page_script = _text("statistics-page.js")
    render_script = _text("local-taste-memory.js")

    assert 'data-stats-section="taste"' in html
    assert 'id="stats-taste-panel"' in html
    assert 'id="taste-memory-list"' in html
    assert "'taste'" in page_script
    assert "taste: 'Taste memory'" in page_script
    assert "const ENDPOINT = '/api/quality/local-feedback';" in render_script
    assert '/static/local-taste-memory.js?v=1' in html
    assert '/static/statistics-page.js?v=4' in html
    assert '/static/statistics.css?v=13' in html
