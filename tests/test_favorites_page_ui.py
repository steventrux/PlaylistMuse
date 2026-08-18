from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_favorites_page_exists_and_mirrors_the_statistics_page_shell() -> None:
    html = _text("favorites.html")

    assert "favorites.js" in html
    assert "favorites.css" in html
    assert 'class="settings-page-shell"' in html
    assert 'data-favorites-section="overview"' in html
    assert 'data-favorites-section="artists"' in html
    assert 'data-favorites-section="songs"' in html
    assert 'id="favorites-overview-panel"' in html
    assert 'id="favorites-artists-panel"' in html
    assert 'id="favorites-songs-panel"' in html
    assert 'id="favorites-artist-count"' in html
    assert 'id="favorites-track-count"' in html


def test_favorites_are_only_added_via_heart_icons_not_from_the_page() -> None:
    html = _text("favorites.html")
    script = _text("favorites.js")

    assert 'id="favorite-artist-form"' not in html
    assert 'id="favorites-track-search-button"' not in html
    assert "SEARCH_ENDPOINT" not in script
    assert "function searchTracks()" not in script
    assert "artistExistsInCatalog" not in script


def test_favorites_page_is_registered_in_sidebar_navigation() -> None:
    home_status = _text("home-status.js")
    common = _text("common.js")

    assert 'data-page="favorites"' in home_status
    assert 'href="/static/favorites.html"' in home_status
    assert "if (path.endsWith('/favorites.html')) return 'favorites';" in home_status
    assert "path.endsWith('/favorites.html')" in common
    assert "sidebar-pages-label" not in home_status
    assert "sidebar-favorites-label" not in home_status


def test_favorites_js_manages_sections_artists_and_tracks_via_the_favorites_api() -> None:
    script = _text("favorites.js")

    assert "const FAVORITES_ENDPOINT = '/api/favorites';" in script
    assert "function selectSection(" in script
    assert "function renderArtists()" in script
    assert "function renderTracks()" in script
    assert "${FAVORITES_ENDPOINT}/artists" in script
    assert "${FAVORITES_ENDPOINT}/tracks" in script


def test_favorite_rows_link_to_a_filtered_library() -> None:
    script = _text("favorites.js")

    assert "function libraryArtistLink(artist)" in script
    assert "/static/library.html?artist=${encodeURIComponent(artist)}" in script
    assert "function libraryTrackLink(entry)" in script
    assert "/static/library.html?track=${encodeURIComponent(entry.video_id)}" in script
    assert "libraryArtistLink(entry.name)" in script
    assert "libraryTrackLink(entry)" in script


def test_artist_and_track_rows_show_how_many_playlists_they_appear_in() -> None:
    script = _text("favorites.js")

    assert "function playlistCountLabel(count)" in script
    assert "meta.textContent = playlistCountLabel(entry.playlist_count);" in script
    assert "playlistCountLabel(entry.playlist_count)" in script
    # Regression: the playlist-count text must be its own row for tracks, not
    # concatenated onto the artist/album line -- on narrow (mobile) viewports
    # that combined single-line text got truncated, cutting the count off.
    assert "const count = document.createElement('span');" in script
    assert "count.textContent = playlistCountLabel(entry.playlist_count);" in script
    assert "copy.append(meta, count);" in script


def test_section_hints_moved_from_page_body_to_an_info_tooltip() -> None:
    html = _text("favorites.html")
    script = _text("favorites.js")
    style = _text("favorites.css")

    assert 'class="field-hint favorites-hero-hint"' not in html
    assert "Favorite a Top artist in Statistics to see it here." not in html
    assert "Favorite a song from Playlist results to see it here." not in html
    assert 'id="favorites-section-info"' in html
    assert 'class="favorites-info-icon"' in html

    assert "const sectionHints = {" in script
    assert "Favorite an artist or a song using the heart icon" in script
    assert "Favorites contribute to how future playlists are generated." in script
    assert "info.dataset.tooltip = sectionHints[selected];" in script
    # Regression: don't also set the native `title` attribute -- that produced a
    # second, browser-styled tooltip stacked on top of the custom CSS one.
    assert "info.title = sectionHints[selected];" not in script

    assert ".favorites-info-icon::after" in style
    assert "content: attr(data-tooltip);" in style


