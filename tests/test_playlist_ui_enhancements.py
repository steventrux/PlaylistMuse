from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_sidebar_replaces_header_shortcuts_and_keeps_provider_status_dynamic() -> None:
    style = _text("header-navigation.css")
    script = _text("home-status.js")

    assert ".library-header-link {\n  display: none !important;" in style
    assert ".playlistmuse-sidebar" in style
    assert ".sidebar-menu-toggle" in style
    assert "sidebar-menu-toggle" in script
    assert "header-service-status" in script
    assert "header-lastfm-status" in script
    assert "element.dataset.provider = provider || '';" in script
    assert "providerIcons[provider] || brainIcon" in script
    assert '#header-ai-status.on[data-provider="openai"]::after' in style
    assert '#header-ai-status.on[data-provider="gemini"]::after' in style
    assert "Not configured" in style
    assert "Configuration error" in style


def test_primary_pages_use_compact_tabs_above_main_cards() -> None:
    script = _text("common.js")
    style = _text("primary-navigation.css")

    assert "function primaryNavigationTarget()" in script
    assert "function installPrimaryNavigationTabs()" in script
    assert "/static/primary-navigation.css?v=1" in script
    assert 'aria-labelledby="sidebar-pages-label"' in script
    assert "pageGroup.remove();" in script
    assert "target.prepend(tabs);" in script
    assert "installPrimaryNavigationTabs();" in script
    assert ".primary-page-tabs" in style
    assert ".primary-page-tab.active" in style
    assert "--primary-navigation-tab-height: 32px;" in style
    assert "overflow: visible;" in style
    assert "top: calc(-1 * (var(--primary-navigation-tab-height) + var(--primary-navigation-tab-gap)));" in style
    assert "border-radius: 16px;" in style
    assert "font-size: .78rem;" in style
    assert 'primary-page-tab[aria-current="page"]' in style


def test_results_allow_manual_reordering_only_before_publication() -> None:
    html = _text("playlist.html")
    script = _text("playlist.js")
    style = _text("playlist-reorder.css")

    assert "/static/playlist-reorder.css?v=1" in html
    assert 'href="/static/library.html"' in html
    assert "function moveTrack(fromIndex, toIndex)" in script
    assert "if (\n      isPublished()" in script
    assert "handle.draggable = true" in script
    assert "Drag to reorder" in script
    assert "Move up" in script
    assert "Move down" in script
    assert "savePlaylist({immediate: true})" in script
    assert "if (!isPublished())" in script
    assert ".track-result-card.reorderable" in style
    assert ".track-result-card.drag-over" in style


def test_library_cards_match_compact_result_card_proportions_and_expand() -> None:
    html = _text("library.html")
    script = _text("library.js")
    style = _text("library.css")

    assert "/static/library.js?v=8" in html
    assert "let expandedLibraryId = null;" in script
    assert "function toggleLibraryCard(card, item)" in script
    assert "library-expand-icon" in script
    assert "library-details" in script
    assert "Initial request" in script
    assert "Original request" not in script
    assert "function refinementPrompts(generationRequest)" in script
    assert "function hydrateRefinementHistory(item, block)" in script
    assert "strong.textContent = 'Refinements';" in script
    assert "data-request-history" in script
    assert "Playlist details" in script
    assert "Created ${formatDate(item.created_at)}" in script
    assert ".library-item.expanded" in style
    assert "grid-template-columns: 54px minmax(0, 1fr) 28px;" in style
    assert "grid-template-rows: 54px;" in style
    assert "width: 54px;" in style
    assert "grid-template-columns: 48px minmax(0, 1fr) 24px;" in style
    assert "width: 138px;" in style
    assert "width: 96px;" in style


def test_library_searches_playlist_copy_and_filters_status_without_backend_queries() -> None:
    html = _text("library.html")
    script = _text("library.js")
    style = _text("library.css")

    assert 'id="library-search"' in html
    assert 'data-status-filter="all"' in html
    assert 'data-status-filter="draft"' in html
    assert 'data-status-filter="published"' in html
    assert "let activeStatusFilter = 'all';" in script
    assert "function matchesSearch(item, query)" in script
    assert "item.name," in script
    assert "item.description," in script
    assert "item.prompt," in script
    assert "tagTools?.searchValues(item)" in script
    assert "function visibleLibraryItems()" in script
    assert "item.status === activeStatusFilter" in script
    assert "$('library-search').addEventListener('input', resetPageAndRenderLibrary);" in script
    assert "function resetPageAndRenderLibrary()" in script
    assert "currentPage = 1;" in script
    assert "No playlists match the current search and filters." in script
    assert ".library-controls" in style
    assert ".library-filter.active" in style


def test_library_heading_is_compact_and_count_tracks_visible_results() -> None:
    html = _text("library.html")
    script = _text("library.js")
    style = _text("library-heading.css")

    assert "/static/library-heading.css?v=2" in html
    assert '<h2 id="library-heading">My playlists</h2>' in html
    assert 'id="library-count"' in html
    assert '<p class="eyebrow">Playlist library</p>' not in html
    assert "Generated playlists are saved locally and remain available across container restarts." not in html
    assert "function updateLibraryCount(count)" in script
    assert "updateLibraryCount(items.length);" in script
    assert "count === 1 ? 'playlist' : 'playlists'" in script
    assert ".library-title-line" in style
    assert ".library-count" in style
    assert "border-bottom: 1px solid" in style
    assert ".library-intro" not in style
    assert ".library-heading-row .eyebrow" not in style


def test_selected_seed_matches_compact_card_layout_and_restrained_palette() -> None:
    html = _text("index.html")
    style = _text("controls.css")

    assert "/static/controls.css?v=8" in html
    assert ".selected-seed {" in style
    assert "grid-template-columns: 54px minmax(0, 1fr) auto;" in style
    assert "background: rgba(21, 26, 51, .86);" in style
    assert "box-shadow: none;" in style
    assert ".selected-seed img" in style
    assert "width: 54px;" in style
    assert "grid-template-columns: 48px minmax(0, 1fr) auto;" in style
    assert "width: 48px;" in style
