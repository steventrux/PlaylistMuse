(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const {readJson} = window.PlaylistMuseCommon;
  const FAVORITES_ENDPOINT = '/api/favorites';

  const SECTIONS = new Set(['overview', 'artists', 'songs']);
  const sectionTitles = {overview: 'Overview', artists: 'Artists', songs: 'Songs'};
  const sectionHints = {
    overview: 'Favorite an artist or a song using the heart icon on Playlist results or on Top artists in Statistics. Favorites contribute to how future playlists are generated.',
    artists: 'Favorite a Top artist in Statistics to see it here.',
    songs: 'Favorite a song from Playlist results to see it here.',
  };
  const query = new URLSearchParams(window.location.search);

  let favorites = {artists: [], tracks: []};

  function requestedSection() {
    const value = query.get('section') || 'overview';
    return SECTIONS.has(value) ? value : 'overview';
  }

  function updateLocation(section) {
    const url = new URL(window.location.href);
    url.searchParams.set('section', section);
    window.history.replaceState({favoritesSection: section}, '', `${url.pathname}${url.search}${url.hash}`);
  }

  function selectSection(section, {updateUrl = true} = {}) {
    const selected = SECTIONS.has(section) ? section : 'overview';

    SECTIONS.forEach((name) => {
      const panel = $(`favorites-${name}-panel`);
      panel?.classList.toggle('hidden', name !== selected);
      panel?.setAttribute('aria-hidden', String(name !== selected));
    });

    document.querySelectorAll('[data-favorites-section]').forEach((button) => {
      const active = button.dataset.favoritesSection === selected;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });

    $('favorites-section-title').textContent = sectionTitles[selected];
    document.title = `${sectionTitles[selected]} · Favorites · PlaylistMuse`;
    const info = $('favorites-section-info');
    if (info) {
      info.dataset.tooltip = sectionHints[selected];
      info.setAttribute('aria-label', sectionHints[selected]);
    }
    if (updateUrl) updateLocation(selected);
  }

  function removeIcon() {
    return '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="m6.5 7 1 13h9l1-13"/><path d="M10 11v5M14 11v5"/></svg>';
  }

  function removeButton(label, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary favorites-row-remove';
    button.innerHTML = removeIcon();
    button.setAttribute('aria-label', label);
    button.title = label;
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await onClick();
      } catch (error) {
        button.disabled = false;
        window.alert(error.message || String(error));
      }
    });
    return button;
  }

  function renderSummary() {
    $('favorites-artist-count').textContent = favorites.artists.length;
    $('favorites-track-count').textContent = favorites.tracks.length;
  }

  function sortedByCount(entries, key) {
    return [...entries].sort((a, b) => {
      const diff = (b.playlist_count || 0) - (a.playlist_count || 0);
      if (diff !== 0) return diff;
      return String(a[key] || '').localeCompare(String(b[key] || ''), undefined, {sensitivity: 'base'});
    });
  }

  function libraryArtistLink(artist) {
    const link = document.createElement('a');
    link.className = 'favorites-row-copy';
    link.href = `/static/library.html?artist=${encodeURIComponent(artist)}`;
    link.title = `Show playlists with ${artist} in Library`;
    return link;
  }

  function libraryTrackLink(entry) {
    const link = document.createElement('a');
    link.className = 'favorites-row-copy';
    link.href = `/static/library.html?track=${encodeURIComponent(entry.video_id)}`
      + `&title=${encodeURIComponent(entry.title)}`;
    link.title = `Show playlists with ${entry.title} in Library`;
    return link;
  }

  function playlistCountLabel(count) {
    const value = count || 0;
    return `In ${value} playlist${value === 1 ? '' : 's'}`;
  }

  function artistRow(entry, {removable, compact}) {
    const row = document.createElement('div');
    row.className = compact ? 'favorites-row favorites-row-compact' : 'favorites-row';

    const image = document.createElement('img');
    image.className = 'favorites-row-avatar';
    image.src = entry.thumbnail_url || '';
    image.alt = '';
    image.loading = 'lazy';

    const copy = libraryArtistLink(entry.name);
    const name = document.createElement('strong');
    name.textContent = entry.name;
    copy.append(name);
    if (!compact) {
      const meta = document.createElement('span');
      meta.textContent = playlistCountLabel(entry.playlist_count);
      copy.append(meta);
    }
    row.append(image, copy);

    if (compact) {
      const count = document.createElement('span');
      count.className = 'favorites-row-count';
      count.textContent = entry.playlist_count || 0;
      row.append(count);
    }

    if (removable) {
      row.append(removeButton(`Remove ${entry.name} from favorites`, async () => {
        favorites = await readJson(await fetch(
          `${FAVORITES_ENDPOINT}/artists?name=${encodeURIComponent(entry.name)}`,
          {method: 'DELETE'},
        ));
        renderAll();
      }));
    }
    return row;
  }

  function trackRow(entry, {removable, compact}) {
    const row = document.createElement('div');
    row.className = compact ? 'favorites-row favorites-row-compact' : 'favorites-row';

    const image = document.createElement('img');
    image.src = entry.thumbnail_url || '';
    image.alt = '';
    image.loading = 'lazy';

    const copy = libraryTrackLink(entry);
    const title = document.createElement('strong');
    title.textContent = entry.title;
    copy.append(title);
    if (!compact) {
      const meta = document.createElement('span');
      meta.textContent = [entry.artists, entry.album].filter(Boolean).join(' · ');
      const count = document.createElement('span');
      count.textContent = playlistCountLabel(entry.playlist_count);
      copy.append(meta, count);
    } else {
      const meta = document.createElement('span');
      meta.textContent = entry.artists || '';
      copy.append(meta);
    }
    row.append(image, copy);

    if (compact) {
      const count = document.createElement('span');
      count.className = 'favorites-row-count';
      count.textContent = entry.playlist_count || 0;
      row.append(count);
    }

    if (removable) {
      row.append(removeButton(`Remove ${entry.title} from favorites`, async () => {
        favorites = await readJson(await fetch(
          `${FAVORITES_ENDPOINT}/tracks/${encodeURIComponent(entry.video_id)}`,
          {method: 'DELETE'},
        ));
        renderAll();
      }));
    }
    return row;
  }

  function renderList(listId, emptyId, entries, rowBuilder, {removable, compact}) {
    const list = $(listId);
    const empty = $(emptyId);
    list.replaceChildren();
    empty.classList.toggle('hidden', entries.length > 0);
    for (const entry of entries) list.append(rowBuilder(entry, {removable, compact}));
  }

  const LIST_LIMIT = 10;
  let artistsExpanded = false;
  let tracksExpanded = false;

  function updateSeeAllToggle(toggleId, total, expanded) {
    const toggle = $(toggleId);
    if (!toggle) return;
    if (total <= LIST_LIMIT) {
      toggle.classList.add('hidden');
      return;
    }
    toggle.classList.remove('hidden');
    toggle.textContent = expanded ? 'Show less ↑' : `See all ${total} →`;
  }

  function renderArtists() {
    const artists = sortedByCount(favorites.artists || [], 'name');
    const items = artistsExpanded ? artists : artists.slice(0, LIST_LIMIT);
    renderList('favorite-artist-list', 'favorite-artist-empty', items, artistRow, {removable: true});
    updateSeeAllToggle('favorite-artist-list-toggle', artists.length, artistsExpanded);
  }

  function renderTracks() {
    const tracks = sortedByCount(favorites.tracks || [], 'title');
    const items = tracksExpanded ? tracks : tracks.slice(0, LIST_LIMIT);
    renderList('favorite-track-list', 'favorite-track-empty', items, trackRow, {removable: true});
    updateSeeAllToggle('favorite-track-list-toggle', tracks.length, tracksExpanded);
  }

  function renderTopArtists() {
    const top = sortedByCount(favorites.artists || [], 'name').slice(0, 5);
    renderList('favorites-top-artists', 'favorites-top-artists-empty', top, artistRow, {compact: true});
  }

  function renderTopTracks() {
    const top = sortedByCount(favorites.tracks || [], 'title').slice(0, 5);
    renderList('favorites-top-tracks', 'favorites-top-tracks-empty', top, trackRow, {compact: true});
  }

  function renderAll() {
    renderSummary();
    renderArtists();
    renderTracks();
    renderTopArtists();
    renderTopTracks();
  }

  async function loadFavorites() {
    try {
      favorites = await readJson(await fetch(FAVORITES_ENDPOINT, {cache: 'no-store'}));
    } catch (error) {
      favorites = {artists: [], tracks: []};
      console.warn('Favorites could not be loaded:', error);
    }
    renderAll();
  }

  document.querySelectorAll('[data-favorites-section]').forEach((button) => {
    button.addEventListener('click', () => selectSection(button.dataset.favoritesSection));
  });

  $('favorite-artist-list-toggle')?.addEventListener('click', () => {
    artistsExpanded = !artistsExpanded;
    renderArtists();
  });
  $('favorite-track-list-toggle')?.addEventListener('click', () => {
    tracksExpanded = !tracksExpanded;
    renderTracks();
  });

  selectSection(requestedSection(), {updateUrl: false});
  void loadFavorites();
})();