def test_artists_and_songs_are_sorted_by_playlist_count() -> None:
    script = _text("favorites.js")

    assert "function sortedByCount(entries, key)" in script
    assert "const diff = (b.playlist_count || 0) - (a.playlist_count || 0);" in script
    assert "sortedByCount(favorites.artists || [], 'name')" in script
    assert "sortedByCount(favorites.tracks || [], 'title')" in script


def test_overview_shows_top_5_artists_and_songs_by_playlist_count() -> None:
    html = _text("favorites.html")
    script = _text("favorites.js")

    assert 'id="favorites-top-artists"' in html
    assert 'id="favorites-top-tracks"' in html
    assert "Top 5 artists" in html
    assert "Top 5 songs" in html
    assert "function renderTopArtists()" in script
    assert "function renderTopTracks()" in script
    assert ".slice(0, 5)" in script
    assert "renderTopArtists();" in script
    assert "renderTopTracks();" in script


def test_favorite_artist_rows_show_a_thumbnail_image() -> None:
    script = _text("favorites.js")
    style = _text("favorites.css")

    assert "image.className = 'favorites-row-avatar';" in script
    assert "image.src = entry.thumbnail_url || '';" in script
    assert "row.append(image, copy);" in script
    assert ".favorites-row-avatar" in style


def test_overview_top_5_artist_and_track_rows_match_in_size_and_image_shape() -> None:
    style = _text("favorites.css")

    # Regression: artist rows used to be shorter than track rows (one line of
    # text vs. two) and their avatar was round while track thumbnails were
    # square -- both are now forced to the same height and image shape within
    # the compact Overview lists.
    assert ".favorites-row-compact {\n  min-height: 40px;" in style
    assert ".favorites-row-compact .favorites-row-avatar {\n  border-radius: 6px;" in style


def test_artists_and_songs_tabs_show_10_then_a_see_all_toggle() -> None:
    html = _text("favorites.html")
    script = _text("favorites.js")
    style = _text("favorites.css")

    assert 'id="favorite-artist-list-toggle" class="favorites-see-all-link hidden"' in html
    assert 'id="favorite-track-list-toggle" class="favorites-see-all-link hidden"' in html

    assert "const LIST_LIMIT = 10;" in script
    assert "artists.slice(0, LIST_LIMIT)" in script
    assert "tracks.slice(0, LIST_LIMIT)" in script
    assert "function updateSeeAllToggle(toggleId, total, expanded)" in script
    assert "artistsExpanded = !artistsExpanded;" in script
    assert "tracksExpanded = !tracksExpanded;" in script

    assert ".favorites-see-all-link" in style


def test_overview_trims_leading_and_trailing_row_padding() -> None:
    style = _text("favorites.css")

    assert ".favorites-overview-row:first-child {\n  padding-top: 0;" in style
    assert ".favorites-overview-row:last-child {\n  padding-bottom: 0;" in style


def test_overview_top_5_rows_use_a_compact_layout() -> None:
    script = _text("favorites.js")
    style = _text("favorites.css")

    assert "renderList('favorites-top-artists', 'favorites-top-artists-empty', top, artistRow, {compact: true});" in script
    assert "renderList('favorites-top-tracks', 'favorites-top-tracks-empty', top, trackRow, {compact: true});" in script
    assert ".favorites-row-compact" in style
    assert ".favorites-row-compact img" in style


def test_removing_a_favorite_artist_uses_a_query_param() -> None:
    script = _text("favorites.js")

    assert "${FAVORITES_ENDPOINT}/artists?name=${encodeURIComponent(entry.name)}" in script


def test_favorite_toggle_helper_exists_and_is_exported() -> None:
    script = _text("action-controls.js")

    assert "function decorateFavoriteToggle(" in script
    assert "window.PlaylistMuseActionControls" in script
    assert "favorite:" in script
    assert "favorited:" in script


def test_playlist_tracks_and_top_artists_expose_a_favorite_toggle() -> None:
    playlist_script = _text("playlist.js")
    statistics_script = _text("statistics.js")

    assert "favorite-track-button" in playlist_script
    assert "/api/favorites" in playlist_script
    assert "decorateFavoriteToggle" in playlist_script

    assert "favoritable: true" in statistics_script
    assert "decorateFavoriteToggle" in statistics_script
    assert "/api/favorites" in statistics_script


def test_primary_navigation_no_longer_depends_on_the_sidebar_pages_group() -> None:
    script = _text("common.js")

    assert "const PRIMARY_PAGES = [" in script
    assert "sidebar-pages-label" not in script
    assert "pageGroup" not in script
