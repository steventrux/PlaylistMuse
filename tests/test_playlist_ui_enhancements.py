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
    assert "right: 0;" in style
    assert "left: -54px;" not in style
    assert "inset: 0 0 0 auto;" in style
    assert "border-left: 1px solid" in style
    assert "transform: translateX(102%);" in style
    assert "box-shadow: -28px 0 70px" in style
    assert "sidebar-menu-toggle" in script
    assert "header-service-status" in script
    assert "header-lastfm-status" in script
    assert "element.dataset.provider = provider || '';" in script
    assert "providerIcons[provider] || brainIcon" in script
    assert "element.dataset.providerLabel = label || '';" in script
    assert "knownCustomHosts[host] || `Custom · ${host}`" in script
    assert '#header-ai-status.on::after { content: attr(data-provider-label) " · Configured"; }' in style
    assert "Not configured" in style
    assert "Configuration error" in style


def test_primary_pages_use_minimal_navigation_beneath_brand() -> None:
    script = _text("common.js")
    style = _text("primary-navigation.css")

    assert "function primaryNavigationHost()" in script
    assert "path.endsWith('/playlist.html')" in script
    assert "function installPrimaryNavigation()" in script
    assert "/static/primary-navigation.css?v=2" in script
    assert "const PRIMARY_PAGES = [" in script
    assert "host.classList.add('has-primary-page-navigation');" in script
    assert "host.append(navigation);" in script
    assert "installPrimaryNavigation();" in script
    assert ".primary-page-navigation" in style
    assert ".primary-page-link.active" in style
    assert ".app-header.has-primary-page-navigation" in style
    assert "background: var(--brand-gradient);" in style
    assert "font-size: .8rem;" in style
    assert "left: 50px;" not in style
    assert "left: 44px;" not in style
    assert 'primary-page-link[aria-current="page"]' in style


def test_primary_card_titles_are_not_duplicated_in_content() -> None:
    home = _text("index.html")
    library = _text("library.html")

    assert '<h2>Create a playlist</h2>' not in home
    assert 'class="hero card" aria-label="Create playlist"' in home
    assert '<h2 id="library-heading">My playlists</h2>' not in library
    assert 'class="card library-card" aria-label="My playlists"' in library


def test_results_page_reuses_shared_navigation_controls_and_card_palette() -> None:
    html = _text("playlist.html")
    card_style = _text("playlist-cards.css")
    header_style = _text("playlist-header.css")

    assert '/static/style.css?v=13' in html
    assert '/static/controls.css?v=12' in html
    assert '/static/header-navigation.css?v=25' in html
    assert '/static/playlist-cards.css?v=5' in html
    assert '/static/playlist-header.css?v=13' in html
    assert 'class="playlist-toolbar"' not in html
    assert 'class="secondary new-playlist-link"' not in html
    assert ".new-playlist-link" not in header_style
    assert "background: var(--item-bg-hover);" in card_style
    assert "box-shadow: none;" in card_style
    assert "linear-gradient(" not in card_style


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

    assert "/static/library.js?v=16" in html
    assert "/static/library.css?v=14" in html
    assert "let expandedLibraryId = null;" in script
    assert "function toggleLibraryCard(card, item)" in script
    assert "function setLibraryCardExpanded(card, expanded)" in script
    assert "const expandIcon = document.createElement('button');" in script
    assert "expandIcon.addEventListener('click'" in script
    assert "if (card.classList.contains('expanded')) return;" in script
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
    assert "cursor: default;" in style
    assert ".library-expand-icon:hover" in style
    assert "grid-template-columns: 54px minmax(0, 1fr) 28px;" in style
    assert "grid-template-rows: 54px;" in style
    assert "width: 54px;" in style
    assert "grid-template-columns: 48px minmax(0, 1fr) 24px;" in style
    assert "width: 138px;" in style
    assert "width: 96px;" in style


def test_library_tag_filter_keeps_expanded_card_open_and_selected() -> None:
    script = _text("library.js")
    tags = _text("library-tags.js")

    assert "function renderLibraryAfterTagFilter()" in script
    assert "items.findIndex((item) => item.id === expandedLibraryId)" in script
    assert "currentPage = Math.floor(expandedIndex / PAGE_SIZE) + 1;" in script
    assert "tagTools?.bindFilters(renderLibraryAfterTagFilter);" in script
    assert "element.classList.toggle('active', active);" in tags
    assert "element.setAttribute('aria-pressed', String(active));" in tags
    assert "toggleFilter(value);" in tags
    assert "renderLibrary?.();" in tags


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


def test_library_count_sits_below_filters_and_reports_filtered_total() -> None:
    html = _text("library.html")
    script = _text("library.js")
    style = _text("library-heading.css")

    assert "/static/library-heading.css?v=4" in html
    assert '<h2 id="library-heading">My playlists</h2>' not in html
    assert 'class="library-count-row"' in html
    assert 'id="library-count"' in html
    assert html.index('class="library-controls"') < html.index('class="library-count-row"')
    assert "function updateLibraryCount(visibleCount)" in script
    assert "const totalCount = libraryItems.length;" in script
    assert "visibleCount === totalCount" in script
    assert "count.append(countNumber(visibleCount), ' of ', countNumber(totalCount), noun);" in script
    assert "updateLibraryCount(items.length);" in script
    assert ".library-count-row" in style
    assert ".library-count" in style
    assert ".library-count-number" in style
    assert "border:" not in style
    assert "background:" not in style
    assert "color: var(--text-muted);" in style


def test_selected_seed_matches_compact_card_layout_and_restrained_palette() -> None:
    html = _text("index.html")
    style = _text("controls.css")

    assert "/static/controls.css?v=12" in html
    assert ".selected-seed {" in style
    assert "grid-template-columns: 54px minmax(0, 1fr) auto;" in style
    assert "background: var(--item-bg-hover);" in style
    assert "box-shadow: none;" in style
    assert ".selected-seed img" in style
    assert "width: 54px;" in style
    assert "grid-template-columns: 48px minmax(0, 1fr) auto;" in style
    assert "width: 48px;" in style
