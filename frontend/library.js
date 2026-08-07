(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const REQUEST_KEY = 'playlistmuse-generation-request';
  const ENDPOINT = '/api/library/playlists';
  const $ = (id) => document.getElementById(id);
  const {readJson, setLoadingButton} = window.PlaylistMuseCommon;
  let expandedLibraryId = null;
  let libraryItems = [];
  let activeStatusFilter = 'all';

  function readSessionJson(key) {
    try {
      return JSON.parse(sessionStorage.getItem(key) || 'null');
    } catch {
      return null;
    }
  }

  async function migrateSessionPlaylist() {
    const playlist = readSessionJson(STORAGE_KEY);
    if (!playlist || !Array.isArray(playlist.tracks) || playlist.library_id) return;

    const generationRequest = readSessionJson(REQUEST_KEY);
    const playlistDocument = {...playlist};
    delete playlistDocument.library_id;
    const record = await readJson(await fetch(ENDPOINT, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        playlist: playlistDocument,
        generation_request: generationRequest || null,
      }),
    }));
    playlist.library_id = record.id;
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(playlist));
  }

  function setStatus(text = '', error = false) {
    const status = $('library-status');
    status.textContent = text;
    status.classList.toggle('library-error', error);
    status.classList.toggle('hidden', !text);
  }

  function formatDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(date);
  }

  function coverPlaceholder() {
    return document.createElement('span');
  }

  function createCover(urls = []) {
    const cover = document.createElement('div');
    cover.className = 'library-cover';
    cover.setAttribute('aria-hidden', 'true');

    for (let index = 0; index < 4; index += 1) {
      const url = urls[index];
      if (!url) {
        cover.append(coverPlaceholder());
        continue;
      }
      const image = document.createElement('img');
      image.src = url;
      image.alt = '';
      image.loading = 'lazy';
      image.addEventListener('error', () => image.replaceWith(coverPlaceholder()), {once: true});
      cover.append(image);
    }
    return cover;
  }

  function detailBlock(title, lines) {
    const block = document.createElement('section');
    block.className = 'library-detail-block';

    const heading = document.createElement('h3');
    heading.textContent = title;
    block.append(heading);

    const values = Array.isArray(lines) ? lines : [lines];
    values.filter(Boolean).forEach((text) => {
      const paragraph = document.createElement('p');
      paragraph.textContent = text;
      block.append(paragraph);
    });
    return block;
  }

  function closeOtherCards(currentCard) {
    document.querySelectorAll('.library-item.expanded').forEach((card) => {
      if (card === currentCard) return;
      card.classList.remove('expanded');
      card.setAttribute('aria-expanded', 'false');
    });
  }

  function toggleLibraryCard(card, item) {
    const willExpand = !card.classList.contains('expanded');
    closeOtherCards(card);
    card.classList.toggle('expanded', willExpand);
    card.setAttribute('aria-expanded', String(willExpand));
    expandedLibraryId = willExpand ? item.id : null;
    if (willExpand) {
      card.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    }
  }

  async function openPlaylist(item, link) {
    const previousText = link.textContent;
    link.textContent = 'Opening…';
    link.setAttribute('aria-busy', 'true');
    link.classList.add('is-loading');
    try {
      const record = await readJson(await fetch(`${ENDPOINT}/${encodeURIComponent(item.id)}`, {
        cache: 'no-store',
      }));
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
        ...record.playlist,
        library_id: record.id,
      }));
      if (record.generation_request) {
        sessionStorage.setItem(REQUEST_KEY, JSON.stringify(record.generation_request));
      } else {
        sessionStorage.removeItem(REQUEST_KEY);
      }
      window.location.assign('/static/playlist.html');
    } catch (error) {
      link.textContent = previousText;
      link.removeAttribute('aria-busy');
      link.classList.remove('is-loading');
      setStatus(error.message || String(error), true);
    }
  }

  async function duplicatePlaylist(item, button) {
    const reset = setLoadingButton(button, {label: 'Duplicating', resetText: 'Duplicate'});
    try {
      await readJson(await fetch(`${ENDPOINT}/${encodeURIComponent(item.id)}/duplicate`, {
        method: 'POST',
      }));
      expandedLibraryId = null;
      await loadLibrary();
    } catch (error) {
      reset();
      setStatus(error.message || String(error), true);
    }
  }

  async function deletePlaylist(item, button) {
    if (!window.confirm(`Delete “${item.name}” from the local library?`)) return;
    const reset = setLoadingButton(button, {label: 'Deleting', resetText: 'Delete'});
    try {
      const response = await fetch(`${ENDPOINT}/${encodeURIComponent(item.id)}`, {
        method: 'DELETE',
      });
      if (!response.ok) await readJson(response);
      const current = (() => {
        try {
          return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
        } catch {
          return null;
        }
      })();
      if (current?.library_id === item.id) {
        sessionStorage.removeItem(STORAGE_KEY);
        sessionStorage.removeItem(REQUEST_KEY);
      }
      if (expandedLibraryId === item.id) expandedLibraryId = null;
      await loadLibrary();
    } catch (error) {
      reset();
      setStatus(error.message || String(error), true);
    }
  }

  function createLibraryItem(item) {
    const card = document.createElement('article');
    card.className = 'library-item';
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    card.setAttribute('aria-expanded', String(expandedLibraryId === item.id));
    card.setAttribute('aria-label', `Show details for ${item.name || 'this playlist'}`);
    if (expandedLibraryId === item.id) card.classList.add('expanded');

    card.append(createCover(item.thumbnail_urls));

    const copy = document.createElement('div');
    copy.className = 'library-copy';

    const titleRow = document.createElement('div');
    titleRow.className = 'library-title-row';
    const title = document.createElement('strong');
    title.className = 'library-title';
    title.textContent = item.name || 'Untitled playlist';
    title.title = title.textContent;
    const badge = document.createElement('span');
    badge.className = `library-status-badge ${item.status === 'published' ? 'published' : ''}`;
    badge.textContent = item.status === 'published' ? 'Published' : 'Draft';
    titleRow.append(title, badge);

    const meta = document.createElement('p');
    meta.className = 'library-meta';
    const trackLabel = `${item.track_count} ${item.track_count === 1 ? 'track' : 'tracks'}`;
    meta.textContent = [trackLabel, `Updated ${formatDate(item.updated_at)}`]
      .filter(Boolean)
      .join(' · ');

    copy.append(titleRow, meta);

    const expandIcon = document.createElement('span');
    expandIcon.className = 'library-expand-icon';
    expandIcon.setAttribute('aria-hidden', 'true');
    expandIcon.innerHTML = '<svg viewBox="0 0 24 24" focusable="false"><path d="m7 10 5 5 5-5"/></svg>';

    const details = document.createElement('div');
    details.className = 'library-details';
    const detailsInner = document.createElement('div');
    detailsInner.className = 'library-details-inner';

    const detailGrid = document.createElement('div');
    detailGrid.className = 'library-detail-grid';
    detailGrid.append(
      detailBlock(
        'Description',
        item.description || 'No description saved.',
      ),
      detailBlock(
        'Original request',
        item.prompt || 'No original prompt saved.',
      ),
      detailBlock('Playlist details', [
        `${trackLabel} · ${item.status === 'published' ? 'Published' : 'Draft'}`,
        `Created ${formatDate(item.created_at)}`,
        `Updated ${formatDate(item.updated_at)}`,
      ]),
    );

    if (item.youtube_playlist_id || item.youtube_playlist_url) {
      detailGrid.append(detailBlock('YouTube Music', [
        item.youtube_playlist_id ? `Playlist ID: ${item.youtube_playlist_id}` : '',
        item.youtube_playlist_url ? 'Published playlist link available below.' : '',
      ]));
    }

    const actions = document.createElement('div');
    actions.className = 'library-actions';

    const open = document.createElement('a');
    open.href = `/static/playlist.html?id=${encodeURIComponent(item.id)}`;
    open.className = 'primary';
    open.textContent = 'Open';
    open.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      void openPlaylist(item, open);
    });

    const duplicate = document.createElement('button');
    duplicate.type = 'button';
    duplicate.className = 'secondary';
    duplicate.textContent = 'Duplicate';
    duplicate.addEventListener('click', (event) => {
      event.stopPropagation();
      void duplicatePlaylist(item, duplicate);
    });

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'secondary library-delete';
    remove.textContent = 'Delete';
    remove.addEventListener('click', (event) => {
      event.stopPropagation();
      void deletePlaylist(item, remove);
    });

    actions.append(open, duplicate, remove);

    if (item.youtube_playlist_url) {
      const youtube = document.createElement('a');
      youtube.href = item.youtube_playlist_url;
      youtube.target = '_blank';
      youtube.rel = 'noopener noreferrer';
      youtube.className = 'secondary';
      youtube.textContent = 'YouTube Music';
      youtube.addEventListener('click', (event) => event.stopPropagation());
      actions.insertBefore(youtube, duplicate);
    }

    detailsInner.append(detailGrid, actions);
    if (item.status === 'draft') {
      window.PlaylistMuseLibraryRefine?.install({
        item,
        actions,
        detailsInner,
        reload: loadLibrary,
      });
    }
    details.append(detailsInner);

    card.append(copy, expandIcon, details);
    card.addEventListener('click', (event) => {
      if (event.target.closest('a, button')) return;
      toggleLibraryCard(card, item);
    });
    card.addEventListener('keydown', (event) => {
      if (event.target !== card || !['Enter', ' '].includes(event.key)) return;
      event.preventDefault();
      toggleLibraryCard(card, item);
    });

    return card;
  }

  function normalizedSearch(value) {
    return String(value || '').trim().toLocaleLowerCase();
  }

  function matchesSearch(item, query) {
    if (!query) return true;
    return [item.name, item.description, item.prompt]
      .some((value) => normalizedSearch(value).includes(query));
  }

  function visibleLibraryItems() {
    const query = normalizedSearch($('library-search').value);
    return libraryItems.filter((item) => {
      const matchesStatus = activeStatusFilter === 'all' || item.status === activeStatusFilter;
      return matchesStatus && matchesSearch(item, query);
    });
  }

  function updateLibraryCount(count) {
    $('library-count').textContent = `${count} ${count === 1 ? 'playlist' : 'playlists'}`;
  }

  function renderLibrary() {
    const items = visibleLibraryItems();
    if (expandedLibraryId && !items.some((item) => item.id === expandedLibraryId)) {
      expandedLibraryId = null;
    }

    $('library-list').replaceChildren(...items.map(createLibraryItem));
    updateLibraryCount(items.length);

    const empty = $('library-empty');
    const hasSavedPlaylists = libraryItems.length > 0;
    empty.textContent = hasSavedPlaylists
      ? 'No playlists match the current search and filters.'
      : 'No saved playlists yet. Create one and it will appear here automatically.';
    empty.classList.toggle('hidden', items.length > 0);
  }

  function setStatusFilter(filter) {
    activeStatusFilter = filter;
    document.querySelectorAll('[data-status-filter]').forEach((button) => {
      const active = button.dataset.statusFilter === filter;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    renderLibrary();
  }

  async function loadLibrary() {
    setStatus('Loading playlists…');
    $('library-empty').classList.add('hidden');
    try {
      const sort = $('library-sort').value;
      const payload = await readJson(await fetch(`${ENDPOINT}?sort=${encodeURIComponent(sort)}`, {
        cache: 'no-store',
      }));
      libraryItems = Array.isArray(payload.items) ? payload.items : [];
      renderLibrary();
      setStatus('');
    } catch (error) {
      libraryItems = [];
      $('library-list').replaceChildren();
      $('library-empty').classList.add('hidden');
      updateLibraryCount(0);
      setStatus(error.message || String(error), true);
    }
  }

  async function initializeLibrary() {
    let migrationError = '';
    try {
      await migrateSessionPlaylist();
    } catch (error) {
      migrationError = error.message || String(error);
    }
    await loadLibrary();
    if (migrationError) setStatus(migrationError, true);
  }

  $('library-search').addEventListener('input', renderLibrary);
  document.querySelectorAll('[data-status-filter]').forEach((button) => {
    button.addEventListener('click', () => setStatusFilter(button.dataset.statusFilter || 'all'));
  });
  $('library-sort').addEventListener('change', () => {
    expandedLibraryId = null;
    void loadLibrary();
  });
  void initializeLibrary();
})();
